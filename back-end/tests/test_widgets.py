"""GET /widgets/summary: value, day change and the next owned dividends."""

import asyncio

import pytest

from app.api.v1 import widgets
from app.services import dividend_calendar
from tests.portfolio_fakes import U1, FakePortfolioDB, make_client
from tests.test_portfolio_home import _setup


@pytest.fixture
def db(monkeypatch):
    d = FakePortfolioDB(monkeypatch)
    d.settings[U1] = {"user_id": U1, "home_currency": "CAD"}
    return d


def _cal(*events):
    return {"events": list(events)}


def _ev(sym, d, owned=True, **kw):
    return {"symbol": sym, "name": sym, "date": d, "ex_date": d, "pay_date": d, "amount_per_share": 1.0,
            "expected_cash": 10.0, "currency": "CAD", "estimated": False, "pay_date_estimated": False,
            "owned": owned, **kw}


def test_next_owned_dividends_picks_upcoming_owned_by_date():
    cal = _cal(_ev("B", "2026-10-20"), _ev("PAST", "2026-10-01"), _ev("W", "2026-10-05", owned=False),
               _ev("A", "2026-10-10"), _ev("C", "2026-11-01"), _ev("D", "2026-12-01"))
    out = widgets.next_owned_dividends(cal, "2026-10-03")
    assert [e["symbol"] for e in out] == ["A", "B", "C"]
    assert "owned" not in out[0] and out[0]["estimated"] is False


def test_summary_matches_portfolio_summary(monkeypatch, db):
    _setup(db)

    async def cal(holdings, watchlist, months, usdcad, home="CAD"):
        return _cal(_ev("XEQT.TO", "2099-01-01"))
    monkeypatch.setattr(dividend_calendar, "get_calendar", cal)
    body = make_client(monkeypatch, widgets.router, level="free").get("/api/v1/widgets/summary").json()
    assert body["currency"] == "CAD"
    assert body["value"] == pytest.approx(960 + 170)                  # same as /portfolio/summary total
    assert body["day_change"]["abs"] == pytest.approx(10 + 3 * 10 * 1.4)
    assert body["holdings_count"] == 2 and body["delayed_minutes"] == 15
    assert [e["symbol"] for e in body["next_dividends"]] == ["XEQT.TO"] and body["dividends_complete"] is True
    assert body["widgets"] == {"max": 1}


def test_premium_has_unlimited_widgets_and_slow_dividends_degrade(monkeypatch, db):
    _setup(db)
    monkeypatch.setattr(widgets, "DIVIDENDS_TIMEOUT_S", 0.01)

    async def slow(*a, **k):
        await asyncio.sleep(1)
    monkeypatch.setattr(dividend_calendar, "get_calendar", slow)
    body = make_client(monkeypatch, widgets.router, level="premium").get("/api/v1/widgets/summary").json()
    assert body["widgets"] == {"max": None}
    assert body["next_dividends"] == [] and body["dividends_complete"] is False
    assert body["value"] == pytest.approx(1130)
