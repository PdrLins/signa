"""Telegram bot — send alerts and handle commands."""

from html import escape

import httpx
from loguru import logger

from app.core.config import settings

# Reusable HTTP client (created lazily, closed on app shutdown)
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    """Get or create a reusable async HTTP client."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=15)
    return _http_client


def _telegram_url(method: str) -> str:
    """Build Telegram API URL (avoids storing token in a module-level string)."""
    return f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}"


async def send_message(chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
    """Send a message via Telegram Bot API."""
    try:
        client = _get_http_client()
        resp = await client.post(
            _telegram_url("sendMessage"),
            json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False


async def send_otp_message(chat_id: str, otp_code: str) -> bool:
    """Send an OTP verification code via Telegram."""
    message = (
        "🔐 <b>Signa Verification Code</b>\n\n"
        f"Your login code is: <code>{escape(otp_code)}</code>\n\n"
        "⏱ Valid for 2 minutes only\n"
        "Never share this code with anyone."
    )
    return await send_message(chat_id, message)


async def send_gem_alert(signal: dict) -> bool:
    """Send a GEM alert for a high-conviction signal."""
    ticker = escape(str(signal.get("symbol", "?")))
    score = signal.get("score", 0)
    action = escape(str(signal.get("action", "?")))
    reasoning = escape(str(signal.get("reasoning", "")))
    catalyst = escape(str(signal.get("catalyst", "")))
    price = signal.get("price_at_signal", "?")
    target = signal.get("target_price", "?")
    stop = signal.get("stop_loss", "?")
    rr = signal.get("risk_reward", "?")

    message = (
        f"💎 <b>GEM ALERT — {ticker}</b>\n\n"
        f"Signal: <b>{action}</b> | Score: <b>{score}/100</b>\n"
        f"Price: ${price} | Target: ${target} | Stop: ${stop}\n"
        f"Risk/Reward: {rr}x\n\n"
        f"📋 {reasoning}\n"
    )
    if catalyst:
        message += f"\n🚀 Catalyst: {catalyst}"
    message += "\n\n⚡ All 5 GEM conditions met"

    return await send_message(settings.telegram_chat_id, message)


async def send_scan_digest(scan_type: str, signals: list[dict]) -> bool:
    """Send a scan summary digest."""
    sorted_signals = sorted(signals, key=lambda s: s.get("score", 0), reverse=True)
    top_3 = sorted_signals[:3]
    gems = [s for s in signals if s.get("is_gem")]
    buys = [s for s in signals if s.get("action") == "BUY"]

    scan_label = escape(scan_type.replace("_", " ").title())
    message = (
        f"📊 <b>Signa {scan_label} Digest</b>\n\n"
        f"Signals: {len(signals)} | BUYs: {len(buys)} | GEMs: {len(gems)}\n\n"
    )

    if top_3:
        message += "<b>Top 3 Signals:</b>\n"
        for i, s in enumerate(top_3, 1):
            sym = escape(str(s.get("symbol", "?")))
            act = escape(str(s.get("action", "?")))
            emoji = "💎" if s.get("is_gem") else "📈" if s.get("action") == "BUY" else "📊"
            message += f"{i}. {emoji} <b>{sym}</b> — {act} ({s.get('score', 0)}/100)\n"

    if gems:
        message += f"\n💎 <b>{len(gems)} GEM Alert(s)</b> — check /gem for details"

    return await send_message(settings.telegram_chat_id, message)


async def handle_command(command: str, args: str = "") -> str:
    """Process a Telegram bot command and return response text."""
    from app.services import signal_service, watchlist_service

    if command == "signals":
        signals = signal_service.get_signals(limit=10)
        if not signals:
            return "No signals yet. Wait for the next scan."
        lines = ["<b>Latest Signals:</b>\n"]
        for s in signals:
            sym = escape(str(s.get("symbol", "?")))
            act = escape(str(s.get("action", "?")))
            emoji = "💎" if s.get("is_gem") else "📈" if s.get("action") == "BUY" else "📊"
            lines.append(f"{emoji} <b>{sym}</b> — {act} ({s.get('score', 0)}/100)")
        return "\n".join(lines)

    elif command == "gem":
        gems = signal_service.get_gem_signals(limit=5)
        if not gems:
            return "No GEM alerts at the moment."
        lines = ["<b>💎 GEM Alerts:</b>\n"]
        for g in gems:
            sym = escape(str(g.get("symbol", "?")))
            reasoning = escape(str(g.get("reasoning", ""))[:100])
            lines.append(f"💎 <b>{sym}</b> — Score: {g.get('score', 0)}/100\n   {reasoning}")
        return "\n".join(lines)

    elif command == "watch":
        if args:
            ticker = args.strip().upper()
            from app.core.utils import validate_ticker
            if not validate_ticker(ticker):
                return f"❌ Invalid ticker format: {escape(ticker)}"
            watchlist_service.add_to_watchlist(ticker)
            return f"✅ Added {escape(ticker)} to watchlist"
        items = watchlist_service.get_watchlist()
        if not items:
            return "Watchlist is empty. Use /watch TICKER to add."
        lines = ["<b>📋 Watchlist:</b>\n"]
        for item in items:
            lines.append(f"• {escape(str(item.get('symbol', '?')))}")
        return "\n".join(lines)

    elif command == "remove":
        if not args:
            return "Usage: /remove TICKER"
        ticker = args.strip().upper()
        removed = watchlist_service.remove_from_watchlist(ticker)
        return f"✅ Removed {escape(ticker)}" if removed else f"❌ {escape(ticker)} not found"

    elif command == "score":
        if not args:
            return "Usage: /score TICKER"
        ticker = args.strip().upper()
        sigs = signal_service.get_signals_by_ticker(ticker, limit=1)
        if not sigs:
            return f"No signals found for {escape(ticker)}"
        s = sigs[0]
        return (
            f"<b>{escape(ticker)}</b> — {escape(str(s.get('action', '?')))} ({s.get('score', 0)}/100)\n"
            f"Status: {escape(str(s.get('status', '?')))}\n"
            f"Gem: {'💎 Yes' if s.get('is_gem') else 'No'}\n"
            f"Reasoning: {escape(str(s.get('reasoning', 'N/A')))}"
        )

    elif command == "status":
        from app.db import queries as db_queries
        last_scan = db_queries.get_last_completed_scan()
        if last_scan:
            return (
                "<b>📊 Signa Status</b>\n\n"
                f"Last scan: {escape(str(last_scan.get('scan_type', '?')))}\n"
                f"Completed: {last_scan.get('completed_at', '?')}\n"
                f"Signals: {last_scan.get('signals_found', 0)}\n"
                f"GEMs: {last_scan.get('gems_found', 0)}"
            )
        return "No scans completed yet."

    elif command == "positions":
        from app.services import position_service
        positions = position_service.get_open_positions()
        if not positions:
            return "No open positions. Open one from the Signa dashboard."
        lines = ["<b>📊 Open Positions:</b>\n"]
        for p in positions:
            sym = escape(str(p.get("symbol", "?")))
            entry = float(p.get("entry_price", 0))
            shares = float(p.get("shares", 0))
            score = p.get("last_signal_score") or "?"
            status = p.get("last_signal_status") or "?"
            lines.append(
                f"• <b>{sym}</b> — {shares:.0f} shares @ ${entry:.2f}\n"
                f"  Signal: {escape(str(status))} (score {score})"
            )
        return "\n".join(lines)

    elif command == "close":
        if not args:
            return "Usage: /close TICKER PRICE\nExample: /close ENB.TO 57.20"
        parts = args.strip().split()
        if len(parts) < 2:
            return "Usage: /close TICKER PRICE"
        ticker = parts[0].upper()
        try:
            price = float(parts[1])
        except ValueError:
            return f"Invalid price: {escape(parts[1])}"
        from app.services import position_service
        positions = position_service.get_open_positions()
        match = [p for p in positions if p.get("symbol") == ticker]
        if not match:
            return f"No open position for {escape(ticker)}"
        result = position_service.close_position_by_id(match[0]["id"], price)
        if result:
            pnl = result.get("pnl_percent", 0)
            amt = result.get("pnl_amount", 0)
            return f"✅ Closed {escape(ticker)} @ ${price:.2f}\nP&L: {'+' if float(pnl) >= 0 else ''}{float(pnl):.1f}% (${float(amt):+.2f})"
        return f"Failed to close position for {escape(ticker)}"

    elif command in ("start", "help"):
        return (
            "<b>🤖 Signa Bot Commands:</b>\n\n"
            "/signals — Latest signals\n"
            "/gem — GEM alerts only\n"
            "/watch — View watchlist\n"
            "/watch TICKER — Add to watchlist\n"
            "/remove TICKER — Remove from watchlist\n"
            "/score TICKER — Get score for a ticker\n"
            "/positions — Open positions with P&L\n"
            "/close TICKER PRICE — Close a position\n"
            "/status — Bot/scan status"
        )

    return "Unknown command. Try /help"
