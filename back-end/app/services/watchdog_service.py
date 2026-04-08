"""Brain Watchdog -- monitors open brain positions between scans.

Runs every 15 min during market hours. Checks prices, detects trouble,
escalates to Grok/Gemini sentiment when concerned, and alerts the user
if a watchlisted ticker is at risk.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from loguru import logger

from app.core.config import settings
from app.db import queries
from app.db.supabase import get_client
from app.notifications.messages import msg
from app.notifications.telegram_bot import send_message
from app.services.price_cache import _fetch_prices_batch


# Event type constants
EVENT_ALERT = "ALERT"
EVENT_CLOSE = "CLOSE"
EVENT_HOLD = "HOLD_THROUGH_DIP"
EVENT_RECOVERY = "RECOVERY"


@dataclass
class WatchdogEntry:
    """In-memory state for a tracked position."""
    last_price: float = 0.0
    last_check: float = 0.0
    alert_level: str = "normal"
    escalation_count: int = 0
    consecutive_holds: int = 0
    cooldown_until: float = 0.0
    last_sentiment: dict = field(default_factory=dict)


# In-memory watchdog state (survives between checks, not between restarts)
_state: dict[str, WatchdogEntry] = {}


async def run_watchdog() -> dict:
    """Check all open brain positions. Called by the scheduler."""
    if not settings.watchdog_enabled:
        return {"skipped": True}

    db = get_client()

    # Get open brain positions
    result = db.table("virtual_trades") \
        .select("id, symbol, entry_price, entry_date, entry_score, stop_loss, source") \
        .eq("status", "OPEN") \
        .eq("source", "brain") \
        .execute()
    open_trades = result.data or []

    if not open_trades:
        return {"positions": 0, "alerts": 0, "closes": 0}

    # Get watchlist for overlap detection
    watchlist_symbols = queries.get_all_watchlist_symbols()

    # Batch fetch current prices (run in thread to avoid blocking event loop)
    symbols = list({t["symbol"] for t in open_trades})
    prices = await asyncio.to_thread(_fetch_prices_batch, symbols)

    # Cleanup stale state entries (symbols no longer in open positions)
    stale_keys = set(_state.keys()) - set(symbols)
    for k in stale_keys:
        del _state[k]

    now = time.time()
    alerts_sent = 0
    closes = 0
    concerned = []
    pending_events: list[dict] = []

    # Batch-fetch latest scores for all positions (avoids N+1 queries in the loop)
    latest_scores: dict[str, dict] = {}
    try:
        sig_result = db.table("signals").select("symbol, score, action").in_("symbol", symbols).order("created_at", desc=True).execute()
        for row in (sig_result.data or []):
            sym = row.get("symbol")
            if sym and sym not in latest_scores:
                latest_scores[sym] = row
    except Exception:
        pass

    # Pre-compute weakest entry score for composite concern rule
    weakest_entry_score = min((t.get("entry_score", 999) or 999 for t in open_trades), default=999)

    for trade in open_trades:
        symbol = trade["symbol"]
        entry_price = float(trade["entry_price"])
        current_price, _ = prices.get(symbol, (None, None))

        # Get or create state early for cooldown check
        state = _state.get(symbol)
        if not state:
            state = WatchdogEntry(last_price=current_price if current_price else 0.0, last_check=now)
            _state[symbol] = state

        # Cooldown: skip if in cooldown period (hourly after 3 consecutive holds)
        if state.cooldown_until > now:
            logger.debug(f"Watchdog: {symbol} in cooldown until {datetime.fromtimestamp(state.cooldown_until).strftime('%H:%M')}")
            continue

        if current_price is None:
            continue

        stop = float(trade["stop_loss"]) if trade.get("stop_loss") else None

        # Compute metrics
        pnl_total_pct = ((current_price - entry_price) / entry_price) * 100
        pnl_since_last = ((current_price - state.last_price) / state.last_price) * 100 if state.last_price > 0 else 0
        stop_distance_pct = ((current_price - stop) / current_price) * 100 if stop else 999

        # Check triggers
        reasons = []
        entry_score = trade.get("entry_score") or 0
        latest_sig_data = latest_scores.get(symbol, {})
        current_score = latest_sig_data.get("score", 0)
        days_held = 0
        try:
            entry_dt = datetime.fromisoformat(trade.get("entry_date", "").replace("Z", "+00:00"))
            days_held = (datetime.now(timezone.utc) - entry_dt).days
        except (ValueError, TypeError):
            pass

        # 1. Interval drop (sudden move)
        if pnl_since_last <= -settings.watchdog_pnl_alert_pct:
            reasons.append(f"P&L dropped {pnl_since_last:+.1f}% since last check")
        # 2. Stop proximity
        if stop_distance_pct <= settings.watchdog_stop_proximity_pct:
            reasons.append(f"Price within {stop_distance_pct:.1f}% of stop loss")
        # 3. Total unrealized loss > 2% (cut losers fast to protect monthly profit target)
        if pnl_total_pct <= -2.0:
            reasons.append(f"Total unrealized loss {pnl_total_pct:+.1f}% (slow bleed)")
        # 4. Score deterioration
        if entry_score > 0 and current_score > 0:
            score_drop = entry_score - current_score
            if score_drop >= 10:
                reasons.append(f"Score deterioration: {entry_score} -> {current_score} (-{score_drop}pts)")
        # 5. Composite concern: weakest position + losing + held > 1 day
        #    A marginal position (lowest score) that's losing money after day 1
        #    should be reviewed even if no single threshold was crossed.
        #    Goal: cut losers fast to protect monthly 1-2% target.
        is_weakest = (entry_score <= weakest_entry_score)
        if is_weakest and pnl_total_pct <= -2.0 and days_held >= 1 and not reasons:
            reasons.append(
                f"Composite concern: weakest position (score {entry_score}) "
                f"+ losing {pnl_total_pct:+.1f}% + held {days_held}d"
            )

        # Update state
        state.last_price = current_price
        state.last_check = now

        if not reasons:
            if state.alert_level != "normal":
                pending_events.append({
                    "symbol": symbol, "event_type": EVENT_RECOVERY, "action_taken": "recovered",
                    "price": current_price, "entry_price": entry_price,
                    "pnl_pct": round(pnl_total_pct, 2),
                    "sentiment_label": state.last_sentiment.get("label"),
                    "sentiment_score": int(state.last_sentiment.get("score", 50)),
                    "in_watchlist": symbol in watchlist_symbols,
                    "notes": f"Recovered after {state.escalation_count} escalation(s)",
                })
                state.alert_level = "normal"
                state.escalation_count = 0
                state.consecutive_holds = 0
                state.cooldown_until = 0.0
                logger.info(f"Watchdog: {symbol} recovered, back to normal monitoring")
            continue

        # --- Escalation ---
        reason = "; ".join(reasons)
        concerned.append(symbol)
        state.alert_level = "concerned"
        state.escalation_count += 1

        logger.warning(
            f"Watchdog ALERT: {symbol} -- {reason} "
            f"(price=${current_price:.2f}, entry=${entry_price:.2f}, P&L={pnl_total_pct:+.1f}%)"
        )

        is_in_watchlist = symbol in watchlist_symbols

        # --- FORCE SELL: catastrophic loss or score collapse (no sentiment check needed) ---
        force_sell_reason = None
        if pnl_total_pct <= -8.0:
            force_sell_reason = f"Emergency stop: total loss {pnl_total_pct:+.1f}% exceeds -8% threshold"
        elif entry_score > 0 and latest_sig_data:
            cs = latest_sig_data.get("score", 0)
            ca = latest_sig_data.get("action", "HOLD")
            if cs < 50:
                force_sell_reason = f"Score collapsed to {cs} (AVOID territory)"
            elif ca in ("SELL", "AVOID") and pnl_total_pct < 0:
                force_sell_reason = f"Signal changed to {ca} with negative P&L"

        if force_sell_reason:
            await _close_virtual_trade(db, trade, current_price, "WATCHDOG_FORCE_SELL")
            closes += 1
            pending_events.append({
                "symbol": symbol, "event_type": EVENT_CLOSE, "action_taken": "force_closed",
                "price": current_price, "entry_price": entry_price,
                "pnl_pct": round(pnl_total_pct, 2), "stop_loss": stop,
                "sentiment_label": "n/a", "sentiment_score": 0,
                "in_watchlist": is_in_watchlist,
                "notes": force_sell_reason,
            })
            await send_message(settings.telegram_chat_id, msg(
                "watchdog_force_sell", symbol=symbol, price=f"{current_price:.2f}",
                pnl=f"{pnl_total_pct:+.1f}", reason=force_sell_reason), urgent=True)
            alerts_sent += 1
            state.alert_level = "critical"
            logger.warning(f"Watchdog: FORCE SOLD {symbol} -- {force_sell_reason}")
            continue

        # --- Normal escalation: fetch sentiment to decide ---
        sentiment = await _get_quick_sentiment(symbol)
        state.last_sentiment = sentiment
        sentiment_label = sentiment.get("label", "neutral")
        sentiment_score = sentiment.get("score", 50)

        event_base = {
            "symbol": symbol, "price": current_price, "entry_price": entry_price,
            "pnl_pct": round(pnl_total_pct, 2), "stop_loss": stop,
            "stop_distance_pct": round(stop_distance_pct, 2) if stop else None,
            "sentiment_label": sentiment_label, "sentiment_score": int(sentiment_score),
            "in_watchlist": is_in_watchlist,
        }

        if sentiment_label == "bearish" and pnl_total_pct < 0:
            await _close_virtual_trade(db, trade, current_price, "WATCHDOG_EXIT")
            closes += 1
            pending_events.append({**event_base, "event_type": EVENT_CLOSE, "action_taken": "closed", "notes": reason})

            await send_message(settings.telegram_chat_id, msg(
                "watchdog_exit", symbol=symbol, price=f"{current_price:.2f}",
                pnl=f"{pnl_total_pct:+.1f}", sentiment=sentiment_label), urgent=True)
            alerts_sent += 1

            if is_in_watchlist:
                await send_message(settings.telegram_chat_id, msg(
                    "watchdog_user_brain_sold", symbol=symbol,
                    price=f"{current_price:.2f}", pnl=f"{pnl_total_pct:+.1f}"))
                alerts_sent += 1

            state.alert_level = "critical"
            logger.warning(f"Watchdog: CLOSED {symbol} -- bearish sentiment + price drop")

        elif pnl_total_pct < 0:
            pending_events.append({**event_base, "event_type": EVENT_ALERT, "action_taken": "warned", "notes": reason})

            # Only send Telegram if the move is significant enough
            if abs(pnl_total_pct) >= settings.watchdog_min_notify_pct:
                await send_message(settings.telegram_chat_id, msg(
                    "watchdog_warning", symbol=symbol, price=f"{current_price:.2f}",
                    stop=f"{stop:.2f}" if stop else "N/A",
                    pnl=f"{pnl_total_pct:+.1f}", reason=reason, sentiment=sentiment_label))
                alerts_sent += 1

                if is_in_watchlist:
                    await send_message(settings.telegram_chat_id, msg("watchdog_user_warning", symbol=symbol))
                    alerts_sent += 1

        else:
            pending_events.append({**event_base, "event_type": EVENT_HOLD, "action_taken": "held",
                                   "notes": f"Held despite trigger: {reason}"})
            logger.info(f"Watchdog: {symbol} flagged but holding -- sentiment={sentiment_label} ({sentiment_score}), P&L={pnl_total_pct:+.1f}%")
            # Track consecutive holds for cooldown
            if sentiment_label == "bullish":
                state.consecutive_holds += 1
                if state.consecutive_holds >= 3:
                    state.cooldown_until = now + 3600  # 1 hour cooldown
                    logger.info(f"Watchdog: {symbol} entering 1h cooldown after {state.consecutive_holds} consecutive bullish holds")
            else:
                state.consecutive_holds = 0

    # Batch insert all events at once
    if pending_events:
        try:
            db.table("watchdog_events").insert(pending_events).execute()
        except Exception as e:
            logger.warning(f"Watchdog events batch insert failed: {e}")

    summary = {
        "positions": len(open_trades),
        "checked": len(symbols),
        "concerned": concerned,
        "alerts": alerts_sent,
        "closes": closes,
    }

    if concerned:
        logger.info(f"Watchdog complete: {summary}")
    else:
        logger.debug(f"Watchdog: {len(open_trades)} positions OK")

    return summary


async def _get_quick_sentiment(ticker: str) -> dict:
    """Quick sentiment check via the AI provider chain."""
    try:
        from app.ai import provider
        return await provider.analyze_sentiment(ticker)
    except Exception as e:
        logger.debug(f"Watchdog sentiment failed for {ticker}: {e}")
        return {"score": 50, "label": "neutral", "confidence": 0}


async def _close_virtual_trade(db, trade: dict, exit_price: float, exit_reason: str):
    """Close a virtual trade from the watchdog."""
    entry_price = float(trade["entry_price"])
    pnl_pct = ((exit_price - entry_price) / entry_price) * 100
    pnl_amount = exit_price - entry_price
    now_iso = datetime.now(timezone.utc).isoformat()

    # Get latest score
    sig = db.table("signals").select("score").eq("symbol", trade["symbol"]) \
        .order("created_at", desc=True).limit(1).execute()
    exit_score = sig.data[0].get("score") if sig.data else None

    db.table("virtual_trades").update({
        "status": "CLOSED",
        "exit_price": exit_price,
        "exit_date": now_iso,
        "exit_score": exit_score,
        "pnl_pct": round(pnl_pct, 2),
        "pnl_amount": round(pnl_amount, 2),
        "is_win": pnl_pct > 0,
        "exit_reason": exit_reason,
    }).eq("id", trade["id"]).execute()
