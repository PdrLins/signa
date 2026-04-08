"""Stats + User Settings API routes — protected.

All sync service/query calls wrapped in asyncio.to_thread to avoid blocking the event loop.
"""

import asyncio

from fastapi import APIRouter, Depends, Query
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
    return await asyncio.to_thread(queries.get_user_settings, user["user_id"])


@router.put("/user-settings")
async def update_user_settings(body: UserSettingsUpdate, user: dict = Depends(get_current_user)):
    """Update current user's settings."""
    updates = body.model_dump(exclude_none=True)
    if not updates:
        return await asyncio.to_thread(queries.get_user_settings, user["user_id"])
    return await asyncio.to_thread(queries.update_user_settings, user["user_id"], updates)


@router.get("/daily", response_model=DailyStatsResponse)
async def get_daily_stats(user: dict = Depends(get_current_user)):
    """Get aggregated daily statistics."""
    return await asyncio.to_thread(stats_service.get_daily_stats)


@router.get("/recent-alerts")
async def get_recent_alerts(user: dict = Depends(get_current_user)):
    """Get the most recent Telegram alerts."""
    return await asyncio.to_thread(queries.get_recent_alerts, user["user_id"], 5)


@router.get("/virtual-portfolio")
async def get_virtual_portfolio(user: dict = Depends(get_current_user)):
    """Get virtual portfolio performance — brain accuracy tracking."""
    from app.services.virtual_portfolio import get_virtual_summary
    return await asyncio.to_thread(get_virtual_summary)


@router.get("/virtual-portfolio/charts")
async def get_virtual_portfolio_charts(user: dict = Depends(get_current_user)):
    """Get chart data for brain performance page.

    Returns: pnl_by_bucket, monthly_returns, exit_reasons, score_vs_pnl, win_rate_over_time.
    """
    from app.services.virtual_portfolio import get_virtual_charts
    return await asyncio.to_thread(get_virtual_charts)


@router.get("/virtual-portfolio/equity-curve")
async def get_equity_curve(user: dict = Depends(get_current_user)):
    """Get daily equity curve snapshots for charting performance over time."""
    def _fetch():
        from app.db.supabase import get_client
        db = get_client()
        result = (
            db.table("virtual_snapshots")
            .select("snapshot_date, brain_open, brain_unrealized_pnl, brain_cumulative_pnl, "
                    "watchlist_open, watchlist_unrealized_pnl, watchlist_cumulative_pnl, spy_price")
            .order("snapshot_date", desc=False)
            .limit(365)
            .execute()
        )
        return result.data or []
    return await asyncio.to_thread(_fetch)


@router.get("/watchdog-events")
async def get_watchdog_events(
    limit: int = Query(10, ge=1, le=50),
    user: dict = Depends(get_current_user),
):
    """Get recent watchdog events for the brain performance page."""
    def _fetch():
        from app.db.supabase import get_client as get_db
        db = get_db()
        result = (
            db.table("watchdog_events")
            .select("symbol, event_type, price, pnl_pct, sentiment_label, action_taken, in_watchlist, notes, created_at")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    return await asyncio.to_thread(_fetch)


@router.get("/positions-summary")
async def get_positions_summary(user: dict = Depends(get_current_user)):
    """Get a summary of open positions for the dashboard."""
    positions = await asyncio.to_thread(queries.get_open_positions, user["user_id"])
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
