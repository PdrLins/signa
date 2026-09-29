"""Log viewer API — protected by brain 2FA.

Provides real-time WebSocket streaming and REST access to application logs.
"""

import asyncio
import json
from typing import Literal

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from loguru import logger

from app.core.config import settings
from app.core.security import decode_token
from app.db.queries import is_token_blacklisted
from app.middleware.brain_auth import _decode_brain_token, brain_session_exists, require_brain_token
from app.services.log_service import get_recent_logs, subscribe, unsubscribe

router = APIRouter(prefix="/logs", tags=["Logs"])

LOGS_SUBPROTOCOL = "signa.logs"


@router.get("/recent")
async def get_logs(
    limit: int = Query(100, ge=1, le=500),
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] | None = Query(None),
    search: str | None = Query(None, max_length=200),
    user: dict = Depends(require_brain_token),
):
    """Get recent logs from in-memory buffer. Requires brain token."""
    logs = get_recent_logs(limit=limit, level=level, search=search)
    return {"logs": logs, "count": len(logs)}


@router.websocket("/stream")
async def log_stream(websocket: WebSocket):
    """WebSocket endpoint for real-time log streaming.

    Browsers can't set headers on WebSocket requests, so both tokens travel
    as subprotocols (kept out of URLs and access logs):
    new WebSocket(url, ["signa.logs", "jwt.<access_token>", "brain-token.<brain_token>"])
    """
    protocols = [
        p.strip()
        for p in websocket.headers.get("sec-websocket-protocol", "").split(",")
        if p.strip()
    ]

    def _protocol_value(prefix: str) -> str | None:
        for proto in protocols:
            if proto.startswith(prefix):
                return proto[len(prefix):]
        return None

    # Validate JWT first
    jwt_token = _protocol_value("jwt.")
    if not jwt_token:
        await websocket.close(code=4001, reason="JWT token required")
        return

    jwt_payload = decode_token(jwt_token)
    if jwt_payload is None:
        await websocket.close(code=4001, reason="Invalid or expired JWT")
        return

    # Same revocation check the HTTP AuthMiddleware performs
    jwt_jti = jwt_payload.get("jti")
    if not jwt_jti or is_token_blacklisted(jwt_jti):
        await websocket.close(code=4001, reason="Token has been revoked")
        return

    # Then validate brain token
    brain_token = _protocol_value("brain-token.")
    if not brain_token:
        await websocket.close(code=4003, reason="Brain token required")
        return

    brain_payload = _decode_brain_token(brain_token)
    if brain_payload is None:
        await websocket.close(code=4003, reason="Invalid or expired brain token")
        return

    # Verify both tokens belong to the same user
    if jwt_payload.get("sub") != brain_payload.get("sub"):
        await websocket.close(code=4003, reason="Token user mismatch")
        return

    # Brain session must exist (same check as require_brain_token)
    if not brain_session_exists(brain_payload.get("jti")):
        await websocket.close(code=4003, reason="Brain session not found")
        return

    await websocket.accept(subprotocol=LOGS_SUBPROTOCOL)
    logger.info("Log stream WebSocket connected")

    queue = subscribe()
    try:
        while True:
            entry = await queue.get()
            await websocket.send_text(json.dumps(entry))
    except WebSocketDisconnect:
        logger.info("Log stream WebSocket disconnected")
    except Exception:
        logger.debug("Log stream WebSocket error")
    finally:
        unsubscribe(queue)
