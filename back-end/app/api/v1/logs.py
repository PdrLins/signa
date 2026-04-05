"""Log viewer API — protected by brain 2FA.

Provides real-time WebSocket streaming and REST access to application logs.
"""

import asyncio
import json

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from loguru import logger

from app.core.config import settings
from app.middleware.brain_auth import require_brain_token, _decode_brain_token
from app.services.log_service import get_recent_logs, subscribe, unsubscribe

router = APIRouter(prefix="/logs", tags=["Logs"])


@router.get("/recent")
async def get_logs(
    limit: int = Query(100, ge=1, le=500),
    level: str | None = Query(None),
    search: str | None = Query(None),
    user: dict = Depends(require_brain_token),
):
    """Get recent logs from in-memory buffer. Requires brain token."""
    logs = get_recent_logs(limit=limit, level=level, search=search)
    return {"logs": logs, "count": len(logs)}


@router.websocket("/stream")
async def log_stream(websocket: WebSocket):
    """WebSocket endpoint for real-time log streaming.

    Requires brain_token as query parameter:
    ws://host/api/v1/logs/stream?token=<brain_token>
    """
    # Validate brain token from query param
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4003, reason="Brain token required")
        return

    payload = _decode_brain_token(token)
    if payload is None:
        await websocket.close(code=4003, reason="Invalid or expired brain token")
        return

    await websocket.accept()
    logger.info("Log stream WebSocket connected")

    queue = subscribe()
    try:
        while True:
            entry = await queue.get()
            await websocket.send_text(json.dumps(entry))
    except WebSocketDisconnect:
        logger.info("Log stream WebSocket disconnected")
    except Exception:
        pass
    finally:
        unsubscribe(queue)
