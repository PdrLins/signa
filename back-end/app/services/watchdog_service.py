"""Brain Watchdog — high-frequency monitor for open brain positions.

============================================================
WHAT THIS MODULE IS
============================================================

The brain (`virtual_portfolio.py`) only acts when scans run — 4 times
per day at scheduled hours. That's a 1-2 hour gap between checks during
market hours, which is way too long for risk management on a position
that's tanking.

The watchdog fills that gap. It runs every 15 minutes during market
hours and does ONE thing: check open brain positions for trouble,
escalate when needed, and force-close losers fast.

The watchdog is the BRAKING SYSTEM. The brain is the accelerator.
Together they make the autonomous loop safe enough to run unattended.

============================================================
WHAT THE WATCHDOG CHECKS
============================================================

Every 15 minutes during market hours, for each open brain position:

  1. PRICE DRIFT
       Compares current price to entry. If down > 2% since entry OR
       within 2% of stop loss, marks the position as "concerned".

  2. SCORE DETERIORATION
       Pulls the most recent signal score from the DB. If it dropped
       10+ points since the brain bought, marks as concerned.

  3. EMERGENCY EXITS (force-close, no sentiment check)
       Auto-closes the position immediately on any of:
         • Total P&L <= -8%       (catastrophic loss cap)
         • Latest score < 50      (signal collapsed to AVOID territory)
         • Latest action SELL/AVOID + negative P&L (signal flipped + losing)

  4. ESCALATION (concerned but not yet emergency)
       If the position is concerned but doesn't trigger an emergency exit,
       fetches a fresh sentiment quote from Grok/Gemini:
         • Bearish sentiment + negative P&L → close position
         • Neutral/bullish sentiment → hold and re-check next cycle
       After 3 consecutive "hold through dip" decisions on the same
       ticker, enters a 1-hour cooldown to avoid alert spam.

  5. RECOVERY
       If a previously-concerned position bounces back to entry+,
       clears the alert level and resumes normal monitoring.

============================================================
MARKET HOURS GUARD
============================================================

The watchdog ONLY checks equity positions during US regular session
(Mon-Fri 9:30am-4:00pm ET). Outside hours:

  • If any open positions are crypto, monitors crypto only.
  • If no crypto, returns immediately with `skipped_equity` count.
  • Equity state is PRESERVED across pre-market periods so escalation
    history (alert_level, consecutive_holds, cooldown_until) doesn't
    reset just because the market closed for a few hours.

The state preservation is important: without it, a position that hit
"concerned" at 3:50pm would lose its escalation context overnight and
be evaluated as fresh at 9:30am the next day, potentially missing
that it's been deteriorating for several check cycles.

============================================================
STATE STORAGE
============================================================

The watchdog uses an IN-MEMORY dict (`_state`) to track per-position
metadata between checks. This survives across watchdog runs but NOT
across process restarts. On restart, the state starts fresh and the
watchdog re-evaluates each position from scratch.

This is intentional — the state is a cache of derived data, not a
source of truth. The DB has all the persistent information; `_state`
just remembers things like "we already alerted on this position
3 times, cool down" so we don't spam Telegram.

============================================================
COST PROFILE
============================================================

The watchdog uses Grok sentiment ($0.0002/call) and Gemini (free) only
when concerned, typically 2-3 sentiment checks per day across all open
positions. Total cost: ~$0.03/month. Price checks via Yahoo Finance
are always free.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from loguru import logger

from app.core.config import settings
from app.core.dates import days_since
from app.db import queries
from app.db.supabase import get_client
from app.notifications.messages import msg
from app.notifications.telegram_bot import enqueue as _tg_send
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
    """Run one watchdog cycle — check all open brain positions for trouble.

    Called by the scheduler every 15 minutes during market hours
    (and optionally on weekends if `weekend_crypto_watchdog` is enabled,
    in which case only crypto positions are checked).

    Steps:
      1. Load all open brain positions from `virtual_trades`.
      2. Capture `all_open_symbols` BEFORE the market-hours filter so
         the state cleanup doesn't drop equity state during pre-market.
      3. Apply market-hours filter: equities are skipped outside hours.
         If filtered to nothing, exit early.
      4. Batch-fetch current prices via the price cache.
      5. Batch-fetch latest signal scores in a single DB query.
      6. For each remaining position:
           a. Check escalation conditions (price drift, score drop, stop
              proximity).
           b. If concerned: check emergency exit conditions; if not,
              fetch sentiment and decide.
           c. Update the in-memory `_state` for this ticker.
           d. Queue any pending watchdog_events for batch insert.
      7. Insert all queued events to the watchdog_events table.

    Returns:
        Dict with counters: positions, alerts, closes, concerned (list).
        Optional `skipped_equity` count when market is closed.

    Side effects:
        • DB inserts: watchdog_events, virtual_trades updates (for closes).
        • Telegram alerts: watchdog_force_sell, watchdog_exit,
          watchdog_warning, watchdog_user_brain_sold.
        • Mutates `_state` (the per-ticker escalation memory).
    """
    if not settings.watchdog_enabled:
        return {"skipped": True}

    db = get_client()

    # Get open brain positions
    result = db.table("virtual_trades") \
        .select("id, symbol, entry_price, entry_date, entry_score, stop_loss, source, bucket, market_regime, target_price, trade_horizon") \
        .eq("status", "OPEN") \
        .eq("source", "brain") \
        .execute()
    open_trades = result.data or []

    if not open_trades:
        return {"positions": 0, "alerts": 0, "closes": 0}

    # Track ALL open symbols (not just the ones we'll iterate this run) so the
    # state cleanup below doesn't accidentally drop state for equities just
    # because we're in pre-market. Equity state should persist across
    # market-closed periods.
    all_open_symbols = {t["symbol"] for t in open_trades}

    # Market hours guard: only equity positions are skipped when market is closed.
    # Crypto positions still get monitored 24/7. The scheduler should already only
    # call this during market hours, but this guard protects against scheduler drift,
    # manual triggers, or weekend runs (when crypto-only watchdog is enabled).
    from app.services.virtual_portfolio import _is_us_market_open
    market_open = _is_us_market_open()
    if not market_open:
        # Filter out equities — only watch crypto outside market hours
        crypto_trades = [t for t in open_trades if (t.get("symbol") or "").endswith("-USD")]
        if not crypto_trades:
            # Still cleanup state for genuinely-closed positions
            stale_keys = set(_state.keys()) - all_open_symbols
            for k in stale_keys:
                del _state[k]
            logger.debug("Watchdog: market closed and no crypto positions, skipping")
            return {"positions": 0, "alerts": 0, "closes": 0, "skipped_equity": len(open_trades)}
        skipped_equity = len(open_trades) - len(crypto_trades)
        if skipped_equity:
            logger.info(
                f"Watchdog: market closed, monitoring {len(crypto_trades)} crypto only "
                f"(skipped {skipped_equity} equity positions)"
            )
        open_trades = crypto_trades

    # SPY crash detection removed — was causing DNS thread exhaustion
    # by adding 2 yfinance calls (SPY price + SPY info) during the same
    # window as the scan's own yfinance calls. The VIX-based regime
    # detection in the scan itself handles market downturns; the watchdog
    # doesn't need its own redundant SPY check.
    # TODO: re-add when we have a dedicated thread pool for scans.

    # Get watchlist for overlap detection
    watchlist_symbols = queries.get_all_watchlist_symbols()

    # Batch fetch current prices (run in thread to avoid blocking event loop)
    symbols = list({t["symbol"] for t in open_trades})
    prices = await asyncio.to_thread(_fetch_prices_batch, symbols)

    # Cleanup stale state entries — based on ALL currently-open symbols (not
    # just the ones being processed this run). This preserves equity state
    # across market-closed runs while still cleaning up genuinely-closed positions.
    stale_keys = set(_state.keys()) - all_open_symbols
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
        days_held = days_since(trade.get("entry_date"))

        # LONG positions get relaxed watchdog thresholds: wider drop
        # tolerance (4% vs 2%) and no composite concern. The thesis
        # tracker (daily) handles LONG exits — the watchdog's job for
        # LONG is only to catch catastrophic moves, not routine dips.
        horizon = trade.get("trade_horizon") or "SHORT"
        interval_threshold = settings.watchdog_pnl_alert_pct * (2.0 if horizon == "LONG" else 1.0)
        bleed_threshold = -4.0 if horizon == "LONG" else -2.0

        # 1. Interval drop (sudden move)
        if pnl_since_last <= -interval_threshold:
            reasons.append(f"P&L dropped {pnl_since_last:+.1f}% since last check")
        # 2. Stop proximity
        if stop_distance_pct <= settings.watchdog_stop_proximity_pct:
            reasons.append(f"Price within {stop_distance_pct:.1f}% of stop loss")
        # 3. Total unrealized loss (SHORT: >2%, LONG: >4%)
        if pnl_total_pct <= bleed_threshold:
            reasons.append(f"Total unrealized loss {pnl_total_pct:+.1f}% (slow bleed)")
        # 4. Score deterioration
        if entry_score > 0 and current_score > 0:
            score_drop = entry_score - current_score
            if score_drop >= 10:
                reasons.append(f"Score deterioration: {entry_score} -> {current_score} (-{score_drop}pts)")
        # 5. Composite concern: weakest position + losing + held > 1 day
        #    Skipped for LONG — they're expected to dip and recover.
        is_weakest = (entry_score <= weakest_entry_score)
        if horizon != "LONG" and is_weakest and pnl_total_pct <= -2.0 and days_held >= 1 and not reasons:
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
            _tg_send(settings.telegram_chat_id, msg(
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

            _tg_send(settings.telegram_chat_id, msg(
                "watchdog_exit", symbol=symbol, price=f"{current_price:.2f}",
                pnl=f"{pnl_total_pct:+.1f}", sentiment=sentiment_label), urgent=True)
            alerts_sent += 1

            if is_in_watchlist:
                _tg_send(settings.telegram_chat_id, msg(
                    "watchdog_user_brain_sold", symbol=symbol,
                    price=f"{current_price:.2f}", pnl=f"{pnl_total_pct:+.1f}"))
                alerts_sent += 1

            state.alert_level = "critical"
            logger.warning(f"Watchdog: CLOSED {symbol} -- bearish sentiment + price drop")

        elif pnl_total_pct < 0:
            pending_events.append({**event_base, "event_type": EVENT_ALERT, "action_taken": "warned", "notes": reason})

            # Only send Telegram if the move is significant enough
            if abs(pnl_total_pct) >= settings.watchdog_min_notify_pct:
                _tg_send(settings.telegram_chat_id, msg(
                    "watchdog_warning", symbol=symbol, price=f"{current_price:.2f}",
                    stop=f"{stop:.2f}" if stop else "N/A",
                    pnl=f"{pnl_total_pct:+.1f}", reason=reason, sentiment=sentiment_label))
                alerts_sent += 1

                if is_in_watchlist:
                    _tg_send(settings.telegram_chat_id, msg("watchdog_user_warning", symbol=symbol))
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
    """Close a virtual trade from the watchdog.

    INTENTIONALLY NOT GATED BY `_exit_is_thesis_protected`. The thesis gate
    in `virtual_portfolio.py` only protects scan-driven exits (SIGNAL,
    STOP_HIT, TARGET_HIT, PROFIT_TAKE, TIME_EXPIRED) where Claude has just
    re-evaluated the thesis with FRESH data from the same scan. The
    watchdog runs every 15 min between scans, so it has fresher real-time
    data than the cached `thesis_last_status` field would reflect — gating
    the watchdog through stale thesis state could BLOCK a legitimate
    emergency exit (e.g., a sentiment flip that the scan hasn't seen yet).

    The watchdog is the BRAKE — its exits should fire fast when the
    real-time conditions warrant it. Claude's stale thesis opinion has no
    business overriding that. The catastrophic carve-out (-8% pnl) that
    the scan-path uses is ALSO the watchdog's first force-sell trigger
    (see WATCHDOG_FORCE_SELL above), so the same hard limit applies.
    """
    entry_price = float(trade["entry_price"])
    pnl_pct = ((exit_price - entry_price) / entry_price) * 100
    pnl_amount = exit_price - entry_price
    now_iso = datetime.now(timezone.utc).isoformat()

    # Get latest score
    sig = db.table("signals").select("score").eq("symbol", trade["symbol"]) \
        .order("created_at", desc=True).limit(1).execute()
    exit_score = sig.data[0].get("score") if sig.data else None

    # Status guard: never mutate an already-closed row. The watchdog runs
    # off a snapshot loaded earlier in the cycle — if a parallel scan
    # already closed this trade, the OPEN filter makes this a no-op
    # instead of overwriting the prior close.
    db.table("virtual_trades").update({
        "status": "CLOSED",
        "exit_price": exit_price,
        "exit_date": now_iso,
        "exit_score": exit_score,
        "pnl_pct": round(pnl_pct, 2),
        "pnl_amount": round(pnl_amount, 2),
        "is_win": pnl_pct > 0,
        "exit_reason": exit_reason,
    }).eq("id", trade["id"]).eq("status", "OPEN").execute()

    # Forward to the learning loop. Best-effort — never blocks the close.
    # Watchdog only acts on brain trades, but the helper double-checks
    # source internally so this stays safe.
    try:
        from app.services.virtual_portfolio import _record_brain_outcome
        _record_brain_outcome(trade, exit_price, exit_score, exit_reason, pnl_pct)
    except Exception as e:
        from loguru import logger
        logger.warning(f"Watchdog failed to record outcome for {trade.get('symbol')}: {e}")
