"""JWT authentication middleware.

Validates JWT on protected routes.
Sets request.state.user for downstream dependencies.
"""

import asyncio

from fastapi import Request, status
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

from app.core import user_cache
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
    "/api/v1/version",
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
            # An expired access token is routine (iOS: every 15 min): the app
            # refreshes it. Only other invalid tokens are audited.
            if not _is_expired(token):
                _log_unauthorized(request, path, "invalid_token")
            return _unauthorized_response("Invalid or expired token")

        jti, sid, uid = payload.get("jti"), payload.get("sid"), payload.get("sub")
        # Blacklist, session and access level: cached; misses hit the DB in ONE
        # worker thread so the event loop never waits on Supabase.
        revoked, active, access = await asyncio.to_thread(_auth_state, jti, sid, uid)
        if revoked:
            _log_unauthorized(request, path, "revoked_token", uid)
            return _unauthorized_response("Token has been revoked")
        # Signed-out device (migration 017): the token's session was revoked or expired.
        if not active:
            _log_unauthorized(request, path, "session_revoked", uid)
            return _unauthorized_response("Session has ended. Please sign in again.")

        # Set user on request state (consumed by get_current_user dependency)
        # Access level comes from the DB (cached 60s), not the token, so a
        # change applies without logging out.
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

        # The current request's level (access.current_request_level) for code without the request.
        level_token = set_request_level(level)
        # A write clears the user's cached portfolio rows (app/core/user_cache.py)
        # before and after it runs, so the next screen shows the change.
        writes = request.method not in ("GET", "HEAD")
        if writes:
            user_cache.invalidate(uid)
        try:
            return await call_next(request)
        finally:
            if writes:
                user_cache.invalidate(uid)
            reset_request_level(level_token)


BLACKLIST_FAIL_OPEN_S = 5
_blacklist_errors = TTLCache(max_size=10000, default_ttl=BLACKLIST_FAIL_OPEN_S)
INVALID_AUDIT_EVERY_S = 60
_invalid_audited = TTLCache(max_size=10000, default_ttl=INVALID_AUDIT_EVERY_S)


def _auth_state(jti: str | None, sid: str | None, uid: str | None) -> tuple[bool, bool, dict]:
    """(revoked, session active, access) — blocking, run in a thread. A DB
    error never turns into a 500: the blacklist fails open (briefly cached),
    like the session check; the access level fails closed to free."""
    revoked = False
    if jti and not _blacklist_errors.get(jti):
        try:
            revoked = is_token_blacklisted(jti)
        except Exception as e:
            logger.warning(f"auth: blacklist check failed ({type(e).__name__}), allowing for {BLACKLIST_FAIL_OPEN_S}s")
            _blacklist_errors.set(jti, True)
    active = True if not sid else sessions.is_active(sid)
    return revoked, active, get_user_access(uid)


def _is_expired(token: str) -> bool:
    """True when the token's signature is valid but it has expired."""
    import jwt as pyjwt
    try:
        pyjwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except pyjwt.ExpiredSignatureError:
        return True
    except Exception:
        return False
    return False


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
    _spawn(write)


def _spawn(fn) -> None:
    """Run fn in the default worker pool without waiting (tests replace it)."""
    try:
        asyncio.get_running_loop().run_in_executor(None, fn)
    except RuntimeError:   # no running loop
        fn()


def _unauthorized_response(detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": detail},
        headers={"WWW-Authenticate": "Bearer"},
    )


def _log_unauthorized(request: Request, path: str, reason: str, user_id: str | None = None):
    """Audit row in a worker thread (never blocks the event loop). Bad tokens
    from one address are recorded at most once a minute (a flood can't turn
    into a flood of DB writes)."""
    ip = get_client_ip(request)
    if reason in ("invalid_token", "missing_token"):
        key = f"{ip}|{reason}"
        if _invalid_audited.get(key):
            return
        _invalid_audited.set(key, True)
    kwargs = dict(event_type=AuditEvent.UNAUTHORIZED_ACCESS, success=False, user_id=user_id, ip_address=ip,
                  user_agent=request.headers.get("User-Agent", ""), metadata={"path": path, "reason": reason})

    def write() -> None:
        try:
            insert_audit_log(**kwargs)
        except Exception as e:
            logger.debug(f"auth: audit not written: {type(e).__name__}")
    try:
        asyncio.get_running_loop().run_in_executor(None, write)
    except RuntimeError:   # no running loop (tests calling directly)
        write()
