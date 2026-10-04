"""Data usage for pricing (owner only, migration 014). No AI.

  GET /api/v1/admin/usage?days=30          area.admin (owner)

Response:
{
  "from": "2026-09-01", "to": "2026-09-30",            # US/Eastern days, inclusive
  "days": [{"date": "2026-09-30", "metrics": {"provider_calls.quotes": 412, ...}}],   # every day, oldest first
  "totals": {"provider_calls.quotes": 9120, "symbols_refreshed": 80211, ...},
  "pending": {"2026-09-30": {"requests.portfolio_history": 3}},   # counted, not flushed yet
  "metrics_help": {"provider_calls.quotes": "Batched quote downloads (yfinance)", ...},
  "followed_symbols": 57,        # distinct symbols in all holdings + watchlists
  "active_symbols": 41,          # of those, followed by an active user (refreshed by the quotes job)
  "active_users": 6,             # seen in the last `active_days` days
  "active_days": 7,
  "refresh_seconds": {"free": 900, "premium": 60}
}
Errors: 422 (days outside 1..365) · 403 upgrade_required · 503 migration_required (014) |
storage_unavailable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query

from app.core.access import require_feature
from app.core.api_errors import INSIGHTS_MIGRATION, run_db_for
from app.core.config import settings
from app.services import quotes, usage_metrics

router = APIRouter(prefix="/admin", tags=["Admin"])


def _usage(days: int) -> dict:
    from app.db import queries

    today = usage_metrics._today()
    since = (today - timedelta(days=days - 1)).isoformat()
    body = usage_metrics.summarize(queries.get_data_usage(since), days, today)
    follows = queries.get_follow_rows()
    users = queries.get_users_activity()
    now = datetime.now(timezone.utc)
    levels = quotes.follower_levels(follows, users, now, settings.quotes_active_user_days)
    active_ids = {str(u.get("id")) for u in users
                  if (quotes._ts(u.get("last_seen_at")) or quotes._ts(u.get("last_login")) or
                      datetime.min.replace(tzinfo=timezone.utc))
                  >= now - timedelta(days=settings.quotes_active_user_days)}
    return {
        **body,
        "pending": usage_metrics.pending(),
        "metrics_help": usage_metrics.METRICS,
        "followed_symbols": len({str(r.get("symbol") or "").upper() for r in follows if r.get("symbol")}),
        "active_symbols": len(levels),
        "active_users": len(active_ids),
        "active_days": settings.quotes_active_user_days,
        "refresh_seconds": {"free": settings.quotes_refresh_seconds_free,
                            "premium": settings.quotes_refresh_seconds_premium},
    }


@router.get("/usage", dependencies=[Depends(require_feature("area.admin"))])
async def usage(days: int = Query(30, ge=1, le=365)):
    return await run_db_for(INSIGHTS_MIGRATION, _usage, days)
