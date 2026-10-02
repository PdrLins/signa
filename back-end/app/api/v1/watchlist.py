"""Watchlist API routes — protected."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from loguru import logger

from app.core.access import require_feature
from app.services import slots
from app.core.dependencies import get_current_user
from app.models.watchlist import WatchlistAddRequest
from app.services import following, watchlist_service
from app.core.api_errors import run_db

router = APIRouter(prefix="/watchlist", tags=["Watchlist"])


@router.get("", dependencies=[Depends(require_feature("area.watchlist"))])
async def get_watchlist(user: dict = Depends(get_current_user)):
    """Get the current watchlist."""
    items = watchlist_service.get_watchlist(user["user_id"])
    return {"items": items, "count": len(items)}


@router.get("/overview", dependencies=[Depends(require_feature("area.watchlist"))])
async def watchlist_overview(user: dict = Depends(get_current_user)):
    """Following, in one call (web Following tab and iOS). No AI.

    {"as_of": ISO | null, "delayed_minutes": 15,
     "watched": [Row + {"added_at": ISO, "in_holdings": bool}],   # watchlist, newest first
     "held":    [Row + {"in_holdings": true}],                    # held symbols not on the watchlist
     "slots": {"used", "limit", "remaining"} | null,               # limit null = unlimited
     "suggestions": [{"key": "popular_ca" | "popular_us" | "monthly_income" | "dividend_growers",
                      "items": [{"symbol", "name", "price" | null, "change_pct" | null (PERCENT, today),
                                 "currency" | null}]}]}          # never already-followed symbols
    Suggestion prices: the shared quotes row when updated in the last 15 min, else
    one batched live download cached 15 min for everyone (delayed ~15 min).
    Row = {"symbol", "name" | null, "price" | null, "change_pct" | null (today),
           "change_1m_pct" | null, "currency" | null, "as_of" | null,
           "spark": [float, ...]}   # up to 22 daily closes, oldest first (may be empty)
    """
    return await run_db(following.load_following, user)


@router.get("/search",dependencies=[Depends(require_feature("area.watchlist"))])
async def search_tickers(q: str = Query(..., min_length=1, max_length=10), user: dict = Depends(get_current_user)):
    """Search for valid tickers via yfinance. Returns matching symbols with name and exchange."""
    import yfinance as yf

    query = q.upper().strip()

    def _search():
        # Try exact match first
        results = []
        candidates = [query]
        # Also try common suffixes
        if not query.endswith(".TO") and not query.endswith("-USD"):
            candidates.append(f"{query}.TO")  # TSX
        if len(query) <= 5 and not "." in query and not "-" in query:
            candidates.append(f"{query}-USD")  # Crypto

        for symbol in candidates:
            try:
                t = yf.Ticker(symbol)
                info = t.info
                name = info.get("longName") or info.get("shortName")
                if name and info.get("regularMarketPrice"):
                    results.append({
                        "symbol": symbol,
                        "name": name,
                        "exchange": info.get("exchange", ""),
                        "price": info.get("regularMarketPrice"),
                        "type": "CRYPTO" if symbol.endswith("-USD") else "EQUITY",
                    })
            except Exception:
                continue
        return results

    try:
        results = await asyncio.to_thread(_search)
        return {"results": results}
    except Exception as e:
        logger.debug(f"Ticker search failed for {query}: {e}")
        return {"results": []}


@router.post("/{ticker}", dependencies=[Depends(require_feature("action.watchlist.edit"))], status_code=status.HTTP_201_CREATED)
async def add_to_watchlist(
    ticker: str = Path(..., pattern=r"^[A-Z0-9.\-]{1,10}$"),
    body: WatchlistAddRequest | None = None,
    user: dict = Depends(get_current_user),
):
    """Add a ticker to the watchlist. Validates against yfinance first."""
    import yfinance as yf

    symbol = ticker.upper()
    await slots.check_new_symbols_async(user, [symbol])

    # Validate ticker exists
    def _validate():
        t = yf.Ticker(symbol)
        info = t.info
        return bool(info.get("regularMarketPrice") or info.get("longName"))

    try:
        valid = await asyncio.to_thread(_validate)
    except Exception:
        valid = False

    if not valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ticker '{symbol}' not found. Check the symbol and try again.",
        )

    notes = body.notes if body else None
    item = watchlist_service.add_to_watchlist(user["user_id"], symbol, notes)
    # an invited user's first follow rewards their referrer (migration 019)
    from app.services import referrals
    await referrals.after_follow(user["user_id"])
    return item


@router.delete("/{ticker}", dependencies=[Depends(require_feature("action.watchlist.edit"))])
async def remove_from_watchlist(
    ticker: str = Path(..., pattern=r"^[A-Z0-9.\-]{1,10}$"),
    user: dict = Depends(get_current_user),
):
    """Remove a ticker from the watchlist."""
    removed = watchlist_service.remove_from_watchlist(user["user_id"], ticker.upper())
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticker not found in watchlist")
    return {"message": f"{ticker.upper()} removed from watchlist"}
