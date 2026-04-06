"""Watchlist service — add/remove/list tickers on the watchlist."""

from typing import Optional

from app.db import queries


def get_watchlist(user_id: str) -> list[dict]:
    """Get all watchlist items for a user."""
    return queries.get_watchlist(user_id)


def add_to_watchlist(user_id: str, symbol: str, notes: Optional[str] = None) -> dict:
    """Add a ticker to the watchlist."""
    return queries.add_to_watchlist(user_id, symbol, notes)


def remove_from_watchlist(user_id: str, symbol: str) -> bool:
    """Remove a ticker from the watchlist."""
    return queries.remove_from_watchlist(user_id, symbol)
