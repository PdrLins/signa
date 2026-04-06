"""Pydantic models for daily stats."""

from typing import Optional

from pydantic import BaseModel


class DailyStatsResponse(BaseModel):
    """Aggregated daily statistics."""
    gems_today: int = 0
    gems_yesterday: int = 0
    win_rate_30d: float = 0.0
    tickers_scanned: int = 0
    discovered_today: int = 0
    next_scan_time: Optional[str] = None
    ai_cost_today: float = 0.0
    claude_cost: float = 0.0
    grok_cost: float = 0.0
