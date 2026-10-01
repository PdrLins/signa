"""JWT authentication middleware.

Validates JWT on protected routes.
Sets request.state.user for downstream dependencies.
"""

import asyncio

from fastapi import Request, status
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.access import get_user_access, reset_request_level, set_request_level
from app.core.config import settings
from app.core.security import decode_token
from app.core.utils import get_client_ip
from app.core.cache import TTLCache
from app.db.queries import insert_audit_log, is_token_blacklisted, touch_user_last_seen
from app.models.audit import AuditEvent
from app.services import sessions

# users.last_seen_at (migration 014) is written at most once per hour per
# user and process; it decides which symbols the quotes job refreshes.
LAST_SEEN_EVERY_S = 3600
_last_seen_written = TTLCache(max_size=10000, default_ttl=LAST_SEEN_EVERY_S)

PUBLIC_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/verify-otp",
    "/api/v1/auth/refresh",
    "/api/v1/auth/token/refresh",
    "/api/v1/auth/register",          # invite-only sign-up (migration 019)
    "/api/v1/health",
    "/api/v1/telegram/webhook",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/",
}
# Public path prefixes (a path parameter follows): invite-code lookup.
PUBLIC_PREFIXES = ("/api/v1/auth/referral/",)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # CORS preflight: always allow OPTIONS through
        if request.method == "OPTIONS":
            return await call_next(request)

        # Public paths: no auth needed
        if (path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)
                or path.startswith("/docs") or path.startswith("/redoc")):
            return await call_next(request)

        # Extract token
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            _log_unauthorized(request, path, "missing_token")
            return _unauthorized_response("Missing authentication token")

        token = auth_header.split(" ", 1)[1]
        payload = decode_token(token)

        if payload is None:
            _log_unauthorized(request, path, "invalid_token")
            return _unauthorized_response("Invalid or expired token")

        # Check blacklist
        jti = payload.get("jti")
        if jti and is_token_blacklisted(jti):
            _log_unauthorized(request, path, "revoked_token", payload.get("sub"))
            return _unauthorized_response("Token has been revoked")

        # Signed-out device (migration 017): the token is tied to a session
        # that was revoked or expired. Cached briefly (sessions.is_active).
        sid = payload.get("sid")
        if sid and not await asyncio.to_thread(sessions.is_active, sid):
            _log_unauthorized(request, path, "session_revoked", payload.get("sub"))
            return _unauthorized_response("Session has ended. Please sign in again.")

        # Set user on request state (consumed by get_current_user dependency)
        # Access level comes from the DB (cached 60s), not the token, so a
        # change applies without logging out.
        access = get_user_access(payload.get("sub"))
        level = effective_level(access["level"], request.headers.get("X-View-As"))
        request.state.user = {
            "user_id": payload.get("sub"),
            "username": payload.get("username"),
            "jti": jti,
            "sid": sid,
            "access_level": level,
            "real_access_level": access["level"],
            "slot_bonus": access["slot_bonus"],
        }

        _touch_last_seen(payload.get("sub"))

        # The AI layer reads this to refuse calls for users without system.ai.
        level_token = set_request_level(level)
        try:
            return await call_next(request)
        finally:
            reset_request_level(level_token)


def effective_level(real_level: str, view_as: str | None) -> str:
    """Dev tools: an owner may preview the app as a lower level with the
    X-View-As header when settings.dev_tools_enabled. Everyone else, and
    every request in production, gets their real level."""
    if (settings.dev_tools_enabled and real_level == "owner"
            and view_as in ("free", "premium", "owner")):
        return view_as
    return real_level


def _touch_last_seen(user_id: str | None) -> None:
    """Fire-and-forget users.last_seen_at update, at most hourly. Never raises."""
    if not user_id or _last_seen_written.get(user_id):
        return
    _last_seen_written.set(user_id, True)

    def write() -> None:
        try:
            touch_user_last_seen(user_id)
        except Exception as e:  # before migration 014, or DB down: activity falls back to last_login
            logger.debug(f"last_seen_at not written for {user_id}: {e}")
    import threading
    threading.Thread(target=write, name="last-seen", daemon=True).start()


def _unauthorized_response(detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": detail},
        headers={"WWW-Authenticate": "Bearer"},
    )


def _log_unauthorized(request: Request, path: str, reason: str, user_id: str | None = None):
    insert_audit_log(
        event_type=AuditEvent.UNAUTHORIZED_ACCESS,
        success=False,
        user_id=user_id,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
        metadata={"path": path, "reason": reason},
    )
