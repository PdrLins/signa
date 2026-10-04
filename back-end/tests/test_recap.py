"""Monthly recap: GET /portfolio/recap and the 1st-of-month push."""

from datetime import date

import pandas as pd
import pytest

from app.api.v1 import portfolio_home
from app.services import dividend_calendar, price_cache
from app.services import portfolio_performance as perf
from app.services import recap
from tests.portfolio_fakes import U1, FakePortfolioDB, make_client
from tests.test_portfolio_home import _setup


def test_month_bounds():
    assert recap.month_bounds(None, date(2026, 10, 3)) == (date(2026, 9, 1), date(2026, 9, 30))
    assert recap.month_bounds(None, date(2026, 1, 15)) == (date(2025, 12, 1), date(2025, 12, 31))
    assert recap.month_bounds("2026-02", date(2026, 10, 3)) == (date(2026, 2, 1), date(2026, 2, 28))
    for bad in ("2026-13", "sept", "2027-01"):
        with pytest.raises(Exception):
            recap.month_bounds(bad, date(2026, 10, 3))


def test_value_at_and_returns():
    pts = [(date(2026, 8, 31), 100.0), (date(2026, 9, 15), 105.0), (date(2026, 9, 30), 110.0)]
    assert recap.value_at(pts, date(2026, 8, 31)) == 100 and recap.value_at(pts, date(2026, 9, 29)) == 105
    assert recap.value_at(pts, date(2026, 8, 1)) is None
    s = pd.Series([10.0, 11.0, 12.0], index=pd.to_datetime(["2026-08-29", "2026-09-10", "2026-09-30"]))
    t = pd.Series([20.0, 18.0], index=pd.to_datetime(["2026-08-31", "2026-09-30"]))
    assert recap.symbol_returns({"A": s, "B": t}, date(2026, 9, 1), date(2026, 9, 30)) == [("A", 20.0), ("B", -10.0)]


def test_dividends_in_month_only():
    txs = [{"type": "dividend", "trade_date": "2026-09-15", "amount": 10, "currency": "CAD"},
           {"type": "dividend", "trade_date": "2026-10-01", "amount": 99, "currency": "CAD"},
           {"type": "buy", "trade_date": "2026-09-02", "amount": 500, "currency": "CAD"}]
    assert recap.dividends_in(txs, date(2026, 9, 1), date(2026, 9, 30), "CAD", 1.4) == (10.0, 1)
    assert recap.dividends_in([], date(2026, 9, 1), date(2026, 9, 30), "CAD", 1.4) == (None, 0)


def test_push_text():
    from app.services.telegram_notify import money
    r = {"month": "2026-09", "currency": "CAD", "change": {"abs": 1240.0, "pct": 3.24}, "dividends_received": 45.0}
    assert recap.push_text(r, money) == "September: +3.2% (+C$1,240.00) · C$45.00 in dividends"
    r = {"month": "2026-09", "currency": "CAD", "change": {"abs": None, "pct": None}, "dividends_received": None}
    assert recap.push_text(r, money) == "September recap is ready."
    r = {"month": "2026-09", "currency": "BRL", "change": {"abs": 1240.0, "pct": 3.24}, "dividends_received": 45.0}
    assert recap.push_text(r, money, "pt") == "Setembro: +3,2% (+R$ 1.240,00) · R$ 45,00 em dividendos"


def test_recap_endpoint(monkeypatch):
    db = FakePortfolioDB(monkeypatch)
    db.settings[U1] = {"user_id": U1, "home_currency": "CAD"}
    _setup(db)
    today = perf.today_et()
    first, last = recap.month_bounds(None, today)
    before = (pd.Timestamp(first) - pd.Timedelta(days=1)).date()
    db.snapshots += [{"user_id": U1, "snapshot_date": before.isoformat(), "account_id": None, "market_value": 1000,
                      "cash": 0, "cost_basis": None, "currency": "CAD", "unconverted": []},
                     {"user_id": U1, "snapshot_date": last.isoformat(), "account_id": None, "market_value": 1100,
                      "cash": 0, "cost_basis": None, "currency": "CAD", "unconverted": []}]
    monkeypatch.setattr(price_cache, "fetch_daily_closes", lambda syms, period="1y": {})

    async def cal(*a, **k):
        return {"events": []}
    monkeypatch.setattr(dividend_calendar, "get_calendar", cal)
    body = make_client(monkeypatch, portfolio_home.router, level="free").get("/api/v1/portfolio/recap").json()
    assert body["month"] == first.strftime("%Y-%m") and body["currency"] == "CAD"
    assert body["start_value"] == 1000 and body["end_value"] == 1100
    assert body["change"] == {"abs": 100.0, "pct": 10.0}
    assert body["next_month"]["payments"] == 0
    r = make_client(monkeypatch, portfolio_home.router).get("/api/v1/portfolio/recap?month=2099-01")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_month"


def test_deposits_in_the_month_are_not_gains():
    from datetime import date

    from app.services import portfolio_performance as perf
    txs = [{"type": "deposit", "trade_date": "2026-09-10", "amount": 10000, "currency": "BRL"}]
    fl = perf.external_flows(txs, date(2026, 8, 31), date(2026, 9, 30), "BRL", None)
    md = perf.modified_dietz(20000, 30500, fl["flows"], date(2026, 8, 31), date(2026, 9, 30))
    assert round(md["gain"], 2) == 500 and md["net_flows"] == 10000   # +R$10k deposited, R$500 earned
