"""Log service — captures loguru output into a circular buffer for streaming.

Provides in-memory log buffer (last 500 entries) and optional DB persistence
with 7-day retention.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger

# Circular buffer — last 500 log entries in memory
_LOG_BUFFER: deque[dict] = deque(maxlen=500)

# WebSocket subscribers
_subscribers: set[asyncio.Queue] = set()

# ── Secret scrubbing ──
# Applied to every log message before it reaches any sink (buffer, WebSocket,
# DB persistence, terminal/log file). Order matters: specific patterns first.
_REDACTED = "[REDACTED]"
_SCRUB_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Telegram bot token inside API URLs: .../bot123456:ABC-def/sendMessage
    (re.compile(r"bot\d{5,}:[A-Za-z0-9_-]{20,}"), "bot" + _REDACTED),
    # Bare Telegram bot token
    (re.compile(r"\b\d{5,}:[A-Za-z0-9_-]{30,}"), _REDACTED),
    # Anthropic / xAI / Google API keys
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"), _REDACTED),
    (re.compile(r"\bxai-[A-Za-z0-9_-]{8,}"), _REDACTED),
    (re.compile(r"AIza[0-9A-Za-z_-]{20,}"), _REDACTED),
    # JWTs (access/brain tokens, Supabase keys): header.payload[.signature]
    (re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}(?:\.[A-Za-z0-9_-]*)?"), _REDACTED),
    # Bearer tokens in headers
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1" + _REDACTED),
    # Secret-looking query/form params: ?api_key=..., &key=..., token=...
    (re.compile(r"(?i)\b((?:api[_-]?key|apikey|key|token|access_token|jwt|secret|password)=)[^&\s\"'<>]+"), r"\1" + _REDACTED),
]


def scrub_secrets(text: str) -> str:
    """Redact API keys, bot tokens, and JWTs from a log string."""
    if not text:
        return text
    for pattern, repl in _SCRUB_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def _scrub_patcher(record) -> None:
    """Loguru patcher: scrub the message before any sink sees it."""
    record["message"] = scrub_secrets(record["message"])


def _loguru_sink(message):
    """Loguru sink that captures logs into the buffer and notifies subscribers."""
    record = message.record
    entry = {
        "timestamp": record["time"].isoformat(),
        "level": record["level"].name,
        "module": record["module"],
        "function": record["function"],
        "line": record["line"],
        # Scrub again here (defence in depth, in case the patcher is bypassed)
        "message": scrub_secrets(record["message"]),
    }

    _LOG_BUFFER.append(entry)

    # Notify all WebSocket subscribers
    for queue in list(_subscribers):
        try:
            queue.put_nowait(entry)
        except asyncio.QueueFull:
            pass  # Drop if subscriber is slow


def init_log_capture():
    """Initialize the loguru sink. Call once at startup."""
    # Remove default handler and add a better formatted one
    logger.remove()
    logger.configure(patcher=_scrub_patcher)
    # httpx logs full request URLs at INFO (Telegram URLs contain the bot token)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logger.add(
        _loguru_sink,
        level="DEBUG",
        format="{message}",
    )
    # Terminal output with clear ERROR/WARNING formatting and colors.
    # Scrub the fully formatted line too (covers exception tracebacks).
    logger.add(
        lambda m: print(scrub_secrets(m), end=""),
        level="DEBUG",
        format="<level>{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {module}:{function}:{line} - {message}</level>",
        colorize=True,
    )
    logger.info("Log capture initialized — streaming available")


def get_recent_logs(limit: int = 100, level: str | None = None, search: str | None = None) -> list[dict]:
    """Get recent logs from the in-memory buffer."""
    logs = list(_LOG_BUFFER)

    if level:
        logs = [l for l in logs if l["level"] == level.upper()]

    if search:
        search_lower = search.lower()
        logs = [l for l in logs if search_lower in l["message"].lower() or search_lower in l.get("module", "").lower()]

    return logs[-limit:]


def subscribe() -> asyncio.Queue:
    """Subscribe to real-time log stream. Returns a queue that receives new entries."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _subscribers.add(queue)
    return queue


def unsubscribe(queue: asyncio.Queue):
    """Unsubscribe from log stream."""
    _subscribers.discard(queue)


async def persist_logs_to_db():
    """Persist buffered logs to Supabase with 7-day TTL. Call periodically."""
    try:
        from app.db.supabase import get_client
        client = get_client()

        # Get logs from last 5 minutes (to avoid duplicates)
        cutoff = time.time() - 300
        recent = [l for l in _LOG_BUFFER if l.get("timestamp", "") > datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()]

        if recent:
            # Batch insert (ignore duplicates via created_at)
            rows = [{
                "level": l["level"],
                "module": l["module"],
                "message": l["message"][:1000],  # Truncate long messages
                "created_at": l["timestamp"],
            } for l in recent[-50]]  # Max 50 per batch

            client.table("app_logs").insert(rows).execute()

        # Cleanup: delete logs older than 7 days
        seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        client.table("app_logs").delete().lt("created_at", seven_days_ago).execute()

    except Exception as e:
        # Don't log this to avoid recursion — just silently fail
        pass
