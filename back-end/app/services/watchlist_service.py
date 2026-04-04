"""Watchlist service — add/remove/list tickers on the watchlist."""

from typing import Optional

from app.db import queries


def get_watchlist() -> list[dict]:
    """Get all watchlist items."""
    return queries.get_watchlist()


def add_to_watchlist(symbol: str, notes: Optional[str] = None) -> dict:
    """Add a ticker to the watchlist."""
    return queries.add_to_watchlist(symbol, notes)


def remove_from_watchlist(symbol: str) -> bool:
    """Remove a ticker from the watchlist."""
    return queries.remove_from_watchlist(symbol)
