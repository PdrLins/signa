"""Daily Signa check statuses per followed symbol (migration 014, table
check_status_daily). No AI.

The five Signa checks of the free stock page (services/stock_page.py:
uptrend, not_overheated, liquidity, earnings_soon, dividend_health) are
stored once per symbol per day, so "Coming up" (GET /events/upcoming) can
say "a Signa check changed" by diffing the latest day against the previous
stored day. Shared per SYMBOL (market data), not per user.

  statuses_from_checks(checks)   pure: [check] -> {key: status}
  diff_statuses(prev, cur)       pure: -> [{"key", "from", "to"}]
  latest_changes(rows)           pure: rows -> {symbol: {"date", "prev_date", "changes"}}
  run_check_snapshots(on_date)   scheduler entry (18:15 ET weekdays): every
                                 followed symbol, stock_page.get_shared_page
                                 (15-minute shared cache), CONCURRENCY at a
                                 time, failures skipped; idempotent upsert.

Before migration 014 the job returns {"status": "unavailable"} without
building any page (a probe read fails first).
"""

from __future__ import annotations

import asyncio
from datetime import date

from loguru import logger

from app.services.stock_page import CHECK_KEYS

CONCURRENCY = 3
PAGE_TIMEOUT_S = 60.0


def statuses_from_checks(checks: list[dict] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for c in checks or []:
        k, st = c.get("key"), c.get("status")
        if k in CHECK_KEYS and isinstance(st, str):
            out[k] = st
    return out


def diff_statuses(prev: dict | None, cur: dict | None) -> list[dict]:
    """Checks whose status changed (both days must know the check). Pure."""
    prev, cur = prev or {}, cur or {}
    return [{"key": k, "from": prev[k], "to": cur[k]}
            for k in CHECK_KEYS if k in prev and k in cur and prev[k] != cur[k]]


def latest_changes(rows: list[dict]) -> dict[str, dict]:
    """{symbol: {"date", "prev_date", "changes"}} for symbols whose latest
    stored day differs from the day before it. Pure."""
    by_sym: dict[str, list[dict]] = {}
    for r in rows or []:
        sym = str(r.get("symbol") or "").upper()
        if sym and r.get("check_date"):
            by_sym.setdefault(sym, []).append(r)
    out: dict[str, dict] = {}
    for sym, rs in by_sym.items():
        rs.sort(key=lambda r: str(r["check_date"]))
        if len(rs) < 2:
            continue
        prev, cur = rs[-2], rs[-1]
        changes = diff_statuses(prev.get("statuses"), cur.get("statuses"))
        if changes:
            out[sym] = {"date": str(cur["check_date"])[:10], "prev_date": str(prev["check_date"])[:10],
                        "changes": changes}
    return out


async def run_check_snapshots(on_date: date | None = None) -> dict:
    from app.core.api_errors import is_missing_schema
    from app.db import queries
    from app.services import dividends, stock_page

    d = (on_date or dividends.today_et()).isoformat()
    try:
        symbols = sorted(await asyncio.to_thread(queries.get_all_followed_symbols))
    except Exception as e:
        logger.warning(f"check snapshots: followed symbols unavailable: {e}")
        return {"status": "unavailable"}
    if not symbols:
        return {"status": "ok", "date": d, "symbols": 0, "rows": 0}
    try:  # probe: don't build pages when the table is missing
        await asyncio.to_thread(queries.get_check_status_rows, symbols[:1], d)
    except Exception as e:
        if is_missing_schema(e):
            logger.warning(f"check snapshots: check_status_daily missing (apply migration 014): {e}")
            return {"status": "unavailable"}
        logger.warning(f"check snapshots: probe failed: {e}")
        return {"status": "unavailable"}

    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(sym: str) -> dict | None:
        async with sem:
            try:
                page = await asyncio.wait_for(stock_page.get_shared_page(sym), PAGE_TIMEOUT_S)
            except Exception as e:
                logger.debug(f"check snapshots: {sym} skipped: {e!r}")
                return None
            st = statuses_from_checks(page.get("checks"))
            return {"symbol": sym, "check_date": d, "statuses": st} if st else None

    rows = [r for r in await asyncio.gather(*(one(s) for s in symbols)) if r]
    if not rows:
        return {"status": "ok", "date": d, "symbols": len(symbols), "rows": 0, "failed": len(symbols)}
    try:
        written = await asyncio.to_thread(queries.upsert_check_status_rows, rows)
    except Exception as e:
        if is_missing_schema(e):
            return {"status": "unavailable"}
        logger.warning(f"check snapshots: write failed: {e}")
        return {"status": "failed", "date": d}
    return {"status": "ok", "date": d, "symbols": len(symbols), "rows": written,
            "failed": len(symbols) - len(rows)}
