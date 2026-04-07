"""JWT authentication middleware.

Validates JWT on protected routes.
Sets request.state.user for downstream dependencies.
"""

from fastapi import Request, status
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.security import decode_token
from app.core.utils import get_client_ip
from app.db.queries import insert_audit_log, is_token_blacklisted
from app.models.audit import AuditEvent

PUBLIC_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/verify-otp",
    "/api/v1/auth/refresh",
    "/api/v1/health",
    "/api/v1/telegram/webhook",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/",
}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # CORS preflight: always allow OPTIONS through
        if request.method == "OPTIONS":
            return await call_next(request)

        # Public paths: no auth needed
        if path in PUBLIC_PATHS or path.startswith("/docs") or path.startswith("/redoc"):
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

        # Set user on request state (consumed by get_current_user dependency)
        request.state.user = {
            "user_id": payload.get("sub"),
            "username": payload.get("username"),
            "jti": jti,
        }

        return await call_next(request)


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
