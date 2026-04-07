"""Supabase client singleton (thread-safe) with auto-reconnect."""

import threading
import time

from loguru import logger
from supabase import Client, create_client

from app.core.config import settings

_client: Client | None = None
_lock = threading.Lock()
_last_created: float = 0
_MAX_AGE = 1800  # Recreate client every 30 min to avoid stale HTTP/2 connections


def get_client() -> Client:
    """Get or create the Supabase client singleton.

    Recreates the client if the connection is older than 30 minutes
    to prevent stale HTTP/2 connections from causing 'Server disconnected' errors.
    """
    global _client, _last_created
    now = time.time()

    if _client is not None and (now - _last_created) < _MAX_AGE:
        return _client

    with _lock:
        # Double-check after acquiring lock
        if _client is not None and (now - _last_created) < _MAX_AGE:
            return _client

        _client = create_client(settings.supabase_url, settings.supabase_key)
        _last_created = now
        if _last_created == 0:
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
