"""Data-usage counters (migration 014, table data_usage_daily). No AI.

Live data and charts cost provider calls; to price the plans later we
count them. `record(metric, n)` is a cheap in-memory increment (safe to call
from any thread); a scheduler job calls `flush()` every few minutes, which
adds the buffered counts to (usage_date, metric) rows through the SQL
function increment_data_usage() (atomic, so several workers can flush).

Before migration 014 a flush drops the counts (logged once) instead of
growing the buffer forever; any other DB failure keeps them for the next
flush (bounded by MAX_PENDING keys).

Metric names (METRICS documents the common ones; any short name works):
  provider_calls.quotes         one batched yfinance quote download
  provider_calls.daily_history  one batched daily-closes download
  provider_calls.intraday       one intraday-bars download (1D chart)
  provider_calls.<kind>         other market-data fetches (analyst, earnings_moves ...)
  symbols_refreshed             quotes written by the quotes job
  requests.<endpoint>           calls to the heavy endpoints
                                (portfolio_history, dividends_summary, events_upcoming)

`summarize(rows, days, today)` shapes GET /api/v1/admin/usage (pure).
"""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from loguru import logger

ET = ZoneInfo("America/New_York")
MAX_PENDING = 2000
METRICS: dict[str, str] = {
    "provider_calls.quotes": "Batched quote downloads (yfinance)",
    "provider_calls.daily_history": "Batched daily-close downloads",
    "provider_calls.intraday": "Intraday bar downloads (1D chart)",
    "provider_calls.analyst": "Analyst upgrades/downgrades fetches",
    "provider_calls.earnings_moves": "Earnings-day move computations (daily history)",
    "symbols_refreshed": "Quotes written by the quotes job",
    "requests.portfolio_history": "GET /portfolio/history",
    "requests.dividends_summary": "GET /dividends/summary",
    "requests.events_upcoming": "GET /events/upcoming",
}

_lock = threading.Lock()
_pending: dict[tuple[str, str], int] = {}
_schema_missing_logged = False


def _today() -> date:
    return datetime.now(ET).date()


def record(metric: str, n: int = 1, today: date | None = None) -> None:
    """Add n to today's (US/Eastern) count of `metric`. Never raises."""
    try:
        n = int(n)
        if n <= 0 or not metric:
            return
        key = ((today or _today()).isoformat(), str(metric)[:64])
        with _lock:
            if key not in _pending and len(_pending) >= MAX_PENDING:
                return
            _pending[key] = _pending.get(key, 0) + n
    except Exception:  # counting must never break a request
        pass


def pending() -> dict[str, dict[str, int]]:
    """Unflushed counts: {date: {metric: n}}."""
    out: dict[str, dict[str, int]] = {}
    with _lock:
        for (d, m), n in _pending.items():
            out.setdefault(d, {})[m] = n
    return out


def reset() -> None:
    """Test helper."""
    global _schema_missing_logged
    with _lock:
        _pending.clear()
    _schema_missing_logged = False


def flush() -> dict:
    """Write the buffered counts. Scheduler entry (sync — run in a thread)."""
    global _schema_missing_logged
    from app.core.api_errors import is_missing_schema
    from app.db import queries

    with _lock:
        batch = dict(_pending)
        _pending.clear()
    if not batch:
        return {"status": "ok", "rows": 0}
    written = 0
    failed: dict[tuple[str, str], int] = {}
    for (d, m), n in batch.items():
        try:
            queries.increment_data_usage(d, m, n)
            written += 1
        except Exception as e:
            if is_missing_schema(e):
                if not _schema_missing_logged:
                    logger.warning(f"usage metrics: data_usage_daily missing (apply migration 014) — dropped: {e}")
                    _schema_missing_logged = True
                return {"status": "unavailable", "rows": written, "dropped": len(batch) - written}
            failed[(d, m)] = n
    if failed:
        logger.warning(f"usage metrics: {len(failed)} counter(s) not written, kept for the next flush")
        with _lock:
            for k, n in failed.items():
                if k in _pending or len(_pending) < MAX_PENDING:
                    _pending[k] = _pending.get(k, 0) + n
    return {"status": "ok", "rows": written, "failed": len(failed)}


def summarize(rows: list[dict], days: int, today: date) -> dict:
    """{"from", "to", "days": [{"date", "metrics": {metric: n}}] (every day,
    empty ones too, oldest first), "totals": {metric: n}}. Pure."""
    start = today - timedelta(days=max(1, days) - 1)
    by_day: dict[str, dict[str, int]] = {}
    for i in range(max(1, days)):
        by_day[(start + timedelta(days=i)).isoformat()] = {}
    totals: dict[str, int] = {}
    for r in rows or []:
        d = str(r.get("usage_date") or "")[:10]
        if d not in by_day:
            continue
        m = str(r.get("metric") or "")
        try:
            n = int(r.get("count") or 0)
        except (TypeError, ValueError):
            continue
        by_day[d][m] = by_day[d].get(m, 0) + n
        totals[m] = totals.get(m, 0) + n
    return {"from": start.isoformat(), "to": today.isoformat(),
            "days": [{"date": d, "metrics": dict(sorted(ms.items()))} for d, ms in by_day.items()],
            "totals": dict(sorted(totals.items()))}
