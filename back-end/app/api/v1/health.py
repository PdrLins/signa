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
    score_buy_safe: Optional[int] = Field(None, ge=55, le=85)
    score_buy_risk: Optional[int] = Field(None, ge=55, le=85)
    score_hold: Optional[int] = Field(None, ge=40, le=65)

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

    # Claude (Anthropic) — test API with minimal cost
    if settings.anthropic_api_key:
        try:
            import anthropic
            c = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            # Use count_tokens instead of a real generation to avoid spending credits
            try:
                r = c.messages.count_tokens(
                    model=settings.claude_model,
                    messages=[{"role": "user", "content": "test"}],
                )
                results["claude"] = {"status": "connected", "ok": True, "model": settings.claude_model, "detail": "API responding"}
            except anthropic.NotFoundError:
                # count_tokens not available on all models, fall back to tiny call
                r = c.messages.create(model=settings.claude_model, max_tokens=1, messages=[{"role": "user", "content": "ok"}])
                results["claude"] = {"status": "connected", "ok": True, "model": settings.claude_model, "detail": "API responding"}
        except Exception as e:
            err = str(e)
            if "credit balance" in err.lower() or "billing" in err.lower():
                results["claude"] = {"status": "no credits", "ok": False, "model": settings.claude_model, "detail": "API key valid but no credits remaining"}
            elif "invalid" in err.lower() or "authentication" in err.lower():
                results["claude"] = {"status": "invalid key", "ok": False, "model": settings.claude_model, "detail": "API key is invalid"}
            else:
                logger.debug(f"Claude health check error: {err}")
                results["claude"] = {"status": "error", "ok": False, "model": settings.claude_model, "detail": f"Connection issue: {err[:100]}"}
    else:
        results["claude"] = {"status": "not configured", "ok": False, "model": settings.claude_model, "detail": "No API key set"}

    # Grok (xAI) — actually test the API
    if settings.xai_api_key:
        try:
            import httpx as _httpx
            async with _httpx.AsyncClient(timeout=5) as _c:
                r = await _c.get("https://api.x.ai/v1/models", headers={"Authorization": f"Bearer {settings.xai_api_key}"})
                if r.status_code == 200:
                    models = [m["id"] for m in r.json().get("data", [])][:5]
                    results["grok"] = {"status": "connected", "ok": True, "model": settings.grok_model, "detail": f"Available models: {', '.join(models)}" if models else "API responding"}
                elif r.status_code == 403:
                    body = r.json().get("error", r.text[:100])
                    if "credit" in str(body).lower():
                        results["grok"] = {"status": "no credits", "ok": False, "model": settings.grok_model, "detail": "API key valid but no credits"}
                    else:
                        results["grok"] = {"status": "forbidden", "ok": False, "model": settings.grok_model, "detail": "Access denied"}
                else:
                    results["grok"] = {"status": "error", "ok": False, "model": settings.grok_model, "detail": f"HTTP {r.status_code}"}
        except Exception:
            results["grok"] = {"status": "error", "ok": False, "model": settings.grok_model, "detail": "Connection failed"}
    else:
        results["grok"] = {"status": "not configured", "ok": False, "model": settings.grok_model, "detail": "No API key set"}

    # Gemini (Google) — actually test the API
    if settings.gemini_api_key:
        try:
            from google import genai
            gc = genai.Client(api_key=settings.gemini_api_key)
            gc.models.generate_content(model=settings.gemini_model, contents="hi")
            results["gemini"] = {"status": "connected", "ok": True, "model": settings.gemini_model, "detail": "API responding"}
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                results["gemini"] = {"status": "rate limited", "ok": True, "model": settings.gemini_model, "detail": "API key valid but daily quota exhausted. Resets at midnight PT."}
            elif "invalid" in err.lower() or "API_KEY" in err:
                results["gemini"] = {"status": "invalid key", "ok": False, "model": settings.gemini_model, "detail": "API key is invalid"}
            else:
                results["gemini"] = {"status": "error", "ok": False, "model": settings.gemini_model, "detail": "Connection failed"}
    else:
        results["gemini"] = {
        "status": "not configured", "ok": False,
        "model": settings.gemini_model, "detail": "No API key set",
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


@router.get("/health/budget")
async def get_budget(user: dict = Depends(get_current_user)):
    """Get AI budget summary — spend per provider, limits, remaining."""
    from app.services.budget_service import BudgetService
    budget = await BudgetService.get_instance()
    return budget.get_budget_summary()


@router.put("/health/budget")
async def update_budget(
    request: Request,
    body: dict,
    user: dict = Depends(get_current_user),
):
    """Update budget limits. Accepts: daily_limit, claude_monthly, grok_monthly, gemini_monthly."""
    from app.core.utils import get_client_ip
    from app.db.queries import insert_audit_log

    changed = []
    if "daily_limit" in body and isinstance(body["daily_limit"], (int, float)):
        settings.budget_daily_limit_usd = max(0.1, float(body["daily_limit"]))
        changed.append("daily_limit")
    if "claude_monthly" in body and isinstance(body["claude_monthly"], (int, float)):
        settings.budget_claude_monthly_usd = max(0, float(body["claude_monthly"]))
        changed.append("claude_monthly")
    if "grok_monthly" in body and isinstance(body["grok_monthly"], (int, float)):
        settings.budget_grok_monthly_usd = max(0, float(body["grok_monthly"]))
        changed.append("grok_monthly")
    if "gemini_monthly" in body and isinstance(body["gemini_monthly"], (int, float)):
        settings.budget_gemini_monthly_usd = max(0, float(body["gemini_monthly"]))
        changed.append("gemini_monthly")

    if changed:
        uid = user.get("user_id")
        insert_audit_log(
            event_type="BUDGET_UPDATED",
            success=True,
            user_id=uid if uid != "dev-user-id" else None,
            ip_address=get_client_ip(request),
            metadata={"changed": changed, **body},
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
    if hasattr(body, 'score_buy_safe') and body.score_buy_safe is not None:
        settings.score_buy_safe = body.score_buy_safe
    if hasattr(body, 'score_buy_risk') and body.score_buy_risk is not None:
        settings.score_buy_risk = body.score_buy_risk
    if hasattr(body, 'score_hold') and body.score_hold is not None:
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
