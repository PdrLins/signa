"""Rejects request bodies over a size limit before anything reads them.

Pure ASGI (no BaseHTTPMiddleware): checks Content-Length up front and counts
the bytes of streamed bodies, answering 413 {"detail": {"code":
"request_too_large"}} as soon as the limit is passed. Without this, a huge
JSON body to a public route (sign-in, sign-up) is read into memory before
any validation runs.
"""

from __future__ import annotations

import json

MAX_BODY_BYTES = 64 * 1024                       # every JSON request
LARGE_PATHS = ("/api/v1/transactions/import",)   # CSV uploads (the import itself caps at 2 MB)
MAX_LARGE_BODY_BYTES = 3 * 1024 * 1024


def limit_for(path: str) -> int:
    return MAX_LARGE_BODY_BYTES if path.startswith(LARGE_PATHS) else MAX_BODY_BYTES


class _TooLarge(Exception):
    pass


class BodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)
        limit = limit_for(scope.get("path", ""))
        for name, value in scope.get("headers") or []:
            if name == b"content-length":
                try:
                    if int(value) > limit:
                        return await _reject(send, limit)
                except ValueError:
                    return await _reject(send, limit)
        seen = 0
        started = False

        async def counted_receive():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body") or b"")
                if seen > limit:
                    raise _TooLarge()
            return message

        async def tracked_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counted_receive, tracked_send)
        except _TooLarge:
            if not started:
                await _reject(send, limit)


async def _reject(send, limit: int) -> None:
    body = json.dumps({"detail": {"code": "request_too_large",
                                  "message": f"Request too large (limit {limit // 1024} KB).",
                                  "limit_bytes": limit}}).encode()
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
