"""Coming up — one date-sorted feed of events for held and watched symbols. No AI.

  GET /api/v1/events/upcoming?days=30&account_id=&person_id=     area.coming_up

Query
  days        1..90 (default 30): forward window today..today+days (US/Eastern)
  account_id  one of the user's accounts (else 404 account_not_found)
  person_id   the accounts of one person (else 404 person_not_found);
              with account_id, the account must be that person's (422 invalid_scope)
  The watchlist is included only without account_id / person_id.

Response:
{
  "as_of": "2026-09-30T14:42:00+00:00" | null,   # oldest price time used (delayed data)
  "delayed_minutes": 15,
  "generated_at": ISO, "today": "2026-09-30",
  "window": {"start": "2026-09-30", "end": "2026-10-30", "days": 30},
  "recent_from": "2026-09-23",                    # analyst / check_changed look back to here
  "home_currency": "CAD", "usdcad": 1.39 | null,
  "symbols": {"held": ["NVDA", ...], "watched": ["AAPL", ...]},
  "count": 12,
  "items": [Item, ...],                           # sorted: date, type order, symbol
  "sources": {"dividends": S, "earnings": S, "analyst": S, "check_changed": S, "economy": "ok"},
                                                  # S = "ok" | "partial" | "failed" | "unavailable"
  "economy_calendar": {"last_reviewed": "2026-09-30", "covered_until": "2027-12-14", "maintained": "manually"}
}
Item (common): {"type": "ex_dividend" | "dividend_payment" | "earnings" | "analyst" | "check_changed" | "economy" | "price_alert",
                "date": "YYYY-MM-DD", "symbol": str | null, "name": str | null, "title": str, "detail": str,
                "cash": float | null (native), "cash_home": float | null, "currency": str | null,
                "estimated": bool, "owned": bool, "recent": bool (analyst / check_changed: a past date)}
  ex_dividend / dividend_payment + {"amount_per_share", "shares", "ex_date", "pay_date", "special",
                "frequency", "accounts": [{"account_id", "shares", "cash"}]}   (watched-only: cash/shares null)
  earnings    + {"days", "trading_days", "avg_abs_move_pct", "reports_measured",
                 "past_moves": [{"date", "move_pct"}], "typical_move_home"}
  analyst     + {"firm", "action", "from_grade", "to_grade", "price_target", "prior_price_target"}
  check_changed + {"changes": [{"key", "from", "to"}], "previous_date"}
  economy     + {"code": "boc_rate" | "fed_rate" | "us_cpi" | "ca_cpi", "country": "CA" | "US"}
                (estimated=true = provisional date in the manually maintained list)
  price_alert + {"alert_id", "direction": "above" | "below", "target_price", "last_price",
                 "triggered_at" (ISO)}   recent=true, dated the day it fired (last 7 days);
                 currency = the alert's. Whole-portfolio scope only;
                 sources.price_alerts = "ok" | "failed" | "unavailable" (before migration 015).

Errors ({"detail": {"code", "message", ...}}): 422 invalid_days | invalid_scope ·
404 account_not_found | person_not_found · 403 upgrade_required · 503 migration_required |
storage_unavailable. A failing data source never fails the request (see `sources`).
"""

from __future__ import annotations

import asyncio
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.access import require_feature
from app.core.api_errors import run_db
from app.core.dependencies import get_current_user
from app.services import events_feed, portfolio_context

router = APIRouter(prefix="/events", tags=["Events"])


def _triggered_alerts(user_id: str) -> tuple[list[dict], str]:
    from app.core.api_errors import is_missing_schema
    from app.services import price_alerts
    try:
        return price_alerts.recent_triggered(user_id), "ok"
    except Exception as e:
        return [], ("unavailable" if is_missing_schema(e) else "failed")


def _watchlist(user_id: str) -> list[dict]:
    from app.db import queries
    try:
        return queries.get_watchlist(user_id)
    except Exception:
        return []


@router.get("/upcoming", dependencies=[Depends(require_feature("area.coming_up"))])
async def upcoming(
    days: int = Query(events_feed.DEFAULT_DAYS),
    account_id: Optional[UUID] = Query(None),
    person_id: Optional[UUID] = Query(None),
    user: dict = Depends(get_current_user),
):
    days = events_feed.validate_days(days)
    whole = account_id is None and person_id is None   # the whole portfolio: watchlist + alerts too

    async def nothing(value):
        return value
    scope, watchlist, alerts = await asyncio.gather(
        run_db(portfolio_context.load_scope, user, str(account_id) if account_id else None,
               str(person_id) if person_id else None, False, True),
        run_db(_watchlist, user["user_id"]) if whole else nothing([]),
        asyncio.to_thread(_triggered_alerts, user["user_id"]) if whole else nothing(None))
    return await events_feed.build_upcoming(scope, watchlist, days, price_alerts=alerts)
