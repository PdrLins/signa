"""Self-learning API — trade outcomes + brain suggestions.

Outcomes: JWT auth only (user records trades).
Analysis + Suggestions: brain 2FA required.
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from loguru import logger
from pydantic import BaseModel, Field
from typing import Optional

from app.core.dependencies import get_current_user
from app.core.utils import get_client_ip
from app.db.queries import insert_audit_log
from app.db.supabase import get_client
from app.middleware.brain_auth import require_brain_token
from app.services import learning_service

router = APIRouter(prefix="/learning", tags=["Self-Learning"])


class TradeOutcomeRequest(BaseModel):
    signal_id: str
    symbol: str
    action: str
    score: int = Field(ge=0, le=100)
    bucket: str
    signal_date: str
    entry_price: float = Field(gt=0)
    exit_price: float = Field(gt=0)
    days_held: int = Field(ge=0)
    target_price: Optional[float] = None
    stop_loss: Optional[float] = None
    market_regime: Optional[str] = None
    catalyst_type: Optional[str] = None
    notes: Optional[str] = None


class RejectSuggestionRequest(BaseModel):
    reason: Optional[str] = None


# ── Outcomes (JWT only) ──

@router.post("/outcomes")
async def record_outcome(
    body: TradeOutcomeRequest,
    user: dict = Depends(get_current_user),
):
    """Record a trade outcome for learning."""
    result = await asyncio.to_thread(learning_service.record_outcome, **body.model_dump())
    return result


@router.get("/outcomes")
async def get_outcomes(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(100, ge=1, le=500),
    user: dict = Depends(get_current_user),
):
    """Get recent trade outcomes."""
    outcomes = await asyncio.to_thread(learning_service.get_outcomes, days=days, limit=limit)
    total = len(outcomes)
    correct = sum(1 for o in outcomes if o.get("signal_correct"))
    win_rate = correct / total if total > 0 else 0
    avg_return = sum(o.get("pnl_pct", 0) for o in outcomes) / total if total > 0 else 0

    return {
        "outcomes": outcomes,
        "count": total,
        "stats": {
            "win_rate": round(win_rate, 4),
            "avg_return_pct": round(avg_return, 4),
            "correct": correct,
            "incorrect": total - correct,
        },
    }


# ── Analysis + Suggestions (brain 2FA required) ──

@router.post("/analyze")
async def run_analysis(
    request: Request,
    days: int = Query(7, ge=1, le=90),
    user: dict = Depends(require_brain_token),
):
    """Run Claude/Gemini analysis on recent trade outcomes.

    Generates brain suggestions with proposed rule changes.
    Requires brain 2FA.
    """
    suggestions = await learning_service.run_weekly_analysis(period_days=days)

    insert_audit_log(
        event_type="LEARNING_ANALYSIS_RUN",
        success=True,
        user_id=user.get("user_id"),
        ip_address=get_client_ip(request),
        metadata={"period_days": days, "suggestions_generated": len(suggestions)},
    )

    return {
        "suggestions": suggestions,
        "count": len(suggestions),
    }


@router.get("/suggestions")
async def get_suggestions(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(require_brain_token),
):
    """Get brain suggestions. Requires brain 2FA."""
    return await asyncio.to_thread(learning_service.get_suggestions, status=status, limit=limit)


@router.put("/suggestions/{suggestion_id}/approve")
async def approve_suggestion(
    suggestion_id: str,
    request: Request,
    user: dict = Depends(require_brain_token),
):
    """Approve a suggestion. Does NOT apply it yet."""
    client = get_client()
    from datetime import datetime, timezone
    client.table("brain_suggestions").update({
        "status": "APPROVED",
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "reviewed_by": user.get("user_id"),
    }).eq("id", suggestion_id).execute()

    insert_audit_log(
        event_type="LEARNING_SUGGESTION_APPROVED",
        success=True,
        user_id=user.get("user_id"),
        ip_address=get_client_ip(request),
        metadata={"suggestion_id": suggestion_id},
    )
    return {"status": "approved"}


@router.put("/suggestions/{suggestion_id}/reject")
async def reject_suggestion(
    suggestion_id: str,
    request: Request,
    body: RejectSuggestionRequest = RejectSuggestionRequest(),
    user: dict = Depends(require_brain_token),
):
    """Reject a suggestion with optional reason."""
    client = get_client()
    from datetime import datetime, timezone
    client.table("brain_suggestions").update({
        "status": "REJECTED",
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "reviewed_by": user.get("user_id"),
        "rejection_reason": body.reason or "",
    }).eq("id", suggestion_id).execute()

    insert_audit_log(
        event_type="LEARNING_SUGGESTION_REJECTED",
        success=True,
        user_id=user.get("user_id"),
        ip_address=get_client_ip(request),
        metadata={"suggestion_id": suggestion_id},
    )
    return {"status": "rejected"}


@router.post("/suggestions/{suggestion_id}/apply")
async def apply_suggestion(
    suggestion_id: str,
    request: Request,
    user: dict = Depends(require_brain_token),
):
    """Apply an approved suggestion to the brain rules."""
    result = await asyncio.to_thread(learning_service.apply_suggestion, suggestion_id, user.get("user_id"))

    if "error" in result:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])

    insert_audit_log(
        event_type="LEARNING_SUGGESTION_APPLIED",
        success=True,
        user_id=user.get("user_id"),
        ip_address=get_client_ip(request),
        metadata={"suggestion_id": suggestion_id, "rule_name": result.get("rule_name")},
    )
    return result
