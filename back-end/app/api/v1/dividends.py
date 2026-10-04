"""Dividend calendar — the user's own holdings (free area, no AI).

  GET /api/v1/dividends/calendar?months=12&include_watchlist=false

Upcoming ex-dividend and payment dates for every holding, the cash to
expect per event (shares x amount per share) and per month, and the
yearly income. Built only from shared, cached market data
(services/dividends.get_dividend_profile, ~12h per symbol, shared across
users), so it costs nothing per user; nothing here reaches the AI.

Query
  months             1-12 (default 12): calendar months from the current one
  include_watchlist  true -> watchlist symbols not held are added as
                     owned=false events (no cash, not in any total)

Response: see the docstring of app/services/dividend_calendar.py
(as_of, window, usdcad, summary, months[], events[], positions[],
non_payers[], unknown[], missing_shares[]). A symbol whose data fails is
listed under "unknown" (never a 500); no holdings -> a valid empty
calendar. Holdings storage missing (migration 010) -> 503
{"code": "holdings_unavailable"}.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger

from app.core.access import require_feature
from app.core.dependencies import get_current_user
from app.db import queries
from app.services import dividend_calendar as dc

router = APIRouter(prefix="/dividends", tags=["Dividends"])


async def _usdcad() -> float | None:
    from app.services.price_cache import get_usdcad_rate
    try:
        return await asyncio.to_thread(get_usdcad_rate)
    except Exception:
        return None


@router.get("/calendar", dependencies=[Depends(require_feature("area.dividends"))])
async def dividend_calendar(
    months: int = Query(12, ge=1, le=dc.MAX_MONTHS),
    include_watchlist: bool = Query(False),
    user: dict = Depends(get_current_user),
):
    uid = user["user_id"]
    try:
        holdings = await asyncio.to_thread(queries.get_holdings, uid)
    except Exception as e:
        logger.warning(f"dividends: holdings unavailable: {e}")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={
            "code": "holdings_unavailable", "message": "Holdings storage is unavailable."})
    # the same symbol can be held in several accounts (migration 013): one position per symbol
    from app.services.holdings_service import merge_by_symbol
    holdings = merge_by_symbol(holdings)
    watchlist = None
    if include_watchlist:
        try:
            watchlist = await asyncio.to_thread(queries.get_watchlist, uid)
        except Exception as e:
            logger.warning(f"dividends: watchlist unavailable: {e}")
            watchlist = []
    home = "CAD"
    try:
        from app.services import profile_service
        row = await asyncio.to_thread(queries.get_profile_settings, uid)
        home = str(profile_service.merged_settings(row).get("home_currency") or "CAD").upper()
    except Exception as e:
        logger.debug(f"dividends: home currency unavailable ({e})")
    return await dc.get_calendar(holdings, watchlist, months, await _usdcad(), home=home)
