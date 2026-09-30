"""Coming up (GET /events/upcoming): merge/sort, each source, scope, failures.
All market data is faked (no network, no DB, no AI)."""

from datetime import date

import pandas as pd
import pytest

from app.api.v1 import events as events_api
from app.db import queries
from app.services import dividends, economic_calendar, events_feed
from tests.portfolio_fakes import U1, FakePortfolioDB, make_client

TODAY = date(2026, 9, 30)


def _profile(sym, ccy="USD", ex="2026-10-05", pay="2026-10-20", amount=0.5):
    return {"symbol": sym, "pays_dividend": True, "currency": ccy, "frequency": "quarterly",
            "upcoming": [{"ex_date": ex, "pay_date": pay, "amount": amount, "estimated": False,
                          "pay_estimated": False}],
            "last_payments": []}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    events_feed.clear_cache()
    monkeypatch.setattr(dividends, "today_et", lambda: TODAY)


@pytest.fixture
def fakes(monkeypatch):
    """Replace every fetcher; returns a dict tests can tweak."""
    state = {
        "profiles": {"NVDA": _profile("NVDA"), "AAPL": _profile("AAPL", ex="2026-10-10", pay="2026-10-25")},
        "earnings": {"NVDA": {"date": "2026-10-15", "days": 15, "trading_days": 11}},
        "earnings_dates": {"NVDA": [date(2026, 8, 20), date(2026, 5, 20), date(2026, 10, 15)]},
        "closes": {"NVDA": pd.Series([100.0, 100.0, 110.0, 110.0, 100.0, 90.0],
                                     index=pd.to_datetime(["2026-05-18", "2026-05-19", "2026-05-21",
                                                           "2026-08-19", "2026-08-21", "2026-08-24"]))},
        "upgrades": {"NVDA": [
            {"date": "2026-09-28", "firm": "Firm A", "from_grade": "Hold", "to_grade": "Buy", "action": "up",
             "current_target": 200.0, "prior_target": 150.0},
            {"date": "2026-09-01", "firm": "Old Firm", "from_grade": "Buy", "to_grade": "Sell", "action": "down"},
        ]},
        "calls": {"upgrades": [], "profiles": []},
    }

    async def fp(symbols):
        state["calls"]["profiles"].append(sorted(symbols))
        if state.get("profiles_raise"):
            raise RuntimeError("yahoo down")
        return {s: state["profiles"].get(s) for s in symbols}

    async def fe(item, today):
        return state["earnings"].get(item["symbol"])

    def fu(sym):
        state["calls"]["upgrades"].append(sym)
        if state.get("upgrades_raise"):
            raise RuntimeError("boom")
        return state["upgrades"].get(sym, [])

    monkeypatch.setattr(events_feed, "fetch_profiles", fp)
    monkeypatch.setattr(events_feed, "fetch_earnings", fe)
    monkeypatch.setattr(events_feed, "fetch_upgrades", fu)
    monkeypatch.setattr(events_feed, "fetch_earnings_dates", lambda s: state["earnings_dates"].get(s, []))
    monkeypatch.setattr(events_feed, "fetch_closes", lambda syms: {s: state["closes"][s] for s in syms
                                                                   if s in state["closes"]})
    return state


@pytest.fixture
def db(monkeypatch):
    d = FakePortfolioDB(monkeypatch)
    a1 = d.add_account(U1, "WS", currency="USD")
    a2 = d.add_account(U1, "Quest", currency="USD")
    d.add_holding(U1, "NVDA", a1, shares=10, avg_cost=100, currency="USD", asset_type="STOCK")
    d.add_holding(U1, "NVDA", a2, shares=5, avg_cost=100, currency="USD", asset_type="STOCK")
    d.quotes["NVDA"] = {"symbol": "NVDA", "price": 180.0, "prev_close": 178.0, "currency": "USD",
                        "as_of": "2026-09-30T14:00:00+00:00"}
    d.watchlist[U1] = [{"symbol": "AAPL"}]
    d.check_rows[("NVDA", "2026-09-28")] = {"symbol": "NVDA", "check_date": "2026-09-28",
                                           "statuses": {"uptrend": "pass", "liquidity": "pass"}}
    d.check_rows[("NVDA", "2026-09-29")] = {"symbol": "NVDA", "check_date": "2026-09-29",
                                           "statuses": {"uptrend": "warn", "liquidity": "pass"}}
    d.a1, d.a2 = a1, a2
    return d


def _get(monkeypatch, path, level="free"):
    return make_client(monkeypatch, events_api.router, level=level).get(path)


# ---------------------------------------------------------------- pure pieces

def test_economy_calendar_window_and_provisional():
    evs = economic_calendar.events_between(date(2026, 10, 1), date(2026, 10, 31))
    codes = {e["code"] for e in evs}
    assert codes == {"boc_rate", "fed_rate", "us_cpi", "ca_cpi"}
    assert [e["date"] for e in evs] == sorted(e["date"] for e in evs)
    assert all(e["date"].startswith("2026-10") for e in evs)
    ev_2027 = economic_calendar.events_between(date(2027, 1, 1), date(2027, 12, 31))
    # StatCan has published Canada CPI through March 2027; everything else in 2027 is provisional.
    confirmed = {e["date"] for e in ev_2027 if not e["provisional"]}
    assert confirmed == {"2027-01-18", "2027-02-16", "2027-03-15"}
    assert all(e["code"] == "ca_cpi" for e in ev_2027 if not e["provisional"])
    assert economic_calendar.COVERED_UNTIL.year == 2027


def test_avg_earnings_move_close_before_to_close_after(fakes):
    move = events_feed.avg_earnings_move(fakes["closes"]["NVDA"], fakes["earnings_dates"]["NVDA"], TODAY)
    # May: 100 -> 110 (+10%); Aug: 110 -> 100 (-9.09%); the Oct report is in the future
    assert move["reports"] == 2
    assert [m["move_pct"] for m in move["moves"]] == [10.0, -9.09]
    assert move["avg_abs_move_pct"] == pytest.approx(9.545, abs=0.01)
    assert events_feed.avg_earnings_move(None, [date(2026, 1, 1)], TODAY) is None


def test_dividend_items_cash_accounts_and_watched():
    pos = events_feed.positions_by_symbol([
        {"symbol": "NVDA", "account_id": "a1", "shares": 10, "currency": "USD"},
        {"symbol": "NVDA", "account_id": "a2", "shares": 5, "currency": "USD"}])["NVDA"]
    items = events_feed.dividend_items(_profile("NVDA"), pos, True, TODAY, date(2026, 10, 30), "CAD", 1.4)
    ex, pay = items
    assert ex["type"] == "ex_dividend" and ex["date"] == "2026-10-05" and pay["date"] == "2026-10-20"
    assert ex["cash"] == 7.5 and ex["cash_home"] == 10.5 and ex["currency"] == "USD"
    assert ex["accounts"] == [{"account_id": "a1", "shares": 10.0, "cash": 5.0},
                              {"account_id": "a2", "shares": 5.0, "cash": 2.5}]
    watched = events_feed.dividend_items(_profile("NVDA"), {**pos, "accounts": []}, False, TODAY,
                                         date(2026, 10, 30), "CAD", 1.4)
    assert all(i["cash"] is None and i["shares"] is None and not i["owned"] for i in watched)
    # payment outside the window: only the ex-date remains
    only_ex = events_feed.dividend_items(_profile("NVDA"), pos, True, TODAY, date(2026, 10, 10), "CAD", 1.4)
    assert [i["type"] for i in only_ex] == ["ex_dividend"]


def test_analyst_items_last_seven_days_only(fakes):
    items = events_feed.analyst_items("NVDA", fakes["upgrades"]["NVDA"], {"name": "Nvidia"}, TODAY)
    assert len(items) == 1
    a = items[0]
    assert a["firm"] == "Firm A" and a["from_grade"] == "Hold" and a["to_grade"] == "Buy"
    assert a["price_target"] == 200.0 and a["prior_price_target"] == 150.0
    assert a["recent"] is True and a["date"] == "2026-09-28" and "Hold → Buy" in a["detail"]


def test_sort_order_date_then_type_then_symbol():
    items = [events_feed._item(t, "2026-10-05", s, "", "") for t, s in
             (("earnings", "B"), ("ex_dividend", "Z"), ("economy", None), ("ex_dividend", "A"))]
    items.append(events_feed._item("analyst", "2026-09-28", "Q", "", ""))
    out = events_feed.sort_items(items)
    assert [(i["type"], i["symbol"]) for i in out] == [
        ("analyst", "Q"), ("economy", None), ("ex_dividend", "A"), ("ex_dividend", "Z"), ("earnings", "B")]


# ---------------------------------------------------------------- API

def test_upcoming_merges_all_sources(monkeypatch, db, fakes):
    r = _get(monkeypatch, "/api/v1/events/upcoming?days=30")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["delayed_minutes"] == 15 and body["as_of"] == "2026-09-30T14:00:00+00:00"
    assert body["sources"] == {"dividends": "ok", "earnings": "ok", "analyst": "ok",
                               "check_changed": "ok", "economy": "ok", "price_alerts": "ok"}
    assert body["symbols"] == {"held": ["NVDA"], "watched": ["AAPL"]}
    items = body["items"]
    assert [i["date"] for i in items] == sorted(i["date"] for i in items)
    types = {i["type"] for i in items}
    assert types == {"ex_dividend", "dividend_payment", "earnings", "analyst", "check_changed", "economy"}

    nv_ex = next(i for i in items if i["type"] == "ex_dividend" and i["symbol"] == "NVDA")
    assert nv_ex["shares"] == 15 and nv_ex["cash"] == 7.5 and nv_ex["cash_home"] == 10.5
    aapl = [i for i in items if i["symbol"] == "AAPL"]
    assert aapl and all(i["cash"] is None and i["owned"] is False for i in aapl)

    earn = next(i for i in items if i["type"] == "earnings")
    assert earn["symbol"] == "NVDA" and earn["avg_abs_move_pct"] == pytest.approx(9.545, abs=0.01)
    assert earn["typical_move_home"] == pytest.approx(15 * 180 * 0.0955 * 1.4, rel=0.01)

    chk = next(i for i in items if i["type"] == "check_changed")
    assert chk["date"] == "2026-09-29" and chk["changes"] == [{"key": "uptrend", "from": "pass", "to": "warn"}]
    assert chk["recent"] is True
    assert fakes["calls"]["upgrades"] == ["NVDA"]            # analyst: held symbols only
    assert all(i["date"] <= "2026-10-30" for i in items)
    assert body["count"] == len(items)


def test_account_scope_drops_watchlist(monkeypatch, db, fakes):
    body = _get(monkeypatch, f"/api/v1/events/upcoming?account_id={db.a2}").json()
    assert body["symbols"] == {"held": ["NVDA"], "watched": []}
    ex = next(i for i in body["items"] if i["type"] == "ex_dividend")
    assert ex["shares"] == 5 and ex["cash"] == 2.5


@pytest.mark.parametrize("days", [0, 91])
def test_days_validation(monkeypatch, db, fakes, days):
    r = _get(monkeypatch, f"/api/v1/events/upcoming?days={days}")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_days"


def test_failing_sources_do_not_break_the_feed(monkeypatch, db, fakes):
    fakes["profiles_raise"] = True
    fakes["upgrades_raise"] = True

    def missing(*a, **k):
        raise RuntimeError('relation "public.check_status_daily" does not exist (42P01)')
    monkeypatch.setattr(queries, "get_check_status_rows", missing)
    r = _get(monkeypatch, "/api/v1/events/upcoming")
    assert r.status_code == 200
    body = r.json()
    assert body["sources"]["dividends"] == "failed" and body["sources"]["analyst"] == "failed"
    assert body["sources"]["check_changed"] == "unavailable"
    types = {i["type"] for i in body["items"]}
    assert types == {"earnings", "economy"}


def test_unknown_account_404(monkeypatch, db, fakes):
    r = _get(monkeypatch, "/api/v1/events/upcoming?account_id=33333333-3333-3333-3333-333333333333")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "account_not_found"


def test_records_usage(monkeypatch, db, fakes):
    from app.services import usage_metrics
    _get(monkeypatch, "/api/v1/events/upcoming")
    counts = next(iter(usage_metrics.pending().values()))
    assert counts["requests.events_upcoming"] == 1
    assert counts["provider_calls.analyst"] == 1 and counts["provider_calls.earnings_moves"] == 1
