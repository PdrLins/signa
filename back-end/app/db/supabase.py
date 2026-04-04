"""Supabase client singleton (thread-safe)."""

import threading

from loguru import logger
from supabase import Client, create_client

from app.core.config import settings

_client: Client | None = None
_lock = threading.Lock()


def get_client() -> Client:
    """Get or create the Supabase client singleton."""
    global _client
    if _client is not None:
        return _client
    with _lock:
        if _client is not None:
            return _client
        _client = create_client(settings.supabase_url, settings.supabase_key)
        logger.info("Supabase client initialized")
        return _client
