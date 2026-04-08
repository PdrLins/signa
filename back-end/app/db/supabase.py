"""Supabase client singleton (thread-safe) with auto-reconnect and retry."""

import threading
import time
from functools import wraps

from loguru import logger
from supabase import Client, create_client

from app.core.config import settings

_client: Client | None = None
_lock = threading.Lock()
_last_created: float = 0
_MAX_AGE = 1800  # Recreate client every 30 min; with_retry handles stale connections


def get_client() -> Client:
    """Get or create the Supabase client singleton.

    Recreates the client if the connection is older than 30 minutes.
    The @with_retry decorator handles stale connection errors.
    """
    global _client, _last_created
    now = time.time()

    if _client is not None and (now - _last_created) < _MAX_AGE:
        return _client

    with _lock:
        # Double-check after acquiring lock
        if _client is not None and (now - _last_created) < _MAX_AGE:
            return _client

        was_first = _last_created == 0
        _client = create_client(settings.supabase_url, settings.supabase_key)
        _last_created = now
        if was_first:
            logger.info("Supabase client initialized")
        else:
            logger.debug("Supabase client reconnected (stale connection)")
        return _client


def reset_client():
    """Force reset the client on next call. Use after connection errors."""
    global _client, _last_created
    with _lock:
        _client = None
        _last_created = 0


def with_retry(fn):
    """Decorator that retries a function once on Supabase connection errors.

    On RemoteProtocolError or ConnectionError, resets the client and retries.
    This handles Supabase's aggressive HTTP/2 connection termination.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            error_str = str(e).lower()
            if "disconnected" in error_str or "remoteerror" in error_str or "connectionterminated" in error_str or "remoteprotocol" in error_str:
                logger.warning(f"Supabase connection dropped in {fn.__name__}, reconnecting and retrying...")
                reset_client()
                return fn(*args, **kwargs)
            raise
    return wrapper
