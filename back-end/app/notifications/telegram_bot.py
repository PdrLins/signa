"""Telegram sending: a background queue + worker, the direct send and OTP.

`enqueue(chat_id, text, ...)` puts a message on an asyncio.Queue and returns
at once; `_telegram_worker()` (started in main.py's lifespan) drains it and
retries once on failure, so a slow Telegram API never blocks a request.
`send_message()` is the direct path for callers that need the result.
Messages are lost on restart (the queue is in memory).
"""

import asyncio
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


# ── Background queue + worker ──────────────────────────────────

_queue: asyncio.Queue | None = None
_worker_task: asyncio.Task | None = None


_loop: asyncio.AbstractEventLoop | None = None   # the worker's loop (enqueue from threads)


def _get_queue() -> asyncio.Queue:
    """Get or create the module-level queue (must be called inside an event loop)."""
    global _queue
    if _queue is None:
        _queue = asyncio.Queue(maxsize=200)
    return _queue


async def _telegram_worker() -> None:
    """Background task that drains the Telegram message queue forever.

    Sends one message at a time (Telegram rate limits are ~30 msg/sec per
    bot, so serialization is fine). Retries once on failure with a 2-second
    delay. Never crashes — exceptions are caught and logged.
    """
    q = _get_queue()
    logger.info("Telegram worker started")
    while True:
        try:
            chat_id, text, parse_mode, urgent = await q.get()
            success = await send_message(chat_id, text, parse_mode, urgent=urgent)
            if not success:
                # Retry once after 2 seconds
                await asyncio.sleep(2)
                await send_message(chat_id, text, parse_mode, urgent=urgent)
            q.task_done()
        except asyncio.CancelledError:
            logger.info("Telegram worker shutting down")
            break
        except Exception as e:
            logger.error(f"Telegram worker error: {type(e).__name__}")
            await asyncio.sleep(1)


def start_telegram_worker() -> None:
    """Start the background Telegram queue worker. Called from lifespan."""
    global _worker_task
    if _worker_task is not None and not _worker_task.done():
        return  # already running
    global _loop
    _loop = asyncio.get_running_loop()
    _worker_task = asyncio.ensure_future(_telegram_worker())


async def stop_telegram_worker() -> None:
    """Gracefully stop the worker, draining remaining messages first."""
    global _worker_task
    if _worker_task is None or _worker_task.done():
        return
    q = _get_queue()
    # Wait up to 10 seconds for the queue to drain
    try:
        await asyncio.wait_for(q.join(), timeout=10)
    except asyncio.TimeoutError:
        logger.warning(f"Telegram worker shutdown: {q.qsize()} messages dropped (timeout)")
    _worker_task.cancel()
    try:
        await _worker_task
    except asyncio.CancelledError:
        pass


def enqueue(chat_id: str, text: str, parse_mode: str = "HTML", urgent: bool = False) -> None:
    """Put a message on the background queue. Returns instantly (non-blocking).

    This is the preferred send path for all non-critical notifications:
    brain trades, watchdog alerts, scan digests, GEM alerts. The background
    worker handles actual delivery + retry.

    If the queue is full (200 messages — should never happen unless the
    worker is stuck), the message is dropped with a warning. This prevents
    a broken Telegram connection from backpressuring the scan pipeline.
    """
    item = (chat_id, text, parse_mode, urgent)
    try:
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if _loop is not None and running is not _loop:
            # asyncio.Queue isn't thread-safe: from a worker thread, hand it to the loop
            _loop.call_soon_threadsafe(_put, item)
            return
        _get_queue().put_nowait(item)
    except asyncio.QueueFull:
        logger.warning(f"Telegram queue full — dropped a message ({len(text)} chars)")
    except Exception as e:
        logger.warning(f"Telegram enqueue failed: {e}")


def _put(item: tuple) -> None:
    try:
        _get_queue().put_nowait(item)
    except asyncio.QueueFull:
        logger.warning("Telegram queue full — dropped a message")


# ── Direct send (still used by health ping and as the worker's backend) ──

# Chats that answered 403 (bot blocked / chat gone): delivery unlinks them.
blocked_chats: set[str] = set()


async def send_message(chat_id: str, text: str, parse_mode: str = "HTML", urgent: bool = False) -> bool:
    """Send a message via Telegram Bot API (direct, awaits HTTP response).

    Most call sites should use `enqueue()` instead. This function is kept
    for: (a) the background worker's internal send loop, (b) the health
    ping endpoint which needs to verify the send actually succeeded.
    """
    from app.notifications.messages import is_quiet_hours
    if not urgent and is_quiet_hours():
        logger.debug("Telegram message suppressed (quiet hours)")
        return False
    try:
        client = _get_http_client()
        resp = await client.post(
            _telegram_url("sendMessage"),
            json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
        )
        if resp.status_code >= 400:
            # Never log the exception/URL: httpx errors embed the request URL,
            # which contains the bot token (api.telegram.org/bot<TOKEN>/...).
            logger.error(f"Telegram send failed: HTTP {resp.status_code}")
            if resp.status_code == 403:
                blocked_chats.add(str(chat_id))   # the user blocked the bot
            return False
        return True
    except Exception as e:
        logger.error(f"Telegram send failed: {type(e).__name__}")
        return False


async def send_otp_message(chat_id: str, otp_code: str) -> bool:
    """Send an OTP verification code via Telegram (enqueued, near-instant delivery).

    The background worker drains the queue continuously so the delay between
    enqueue and actual Telegram delivery is typically <100ms. The caller
    (auth_service) returns "OTP sent" regardless of actual delivery, so
    there's no behavioral change from switching to the queue path.
    """
    from app.notifications.messages import msg
    enqueue(chat_id, msg("otp", otp_code=escape(otp_code)), urgent=True)
    return True
