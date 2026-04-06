"""Simple in-memory TTL cache for hot paths.

Thread-safe, bounded, with automatic expiry.
For multi-worker production, replace with Redis.
"""

import threading
import time
from collections import OrderedDict
from typing import Any


class TTLCache:
    """In-memory cache with per-key TTL and bounded size."""

    def __init__(self, max_size: int = 1000, default_ttl: int = 60):
        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = threading.Lock()
        self._max_size = max_size
        self._default_ttl = default_ttl

    def get(self, key: str) -> Any | None:
        """Get a value if it exists and hasn't expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.time() > expires_at:
                del self._store[key]
                return None
            # Move to end (LRU)
            self._store.move_to_end(key)
            return value

    def set(self, key: str, value: Any, ttl: int | None = None):
        """Set a value with TTL in seconds."""
        ttl = ttl if ttl is not None else self._default_ttl
        with self._lock:
            self._store[key] = (value, time.time() + ttl)
            self._store.move_to_end(key)
            while len(self._store) > self._max_size:
                self._store.popitem(last=False)

    def delete(self, key: str):
        """Remove a key from the cache."""
        with self._lock:
            self._store.pop(key, None)

    def clear(self):
        """Clear all entries."""
        with self._lock:
            self._store.clear()

    def cleanup(self):
        """Remove all expired entries."""
        now = time.time()
        with self._lock:
            expired = [k for k, (_, exp) in self._store.items() if now > exp]
            for k in expired:
                del self._store[k]


# ── Shared cache instances ──

# Token blacklist: short TTL since revocation must propagate quickly
blacklist_cache = TTLCache(max_size=5000, default_ttl=30)

# Stats/signals: longer TTL for expensive queries
stats_cache = TTLCache(max_size=100, default_ttl=30)

# yfinance price data: cache for 60s to avoid hammering Yahoo
price_cache = TTLCache(max_size=500, default_ttl=60)

# Brain editor rate limiting (OTP challenges, attempts, lockouts)
brain_challenge_cache = TTLCache(max_size=500, default_ttl=900)
brain_otp_attempt_cache = TTLCache(max_size=500, default_ttl=900)
brain_lockout_cache = TTLCache(max_size=500, default_ttl=900)

# Login attempt tracking (lockout after 3 failures, 10 min TTL)
login_attempt_cache = TTLCache(max_size=1000, default_ttl=600)
