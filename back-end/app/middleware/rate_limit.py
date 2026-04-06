"""Tiered IP-based rate limiting for all endpoints.

Three tiers:
- AUTH: 5 requests per 15 minutes (login, OTP)
- STRICT: 3 requests per 5 minutes (scan trigger, learning analyze)
- STANDARD: 60 requests per minute (all other protected endpoints)

Uses in-memory tracking with bounded size and threading lock.
For multi-worker production, replace with Redis TTL keys.
"""

import threading
import time
from collections import OrderedDict

from fastapi import Request, status
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.utils import get_client_ip
from app.db.queries import insert_audit_log
from app.models.audit import AuditEvent

MAX_TRACKED_IPS = 10_000

# ── Tier definitions ──
# (max_requests, window_seconds, count_only_failures)
TIER_AUTH = (5, 15 * 60, True)       # 5 failed attempts per 15 min
TIER_STRICT = (3, 5 * 60, False)     # 3 requests per 5 min
TIER_STANDARD = (60, 60, False)      # 60 requests per minute

# Path → tier mapping
_AUTH_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/verify-otp",
}

_STRICT_PATHS = {
    "/api/v1/scans/trigger",
    "/api/v1/learning/analyze",
    "/api/v1/learning/outcomes",
}

# Paths exempt from rate limiting
_EXEMPT_PATHS = {
    "/api/v1/health",
    "/api/v1/telegram/webhook",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/",
}

# ── Thread-safe storage ──
_lock = threading.Lock()
_attempts: dict[str, OrderedDict[str, list[float]]] = {
    "auth": OrderedDict(),
    "strict": OrderedDict(),
    "standard": OrderedDict(),
}
_blocked: OrderedDict[str, float] = OrderedDict()


def _get_tier(path: str) -> tuple[str, int, int, bool]:
    """Return (tier_name, max_requests, window_seconds, count_only_failures)."""
    if path in _AUTH_PATHS:
        return ("auth", *TIER_AUTH)
    if path in _STRICT_PATHS:
        return ("strict", *TIER_STRICT)
    return ("standard", *TIER_STANDARD)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip exempt paths (includes scan progress polling)
        if path in _EXEMPT_PATHS or path.startswith("/docs") or path.startswith("/redoc") or "/progress" in path:
            return await call_next(request)

        ip = get_client_ip(request)
        now = time.time()
        tier_name, max_requests, window_seconds, count_only_failures = _get_tier(path)
        bucket_key = f"{ip}|{tier_name}"
        should_block = False
        should_audit = False
        attempt_count = 0

        with _lock:
            # Check global block (from auth tier)
            if ip in _blocked:
                block_until = _blocked[ip]
                if now < block_until:
                    remaining = int(block_until - now)
                    return JSONResponse(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        content={"detail": f"Too many requests. Try again in {remaining} seconds."},
                        headers={"Retry-After": str(remaining)},
                    )
                else:
                    _blocked.pop(ip, None)

            store = _attempts[tier_name]

            # Clean old attempts outside the window
            cutoff = now - window_seconds
            if bucket_key in store:
                store[bucket_key] = [t for t in store[bucket_key] if t > cutoff]

            attempts = store.get(bucket_key, [])
            attempt_count = len(attempts)

            if attempt_count >= max_requests:
                should_block = True
                if tier_name == "auth":
                    _blocked[ip] = now + window_seconds
                    _evict_if_needed(_blocked, MAX_TRACKED_IPS)
                    should_audit = True

        # DB I/O and response outside lock
        if should_block:
            if should_audit:
                insert_audit_log(
                    event_type=AuditEvent.RATE_LIMIT_EXCEEDED,
                    success=False,
                    ip_address=ip,
                    user_agent=request.headers.get("User-Agent", ""),
                    metadata={"path": path, "tier": tier_name, "attempts": attempt_count},
                )
            logger.warning(f"Rate limit [{tier_name}] exceeded for {ip}: {attempt_count} requests on {path}")
            retry_after = window_seconds if tier_name == "auth" else 10
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Rate limit exceeded. Try again later."},
                headers={"Retry-After": str(retry_after)},
            )

        # Process request (outside lock)
        response = await call_next(request)

        # Record attempt
        should_record = not count_only_failures or response.status_code >= 400
        if should_record:
            with _lock:
                store = _attempts[tier_name]
                if bucket_key not in store:
                    store[bucket_key] = []
                store[bucket_key].append(now)
                _evict_if_needed(store, MAX_TRACKED_IPS)

        return response


def _evict_if_needed(store: OrderedDict, max_size: int):
    """Evict oldest entries if store exceeds max size. Must be called under _lock."""
    while len(store) > max_size:
        store.popitem(last=False)
