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


# ---------------------------------------------------------------- the real return (return_pct) and Year in review

def _series(points: dict) -> pd.Series:
    return pd.Series(list(points.values()), index=pd.to_datetime(list(points.keys())))


def _scope(holdings=(), transactions=(), home="CAD"):
    return {"home_currency": home, "usdcad": 1.4, "holdings": list(holdings), "transactions": list(transactions),
            "quotes": {}, "accounts": [], "account_ids": None, "fixed_income": [], "user_id": None}


def _live(*positions):
    return {"merged": [{"symbol": s, "shares": sh, "currency": "CAD", "value_home": v} for s, sh, v in positions]}


def test_without_transactions_the_return_is_price_only():
    # the value doubled because holdings were added: none of that is return
    closes = {"A.TO": _series({"2026-08-31": 10.0, "2026-09-30": 11.0}),
              "B.TO": _series({"2026-08-31": 20.0, "2026-09-30": 19.0})}
    points = [(date(2026, 8, 31), 1000.0), (date(2026, 9, 30), 2000.0)]
    live = _live(("A.TO", 100, 1100.0), ("B.TO", 50, 950.0))
    r = recap.period_return(_scope(), live, points, closes, date(2026, 9, 1), date(2026, 9, 30))
    assert r == pytest.approx(round((100 * 11 + 50 * 19) / (100 * 10 + 50 * 20) * 100 - 100, 2))   # 2.5


def test_without_transactions_too_few_prices_gives_null():
    closes = {"A.TO": _series({"2026-08-31": 10.0, "2026-09-30": 11.0})}
    live = _live(("A.TO", 1, 11.0), ("B.TO", 100, 5000.0))   # B (most of the value) has no closes
    assert recap.period_return(_scope(), live, [], closes, date(2026, 9, 1), date(2026, 9, 30)) is None


def test_with_transactions_a_deposit_is_not_return():
    txs = [{"type": "deposit", "trade_date": "2026-09-15", "amount": 5000, "currency": "CAD"}]
    points = [(date(2026, 8, 31), 20000.0), (date(2026, 9, 30), 25500.0)]
    r = recap.period_return(_scope(transactions=txs), _live(), points, {}, date(2026, 9, 1), date(2026, 9, 30))
    # Modified Dietz: gain 500 over 20000 + 5000 x 15/30
    assert r == pytest.approx(round(500 / (20000 + 5000 * 15 / 30) * 100, 2))
    # no value before the month (started mid-month): null
    assert recap.period_return(_scope(transactions=txs), _live(), points[1:], {}, date(2026, 9, 1),
                               date(2026, 9, 30)) is None


def test_benchmark_return_and_name():
    closes = {"SPY": _series({"2026-08-29": 500.0, "2026-09-30": 510.5})}
    assert recap.benchmark_return(closes, "SPY", date(2026, 9, 1), date(2026, 9, 30)) == 2.1
    assert recap.benchmark_return(closes, None, date(2026, 9, 1), date(2026, 9, 30)) is None
    assert recap.benchmark_name("SPY")


def test_year_bounds():
    today = date(2026, 10, 10)
    assert recap.year_bounds(None, today) == (date(2026, 1, 1), today)
    assert recap.year_bounds(2025, today) == (date(2025, 1, 1), date(2025, 12, 31))
    with pytest.raises(Exception) as e:
        recap.year_bounds(2027, today)
    assert e.value.detail["code"] == "invalid_year"


def test_year_symbols_deposits_and_new_holdings():
    first, last = date(2026, 1, 1), date(2026, 10, 10)
    closes = {"OLD.TO": _series({"2025-12-31": 10.0, "2026-10-09": 12.0}),
              "NEW.TO": _series({"2025-12-31": 50.0, "2026-10-09": 44.0})}
    txs = [{"type": "buy", "symbol": "OLD.TO", "trade_date": "2024-05-01", "quantity": 10, "price": 8},
           {"type": "buy", "symbol": "NEW.TO", "trade_date": "2026-06-01", "quantity": 10, "price": 40},
           {"type": "buy", "symbol": "NEW.TO", "trade_date": "2026-07-01", "quantity": 10, "price": 60},
           {"type": "deposit", "trade_date": "2026-02-01", "amount": 1000, "currency": "CAD"},
           {"type": "withdrawal", "trade_date": "2026-03-01", "amount": 100, "currency": "USD"},
           {"type": "deposit", "trade_date": "2025-02-01", "amount": 9999, "currency": "CAD"}]
    holdings = [{"symbol": "OLD.TO", "created_at": "2024-05-01"}, {"symbol": "NEW.TO", "created_at": "2026-06-01"},
                {"symbol": "HAND.TO", "created_at": "2026-08-01T10:00:00+00:00"}]   # added by hand this year
    scope = _scope(holdings, txs)
    rets = dict(recap.year_symbol_returns(scope, closes, {"OLD.TO", "NEW.TO"}, first, last))
    assert rets == {"OLD.TO": 20.0, "NEW.TO": -12.0}   # NEW: from its average buy price (50), not Jan 1
    assert recap._net_deposits(txs, first, last, "CAD", 1.4) == 860.0   # 1000 - 100 USD x 1.4
    assert recap._net_deposits([], first, last, "CAD", 1.4) is None
    acquired = recap._first_acquired(scope)
    assert sum(1 for d in acquired.values() if first <= d <= last) == 2   # NEW.TO and HAND.TO


def test_year_endpoint(monkeypatch):
    db = FakePortfolioDB(monkeypatch)
    db.settings[U1] = {"user_id": U1, "home_currency": "CAD"}
    _setup(db)
    monkeypatch.setattr(price_cache, "fetch_daily_closes", lambda syms, period="1y": {})
    c = make_client(monkeypatch, portfolio_home.router, level="free")
    body = c.get("/api/v1/portfolio/recap/year").json()
    today = perf.today_et()
    assert body["year"] == today.year and body["currency"] == "CAD" and body["holdings_count"] == 2
    for k in ("return_pct", "benchmark_return_pct", "best_month", "worst_month", "net_deposits",
              "dividends_received", "best", "worst", "new_holdings", "estimated", "months"):
        assert k in body
    assert c.get(f"/api/v1/portfolio/recap/year?year={today.year + 1}").json()["detail"]["code"] == "invalid_year"
