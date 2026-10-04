"""Health and version routes (public, no DB)."""

import time

from fastapi import APIRouter

from app.core.version import APP_VERSION
from app.scheduler.runner import scheduler

router = APIRouter(tags=["Health"])

_start_time = time.time()


@router.get("/health")
async def health_check():
    """Public health check endpoint. Lightweight — no DB calls."""
    return {
        "status": "ok",
        "app": "Signa",
        "version": APP_VERSION,   # back-end/VERSION, bumped on every back-end commit
        "uptime_seconds": round(time.time() - _start_time, 2),
        "scheduler_running": scheduler.running,
    }


@router.get("/version")
async def version():
    """Public: the back-end version (back-end/VERSION, bumped on every commit
    that touches back-end/). Clients show it next to their own version.
    {"backend": "1.0.3"}"""
    return {"backend": APP_VERSION}
