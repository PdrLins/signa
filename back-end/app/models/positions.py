"""Pydantic models for position tracking."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class PositionCreateRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=10, pattern=r"^[A-Z0-9.\-]+$")
    entry_price: Decimal = Field(..., gt=0)
    shares: Decimal = Field(..., gt=0)
    account_type: str | None = Field(None, pattern=r"^(TFSA|RRSP|TAXABLE)$")
    bucket: str | None = Field(None, pattern=r"^(SAFE_INCOME|HIGH_RISK)$")
    currency: str = Field("CAD", pattern=r"^(CAD|USD)$")
    target_price: Decimal | None = None
    stop_loss: Decimal | None = None
    notes: str | None = Field(None, max_length=1000)


class PositionUpdateRequest(BaseModel):
    target_price: Decimal | None = None
    stop_loss: Decimal | None = None
    notes: str | None = Field(None, max_length=1000)


class PositionCloseRequest(BaseModel):
    exit_price: Decimal = Field(..., gt=0)


class PositionItem(BaseModel):
    id: str
    symbol: str
    entry_price: Decimal
    entry_date: datetime | None = None
    shares: Decimal
    account_type: str | None = None
    bucket: str | None = None
    currency: str = "CAD"
    target_price: Decimal | None = None
    stop_loss: Decimal | None = None
    notes: str | None = None
    status: str = "OPEN"
    exit_price: Decimal | None = None
    exit_date: datetime | None = None
    exit_reason: str | None = None
    pnl_amount: Decimal | None = None
    pnl_percent: Decimal | None = None
    last_signal_score: int | None = None
    last_signal_status: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PositionWithPnL(PositionItem):
    """Position with live unrealized P&L (calculated, not stored)."""
    current_price: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    unrealized_pnl_pct: Decimal | None = None
