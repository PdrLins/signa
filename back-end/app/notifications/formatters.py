"""Message formatters for Telegram alerts."""

from html import escape


def format_signal_summary(signal: dict) -> str:
    """Format a signal into a single-line summary."""
    emoji = "💎" if signal.get("is_gem") else "📈" if signal.get("action") == "BUY" else "📊"
    sym = escape(str(signal.get("symbol", "?")))
    act = escape(str(signal.get("action", "?")))
    return f"{emoji} <b>{sym}</b> — {act} ({signal.get('score', 0)}/100)"


def format_signal_detail(signal: dict) -> str:
    """Format a signal with full details."""
    ticker = escape(str(signal.get("symbol", "?")))
    action = escape(str(signal.get("action", "?")))
    score = signal.get("score", 0)
    status = escape(str(signal.get("status", "CONFIRMED")))
    reasoning = escape(str(signal.get("reasoning", "")))
    catalyst = escape(str(signal.get("catalyst", "")))
    price = signal.get("price_at_signal")
    target = signal.get("target_price")
    stop = signal.get("stop_loss")
    rr = signal.get("risk_reward")
    bucket = escape(str(signal.get("bucket", "")))

    lines = [
        f"<b>{ticker}</b> — {action} ({score}/100)",
        f"Status: {status} | Bucket: {bucket}",
    ]

    if price:
        lines.append(f"Price: ${price}")
    if target:
        lines.append(f"Target: ${target}")
    if stop:
        lines.append(f"Stop Loss: ${stop}")
    if rr:
        lines.append(f"Risk/Reward: {rr}x")
    if reasoning:
        lines.append(f"\n📋 {reasoning}")
    if catalyst:
        lines.append(f"🚀 Catalyst: {catalyst}")

    return "\n".join(lines)


def format_morning_digest(signals: list[dict]) -> str:
    """Format the morning digest message."""
    sorted_sigs = sorted(signals, key=lambda s: s.get("score", 0), reverse=True)
    buys = [s for s in signals if s.get("action") == "BUY"]
    gems = [s for s in signals if s.get("is_gem")]

    lines = [
        "☀️ <b>Signa Morning Digest</b>\n",
        f"Total Signals: {len(signals)}",
        f"BUYs: {len(buys)} | GEMs: {len(gems)}",
        "",
        "<b>Top 3 Picks:</b>",
    ]

    for i, s in enumerate(sorted_sigs[:3], 1):
        lines.append(f"{i}. {format_signal_summary(s)}")

    if gems:
        lines.append(f"\n💎 {len(gems)} GEM Alert(s) — use /gem for details")

    return "\n".join(lines)
