"""IP-based rate limiting for auth endpoints.

Uses in-memory tracking with bounded size. For multi-worker production,
replace with Redis TTL keys.
"""

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

# Bounded ordered dicts (LRU-style eviction)
_login_attempts: OrderedDict[str, list[float]] = OrderedDict()
_blocked_ips: OrderedDict[str, float] = OrderedDict()

RATE_LIMITED_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/verify-otp",
}


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path not in RATE_LIMITED_PATHS:
            return await call_next(request)

        ip = get_client_ip(request)
        now = time.time()

        # Check if IP is blocked
        if ip in _blocked_ips:
            block_until = _blocked_ips[ip]
            if now < block_until:
                remaining = int(block_until - now)
                logger.warning(f"Blocked IP {ip} attempted auth ({remaining}s remaining)")
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={"detail": f"Too many attempts. Try again in {remaining} seconds."},
                    headers={"Retry-After": str(remaining)},
                )
            else:
                del _blocked_ips[ip]

        # Clean old attempts outside the window
        window_seconds = settings.rate_limit_window_minutes * 60
        cutoff = now - window_seconds
        if ip in _login_attempts:
            _login_attempts[ip] = [t for t in _login_attempts[ip] if t > cutoff]

        # Check rate limit
        attempts = _login_attempts.get(ip, [])
        if len(attempts) >= settings.max_login_attempts_per_ip:
            _blocked_ips[ip] = now + window_seconds
            _evict_if_needed(_blocked_ips, MAX_TRACKED_IPS)
            logger.warning(f"Rate limit exceeded for {ip}: {len(attempts)} attempts")
            insert_audit_log(
                event_type=AuditEvent.RATE_LIMIT_EXCEEDED,
                success=False,
                ip_address=ip,
                user_agent=request.headers.get("User-Agent", ""),
                metadata={"path": path, "attempts": len(attempts)},
            )
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": f"Too many attempts. Try again in {settings.rate_limit_window_minutes} minutes."},
                headers={"Retry-After": str(window_seconds)},
            )

        # Process request
        response = await call_next(request)

        # Only count failed attempts (4xx responses)
        if response.status_code >= 400:
            if ip not in _login_attempts:
                _login_attempts[ip] = []
            _login_attempts[ip].append(now)
            _evict_if_needed(_login_attempts, MAX_TRACKED_IPS)

        return response


def _evict_if_needed(store: OrderedDict, max_size: int):
    """Evict oldest entries if store exceeds max size."""
    while len(store) > max_size:
        store.popitem(last=False)
