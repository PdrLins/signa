"""Pydantic models for watchlist."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class WatchlistItem(BaseModel):
    """A ticker on the watchlist."""
    id: Optional[str] = None
    symbol: str = Field(..., min_length=1, max_length=10)
    added_at: Optional[datetime] = None
    notes: Optional[str] = None


class WatchlistAddRequest(BaseModel):
    """Request to add a ticker to the watchlist."""
    symbol: str = Field(..., min_length=1, max_length=10)
    notes: Optional[str] = None


class WatchlistResponse(BaseModel):
    """Watchlist response."""
    items: list[WatchlistItem]
    count: int
