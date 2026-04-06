"""Stats + User Settings API routes — protected."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import Optional

from app.core.dependencies import get_current_user
from app.db import queries
from app.models.stats import DailyStatsResponse
from app.services import stats_service

router = APIRouter(prefix="/stats", tags=["Stats"])


class UserSettingsUpdate(BaseModel):
    theme: Optional[str] = Field(None, pattern=r"^(midnight|arctic|sunset|ocean|forest|lavender)$")
    language: Optional[str] = Field(None, pattern=r"^(en|pt)$")


@router.get("/user-settings")
async def get_user_settings(user: dict = Depends(get_current_user)):
    """Get current user's settings (theme, language)."""
    return queries.get_user_settings(user["user_id"])


@router.put("/user-settings")
async def update_user_settings(body: UserSettingsUpdate, user: dict = Depends(get_current_user)):
    """Update current user's settings."""
    updates = body.model_dump(exclude_none=True)
    if not updates:
        return queries.get_user_settings(user["user_id"])
    return queries.update_user_settings(user["user_id"], updates)


@router.get("/daily", response_model=DailyStatsResponse)
async def get_daily_stats(user: dict = Depends(get_current_user)):
    """Get aggregated daily statistics."""
    return stats_service.get_daily_stats()


@router.get("/recent-alerts")
async def get_recent_alerts(user: dict = Depends(get_current_user)):
    """Get the most recent Telegram alerts."""
    return queries.get_recent_alerts(user["user_id"], limit=5)


@router.get("/virtual-portfolio")
async def get_virtual_portfolio(user: dict = Depends(get_current_user)):
    """Get virtual portfolio performance — brain accuracy tracking."""
    from app.services.virtual_portfolio import get_virtual_summary
    return get_virtual_summary()


@router.get("/positions-summary")
async def get_positions_summary(user: dict = Depends(get_current_user)):
    """Get a summary of open positions for the dashboard."""
    positions = queries.get_open_positions(user["user_id"])
    if not positions:
        return {"count": 0, "positions": [], "total_pnl_pct": 0}

    return {
        "count": len(positions),
        "positions": [
            {
                "symbol": p.get("symbol"),
                "entry_price": p.get("entry_price"),
                "shares": p.get("shares"),
                "bucket": p.get("bucket"),
                "account_type": p.get("account_type"),
                "last_signal_score": p.get("last_signal_score"),
                "last_signal_status": p.get("last_signal_status"),
            }
            for p in positions[:5]
        ],
    }
