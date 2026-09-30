"""Insights API — read-only aggregations for the Today, Is-it-working and
signal decision-trail pages. Protected (JWT via AuthMiddleware +
get_current_user). Response shapes: front-end/src/types/insights.ts.
"""

import asyncio
import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger

from app.core.access import require_feature
from app.core.cache import TTLCache
from app.core.dependencies import get_current_user
from app.core.utils import validate_ticker
from app.services import insights_service

router = APIRouter(prefix="/insights", tags=["Insights"])

_cache = TTLCache(max_size=200, default_ttl=60)
TTL_TODAY = 30
TTL_PERFORMANCE = 300
TTL_BACKTEST = 600
TTL_SIGNAL = 60


async def _ai_spend() -> dict | None:
    """Month-to-date AI spend vs the paid providers' monthly budgets."""
    try:
        from app.services.budget_service import BudgetService

        budget = BudgetService._instance or await BudgetService.get_instance()
        return insights_service.ai_spend_from_summary(budget.get_budget_summary())
    except Exception as e:
        logger.debug(f"insights: budget summary unavailable ({e})")
        return None


@router.get("/today", dependencies=[Depends(require_feature("area.today"))])
async def get_today(user: dict = Depends(get_current_user)):
    # Key the cache on the newest scan's id + status: a scan finishing (or
    # starting) changes the key, so the page sees fresh results immediately
    # instead of up to TTL_TODAY seconds later. Progress of a running scan is
    # read fresh on every request and never cached.
    newest = await asyncio.to_thread(insights_service.newest_scan)
    key = f"today:{(newest or {}).get('id')}:{(newest or {}).get('status')}"
    data = _cache.get(key)
    if data is None:
        spend = await _ai_spend()
        data = await asyncio.to_thread(insights_service.get_today, spend)
        _cache.set(key, data, TTL_TODAY)
    return {**data, "running_scan": insights_service.running_scan_ref(newest)}


@router.get("/performance", dependencies=[Depends(require_feature("area.performance"))])
async def get_performance(user: dict = Depends(get_current_user)):
    cached = _cache.get("performance")
    if cached is not None:
        return cached
    data = await asyncio.to_thread(insights_service.get_performance)
    _cache.set("performance", data, TTL_PERFORMANCE)
    return data


@router.get("/backtest", dependencies=[Depends(require_feature("area.performance"))])
async def get_backtest(user: dict = Depends(get_current_user)):
    cached = _cache.get("backtest")
    if cached is not None:
        return cached
    data = await asyncio.to_thread(insights_service.parse_backtests)
    _cache.set("backtest", data, TTL_BACKTEST)
    return data


@router.get("/signal/{ticker}", dependencies=[Depends(require_feature("area.signals"))])
async def get_signal_trail(ticker: str, user: dict = Depends(get_current_user)):
    if not ticker or len(ticker) > 20 or not validate_ticker(ticker):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid ticker")
    symbol = ticker.upper()
    key = f"signal:{symbol}"
    cached = _cache.get(key)
    if cached is not None:
        return cached
    try:
        data = await asyncio.to_thread(insights_service.get_signal_trail, symbol)
    except insights_service.SignalNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No signal for this ticker")
    _cache.set(key, data, TTL_SIGNAL)
    return data


_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
MAX_VERDICT_IDS = 200


@router.get("/verdicts", dependencies=[Depends(require_feature("area.performance"))])
async def get_signal_verdicts(
    ids: str = Query(..., max_length=MAX_VERDICT_IDS * 37),
    user: dict = Depends(get_current_user),
):
    """AI verdict chips for signal cards: {signal_id: {ai_status, ai_signal,
    p_win, routine_ai_signal, decision_overturned, tech_filter_passed}}.
    `ids` is a comma-separated list of signal UUIDs (max 200)."""
    id_list = [i.strip() for i in ids.split(",") if i.strip()]
    if not id_list or len(id_list) > MAX_VERDICT_IDS or not all(_UUID_RE.match(i) for i in id_list):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid ids")
    from app.db import queries

    rows = await asyncio.to_thread(queries.get_signal_verdicts, id_list)
    return {"verdicts": insights_service.verdicts_from_rows(rows)}
