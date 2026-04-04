"""Health check route — public."""

import time

from fastapi import APIRouter, Depends
from loguru import logger

from app.core.config import settings
from app.core.dependencies import get_current_user
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


@router.get("/health/integrations")
async def integration_status(user: dict = Depends(get_current_user)):
    """Check connectivity of all external integrations."""
    results = {}

    # Supabase
    try:
        from app.db.supabase import get_client
        client = get_client()
        client.table("users").select("id").limit(1).execute()
        results["supabase"] = {"status": "connected", "ok": True}
    except Exception as e:
        logger.debug(f"Supabase health check failed: {e}")
        results["supabase"] = {"status": "error", "ok": False, "detail": str(e)[:100]}

    # Telegram
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/getMe"
            )
            if r.status_code == 200 and r.json().get("ok"):
                results["telegram"] = {"status": "connected", "ok": True}
            else:
                results["telegram"] = {"status": "error", "ok": False, "detail": "Invalid token"}
    except Exception as e:
        logger.debug(f"Telegram health check failed: {e}")
        results["telegram"] = {"status": "error", "ok": False, "detail": str(e)[:100]}

    # Claude (Anthropic)
    results["claude"] = {
        "status": "configured" if settings.anthropic_api_key else "missing key",
        "ok": bool(settings.anthropic_api_key),
        "model": settings.claude_model,
    }

    # Grok (xAI)
    results["grok"] = {
        "status": "configured" if settings.xai_api_key else "missing key",
        "ok": bool(settings.xai_api_key),
        "model": settings.grok_model,
    }

    # Scheduler
    results["scheduler"] = {
        "status": "running" if scheduler.running else "stopped",
        "ok": scheduler.running,
    }

    all_ok = all(r["ok"] for r in results.values())
    return {"status": "healthy" if all_ok else "degraded", "integrations": results}


@router.post("/health/ping-telegram")
async def ping_telegram(user: dict = Depends(get_current_user)):
    """Send a test ping to Telegram to verify the bot is working."""
    from app.notifications.telegram_bot import send_message

    ok = await send_message(
        settings.telegram_chat_id,
        "🏓 <b>Signa Ping</b>\n\nTelegram integration is working.",
    )
    if ok:
        return {"status": "sent", "message": "Ping sent to Telegram"}
    return {"status": "failed", "message": "Failed to send — check bot token and chat ID"}
