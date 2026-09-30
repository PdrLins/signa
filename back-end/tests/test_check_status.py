"""Daily Signa check statuses per symbol (migration 014): pure diff + the job."""

import asyncio
from datetime import date

from app.db import queries
from app.services import check_status, stock_page


def _checks(**st):
    return [{"key": k, "status": v} for k, v in st.items()]


def test_statuses_from_checks_keeps_known_keys():
    st = check_status.statuses_from_checks(_checks(uptrend="pass", liquidity="warn", bogus="fail"))
    assert st == {"uptrend": "pass", "liquidity": "warn"}


def test_diff_statuses_only_changes_known_both_days():
    prev = {"uptrend": "pass", "liquidity": "pass", "dividend_health": "warn"}
    cur = {"uptrend": "fail", "liquidity": "pass", "earnings_soon": "warn"}
    assert check_status.diff_statuses(prev, cur) == [{"key": "uptrend", "from": "pass", "to": "fail"}]
    assert check_status.diff_statuses(None, cur) == []


def test_latest_changes_uses_last_two_days():
    rows = [
        {"symbol": "nvda", "check_date": "2026-09-27", "statuses": {"uptrend": "fail"}},
        {"symbol": "NVDA", "check_date": "2026-09-29", "statuses": {"uptrend": "pass"}},
        {"symbol": "NVDA", "check_date": "2026-09-28", "statuses": {"uptrend": "warn"}},
        {"symbol": "XEQT.TO", "check_date": "2026-09-29", "statuses": {"uptrend": "pass"}},   # one day only
        {"symbol": "ENB.TO", "check_date": "2026-09-28", "statuses": {"uptrend": "pass"}},
        {"symbol": "ENB.TO", "check_date": "2026-09-29", "statuses": {"uptrend": "pass"}},    # unchanged
    ]
    out = check_status.latest_changes(rows)
    assert out == {"NVDA": {"date": "2026-09-29", "prev_date": "2026-09-28",
                            "changes": [{"key": "uptrend", "from": "warn", "to": "pass"}]}}


def test_run_check_snapshots_writes_and_skips_failures(monkeypatch):
    written = []
    monkeypatch.setattr(queries, "get_all_followed_symbols", lambda: {"NVDA", "BAD", "ENB.TO"})
    monkeypatch.setattr(queries, "get_check_status_rows", lambda syms, since=None: [])
    monkeypatch.setattr(queries, "upsert_check_status_rows", lambda rows: written.extend(rows) or len(rows))

    async def page(sym):
        if sym == "BAD":
            raise stock_page.StockPageError("not_found", "x", 404)
        return {"checks": _checks(uptrend="pass", liquidity="warn")}
    monkeypatch.setattr(stock_page, "get_shared_page", page)
    r = asyncio.run(check_status.run_check_snapshots(date(2026, 9, 30)))
    assert r == {"status": "ok", "date": "2026-09-30", "symbols": 3, "rows": 2, "failed": 1}
    assert sorted(w["symbol"] for w in written) == ["ENB.TO", "NVDA"]
    assert written[0]["check_date"] == "2026-09-30" and written[0]["statuses"] == {"uptrend": "pass",
                                                                                   "liquidity": "warn"}


def test_run_check_snapshots_missing_table_builds_nothing(monkeypatch):
    built = []
    monkeypatch.setattr(queries, "get_all_followed_symbols", lambda: {"NVDA"})

    def missing(*a, **k):
        raise RuntimeError('relation "public.check_status_daily" does not exist (42P01)')
    monkeypatch.setattr(queries, "get_check_status_rows", missing)

    async def page(sym):
        built.append(sym)
        return {"checks": []}
    monkeypatch.setattr(stock_page, "get_shared_page", page)
    assert asyncio.run(check_status.run_check_snapshots(date(2026, 9, 30))) == {"status": "unavailable"}
    assert built == []


def test_run_check_snapshots_no_symbols(monkeypatch):
    monkeypatch.setattr(queries, "get_all_followed_symbols", lambda: set())
    r = asyncio.run(check_status.run_check_snapshots(date(2026, 9, 30)))
    assert r["status"] == "ok" and r["rows"] == 0
