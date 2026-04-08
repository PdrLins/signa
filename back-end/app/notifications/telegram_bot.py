"""Telegram bot — send alerts and handle commands."""

from datetime import datetime, timezone
from html import escape
from zoneinfo import ZoneInfo

import httpx
from loguru import logger

from app.core.config import settings


def _now_et() -> str:
    """Current date/time in ET for Telegram messages."""
    et = ZoneInfo("America/New_York")
    return datetime.now(timezone.utc).astimezone(et).strftime("%b %d, %Y • %I:%M %p ET")

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


async def send_message(chat_id: str, text: str, parse_mode: str = "HTML", urgent: bool = False) -> bool:
    """Send a message via Telegram Bot API."""
    from app.notifications.messages import is_quiet_hours
    if not urgent and is_quiet_hours():
        logger.debug(f"Telegram message suppressed (quiet hours): {text[:50]}...")
        return False
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
    from app.notifications.messages import msg
    return await send_message(chat_id, msg("otp", otp_code=escape(otp_code)), urgent=True)


async def send_gem_alert(signal: dict) -> bool:
    """Send a GEM alert for a high-conviction signal."""
    from app.notifications.messages import msg
    ticker = escape(str(signal.get("symbol", "?")))
    catalyst = escape(str(signal.get("catalyst", "")))
    catalyst_line = f"\n🚀 Catalyst: {catalyst}" if catalyst else ""

    message = msg("gem_alert",
        ticker=ticker,
        date=_now_et(),
        action=escape(str(signal.get("action", "?"))),
        score=signal.get("score", 0),
        price=signal.get("price_at_signal", "?"),
        target=signal.get("target_price", "?"),
        stop=signal.get("stop_loss", "?"),
        rr=signal.get("risk_reward", "?"),
        reasoning=escape(str(signal.get("reasoning", ""))),
        catalyst_line=catalyst_line,
    )
    return await send_message(settings.telegram_chat_id, message)


async def send_scan_digest(scan_type: str, signals: list[dict]) -> bool:
    """Send a scan summary digest."""
    from app.notifications.messages import msg
    sorted_signals = sorted(signals, key=lambda s: s.get("score", 0), reverse=True)
    top_3 = sorted_signals[:3]
    gems = [s for s in signals if s.get("is_gem")]
    buys = [s for s in signals if s.get("action") == "BUY"]

    scan_label = escape(scan_type.replace("_", " ").title())
    message = msg("scan_digest_header",
        scan_label=scan_label,
        date=_now_et(),
        total=len(signals),
        buys=len(buys),
        gems=len(gems),
    )

    if top_3:
        message += msg("scan_digest_top3")
        for i, s in enumerate(top_3, 1):
            sym = escape(str(s.get("symbol", "?")))
            act = escape(str(s.get("action", "?")))
            emoji = "💎" if s.get("is_gem") else "📈" if s.get("action") == "BUY" else "📊"
            message += f"{i}. {emoji} <b>{sym}</b> — {act} ({s.get('score', 0)}/100)\n"

    if gems:
        message += msg("scan_digest_gem_footer", count=len(gems))

    return await send_message(settings.telegram_chat_id, message)


async def send_watchlist_sell_alert(signal: dict) -> bool:
    """Send an urgent alert when a watchlisted ticker gets a SELL or AVOID signal."""
    from app.notifications.messages import msg
    action = escape(str(signal.get("action", "?")))
    emoji = "🚨" if action == "SELL" else "⚠️"

    # Build target/stop line
    target = signal.get("target_price")
    stop = signal.get("stop_loss")
    target_line = ""
    if target or stop:
        parts = []
        if target:
            parts.append(f"Target: ${target}")
        if stop:
            parts.append(f"Stop: ${stop}")
        target_line = "🎯 " + " | ".join(parts) + "\n"

    # Bucket line
    bucket = signal.get("bucket")
    bucket_label = "Safe Income" if bucket == "SAFE_INCOME" else "High Risk" if bucket == "HIGH_RISK" else ""
    bucket_line = f"📦 {bucket_label}\n" if bucket_label else ""

    # Better reasoning — replace tech-only placeholder
    reasoning = str(signal.get("reasoning", ""))
    if "AI skipped" in reasoning:
        reasoning = f"Score {signal.get('score', 0)}/100 based on technical + fundamental analysis. Below AI threshold — consider reviewing manually."

    message = msg("watchlist_sell",
        emoji=emoji,
        ticker=escape(str(signal.get("symbol", "?"))),
        date=_now_et(),
        action=action,
        score=signal.get("score", 0),
        status=escape(str(signal.get("status", "?"))),
        price=signal.get("price_at_signal", "?"),
        target_line=target_line,
        bucket_line=bucket_line,
        reasoning=escape(reasoning),
    )
    return await send_message(settings.telegram_chat_id, message)


async def handle_command(command: str, args: str = "", user_id: str = "") -> str:
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
            watchlist_service.add_to_watchlist(user_id, ticker)
            return f"✅ Added {escape(ticker)} to watchlist"
        items = watchlist_service.get_watchlist(user_id)
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
        removed = watchlist_service.remove_from_watchlist(user_id, ticker)
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
        positions = position_service.get_open_positions(user_id)
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
        positions = position_service.get_open_positions(user_id)
        match = [p for p in positions if p.get("symbol") == ticker]
        if not match:
            return f"No open position for {escape(ticker)}"
        result = position_service.close_position_by_id(match[0]["id"], price)
        if result:
            pnl = result.get("pnl_percent", 0)
            amt = result.get("pnl_amount", 0)
            return f"✅ Closed {escape(ticker)} @ ${price:.2f}\nP&L: {'+' if float(pnl) >= 0 else ''}{float(pnl):.1f}% (${float(amt):+.2f})"
        return f"Failed to close position for {escape(ticker)}"

    elif command == "forcesell":
        # Manual override for pending review positions: confirm sell at next open.
        # Uses the sentinel pending_review_action="FORCE_SELL" so process_pending_reviews
        # can detect it reliably without parsing the reason text.
        if not args:
            return "Usage: /forcesell TICKER\nForces a flagged position to sell at next market open."
        ticker = args.strip().upper()
        from app.db.supabase import get_client as _get_db
        _db = _get_db()
        try:
            flagged = (
                _db.table("virtual_trades")
                .select("id, symbol, source, pending_review_action, pending_review_score, entry_score")
                .eq("status", "OPEN")
                .eq("symbol", ticker)
                .not_.is_("pending_review_at", "null")
                .execute()
            )
            rows = flagged.data or []
            if not rows:
                return f"❌ {escape(ticker)} is not flagged for review"
            for row in rows:
                _db.table("virtual_trades").update({
                    "pending_review_action": "FORCE_SELL",
                    "pending_review_reason": "User forced sell via Telegram /forcesell",
                }).eq("id", row["id"]).execute()
            return (
                f"✅ {escape(ticker)} marked to <b>force sell</b> at next market open.\n"
                f"The next scan during 9:30am-4:00pm ET will execute the sell."
            )
        except Exception as e:
            logger.warning(f"/forcesell error: {e}")
            return f"❌ Failed to mark {escape(ticker)} for force sell"

    elif command == "keep":
        # Manual override for pending review positions: clear the flag (keep position)
        if not args:
            return "Usage: /keep TICKER\nClears a pending review flag — brain keeps the position."
        ticker = args.strip().upper()
        from app.db.supabase import get_client as _get_db
        _db = _get_db()
        try:
            flagged = (
                _db.table("virtual_trades")
                .select("id, symbol")
                .eq("status", "OPEN")
                .eq("symbol", ticker)
                .not_.is_("pending_review_at", "null")
                .execute()
            )
            rows = flagged.data or []
            if not rows:
                return f"❌ {escape(ticker)} is not flagged for review"
            for row in rows:
                _db.table("virtual_trades").update({
                    "pending_review_at": None,
                    "pending_review_action": None,
                    "pending_review_score": None,
                    "pending_review_reason": None,
                }).eq("id", row["id"]).execute()
            return (
                f"✅ {escape(ticker)} review flag cleared. Position kept.\n"
                f"Brain will continue normal monitoring."
            )
        except Exception as e:
            logger.warning(f"/keep error: {e}")
            return f"❌ Failed to clear flag for {escape(ticker)}"

    elif command == "review":
        # List all positions currently flagged for review
        from app.db.supabase import get_client as _get_db
        _db = _get_db()
        try:
            flagged = (
                _db.table("virtual_trades")
                .select("symbol, source, entry_score, pending_review_action, pending_review_score, pending_review_reason")
                .eq("status", "OPEN")
                .not_.is_("pending_review_at", "null")
                .execute()
            )
            rows = flagged.data or []
            if not rows:
                return "No positions flagged for review."
            lines = ["<b>⚠ Positions Flagged for Review:</b>\n"]
            for r in rows:
                sym = escape(str(r.get("symbol", "?")))
                act = escape(str(r.get("pending_review_action", "?")))
                es = r.get("entry_score", 0) or 0
                ps = r.get("pending_review_score", 0) or 0
                src = escape(str(r.get("source", "?")))
                lines.append(f"• <b>{sym}</b> [{src}] — {act} (score {es}→{ps})")
            lines.append("\nUse /forcesell TICKER to confirm sell at open")
            lines.append("Use /keep TICKER to clear the flag and keep")
            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"/review error: {e}")
            return "❌ Failed to fetch flagged positions"

    elif command in ("start", "help"):
        from app.notifications.messages import msg
        return msg("bot_help")

    return "Unknown command. Try /help"
