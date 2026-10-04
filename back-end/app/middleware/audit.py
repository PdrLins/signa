"""Request log, request ids and the last line of defence for errors.

Every request gets an id (X-Request-ID response header, request_id_var for
log lines), so a problem report or a support message can be matched with the
server log. One line per request: method, ROUTE TEMPLATE (/stocks/{symbol},
not the ticker or device token), status, duration, a truncated IP and a short
user id (never the username). Slow requests are logged as warnings.

An exception that escaped every handler is logged once with its traceback
and the request id, and the client gets 500 {"detail": {"code":
"internal_error", "request_id"}} instead of a bare error.
"""

from __future__ import annotations

import ipaddress
import time
import uuid
from contextvars import ContextVar

from fastapi import Request
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.utils import get_client_ip

SLOW_REQUEST_MS = 2000
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def short_ip(ip: str) -> str:
    """Logs keep the network, not the person: 203.0.113.0/24, 2001:db8:1::/48."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return "unknown"
    prefix = 24 if addr.version == 4 else 48
    return str(ipaddress.ip_network(f"{ip}/{prefix}", strict=False))


def route_of(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", None) or "unmatched"


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        start = time.time()
        try:
            try:
                response = await call_next(request)
            except Exception:
                logger.exception(f"Unhandled error [{rid}] {request.method} {route_of(request)}")
                response = JSONResponse(status_code=500, content={"detail": {
                    "code": "internal_error", "message": "Something went wrong. Please try again.",
                    "request_id": rid}})
            response.headers["X-Request-ID"] = rid
            if request.url.path != "/api/v1/health":
                ms = round((time.time() - start) * 1000)
                user = getattr(request.state, "user", None) or {}
                who = str(user.get("user_id") or "anon")[:8]
                line = (f"{request.method} {route_of(request)} → {response.status_code} ({ms}ms) "
                        f"from {short_ip(get_client_ip(request))} [{who}] [{rid}]")
                if ms >= SLOW_REQUEST_MS:
                    logger.warning(f"Slow request: {line}")
                else:
                    logger.info(line)
            return response
        finally:
            request_id_var.reset(token)
