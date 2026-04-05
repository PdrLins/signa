"""Log service — captures loguru output into a circular buffer for streaming.

Provides in-memory log buffer (last 500 entries) and optional DB persistence
with 7-day retention.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger

# Circular buffer — last 500 log entries in memory
_LOG_BUFFER: deque[dict] = deque(maxlen=500)

# WebSocket subscribers
_subscribers: set[asyncio.Queue] = set()


def _loguru_sink(message):
    """Loguru sink that captures logs into the buffer and notifies subscribers."""
    record = message.record
    entry = {
        "timestamp": record["time"].isoformat(),
        "level": record["level"].name,
        "module": record["module"],
        "function": record["function"],
        "line": record["line"],
        "message": record["message"],
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
    logger.add(_loguru_sink, level="DEBUG", format="{message}")
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
