"""Per-holding change over a range (GET /holdings/changes), dividend fields on
/holdings items, similar funds for every plan (migration 033)."""

from datetime import date

import pandas as pd
import pytest

from app.services import portfolio_performance as perf

TODAY = date(2026, 10, 9)
BASE = date(2026, 10, 2)   # 1W


def _closes(points: dict[str, float]) -> pd.Series:
    return pd.Series(list(points.values()), index=pd.to_datetime(list(points.keys())))


def _scope(holdings, transactions=(), quotes=None, home="CAD", usdcad=1.4):
    return {"user_id": None, "home_currency": home, "usdcad": usdcad, "holdings": list(holdings),
            "transactions": list(transactions), "accounts": [], "account_ids": None, "fixed_income": [],
            "quotes": quotes or {}}


@pytest.fixture
def daily(monkeypatch):
    closes = {"XEQT.TO": _closes({"2026-10-01": 39.0, "2026-10-02": 40.0, "2026-10-08": 41.0}),
              "NVDA": _closes({"2026-10-02": 100.0, "2026-10-08": 110.0})}
    monkeypatch.setattr(perf, "_daily", lambda scope, live, rng, today, extra=(): {"closes": closes, "base": BASE})
    return closes


QUOTES = {"XEQT.TO": {"price": 42.0, "prev_close": 41.0, "currency": "CAD"},
          "NVDA": {"price": 120.0, "prev_close": 110.0, "currency": "USD"}}


def test_every_holding_gets_its_range_change(daily):
    hs = [{"id": "h1", "symbol": "XEQT.TO", "account_id": "a1", "shares": 10, "avg_cost": 30},
          {"id": "h2", "symbol": "NVDA", "account_id": "a1", "shares": 2, "avg_cost": 50}]
    out = perf.holding_changes_body(_scope(hs, quotes=QUOTES), "1W", TODAY)
    xeqt, nvda = out["items"]
    assert (xeqt["holding_id"], xeqt["pct"], xeqt["abs"], xeqt["abs_home"]) == ("h1", 5.0, 20.0, 20.0)
    assert (nvda["pct"], nvda["abs"], nvda["abs_home"]) == (20.0, 40.0, 56.0)   # USD -> CAD at 1.4
    assert xeqt["basis"] == "range" and xeqt["since"] == "2026-10-02" and out["currency"] == "CAD"


def test_bought_inside_the_range_counts_from_the_purchase(daily):
    hs = [{"id": "h1", "symbol": "XEQT.TO", "account_id": "a1", "shares": 10}]
    txs = [{"type": "buy", "symbol": "XEQT.TO", "account_id": "a1", "trade_date": "2026-10-05", "quantity": 4,
            "price": 40.5, "currency": "CAD"},
           {"type": "buy", "symbol": "XEQT.TO", "account_id": "a1", "trade_date": "2026-10-07", "quantity": 6,
            "price": 41.5, "currency": "CAD"}]
    [it] = perf.holding_changes_body(_scope(hs, txs, QUOTES), "1W", TODAY)["items"]
    assert it["basis"] == "purchase" and it["since"] == "2026-10-05"
    assert it["pct"] == pytest.approx(round((42 / 41.1 - 1) * 100, 2)) and it["abs"] == pytest.approx(9.0)


def test_a_buy_in_another_account_or_before_the_range_keeps_the_range_start(daily):
    hs = [{"id": "h1", "symbol": "XEQT.TO", "account_id": "a1", "shares": 10}]
    txs = [{"type": "buy", "symbol": "XEQT.TO", "account_id": "a1", "trade_date": "2026-09-01", "quantity": 5,
            "price": 30},
           {"type": "buy", "symbol": "XEQT.TO", "account_id": "a1", "trade_date": "2026-10-05", "quantity": 5,
            "price": 41},
           {"type": "buy", "symbol": "XEQT.TO", "account_id": "a2", "trade_date": "2026-10-06", "quantity": 5,
            "price": 41}]
    [it] = perf.holding_changes_body(_scope(hs, txs, QUOTES), "1W", TODAY)["items"]
    assert it["basis"] == "range" and it["pct"] == 5.0


def test_missing_prices_give_nulls_and_all_uses_the_average_cost(daily):
    hs = [{"id": "h1", "symbol": "XEQT.TO", "account_id": None, "shares": 10, "avg_cost": 30},
          {"id": "h2", "symbol": "ZZZ.TO", "account_id": None, "shares": 1}]
    one_w = perf.holding_changes_body(_scope(hs, quotes=QUOTES), "1W", TODAY)["items"]
    assert (one_w[1]["pct"], one_w[1]["abs"], one_w[1]["abs_home"]) == (None, None, None)
    all_ = perf.holding_changes_body(_scope(hs[:1], quotes=QUOTES), "ALL", TODAY)["items"][0]
    assert all_["basis"] == "purchase" and all_["pct"] == 40.0 and all_["abs"] == 120.0


def test_1d_uses_the_live_previous_close():
    hs = [{"id": "h1", "symbol": "NVDA", "account_id": None, "shares": 2}]
    [it] = perf.holding_changes_body(_scope(hs, quotes=QUOTES, home="USD"), "1D", TODAY)["items"]
    assert it["pct"] == pytest.approx(9.09) and it["abs_home"] == 20.0


def test_route_checks_the_plan_for_long_ranges():
    from fastapi import HTTPException

    from app.api.v1.portfolio_home import _check_range
    with pytest.raises(HTTPException) as e:
        _check_range({"access_level": "free"}, "5Y")
    assert e.value.status_code == 403
    assert _check_range({"access_level": "free"}, "1y") == "1Y"


# ---------------------------------------------------------------- dividend fields

def test_holding_dividend_yield_and_next_payment():
    from app.services.dividend_calendar import holding_dividend
    prof = {"pays_dividend": True, "yield": 0.0342, "symbol": "ENB.TO",
            "upcoming": [{"ex_date": "2026-11-14", "pay_date": "2026-12-01"}],
            "last_payments": [{"ex_date": "2026-09-20", "amount": 0.97}]}   # paid 17 days later: 10-07
    today = date(2026, 9, 25)
    assert holding_dividend(prof, date(2026, 1, 1), today) == {"yield_pct": 3.42, "next_pay_date": "2026-10-07"}
    # bought after the September ex-date: the next payment is December's
    assert holding_dividend(prof, date(2026, 9, 22), today)["next_pay_date"] == "2026-12-01"
    assert holding_dividend({"pays_dividend": False}, None, today) is None
    assert holding_dividend(None, None, today) is None


def test_holdings_list_reads_cached_profiles_only(monkeypatch):
    from app.api.v1 import holdings as route
    from app.services import dividends
    dividends._cache.set("ENB.TO", {"pays_dividend": True, "yield": 0.05, "upcoming": [], "last_payments": []})
    items = [{"symbol": "ENB.TO", "created_at": "2026-01-01T00:00:00+00:00"}, {"symbol": "NVDA"}]
    route._add_dividends(items)   # no running loop: the background fetch is skipped
    assert items[0]["dividend"] == {"yield_pct": 5.0, "next_pay_date": None}
    assert items[1]["dividend"] is None


# ---------------------------------------------------------------- similar funds

def test_similar_funds_are_free():
    from app.core import access
    assert access.FEATURE_CATALOG["feature.similar_funds"][0] == "free"
    assert access.can("free", "feature.similar_funds")
