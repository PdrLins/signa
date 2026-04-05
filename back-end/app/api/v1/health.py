"""Health check route — public."""

import time
from typing import Optional

from fastapi import APIRouter, Depends, Request
from loguru import logger
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.scheduler.runner import scheduler


class AIConfigUpdateRequest(BaseModel):
    language: Optional[str] = Field(None, pattern=r"^(en|pt)$")
    synthesis_providers: Optional[list[str]] = None
    sentiment_providers: Optional[list[str]] = None
    ai_enabled: Optional[bool] = None
    ai_candidate_limit: Optional[int] = Field(None, ge=5, le=50)
    max_candidates: Optional[int] = Field(None, ge=10, le=100)

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
        results["supabase"] = {"status": "error", "ok": False}

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
        results["telegram"] = {"status": "error", "ok": False}

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

    # Gemini (Google)
    results["gemini"] = {
        "status": "configured" if settings.gemini_api_key else "missing key",
        "ok": bool(settings.gemini_api_key),
        "model": settings.gemini_model,
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
    from app.notifications.messages import msg

    ok = await send_message(settings.telegram_chat_id, msg("ping"))
    if ok:
        return {"status": "sent", "message": "Ping sent to Telegram"}
    return {"status": "failed", "message": "Failed to send — check bot token and chat ID"}


@router.get("/health/ai-config")
async def get_ai_config(user: dict = Depends(get_current_user)):
    """Get current AI provider configuration."""
    return {
        "synthesis": {
            "providers": settings.synthesis_providers,
            "available": {
                "claude": {
                    "configured": bool(settings.anthropic_api_key),
                    "model": settings.claude_model,
                },
                "gemini": {
                    "configured": bool(settings.gemini_api_key),
                    "model": settings.gemini_model,
                },
            },
        },
        "sentiment": {
            "providers": settings.sentiment_providers,
            "available": {
                "grok": {
                    "configured": bool(settings.xai_api_key),
                    "model": settings.grok_model,
                },
                "gemini": {
                    "configured": bool(settings.gemini_api_key),
                    "model": settings.gemini_model,
                },
            },
        },
        "scanning": {
            "ai_enabled": settings.ai_enabled,
            "ai_candidate_limit": settings.ai_candidate_limit,
            "max_candidates": settings.max_candidates,
        },
    }


@router.put("/health/ai-config")
async def update_ai_config(
    request: Request,
    body: AIConfigUpdateRequest,
    user: dict = Depends(get_current_user),
):
    """Update AI provider config. Changes apply to the next scan.

    Validates all input values. Logs changes to audit.
    """
    from app.core.utils import get_client_ip
    from app.db.queries import insert_audit_log

    valid_synthesis = {"claude", "gemini"}
    valid_sentiment = {"grok", "gemini"}

    updates = body.model_dump(exclude_none=True)

    if body.language is not None:
        settings.language = body.language

    if body.synthesis_providers is not None:
        providers = [p for p in body.synthesis_providers if p in valid_synthesis]
        if providers:
            settings.synthesis_providers = providers

    if body.sentiment_providers is not None:
        providers = [p for p in body.sentiment_providers if p in valid_sentiment]
        if providers:
            settings.sentiment_providers = providers

    # Scanning config
    if body.ai_enabled is not None:
        settings.ai_enabled = body.ai_enabled
    if body.ai_candidate_limit is not None:
        settings.ai_candidate_limit = body.ai_candidate_limit
    if body.max_candidates is not None:
        settings.max_candidates = body.max_candidates

    # Audit log config changes
    insert_audit_log(
        event_type="CONFIG_UPDATED",
        success=True,
        user_id=user.get("user_id"),
        ip_address=get_client_ip(request),
        metadata={"changed_keys": list(updates.keys())},
    )

    return {
        "synthesis_providers": settings.synthesis_providers,
        "sentiment_providers": settings.sentiment_providers,
        "scanning": {
            "ai_enabled": settings.ai_enabled,
            "ai_candidate_limit": settings.ai_candidate_limit,
            "max_candidates": settings.max_candidates,
        },
    }
