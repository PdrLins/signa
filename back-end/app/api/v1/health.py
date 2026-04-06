"""Health check and configuration routes — protected."""

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
    score_buy_safe: Optional[int] = Field(None, ge=55, le=85)
    score_buy_risk: Optional[int] = Field(None, ge=55, le=85)
    score_hold: Optional[int] = Field(None, ge=40, le=65)


class BudgetUpdateRequest(BaseModel):
    """Validated budget update — all fields optional, all clamped."""
    daily_limit: Optional[float] = Field(None, ge=0.10, le=50.0)
    claude_monthly: Optional[float] = Field(None, ge=0, le=100.0)
    grok_monthly: Optional[float] = Field(None, ge=0, le=100.0)
    gemini_monthly: Optional[float] = Field(None, ge=0, le=100.0)


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
    """Check connectivity of all external integrations in parallel.

    Returns status only — no model names, no error details, no API key hints.
    """
    import asyncio

    async def _check_supabase() -> tuple[str, dict]:
        try:
            from app.db.supabase import get_client
            client = get_client()
            await asyncio.to_thread(
                lambda: client.table("users").select("id").limit(1).execute()
            )
            return "supabase", {"status": "connected", "ok": True}
        except Exception:
            return "supabase", {"status": "error", "ok": False}

    async def _check_telegram() -> tuple[str, dict]:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(
                    f"https://api.telegram.org/bot{settings.telegram_bot_token}/getMe"
                )
                if r.status_code == 200 and r.json().get("ok"):
                    return "telegram", {"status": "connected", "ok": True}
                return "telegram", {"status": "error", "ok": False}
        except Exception:
            return "telegram", {"status": "error", "ok": False}

    async def _check_claude() -> tuple[str, dict]:
        if not settings.anthropic_api_key:
            return "claude", {"status": "not_configured", "ok": False}
        try:
            import anthropic
            def _test():
                c = anthropic.Anthropic(api_key=settings.anthropic_api_key)
                try:
                    c.messages.count_tokens(
                        model=settings.claude_model,
                        messages=[{"role": "user", "content": "test"}],
                    )
                except anthropic.NotFoundError:
                    c.messages.create(model=settings.claude_model, max_tokens=1, messages=[{"role": "user", "content": "ok"}])
            await asyncio.to_thread(_test)
            return "claude", {"status": "connected", "ok": True}
        except Exception as e:
            err = str(e).lower()
            if "credit" in err or "billing" in err:
                return "claude", {"status": "no_credits", "ok": False}
            elif "invalid" in err or "authentication" in err:
                return "claude", {"status": "invalid_key", "ok": False}
            return "claude", {"status": "error", "ok": False}

    async def _check_grok() -> tuple[str, dict]:
        if not settings.xai_api_key:
            return "grok", {"status": "not_configured", "ok": False}
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get("https://api.x.ai/v1/models", headers={"Authorization": f"Bearer {settings.xai_api_key}"})
                if r.status_code == 200:
                    return "grok", {"status": "connected", "ok": True}
                elif r.status_code == 403:
                    return "grok", {"status": "no_credits", "ok": False}
                return "grok", {"status": "error", "ok": False}
        except Exception:
            return "grok", {"status": "error", "ok": False}

    async def _check_gemini() -> tuple[str, dict]:
        if not settings.gemini_api_key:
            return "gemini", {"status": "not_configured", "ok": False}
        try:
            from google import genai
            def _test():
                gc = genai.Client(api_key=settings.gemini_api_key)
                gc.models.generate_content(model=settings.gemini_model, contents="hi")
            await asyncio.to_thread(_test)
            return "gemini", {"status": "connected", "ok": True}
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                return "gemini", {"status": "rate_limited", "ok": True}
            elif "invalid" in err.lower() or "API_KEY" in err:
                return "gemini", {"status": "invalid_key", "ok": False}
            return "gemini", {"status": "error", "ok": False}

    # Run all checks in parallel (~5s instead of ~25s)
    checks = await asyncio.gather(
        _check_supabase(), _check_telegram(), _check_claude(),
        _check_grok(), _check_gemini(),
    )
    results = dict(checks)

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


@router.get("/health/budget")
async def get_budget(user: dict = Depends(get_current_user)):
    """Get AI budget summary — spend per provider, limits, remaining."""
    from app.services.budget_service import BudgetService
    budget = await BudgetService.get_instance()
    return budget.get_budget_summary()


@router.put("/health/budget")
async def update_budget(
    request: Request,
    body: BudgetUpdateRequest,
    user: dict = Depends(get_current_user),
):
    """Update budget limits. Validated via Pydantic model."""
    from app.core.utils import get_client_ip
    from app.db.queries import insert_audit_log
    changed = []

    if body.daily_limit is not None:
        settings.budget_daily_limit_usd = body.daily_limit
        changed.append("daily_limit")
    if body.claude_monthly is not None:
        settings.budget_claude_monthly_usd = body.claude_monthly
        changed.append("claude_monthly")
    if body.grok_monthly is not None:
        settings.budget_grok_monthly_usd = body.grok_monthly
        changed.append("grok_monthly")
    if body.gemini_monthly is not None:
        settings.budget_gemini_monthly_usd = body.gemini_monthly
        changed.append("gemini_monthly")

    if changed:
        uid = user.get("user_id")
        insert_audit_log(
            event_type="BUDGET_UPDATED",
            success=True,
            user_id=uid if uid != "dev-user-id" else None,
            ip_address=get_client_ip(request),
            metadata={"changed": changed},
        )

    from app.services.budget_service import BudgetService
    budget = await BudgetService.get_instance()
    return budget.get_budget_summary()


@router.get("/health/ai-config")
async def get_ai_config(user: dict = Depends(get_current_user)):
    """Get current AI provider configuration."""
    return {
        "synthesis": {
            "providers": settings.synthesis_providers,
            "available": {
                "claude": {"configured": bool(settings.anthropic_api_key)},
                "gemini": {"configured": bool(settings.gemini_api_key)},
            },
        },
        "sentiment": {
            "providers": settings.sentiment_providers,
            "available": {
                "grok": {"configured": bool(settings.xai_api_key)},
                "gemini": {"configured": bool(settings.gemini_api_key)},
            },
        },
        "scanning": {
            "ai_enabled": settings.ai_enabled,
            "ai_candidate_limit": settings.ai_candidate_limit,
            "max_candidates": settings.max_candidates,
        },
        "thresholds": {
            "score_buy_safe": settings.score_buy_safe,
            "score_buy_risk": settings.score_buy_risk,
            "score_hold": settings.score_hold,
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

    # Score thresholds
    if body.score_buy_safe is not None:
        settings.score_buy_safe = body.score_buy_safe
    if body.score_buy_risk is not None:
        settings.score_buy_risk = body.score_buy_risk
    if body.score_hold is not None:
        settings.score_hold = body.score_hold

    # Audit log config changes
    uid = user.get("user_id")
    insert_audit_log(
        event_type="CONFIG_UPDATED",
        success=True,
        user_id=uid if uid != "dev-user-id" else None,
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
        "thresholds": {
            "score_buy_safe": settings.score_buy_safe,
            "score_buy_risk": settings.score_buy_risk,
            "score_hold": settings.score_hold,
        },
    }
