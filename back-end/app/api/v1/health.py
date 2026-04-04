"""Health check route — public."""

import time

from fastapi import APIRouter

from app.scheduler.runner import scheduler

router = APIRouter(tags=["Health"])

_start_time = time.time()


@router.get("/health")
async def health_check():
    """Public health check endpoint. Lightweight — no DB calls."""
    return {
        "status": "ok",
        "app": "Signa",
        "uptime_seconds": round(time.time() - _start_time, 2),
        "scheduler_running": scheduler.running,
    }
