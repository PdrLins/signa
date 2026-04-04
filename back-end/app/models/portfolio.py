"""Pydantic models for portfolio."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class PortfolioItem(BaseModel):
    """A position in the portfolio."""
    id: Optional[str] = None
    symbol: str
    bucket: Optional[str] = None          # SAFE_INCOME, HIGH_RISK
    account_type: Optional[str] = None    # TFSA, RRSP, TAXABLE
    shares: Optional[Decimal] = None
    avg_cost: Optional[Decimal] = None
    currency: str = "CAD"                 # CAD, USD
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PortfolioAddRequest(BaseModel):
    """Request to add a position."""
    symbol: str = Field(..., min_length=1, max_length=10)
    bucket: Optional[str] = None
    account_type: Optional[str] = None
    shares: Optional[Decimal] = None
    avg_cost: Optional[Decimal] = None
    currency: str = "CAD"


class PortfolioUpdateRequest(BaseModel):
    """Request to update a position."""
    bucket: Optional[str] = None
    account_type: Optional[str] = None
    shares: Optional[Decimal] = None
    avg_cost: Optional[Decimal] = None
    currency: Optional[str] = None


class PortfolioResponse(BaseModel):
    """Portfolio list response."""
    items: list[PortfolioItem]
    count: int
