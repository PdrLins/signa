"""Pydantic models for daily stats."""

from typing import Optional

from pydantic import BaseModel


class FearGreedDetail(BaseModel):
    """CNN Fear & Greed Index detail pulled through the macro scanner."""
    score: float
    label: str


class IntermarketDetail(BaseModel):
    """Intermarket signals from macro scanner (gold, oil, copper/gold)."""
    gold_price: Optional[float] = None
    gold_change_pct: Optional[float] = None
    oil_price: Optional[float] = None
    oil_change_pct: Optional[float] = None
    copper_gold_ratio: Optional[float] = None


class VixTermDetail(BaseModel):
    """VIX term structure (spot vs 3-month futures)."""
    spot: Optional[float] = None
    futures_3m: Optional[float] = None
    ratio: Optional[float] = None
    structure: Optional[str] = None


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
    # Macro data lifted from latest signal for dashboard display
    intermarket: Optional[IntermarketDetail] = None
    vix_term: Optional[VixTermDetail] = None
    yield_curve: Optional[float] = None
    credit_spread: Optional[float] = None
