"""Signal API routes — protected.

All sync service calls wrapped in asyncio.to_thread to avoid blocking the event loop.
"""

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, Path, Query

from app.core.dependencies import get_current_user
from app.services import signal_service

router = APIRouter(prefix="/signals", tags=["Signals"])


@router.get("")
async def get_signals(
    bucket: Literal["SAFE_INCOME", "HIGH_RISK"] | None = Query(None),
    action: Literal["BUY", "HOLD", "SELL", "AVOID"] | None = Query(None),
    status: Literal["CONFIRMED", "WEAKENING", "CANCELLED", "UPGRADED"] | None = Query(None),
    period: Literal["today", "week", "month"] | None = Query(None),
    min_score: int = Query(0, ge=0, le=100),
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_current_user),
):
    """Get today's signals with optional filters."""
    signals = await asyncio.to_thread(
        signal_service.get_signals,
        bucket=bucket, action=action, status=status,
        period=period, min_score=min_score, limit=limit,
    )
    return {"signals": signals, "count": len(signals)}


@router.get("/gems")
async def get_gem_signals(
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """Get only GEM alerts."""
    gems = await asyncio.to_thread(signal_service.get_gem_signals, limit=limit)
    return {"signals": gems, "count": len(gems)}


@router.get("/{ticker}")
async def get_ticker_signals(
    ticker: str = Path(..., pattern=r"^[A-Z0-9.\-]{1,10}$"),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """Get signal history for a specific ticker."""
    signals = await asyncio.to_thread(
        signal_service.get_signals_by_ticker, ticker.upper(), limit,
    )
    return {"signals": signals, "count": len(signals)}
