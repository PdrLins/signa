"""Request audit logging middleware.

Logs every incoming request to the audit system for security monitoring.
"""

import time

from fastapi import Request
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.utils import get_client_ip


class AuditMiddleware(BaseHTTPMiddleware):
    """Logs request metadata for auditing purposes."""

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        duration_ms = round((time.time() - start_time) * 1000, 2)

        path = request.url.path
        if path != "/api/v1/health":
            ip = get_client_ip(request)
            user = getattr(request.state, "user", {})
            username = user.get("username", "anon")

            logger.info(
                f"{request.method} {path} → {response.status_code} "
                f"({duration_ms}ms) from {ip} [{username}]"
            )

        return response
