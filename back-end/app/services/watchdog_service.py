"""Brain Watchdog — high-frequency stop enforcement for open brain positions.

============================================================
WHAT THIS MODULE IS
============================================================

Scans run a handful of times per day; stops must be enforced in between.
Every run (every 15 min in US hours, and around the clock for crypto —
see app/scheduler/runner.py) the watchdog:

  1. loads every OPEN brain position that can actually fill right now
     (crypto 24/7; equities only in the US session on an open exchange),
  2. fetches a fresh price,
  3. applies THE SAME exit policy the scan uses —
     `virtual_portfolio.evaluate_exit` — which enforces each position's own
     stop_loss (including the ATR trailing ratchet), target and time stop,
  4. persists any ratcheted stop / new peak, closes through the shared
     `close_virtual_trade`, and logs a watchdog_events row.

Because both paths call one function with the same inputs, the scan and
the watchdog can never contradict each other.

============================================================
WHAT WAS REMOVED IN THE 2026-09 RESET (and why)
============================================================

  * WATCHDOG_EXIT on a single bearish sentiment call when P&L < 0 — one
    noisy LLM read was closing positions long before their stop.
  * WATCHDOG_FORCE_SELL on latest score < 50 or SELL/AVOID + red P&L —
    duplicated (and contradicted) the scan's signal policy.
  * The fixed −8% "catastrophic" force-sell — replaced by the position's
    real stop, which is always hard. A row with no stop uses
    `brain_catastrophic_stop_pct` as a safety net inside evaluate_exit.
  * Sentiment calls (Grok) — no longer needed; zero AI cost.

What remains besides exits: a WARNING alert (no action) when price is
within `watchdog_stop_proximity_pct` of the stop, throttled per position.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from loguru import logger

from app.core.config import settings
from app.db.supabase import get_client
from app.notifications.messages import msg
from app.notifications.telegram_bot import enqueue as _tg_send
from app.services.price_cache import _fetch_prices_batch


EVENT_ALERT = "ALERT"
EVENT_CLOSE = "CLOSE"
EVENT_HOLD = "HOLD_THROUGH_DIP"
EVENT_RECOVERY = "RECOVERY"
# Kept for dashboards that filter historical watchdog_events by type; the
# grace path that emitted it was removed in the 2026-09 reset.
EVENT_GRACE_PROTECTED = "GRACE_PROTECTED"


@dataclass
class WatchdogEntry:
    """In-memory alert throttle for a tracked position (not a source of truth)."""
    alert_level: str = "normal"
    last_alert_at: float = 0.0


_state: dict[str, WatchdogEntry] = {}
ALERT_THROTTLE_SECONDS = 3600


def _stop_distance_pct(price: float, stop: float | None, direction: str) -> float | None:
    if not stop or not price:
        return None
    if direction == "SHORT":
        return (stop - price) / price * 100
    return (price - stop) / price * 100


async def run_watchdog() -> dict:
    """One watchdog cycle. Returns {positions, checked, concerned, alerts, closes}."""
    if not settings.watchdog_enabled:
        return {"skipped": True}

    from app.services.virtual_portfolio import (
        VIRTUAL_TRADES_CLOSE_FIELDS,
        _is_tradable_now,
        _is_us_market_open,
        close_virtual_trade,
        evaluate_exit,
        persist_exit_state,
    )

    db = get_client()
    open_trades = (
        db.table("virtual_trades")
        .select(VIRTUAL_TRADES_CLOSE_FIELDS)
        .eq("status", "OPEN")
        .eq("source", "brain")
        .execute()
    ).data or []
    if not open_trades:
        _state.clear()
        return {"positions": 0, "checked": 0, "concerned": [], "alerts": 0, "closes": 0}

    all_open_ids = {t["id"] for t in open_trades}
    for k in set(_state) - all_open_ids:
        del _state[k]

    market_open = _is_us_market_open()
    tradable = [t for t in open_trades if _is_tradable_now(t["symbol"], market_open)]
    skipped = len(open_trades) - len(tradable)
    if not tradable:
        return {"positions": 0, "checked": 0, "concerned": [], "alerts": 0, "closes": 0,
                "skipped_equity": skipped}

    symbols = list({t["symbol"] for t in tradable})
    prices = await asyncio.to_thread(_fetch_prices_batch, symbols)

    now = time.time()
    alerts = closes = 0
    concerned: list[str] = []
    events: list[dict] = []

    for trade in tradable:
        symbol = trade["symbol"]
        price, _ = prices.get(symbol, (None, None))
        if not price:
            continue
        direction = trade.get("direction") or "LONG"
        entry = float(trade["entry_price"])
        pnl_pct = ((entry - price) if direction == "SHORT" else (price - entry)) / entry * 100
        state = _state.setdefault(trade["id"], WatchdogEntry())

        decision = evaluate_exit(trade, float(price))
        await asyncio.to_thread(persist_exit_state, db, trade, decision)

        if decision.reason:
            try:
                res = await asyncio.to_thread(
                    close_virtual_trade, trade, float(price), decision.reason, None,
                )
            except Exception as e:
                logger.exception(f"Watchdog close failed for {symbol}: {e}")
                continue
            if res.get("skipped"):
                continue
            closes += 1
            events.append({
                "symbol": symbol, "event_type": EVENT_CLOSE, "action_taken": decision.reason.lower(),
                "price": price, "entry_price": entry, "pnl_pct": round(res["pnl_pct"], 2),
                "stop_loss": decision.stop, "notes": f"watchdog: {decision.detail}",
            })
            _tg_send(settings.telegram_chat_id, msg(
                "watchdog_force_sell", symbol=symbol, price=f"{price:.2f}",
                pnl=f"{res['pnl_pct']:+.1f}", reason=f"{decision.reason} — {decision.detail}"), urgent=True)
            alerts += 1
            logger.warning(f"Watchdog CLOSED {symbol}: {decision.reason} ({decision.detail})")
            continue

        dist = _stop_distance_pct(float(price), decision.stop, direction)
        near_stop = dist is not None and dist <= settings.watchdog_stop_proximity_pct
        if near_stop:
            concerned.append(symbol)
            if state.alert_level != "concerned" or now - state.last_alert_at >= ALERT_THROTTLE_SECONDS:
                state.alert_level, state.last_alert_at = "concerned", now
                events.append({
                    "symbol": symbol, "event_type": EVENT_ALERT, "action_taken": "warned",
                    "price": price, "entry_price": entry, "pnl_pct": round(pnl_pct, 2),
                    "stop_loss": decision.stop, "stop_distance_pct": round(dist, 2),
                    "notes": f"within {dist:.1f}% of stop",
                })
                if abs(pnl_pct) >= settings.watchdog_min_notify_pct:
                    _tg_send(settings.telegram_chat_id, msg(
                        "watchdog_warning", symbol=symbol, price=f"{price:.2f}",
                        stop=f"{decision.stop:.2f}", pnl=f"{pnl_pct:+.1f}",
                        reason=f"within {dist:.1f}% of stop", sentiment="n/a"))
                    alerts += 1
        elif state.alert_level != "normal":
            state.alert_level = "normal"
            events.append({
                "symbol": symbol, "event_type": EVENT_RECOVERY, "action_taken": "recovered",
                "price": price, "entry_price": entry, "pnl_pct": round(pnl_pct, 2),
                "stop_loss": decision.stop, "notes": "moved away from stop",
            })

    if events:
        try:
            db.table("watchdog_events").insert(events).execute()
        except Exception as e:
            logger.warning(f"Watchdog events batch insert failed: {e}")

    summary = {"positions": len(tradable), "checked": len(symbols), "concerned": concerned,
               "alerts": alerts, "closes": closes}
    if skipped:
        summary["skipped_equity"] = skipped
    (logger.info if (concerned or closes) else logger.debug)(f"Watchdog: {summary}")
    return summary
