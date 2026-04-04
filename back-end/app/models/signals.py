"""Pydantic models for signals."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class SignalResponse(BaseModel):
    """Signal data returned by the API."""
    id: str
    symbol: str
    name: Optional[str] = None
    action: str              # BUY, HOLD, SELL, AVOID
    status: str              # CONFIRMED, WEAKENING, CANCELLED, UPGRADED
    score: int = Field(ge=0, le=100)
    confidence: int = Field(ge=0, le=100)
    is_gem: bool = False
    gem_reason: Optional[str] = None
    bucket: Optional[str] = None
    price_at_signal: Optional[Decimal] = None
    current_price: Optional[Decimal] = None
    change_pct: Optional[Decimal] = None
    target_price: Optional[Decimal] = None
    stop_loss: Optional[Decimal] = None
    risk_reward: Optional[Decimal] = None
    catalyst: Optional[str] = None
    sentiment_score: Optional[int] = None
    reasoning: Optional[str] = None
    entry_window: Optional[str] = None
    technical_data: Optional[dict] = None
    fundamental_data: Optional[dict] = None
    macro_data: Optional[dict] = None
    grok_data: Optional[dict] = None
    scan_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SignalListResponse(BaseModel):
    """Paginated signal list."""
    signals: list[SignalResponse]
    count: int


class ScanResponse(BaseModel):
    """Scan metadata."""
    id: str
    scan_type: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    tickers_scanned: int = 0
    signals_found: int = 0
    gems_found: int = 0
    status: str = "RUNNING"
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None


class ScanTodayRecord(BaseModel):
    """A single scan slot for the /scans/today endpoint."""
    id: Optional[str] = None
    scan_type: str
    label: str
    scheduled_time: str
    status: str = "PENDING"
    tickers_scanned: int = 0
    signals_found: int = 0
    gems_found: int = 0
    completed_at: Optional[datetime] = None


class ScanTriggerResponse(BaseModel):
    """Response when manually triggering a scan."""
    scan_id: str
    status: str = "RUNNING"
    message: str = "Scan triggered successfully"
