"""Watchlist API routes — protected."""

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.core.dependencies import get_current_user
from app.models.watchlist import WatchlistAddRequest
from app.services import watchlist_service

router = APIRouter(prefix="/watchlist", tags=["Watchlist"])


@router.get("")
async def get_watchlist(user: dict = Depends(get_current_user)):
    """Get the current watchlist."""
    items = watchlist_service.get_watchlist()
    return {"items": items, "count": len(items)}


@router.post("/{ticker}", status_code=status.HTTP_201_CREATED)
async def add_to_watchlist(
    ticker: str = Path(..., pattern=r"^[A-Z0-9.\-]{1,10}$"),
    body: WatchlistAddRequest | None = None,
    user: dict = Depends(get_current_user),
):
    """Add a ticker to the watchlist."""
    notes = body.notes if body else None
    item = watchlist_service.add_to_watchlist(ticker.upper(), notes)
    return item


@router.delete("/{ticker}")
async def remove_from_watchlist(
    ticker: str = Path(..., pattern=r"^[A-Z0-9.\-]{1,10}$"),
    user: dict = Depends(get_current_user),
):
    """Remove a ticker from the watchlist."""
    removed = watchlist_service.remove_from_watchlist(ticker.upper())
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticker not found in watchlist")
    return {"message": f"{ticker.upper()} removed from watchlist"}
