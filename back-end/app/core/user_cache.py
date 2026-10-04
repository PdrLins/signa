"""Short per-user cache of the portfolio rows every screen reads.

Home, Holdings, Dividends, Allocation and the stock page all start from the
same rows (settings, accounts, holdings, transactions). Opening the app fires
several of these screens at once, so the rows are read once and kept for
USER_TTL_S seconds.

Never stale after your own change: every write request (POST/PUT/PATCH/DELETE)
by the user clears their entry before and after it runs (AuthMiddleware), and
a generation counter stops a read that started before the write from storing
its older rows afterwards. Writes made outside a request (scheduler jobs)
show within USER_TTL_S. In-process: one back-end instance (like the scheduler).
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from app.core.cache import TTLCache

USER_TTL_S = 30

_cache = TTLCache(max_size=5000, default_ttl=USER_TTL_S)
_gen: dict[str, int] = {}
_lock = threading.Lock()


def generation(uid: str) -> int:
    with _lock:
        return _gen.get(str(uid), 0)


def invalidate(uid: str | None) -> None:
    if not uid:
        return
    uid = str(uid)
    with _lock:
        _gen[uid] = _gen.get(uid, 0) + 1
        if len(_gen) > 20000:   # bounded; a dropped counter only means a re-read
            _gen.clear()
    for part in ("settings", "accounts", "people", "holdings", "transactions"):
        _cache.delete(f"{uid}:{part}")


def _copy(value: Any) -> Any:
    """Rows are flat dicts: a copy of each row (cheap, ~10x faster than deepcopy
    on 10k transactions) so a caller changing a row can't change the cache."""
    if isinstance(value, list):
        return [dict(r) if isinstance(r, dict) else r for r in value]
    if isinstance(value, dict):
        return dict(value)
    return value


def get(uid: str, part: str, load: Callable[[], Any]) -> Any:
    """The cached rows of one part (a copy, safe to change), else load()."""
    key = f"{uid}:{part}"
    hit = _cache.get(key)
    if hit is not None:
        return _copy(hit)
    gen = generation(uid)
    value = load()
    if generation(uid) == gen:
        _cache.set(key, _copy(value))
    return value


def clear() -> None:
    _cache.clear()
    with _lock:
        _gen.clear()
