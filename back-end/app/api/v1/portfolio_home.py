"""Home and performance: portfolio value, chart and returns (no AI).

Math and rules: app/services/portfolio_performance.py. Scope filters on
every endpoint: ?account_id=<uuid> (one account) and/or ?person_id=<uuid>
(that person's accounts); none = the whole portfolio. Money is in the
user's home currency. Prices are free, delayed data: every response
carries `as_of` (oldest price time used, ISO) and `delayed_minutes` (15).

GET /api/v1/portfolio/summary?account_id=&person_id=            area.home
{
  "currency": "CAD",
  "market_value": 12345.67, "cash": 500.0, "total": 12845.67,
  "day_change": {"abs": 120.5 | null, "pct": 0.95 | null},   # live quotes only: positions priced
                                           # from the last close (prices_from_last_close) are left out
  "total_gain": {"abs": 2100.0 | null, "pct": 19.6 | null,
                 "unrealized": 1800.0 | null, "realized": 150.0 | null,
                 "dividends": 150.0 | null, "dividends_included": true},   # realized/dividends need transactions
  "cost_basis": 10700.0 | null,
  "holdings_count": 7,                     # distinct symbols in the scope
  "as_of": "2026-09-30T14:42:00+00:00" | null, "delayed_minutes": 15,
  "estimated": false,
  "estimated_flags": {"prices_from_last_close": [sym], "unpriced": [sym], "missing_cost": [sym],
                      "missing_shares": [sym], "unconverted": [{...}]},
  "usdcad": 1.39 | null
}

GET /api/v1/portfolio/history?range=1D|1W|1M|3M|YTD|1Y|5Y|ALL&account_id=&person_id=&compare=   area.home
{
  "range": "1M", "interval": "1d" | "5m" | "15m", "currency": "CAD",
  "start": "2026-08-29", "end": "2026-09-30",
  "series": [{"t": "2026-08-29" | "2026-09-30T13:35:00+00:00", "value": 12000.0}],
  "range_return_pct": 3.4 | null,
  "estimated": true, "estimated_reason": "no_snapshots" | "partial_snapshots" | "no_intraday" | "no_history" | null,
  "sources": {"snapshots": 12, "estimated": 9, "history_truncated": false},
  "compare": null | {"symbol": "XEQT.TO", "name": "...", "series": [{"t", "value"}],   # scaled to the first value
                     "range_return_pct": 2.1 | null, "available": true},
  "as_of": "...", "delayed_minutes": 15
}
  compare is opt-in (no default), one of GET /profile/options compare indexes.
  1D: 5-minute bars with feature.intraday_chart (free since migration 022), else 15-minute.
  ALL needs feature.full_history (premium) -> else 403 upgrade_required.

GET /api/v1/portfolio/performance?range=&account_id=&person_id=&compare=    area.insights
{
  "range": "1Y", "start": "2025-09-30", "end": "2026-09-30", "currency": "CAD",
  "method": "transactions" | "estimate",   # modified Dietz when the scope has transactions
  "flows_basis": "deposits" | "trades" | null,
  "return_pct": 8.2 | null, "gain": 950.0 | null, "start_value": 11000.0 | null, "end_value": 12845.67,
  "net_flows": 1000.0 | null, "dividends_received": 150.0 | null,
  "drivers": {"positive": [Driver], "negative": [Driver]},        # top 5 each
  "compare": null | {"symbol", "name", "return_pct", "difference_pts",
                     "drivers": {"positive": [Driver], "negative": [Driver]}},   # sorted by vs_benchmark_pts
  "estimated": bool, "estimated_reason": str | null,
  "as_of": "...", "delayed_minutes": 15
}
Driver = {"symbol", "weight_pct", "return_pct", "contribution_pts", "vs_benchmark_pts"?}

GET /api/v1/portfolio/recap?month=YYYY-MM          area.home   (default: last month)
{
  "month": "2026-09", "currency": "CAD",
  "start_value": 12000.0 | null, "end_value": 12400.0 | null,
  "change": {"abs": 400.0 | null, "pct": 3.33 | null},      # value moved (includes deposits)
  "dividends_received": 45.0 | null, "dividend_payments": 3,  # null when no transactions are recorded
  "best": [{"symbol", "return_pct"}], "worst": [{"symbol", "return_pct"}],   # up to 3 each
  "next_month": {"month": "2026-10", "expected": 52.3 | null, "payments": 4},
  "estimated": bool                                           # some values estimated from closes
}
  A push with the recap goes out on the 1st of each month (09:05 ET) to users with the app.
  422 invalid_month (bad format or a future month).

Errors ({"detail": {"code", "message", ...}}):
  403 upgrade_required (feature: area.home | area.insights | feature.full_history) ·
  404 account_not_found | person_not_found · 422 invalid_scope | invalid_range | invalid_compare ·
  503 migration_required | storage_unavailable
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.access import can, require_feature, upgrade_required
from app.core.api_errors import run_db
from app.core.dependencies import get_current_user
from app.services import portfolio_context, usage_metrics
from app.services import portfolio_performance as perf

router = APIRouter(prefix="/portfolio", tags=["Portfolio"])


def _s(v: Optional[UUID]) -> Optional[str]:
    return str(v) if v else None


def _check_range(user: dict, rng: str) -> str:
    r = perf.validate_range(rng)
    if r in perf.LONG_RANGES and not can(user.get("access_level") or "free", "feature.full_history"):
        raise upgrade_required("feature.full_history")
    return r


@router.get("/summary", dependencies=[Depends(require_feature("area.home"))])
async def summary(
    account_id: Optional[UUID] = Query(None),
    person_id: Optional[UUID] = Query(None),
    user: dict = Depends(get_current_user),
):
    scope = await run_db(portfolio_context.load_scope, user, _s(account_id), _s(person_id))
    return perf.summary_body(scope)


@router.get("/history", dependencies=[Depends(require_feature("area.home"))])
async def history(
    range: str = Query("1M"),
    account_id: Optional[UUID] = Query(None),
    person_id: Optional[UUID] = Query(None),
    compare: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    rng = _check_range(user, range)
    bench = perf.validate_compare(compare)
    usage_metrics.record("requests.portfolio_history")
    interval = "5m" if can(user.get("access_level") or "free", "feature.intraday_chart") else "15m"
    scope = await run_db(portfolio_context.load_scope, user, _s(account_id), _s(person_id))
    return await run_db(perf.history_body, scope, rng, interval, bench)


@router.get("/performance", dependencies=[Depends(require_feature("area.insights"))])
async def performance(
    range: str = Query("1Y"),
    account_id: Optional[UUID] = Query(None),
    person_id: Optional[UUID] = Query(None),
    compare: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    rng = _check_range(user, range)
    bench = perf.validate_compare(compare)
    scope = await run_db(portfolio_context.load_scope, user, _s(account_id), _s(person_id))
    return await run_db(perf.performance_body, scope, rng, bench)


@router.get("/recap", dependencies=[Depends(require_feature("area.home"))])
async def recap(month: Optional[str] = Query(None), user: dict = Depends(get_current_user)):
    from app.services import recap as recap_svc

    today = perf.today_et()
    first, last = recap_svc.month_bounds(month, today)
    scope = await run_db(portfolio_context.load_scope, user, None, None, True)
    events = await recap_svc.next_month_events(scope)
    return await run_db(recap_svc.build, scope, first, last, today, events)
