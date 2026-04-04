"""Position tracking service — CRUD + monitoring + smart alerts."""

from datetime import datetime, timezone
from html import escape

from loguru import logger

from app.core.config import settings
from app.db import queries
from app.notifications.telegram_bot import send_message


def open_position(
    symbol: str,
    entry_price: float,
    shares: float,
    account_type: str | None = None,
    bucket: str | None = None,
    currency: str = "CAD",
    target_price: float | None = None,
    stop_loss: float | None = None,
    notes: str | None = None,
) -> dict:
    """Open a new position."""
    data = {
        "symbol": symbol.upper(),
        "entry_price": entry_price,
        "shares": shares,
        "account_type": account_type,
        "bucket": bucket,
        "currency": currency,
        "target_price": target_price,
        "stop_loss": stop_loss,
        "notes": notes,
        "status": "OPEN",
    }
    return queries.create_position(data)


def close_position_by_id(position_id: str, exit_price: float) -> dict:
    """Close a position and calculate P&L."""
    position = queries.get_position_by_id(position_id)
    if not position:
        return {}

    entry_price = float(position["entry_price"])
    shares = float(position["shares"])
    pnl_amount = (exit_price - entry_price) * shares
    pnl_percent = ((exit_price - entry_price) / entry_price) * 100

    return queries.close_position(
        position_id=position_id,
        exit_price=exit_price,
        exit_reason="USER_CLOSE",
        pnl_amount=pnl_amount,
        pnl_percent=pnl_percent,
    )


def get_open_positions() -> list[dict]:
    """Get all open positions."""
    return queries.get_open_positions()


def get_closed_positions(limit: int = 50) -> list[dict]:
    """Get closed positions (trade history)."""
    return queries.get_closed_positions(limit)


def get_position(position_id: str) -> dict | None:
    """Get a single position."""
    return queries.get_position_by_id(position_id)


def update_position(position_id: str, data: dict) -> dict:
    """Update a position's target, stop_loss, or notes."""
    return queries.update_position(position_id, data)


async def monitor_positions(signals: list[dict]) -> int:
    """Monitor open positions against latest scan signals.

    Called after each scan. Checks for:
    1. Stop loss hit
    2. Target price hit
    3. Signal status changed (WEAKENING, CANCELLED)
    4. P&L milestone crossed (every 5%)

    Returns number of alerts sent.
    """
    if not settings.position_monitor_enabled:
        return 0

    positions = queries.get_open_positions()
    if not positions:
        return 0

    # Build signal lookup by symbol
    signal_map = {}
    for s in signals:
        symbol = s.get("symbol")
        if symbol:
            signal_map[symbol] = s

    alerts_sent = 0

    for pos in positions:
        symbol = pos["symbol"]
        signal = signal_map.get(symbol)
        if not signal:
            continue

        current_price = signal.get("price_at_signal")
        if not current_price:
            continue

        entry_price = float(pos["entry_price"])
        shares = float(pos["shares"])
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        pnl_amount = (current_price - entry_price) * shares
        position_id = pos["id"]

        signal_score = signal.get("score", 0)
        signal_status = signal.get("status", "CONFIRMED")
        prev_score = pos.get("last_signal_score") or 0
        prev_status = pos.get("last_signal_status") or "CONFIRMED"
        last_alerted_pnl = float(pos.get("last_alerted_pnl") or 0)

        alert_message = None

        # Check 1: Stop loss hit
        stop_loss = pos.get("stop_loss")
        if stop_loss and current_price <= float(stop_loss):
            alert_message = _format_stop_alert(pos, current_price, pnl_pct, pnl_amount)
            # Auto-close
            queries.close_position(
                position_id, current_price, "STOP_HIT", pnl_amount, pnl_pct,
            )

        # Check 2: Target hit
        elif pos.get("target_price") and current_price >= float(pos["target_price"]):
            alert_message = _format_target_alert(pos, current_price, pnl_pct, pnl_amount)

        # Check 3: Signal weakened or cancelled
        elif signal_status in ("WEAKENING", "CANCELLED") and prev_status == "CONFIRMED":
            alert_message = _format_signal_alert(
                pos, current_price, pnl_pct, pnl_amount,
                signal_score, signal_status, signal.get("reasoning", ""),
            )

        # Check 4: P&L milestone (every 5%)
        elif abs(pnl_pct) >= 5:
            milestone = int(pnl_pct / 5) * 5  # Round to nearest 5%
            if milestone != 0 and abs(milestone - last_alerted_pnl) >= 5:
                alert_message = _format_pnl_alert(pos, current_price, pnl_pct, pnl_amount, milestone)
                queries.update_position(position_id, {"last_alerted_pnl": milestone})

        # Update signal tracking on position
        queries.update_position(position_id, {
            "last_signal_score": signal_score,
            "last_signal_status": signal_status,
        })

        # Send alert
        if alert_message:
            await send_message(settings.telegram_chat_id, alert_message)
            alerts_sent += 1

    if alerts_sent:
        logger.info(f"Position monitor: {alerts_sent} alerts sent for {len(positions)} open positions")

    return alerts_sent


# ============================================================
# ALERT FORMATTERS
# ============================================================

def _format_stop_alert(pos: dict, current_price: float, pnl_pct: float, pnl_amount: float) -> str:
    sym = escape(pos["symbol"])
    entry = float(pos["entry_price"])
    shares = float(pos["shares"])
    return (
        f"🔴 <b>STOP LOSS HIT — {sym}</b>\n\n"
        f"Entry: ${entry:.2f} → Stop: ${current_price:.2f}\n"
        f"P&L: {_fmt_pnl(pnl_amount, pnl_pct)}\n"
        f"Shares: {shares:.0f} | Position auto-closed\n\n"
        f"⚠️ Review the signal before re-entering."
    )


def _format_target_alert(pos: dict, current_price: float, pnl_pct: float, pnl_amount: float) -> str:
    sym = escape(pos["symbol"])
    entry = float(pos["entry_price"])
    target = float(pos["target_price"])
    return (
        f"🎯 <b>TARGET HIT — {sym}</b>\n\n"
        f"Entry: ${entry:.2f} → Target: ${target:.2f} (now ${current_price:.2f})\n"
        f"P&L: {_fmt_pnl(pnl_amount, pnl_pct)}\n\n"
        f"💡 Consider taking profit."
    )


def _format_signal_alert(
    pos: dict, current_price: float, pnl_pct: float, pnl_amount: float,
    score: int, status: str, reasoning: str,
) -> str:
    sym = escape(pos["symbol"])
    entry = float(pos["entry_price"])
    prev_score = pos.get("last_signal_score") or 0

    action_line = ""
    if pnl_pct > 0:
        action_line = f"💡 You're up {pnl_pct:+.1f}%. Signal is {status.lower()}.\nConsider taking profit now and re-entering on pullback."
    else:
        action_line = f"⚠️ You're down {pnl_pct:.1f}%. Signal is {status.lower()}.\nConsider cutting your loss."

    return (
        f"📊 <b>{sym} Position Update</b>\n\n"
        f"Entry: ${entry:.2f} → Now: ${current_price:.2f}\n"
        f"P&L: {_fmt_pnl(pnl_amount, pnl_pct)}\n\n"
        f"Signal: <b>{status}</b> (score {score}, was {prev_score})\n"
        f"{escape(reasoning[:150])}\n\n"
        f"{action_line}"
    )


def _format_pnl_alert(
    pos: dict, current_price: float, pnl_pct: float, pnl_amount: float, milestone: int,
) -> str:
    sym = escape(pos["symbol"])
    entry = float(pos["entry_price"])
    emoji = "📈" if pnl_pct > 0 else "📉"

    return (
        f"{emoji} <b>{sym} — {milestone:+d}% milestone</b>\n\n"
        f"Entry: ${entry:.2f} → Now: ${current_price:.2f}\n"
        f"P&L: {_fmt_pnl(pnl_amount, pnl_pct)}"
    )


def _fmt_pnl(amount: float, pct: float) -> str:
    """Format P&L with color."""
    sign = "+" if amount >= 0 else ""
    emoji = "✅" if amount >= 0 else "❌"
    return f"<b>{sign}${amount:.2f} ({sign}{pct:.1f}%)</b> {emoji}"
