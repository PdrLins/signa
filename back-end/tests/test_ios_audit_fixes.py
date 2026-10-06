"""Fixes from the iOS audit of back-end 1.0.9."""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.services import fixed_income as fi
from app.services import portfolio_performance as perf
from tests.portfolio_fakes import U1, FakePortfolioDB, make_client

NOW = datetime.now(timezone.utc)
CDB = {"id": "f1", "account_id": None, "name": "CDB", "kind": "cdb", "indexer": "pre", "rate": 0,
       "principal": 100000, "currency": "CAD", "start_date": "2026-01-02", "tax_exempt": False}


@pytest.fixture
def db(monkeypatch):
    perf.clear_cache()
    d = FakePortfolioDB(monkeypatch)
    d.settings[U1] = {"user_id": U1, "home_currency": "CAD"}
    yield d
    perf.clear_cache()


# ---------------------------------------------------------------- 1. auto_dividends switch

def test_profile_saves_auto_dividends(monkeypatch, db):
    from app.api.v1 import profile
    c = make_client(monkeypatch, profile.router)
    assert c.put("/api/v1/profile", json={"auto_dividends": False}).json()["auto_dividends"] is False
    assert c.get("/api/v1/profile").json()["auto_dividends"] is False
    assert c.put("/api/v1/profile", json={"auto_dividends": True}).json()["auto_dividends"] is True
    r = c.put("/api/v1/profile", json={"auto_dividends": "no"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_value"


# ---------------------------------------------------------------- 2. fixed income in history / performance

def _stocks_and_cdb(db, monkeypatch):
    a = db.add_account(U1, "Main", currency="CAD", cash_balance=0)
    db.add_holding(U1, "XEQT.TO", a, shares=100, avg_cost=30)
    db.quotes["XEQT.TO"] = {"symbol": "XEQT.TO", "price": 30.0, "prev_close": 30.0, "currency": "CAD",
                            "as_of": NOW.isoformat()}
    db.closes["XEQT.TO"] = pd.Series([30.0] * 60, index=pd.bdate_range(end=pd.Timestamp(perf.today_et()), periods=60))
    monkeypatch.setattr(fi, "rows_for", lambda uid: [dict(CDB)])
    bar = (NOW - timedelta(minutes=5), 30.0)   # no Yahoo in tests: today's 5-minute bars
    monkeypatch.setattr(perf, "_download_intraday", lambda syms, interval, prepost=False: {s: [bar] for s in syms})


def test_history_last_point_equals_summary_total(monkeypatch, db):
    from app.api.v1 import portfolio_home
    _stocks_and_cdb(db, monkeypatch)
    c = make_client(monkeypatch, portfolio_home.router)
    total = c.get("/api/v1/portfolio/summary").json()["total"]
    assert total == pytest.approx(103000)                      # 3,000 in stocks + 100,000 CDB
    for rng in ("1W", "1M"):
        h = c.get(f"/api/v1/portfolio/history?range={rng}").json()
        assert h["series"][-1]["value"] == pytest.approx(total)
        assert abs(h["range_return_pct"]) < 1                   # no -97% drop at today
    one_day = c.get("/api/v1/portfolio/history?range=1D").json()
    assert one_day["series"][-1]["value"] == pytest.approx(total)


def test_performance_ignores_fixed_income_principal(monkeypatch, db):
    from app.api.v1 import portfolio_home
    _stocks_and_cdb(db, monkeypatch)
    c = make_client(monkeypatch, portfolio_home.router)
    p = c.get("/api/v1/portfolio/performance?range=1M").json()
    assert abs(p["return_pct"]) < 1


# ---------------------------------------------------------------- 3. two accounts, one calendar position

def test_calendar_merges_the_same_stock_in_two_accounts():
    import asyncio

    from app.services import dividend_calendar as dc
    today = perf.today_et()
    ex = today + timedelta(days=5)
    prof = {"symbol": "ENB.TO", "pays_dividend": True, "currency": "CAD", "last_payments": [],
            "upcoming": [{"ex_date": ex.isoformat(), "pay_date": (ex + timedelta(days=15)).isoformat(),
                          "amount": 1.0, "estimated": False}]}

    async def fetch(sym):
        return prof
    holdings = [{"symbol": "ENB.TO", "shares": 10, "account_id": "a"},
                {"symbol": "ENB.TO", "shares": 5, "account_id": "b"}]
    cal = asyncio.run(dc.get_calendar(holdings, None, 2, 1.4, today, fetch, "CAD"))
    owned = [e for e in cal["events"] if e.get("owned")]
    assert owned and owned[0]["shares"] == 15


# ---------------------------------------------------------------- 4. start date in New York

def test_start_date_today_in_new_york_is_accepted(monkeypatch):
    from app.services import dividends
    today = dividends.today_et()
    for d in (today, today + timedelta(days=1)):   # "today" east of UTC can be tomorrow in New York
        v = fi.validate({"name": "CDB", "kind": "cdb", "indexer": "cdi", "rate": 100, "principal": 1,
                         "start_date": d.isoformat()})
        assert v["start_date"] == d.isoformat()


# ---------------------------------------------------------------- 5. auto note

def test_editing_an_estimate_clears_signa_note(monkeypatch, db):
    from app.services import auto_dividends as ad
    from app.services import transactions_service as ts
    a = db.add_account(U1, "Main", currency="CAD", cash_balance=0)
    [row] = db.insert_transactions(U1, [{"account_id": a, "symbol": "ENB.TO", "type": "dividend",
                                         "trade_date": "2026-09-10", "quantity": 100, "price": 0.97, "amount": 97,
                                         "currency": "CAD", "fee": 0, "note": ad.NOTE_PT, "source": "auto",
                                         "auto_ref": "auto:x:ENB.TO:2026-09-01", "import_batch_id": None}])
    out = ts.update_transaction(U1, row["id"], {"amount": 82.45})
    assert out["source"] == "manual" and out["estimated"] is False and out["note"] is None
    assert ad.note_for("pt").startswith("Estimado pelo Signa")


# ---------------------------------------------------------------- 6. alert feed day

def test_alert_feed_uses_the_new_york_day():
    from app.services import price_alerts as pa
    late = "2026-10-03T02:30:00+00:00"   # 22:30 on Oct 2 in New York
    item = pa.feed_items([{"id": "a", "symbol": "X", "direction": "above", "target_price": 1, "last_price": 1.1,
                           "currency": "USD", "triggered_at": late}])[0]
    assert item["date"] == "2026-10-02"
