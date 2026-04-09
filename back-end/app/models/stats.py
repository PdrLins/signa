"""Pydantic models for daily stats."""

from typing import Optional

from pydantic import BaseModel


class FearGreedDetail(BaseModel):
    """CNN Fear & Greed Index detail pulled through the macro scanner."""
    score: float
    label: str


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
    # Lifted from the latest signal's macro_data.fear_greed.
    # Stats service populates this; the frontend StatsBar card
    # renders it. Previously missing from the response model, which
    # caused FastAPI to strip the field and show an empty UI card.
    fear_greed: Optional[FearGreedDetail] = None
