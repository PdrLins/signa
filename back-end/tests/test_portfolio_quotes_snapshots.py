"""Shared quotes (one batched download, upsert, table-first reads) and daily
portfolio snapshots (per user + per account, home currency, idempotent)."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app.db import queries
from app.services import portfolio_snapshots as snaps
from app.services import quotes

ET = ZoneInfo("America/New_York")


def _frame(data: dict[str, list[float]]) -> pd.DataFrame:
    """Fake multi-ticker yf.download frame (2 daily bars)."""
    idx = pd.to_datetime(["2026-09-29", "2026-09-30"])
    cols, values = [], []
    for field in ("Close", "High", "Low"):
        for sym, closes in data.items():
            cols.append((field, sym))
            bump = {"Close": 0, "High": 1, "Low": -1}[field]
            values.append([c + bump for c in closes])
    return pd.DataFrame(list(zip(*values)), index=idx, columns=pd.MultiIndex.from_tuples(cols))


@pytest.fixture
def downloads(monkeypatch):
    calls = []

    def fake(symbols):
        calls.append(list(symbols))
        return _frame({s: [100.0, 110.0] for s in symbols if s != "NOPE"})
    monkeypatch.setattr(quotes, "_download", fake)
    return calls


@pytest.fixture
def table(monkeypatch):
    rows: dict[str, dict] = {}
    monkeypatch.setattr(queries, "upsert_quotes", lambda rs: rows.update({r["symbol"]: r for r in rs}) or len(rs))
    monkeypatch.setattr(queries, "get_quote_rows", lambda syms: [rows[s] for s in syms if s in rows])
    return rows


# ---------------------------------------------------------------- quotes

def test_refresh_is_one_batched_call(downloads, table):
    out = quotes.refresh_quotes(["nvda", "XEQT.TO", "NVDA", "BTC-USD", "NOPE", "bad!!"])
    assert downloads == [["NVDA", "XEQT.TO", "BTC-USD", "NOPE"]]   # one call, deduped, invalid dropped
    assert set(out) == {"NVDA", "XEQT.TO", "BTC-USD"} and set(table) == set(out)
    q = out["XEQT.TO"]
    assert q["price"] == 110 and q["prev_close"] == 100 and q["change_pct"] == pytest.approx(10)
    assert q["currency"] == "CAD" and out["NVDA"]["currency"] == "USD"
    assert q["day_high"] == 111 and q["day_low"] == 109 and q["as_of"].startswith("2026-09-30")


def test_refresh_chunks_large_lists(monkeypatch, downloads, table):
    monkeypatch.setattr(quotes, "QUOTE_BATCH", 2)
    quotes.refresh_quotes(["A", "B", "C"])
    assert downloads == [["A", "B"], ["C"]]


def test_get_quotes_reads_table_and_fetches_only_missing(downloads, table):
    table["NVDA"] = {"symbol": "NVDA", "price": "500", "currency": "USD"}
    out = quotes.get_quotes(["NVDA", "AAPL"])
    assert out["NVDA"]["price"] == 500 and out["AAPL"]["price"] == 110
    assert downloads == [["AAPL"]]


def test_get_quotes_without_table_falls_back_live(monkeypatch, downloads):
    def missing(*a, **k):
        raise RuntimeError('relation "quotes" does not exist')
    monkeypatch.setattr(queries, "get_quote_rows", missing)
    monkeypatch.setattr(queries, "upsert_quotes", missing)
    assert quotes.get_quotes(["NVDA"])["NVDA"]["price"] == 110


def test_download_failure_never_raises(monkeypatch, table):
    def boom(symbols):
        raise RuntimeError("yahoo down")
    monkeypatch.setattr(quotes, "_download", boom)
    assert quotes.refresh_quotes(["NVDA"]) == {}


@pytest.mark.parametrize("when,open_", [
    (datetime(2026, 9, 30, 10, 0, tzinfo=ET), True),
    (datetime(2026, 9, 30, 9, 15, tzinfo=ET), False),
    (datetime(2026, 9, 30, 16, 30, tzinfo=ET), False),
    (datetime(2026, 10, 3, 11, 0, tzinfo=ET), False),    # Saturday
    (datetime(2026, 12, 25, 11, 0, tzinfo=ET), False),   # both closed
    (datetime(2026, 10, 12, 11, 0, tzinfo=ET), True),    # CA Thanksgiving: NYSE open
])
def test_in_market_session(when, open_):
    assert quotes.in_market_session(when) is open_


def test_followed_refresh_skips_when_closed(monkeypatch, downloads, table):
    monkeypatch.setattr(queries, "get_follow_rows",
                        lambda: [{"user_id": "u1", "symbol": "NVDA"}, {"user_id": "u1", "symbol": "XEQT.TO"}])
    monkeypatch.setattr(queries, "get_users_activity", lambda: [
        {"id": "u1", "access_level": "free", "last_seen_at": datetime.now(ET).isoformat()}])
    monkeypatch.setattr(quotes, "_last_refresh", {})
    closed = datetime(2026, 10, 3, 11, 0, tzinfo=ET)
    assert quotes.refresh_followed_quotes(now=closed) == {"status": "closed"} and downloads == []
    r = quotes.refresh_followed_quotes(force=True)
    assert r == {"status": "ok", "followed": 2, "symbols": 2, "quotes": 2} and len(downloads) == 1


# ---------------------------------------------------------------- snapshots

def test_convert_usd_cad_only():
    assert snaps.convert(100, "USD", "CAD", 1.4) == 140
    assert snaps.convert(140, "CAD", "USD", 1.4) == pytest.approx(100)
    assert snaps.convert(100, "EUR", "CAD", 1.4) is None
    assert snaps.convert(100, "USD", "CAD", None) is None
    assert snaps.convert(100, "BRL", "BRL", None) == 100


def test_compute_snapshot_rows():
    accounts = [{"id": "a", "currency": "CAD", "cash_balance": 1000},
                {"id": "b", "currency": "USD", "cash_balance": 100},
                {"id": "c", "currency": "EUR", "cash_balance": 50}]
    holdings = [
        {"symbol": "XEQT.TO", "account_id": "a", "shares": 10, "avg_cost": 30},
        {"symbol": "NVDA", "account_id": "b", "shares": 2, "avg_cost": 100},
        {"symbol": "NVDA", "account_id": None, "shares": 1},                      # no account: total only
        {"symbol": "SAP.DE", "account_id": "c", "shares": 1, "currency": "EUR"},  # unconverted
        {"symbol": "NOPRICE", "account_id": "a", "shares": 5},
        {"symbol": "ENB.TO", "account_id": "a", "shares": None},
    ]
    q = {"XEQT.TO": {"price": 35, "currency": "CAD"}, "NVDA": {"price": 150, "currency": "USD"},
         "SAP.DE": {"price": 200, "currency": "EUR"}}
    rows = {r["account_id"]: r for r in snaps.compute_snapshot_rows(holdings, accounts, q, "CAD", 1.4)}
    total = rows[None]
    assert total["currency"] == "CAD"
    assert total["market_value"] == pytest.approx(350 + 3 * 150 * 1.4)
    assert total["cost_basis"] == pytest.approx(300 + 200 * 1.4)
    assert total["cash"] == pytest.approx(1000 + 140)
    assert {u.get("symbol") or u.get("currency") for u in total["unconverted"]} == {"SAP.DE", "EUR"}
    assert rows["a"]["market_value"] == 350 and rows["a"]["cash"] == 1000 and rows["a"]["unconverted"] is None
    assert rows["b"]["market_value"] == pytest.approx(420) and rows["b"]["cash"] == pytest.approx(140)
    assert rows["c"]["market_value"] == 0 and len(rows["c"]["unconverted"]) == 2


def test_run_snapshots_is_idempotent(monkeypatch):
    store: dict[tuple, list] = {}
    monkeypatch.setattr(queries, "get_all_holdings", lambda: [
        {"user_id": "u1", "symbol": "NVDA", "account_id": "a", "shares": 1, "avg_cost": 100},
        {"user_id": "u2", "symbol": "XEQT.TO", "account_id": None, "shares": 2},
    ])
    monkeypatch.setattr(queries, "get_all_accounts", lambda: [
        {"id": "a", "user_id": "u1", "currency": "USD", "cash_balance": 0},
        {"id": "z", "user_id": "u3", "currency": "CAD", "cash_balance": 10},
    ])
    monkeypatch.setattr(queries, "get_user_home_currencies", lambda uids: {"u1": "USD"})
    monkeypatch.setattr(quotes, "get_quotes", lambda syms: {"NVDA": {"price": 150, "currency": "USD"},
                                                            "XEQT.TO": {"price": 35, "currency": "CAD"}})
    monkeypatch.setattr("app.services.price_cache.get_usdcad_rate", lambda *a, **k: 1.4)

    def replace(d, rows_by_user):
        for uid, rows in rows_by_user.items():
            store[(uid, d)] = rows
        return sum(len(r) for r in rows_by_user.values()), 0
    monkeypatch.setattr(queries, "replace_portfolio_snapshots_batch", replace)
    day = date(2026, 9, 30)
    r1 = snaps.run_snapshots(day)
    first = dict(store)
    r2 = snaps.run_snapshots(day)
    assert r1 == r2 and r1["users"] == 3 and store == first and len(store) == 3
    u1 = {r["account_id"]: r for r in store[("u1", "2026-09-30")]}
    assert u1[None]["currency"] == "USD" and u1[None]["market_value"] == 150 and u1["a"]["cost_basis"] == 100
    assert store[("u2", "2026-09-30")][0]["market_value"] == 70   # default CAD
    assert store[("u3", "2026-09-30")][0]["cash"] == 10


def test_run_snapshots_degrades(monkeypatch):
    assert snaps.run_snapshots(date(2026, 12, 25))["status"] == "market_closed"

    def missing():
        raise RuntimeError('relation "accounts" does not exist')
    monkeypatch.setattr(queries, "get_all_holdings", lambda: [])
    monkeypatch.setattr(queries, "get_all_accounts", missing)
    assert snaps.run_snapshots(date(2026, 9, 30))["status"] == "unavailable"


def test_scheduler_registers_portfolio_jobs():
    from app.scheduler.runner import init_scheduler
    s = init_scheduler()
    jobs = {j.id: j for j in s.get_jobs()}
    assert {"quotes_refresh", "quotes_refresh_after_close", "portfolio_snapshots"} <= set(jobs)
    q = jobs["quotes_refresh"]
    assert q.coalesce is True and q.max_instances == 1 and q.misfire_grace_time == 30
