"""Signal service — CRUD operations and status management."""

from typing import Optional

from app.db import queries
from app.services.price_cache import enrich_signals


def get_signals(
    bucket: Optional[str] = None,
    action: Optional[str] = None,
    status: Optional[str] = None,
    period: Optional[str] = None,
    min_score: int = 0,
    limit: int = 50,
    gems_only: bool = False,
) -> list[dict]:
    """Get latest signals with optional filters."""
    signals = queries.get_signals(
        bucket=bucket,
        action=action,
        status=status,
        period=period,
        min_score=min_score,
        limit=limit,
        gems_only=gems_only,
    )
    return enrich_signals(signals)


def get_signals_by_ticker(symbol: str, limit: int = 20) -> list[dict]:
    """Get signal history for a specific ticker."""
    signals = queries.get_signals_by_ticker(symbol, limit)
    return enrich_signals(signals)


def get_gem_signals(limit: int = 20) -> list[dict]:
    """Get only GEM alerts."""
    signals = queries.get_signals(gems_only=True, limit=limit)
    return enrich_signals(signals)


def get_scans(limit: int = 20) -> list[dict]:
    """Get recent scan history."""
    return queries.get_scans(limit)
