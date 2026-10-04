"""Home-screen widget data: one small, fast call (no AI).

GET /api/v1/widgets/summary                                   area.home
{
  "currency": "CAD",                         # the user's home currency
  "value": 12845.67 | null,                  # market value + cash (= /portfolio/summary total)
  "day_change": {"abs": 120.5 | null, "pct": 0.95 | null},
  "market_phase": "pre" | "open" | "post" | "closed" | null,
  "holdings_count": 7,
  "next_dividends": [                        # up to 3 owned payouts from today on, by date
    {"symbol": "ENB.TO", "name": "Enbridge", "date": "2026-10-15",
     "ex_date": "2026-09-30", "pay_date": "2026-10-15" | null,
     "amount_per_share": 0.9425 | null, "expected_cash": 94.25 | null, "currency": "CAD",
     "expected_cash_home": 94.25 | null,          # in the user's home currency
     "estimated": false, "pay_date_estimated": false}
  ],
  "dividends_complete": true,                # false when dividend data timed out (list may be short)
  "widgets": {"max": 1 | null},             # widgets the plan allows; null = unlimited (feature.all_widgets)
  "as_of": "2026-10-03T19:55:00+00:00" | null, "delayed_minutes": 15
}

Built for a widget timeline refresh (every ~15-30 min): the whole portfolio,
no transactions, dividend data capped at DIVIDENDS_TIMEOUT_S (then the list
is what was ready). Errors: 403 upgrade_required, 503 migration_required.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends
from loguru import logger

from app.core.access import can, require_feature
from app.core.api_errors import run_db
from app.core.dependencies import get_current_user
from app.services import portfolio_context
from app.services import portfolio_performance as perf

router = APIRouter(prefix="/widgets", tags=["Widgets"])

NEXT_DIVIDENDS = 3
DIVIDENDS_TIMEOUT_S = 4.0
FREE_WIDGETS = 1


def next_owned_dividends(calendar: dict, today: str, limit: int = NEXT_DIVIDENDS) -> list[dict]:
    """The first `limit` owned payouts dated today or later. Pure."""
    keys = ("symbol", "name", "date", "ex_date", "pay_date", "amount_per_share", "expected_cash",
            "expected_cash_home", "currency", "estimated", "pay_date_estimated")
    events = [e for e in calendar.get("events") or [] if e.get("owned") and str(e.get("date") or "") >= today]
    events.sort(key=lambda e: (str(e.get("date")), str(e.get("symbol"))))
    return [{k: e.get(k) for k in keys} for e in events[:limit]]


@router.get("/summary", dependencies=[Depends(require_feature("area.home"))])
async def widget_summary(user: dict = Depends(get_current_user)):
    from app.services import dividend_calendar, dividends

    scope = await run_db(portfolio_context.load_scope, user, None, None, False)
    body = await asyncio.to_thread(perf.summary_body, scope)
    today = dividends.today_et().isoformat()
    upcoming: list[dict] = []
    complete = True
    if scope["holdings"]:
        try:
            cal = await asyncio.wait_for(
                dividend_calendar.get_calendar(scope["holdings"], None, 3, scope.get("usdcad"), home=scope["home_currency"]),
                DIVIDENDS_TIMEOUT_S)
            upcoming = next_owned_dividends(cal, today)
        except Exception as e:   # includes the timeout
            logger.debug(f"widgets: dividends unavailable ({e!r})")
            complete = False
    level = user.get("access_level") or "free"
    return {
        "currency": body.get("currency"),
        "value": body.get("total"),
        "day_change": body.get("day_change"),
        "market_phase": body.get("market_phase"),
        "holdings_count": body.get("holdings_count"),
        "next_dividends": upcoming,
        "dividends_complete": complete,
        "widgets": {"max": None if can(level, "feature.all_widgets") else FREE_WIDGETS},
        "as_of": body.get("as_of"),
        "delayed_minutes": body.get("delayed_minutes", 15),
    }
