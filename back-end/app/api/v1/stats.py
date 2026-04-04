"""Stats API routes — protected."""

from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.models.stats import DailyStatsResponse
from app.services import stats_service

router = APIRouter(prefix="/stats", tags=["Stats"])


@router.get("/daily", response_model=DailyStatsResponse)
async def get_daily_stats(user: dict = Depends(get_current_user)):
    """Get aggregated daily statistics."""
    return stats_service.get_daily_stats()
