"""Free stock page (GET /api/v1/stocks/{symbol}, services/stock_page.py):
Signa checks, response shape, 404 / 400, caching, free-level access and
the no-AI guarantee. yfinance, earnings and the DB are faked."""

import math

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import stocks as api
from app.core import access
from app.core.config import settings
from app.core.security import create_access_token
from app.middleware import auth as auth_mw
from app.services import dividends
from app.services import holdings_monitor as hm
from app.services import stock_page as sp

U1 = "11111111-1111-1111-1111-111111111111"
LIQUID = {"dollar_volume_avg_20": 50_000_000}


def _tech(price=110.0, sma50=105.0, sma200=100.0, rsi=55.0, **kw):
    return {"current_price": price, "last_close": price, "sma_50": sma50, "sma_200": sma200, "rsi": rsi,
            **LIQUID, **kw}


def _by_key(checks):
    return {c["key"]: c for c in checks}


GOOD_DIV = {"key": "dividend", "code": "measured", "rating": "good", "reason": "", "params": {"yield": 3.1}}


# ---------------------------------------------------------------- checks (pure)

def test_all_pass_for_a_healthy_stock():
    earn = {"date": "2026-11-01", "days": 33, "trading_days": 23}
    c = _by_key(sp.build_checks(_tech(), "STOCK", earn, GOOD_DIV, "USD"))
    assert [k for k in c] == list(sp.CHECK_KEYS)
    assert {k: v["status"] for k, v in c.items()} == {k: "pass" for k in sp.CHECK_KEYS}
    assert c["earnings_soon"]["value"] == "2026-11-01" and c["earnings_soon"]["detail_code"] == "earnings_later"
    assert c["uptrend"]["value"] == 10.0  # % above SMA200
    assert c["not_overheated"]["params"]["max_rsi"] == settings.tech_filter_max_rsi
    assert c["liquidity"]["params"]["min"] == settings.tech_filter_min_dollar_volume


@pytest.mark.parametrize("tech,status,code", [
    (_tech(price=95, sma50=105, sma200=100), "warn", "below_sma200"),
    (_tech(price=110, sma50=98, sma200=100), "warn", "sma50_below_sma200"),
    (_tech(price=90, sma50=95, sma200=100), "fail", "downtrend"),
    ({**LIQUID, "current_price": 10, "rsi": 50}, "na", "insufficient_history"),
])
def test_uptrend_statuses(tech, status, code):
    c = _by_key(sp.build_checks(tech, "STOCK", None, None))["uptrend"]
    assert (c["status"], c["detail_code"]) == (status, code)


@pytest.mark.parametrize("rsi,price,status,code", [
    (76, 110, "warn", "rsi_overbought"),
    (60, 125, "warn", "overextended_vs_sma50"),     # 19% above SMA50 > 15%
    (80, 125, "warn", "rsi_and_extended"),
    (75, 110, "pass", "calm"),                      # the limit itself passes
])
def test_not_overheated(rsi, price, status, code):
    c = _by_key(sp.build_checks(_tech(price=price, rsi=rsi), "STOCK", None, None))["not_overheated"]
    assert (c["status"], c["detail_code"]) == (status, code)


def test_not_overheated_na_without_data():
    c = _by_key(sp.build_checks({}, "STOCK", None, None))["not_overheated"]
    assert c["status"] == "na"


def test_liquidity_floor_stock_vs_crypto():
    low = {**_tech(), "dollar_volume_avg_20": 2_000_000}
    assert _by_key(sp.build_checks(low, "STOCK", None, None))["liquidity"]["status"] == "warn"
    # crypto: Yahoo volume is USD already; 30M < 50M crypto floor
    crypto = {**_tech(), "dollar_volume_avg_20": None, "volume_avg_20": 30_000_000}
    c = _by_key(sp.build_checks(crypto, "CRYPTO", None, None))["liquidity"]
    assert (c["status"], c["params"]["min"]) == ("warn", settings.tech_filter_min_dollar_volume_crypto)
    no_vol = {k: v for k, v in _tech().items() if k != "dollar_volume_avg_20"}
    assert _by_key(sp.build_checks(no_vol, "STOCK", None, None))["liquidity"]["status"] == "na"


def test_earnings_soon_statuses():
    n = settings.earnings_blackout_trading_days
    soon = {"date": "2026-10-01", "days": 2, "trading_days": n}
    c = _by_key(sp.build_checks(_tech(), "STOCK", soon, None))["earnings_soon"]
    assert (c["status"], c["detail_code"], c["params"]["limit"]) == ("warn", "earnings_soon", n)
    later = {"date": "2026-10-09", "days": 10, "trading_days": n + 1}
    assert _by_key(sp.build_checks(_tech(), "STOCK", later, None))["earnings_soon"]["status"] == "pass"
    nodate = {"date": None, "days": None, "trading_days": None}
    assert _by_key(sp.build_checks(_tech(), "STOCK", nodate, None))["earnings_soon"]["detail_code"] == "no_date"
    etf = _by_key(sp.build_checks(_tech(), "ETF", soon, None))["earnings_soon"]
    assert (etf["status"], etf["detail_code"]) == ("na", "not_applicable")


@pytest.mark.parametrize("rating,status", [("good", "pass"), ("fair", "warn"), ("poor", "fail"), ("n/a", "na")])
def test_dividend_health_maps_rating(rating, status):
    item = {**GOOD_DIV, "rating": rating}
    assert _by_key(sp.build_checks(_tech(), "STOCK", None, item))["dividend_health"]["status"] == status


def test_dividend_health_uses_the_hold_mode_rules():
    """Recent cut + payout > 100% -> the real rules say poor -> fail."""
    prof = {**dividends.empty_profile("X"), "pays_dividend": True, "yield": 0.08, "payout_ratio": 1.4,
            "recent_cut": True, "last_cut_date": "2026-01-15"}
    item = dividends.long_term_dividend_assessment(prof, "STOCK")["item"]
    assert _by_key(sp.build_checks(_tech(), "STOCK", None, item))["dividend_health"]["status"] == "fail"
    none = dividends.long_term_dividend_assessment(dividends.empty_profile("Y"), "STOCK")["item"]
    c = _by_key(sp.build_checks(_tech(), "STOCK", None, none))["dividend_health"]
    assert (c["status"], c["detail_code"]) == ("na", "none")


def test_events_from_earnings_and_profile():
    prof = {**dividends.empty_profile("X"), "pays_dividend": True, "next_ex_date": "2026-10-10",
            "next_estimated": True, "next_amount": 0.5, "next_pay_date": "2026-10-30", "next_pay_estimated": False}
    ev = sp.build_events({"date": "2026-10-20", "days": 21, "trading_days": 15}, prof)
    assert ev["earnings"]["date"] == "2026-10-20"
    assert ev["ex_dividend"] == {"date": "2026-10-10", "estimated": True, "amount": 0.5}
    assert ev["dividend_payment"] == {"date": "2026-10-30", "estimated": False}
    assert sp.build_events(None, dividends.empty_profile("Y")) == {
        "earnings": None, "ex_dividend": None, "dividend_payment": None}


# ---------------------------------------------------------------- API

def _history(n=260, end="2025-06-30"):
    idx = pd.bdate_range(end=end, periods=n, tz="America/New_York")
    close = [100 + 0.08 * i + 1.5 * math.sin(i / 3) for i in range(n)]
    return pd.DataFrame({"Open": close, "High": [c * 1.01 for c in close], "Low": [c * 0.99 for c in close],
                         "Close": close, "Volume": [2_000_000] * n}, index=idx)


INFO = {"quoteType": "EQUITY", "longName": "Microsoft Corporation", "exchange": "NMS", "currency": "USD",
        "fullExchangeName": "NasdaqGS", "sector": "Technology", "industry": "Software", "marketCap": 3.1e12,
        "regularMarketPrice": 121.0, "regularMarketPreviousClose": 120.0, "fiftyTwoWeekHigh": 125.0,
        "fiftyTwoWeekLow": 98.0}


class Fakes:
    def __init__(self, monkeypatch, data=None):
        self.data = data if data is not None else {"MSFT": {"history": _history(), "info": dict(INFO)}}
        self.fetches: list[str] = []
        self.followed_calls = 0
        self.ai_calls: list[str] = []
        monkeypatch.setattr(sp, "_fetch_market", self.fetch)
        monkeypatch.setattr(sp, "followed", self.followed)
        monkeypatch.setattr(hm, "earnings_info", self.earnings)
        monkeypatch.setattr(access, "assert_ai_allowed", lambda what="": self.ai_calls.append(what))

    def fetch(self, symbol):
        self.fetches.append(symbol)
        return self.data.get(symbol, {"history": None, "info": {}})

    def followed(self, user_id, symbols):
        self.followed_calls += 1
        return {"in_holdings": "MSFT" in symbols, "in_watchlist": False}

    async def earnings(self, h, today=None):
        return {"date": "2026-10-28", "days": 29, "trading_days": 21}


def _client(monkeypatch, level="free"):
    fn = lambda _uid: {"level": level, "slot_bonus": 0}  # noqa: E731
    monkeypatch.setattr(access, "get_user_access", fn)
    monkeypatch.setattr(auth_mw, "get_user_access", fn)
    defaults = {k: v[0] for k, v in access.FEATURE_CATALOG.items()}
    monkeypatch.setattr(access, "get_feature_levels", lambda: dict(defaults))
    monkeypatch.setattr(auth_mw, "is_token_blacklisted", lambda _jti: False)
    monkeypatch.setattr(auth_mw, "insert_audit_log", lambda *a, **k: None)
    access.clear_access_cache()
    app = FastAPI()
    app.add_middleware(auth_mw.AuthMiddleware)
    app.include_router(api.router, prefix="/api/v1")
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {create_access_token(U1, 'u')}"
    return c


@pytest.fixture(autouse=True)
def _fresh_cache():
    sp.clear_cache()
    yield
    sp.clear_cache()


@pytest.mark.real_access
def test_free_user_gets_the_full_page(monkeypatch):
    fakes = Fakes(monkeypatch)
    r = _client(monkeypatch, "free").get("/api/v1/stocks/msft")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) >= {"symbol", "name", "exchange", "exchange_name", "currency", "asset_type", "sector",
                         "industry", "quote", "dividend", "events", "checks", "generated_at", "followed"}
    assert (body["symbol"], body["exchange"], body["asset_type"], body["currency"]) == ("MSFT", "NASDAQ", "stock", "USD")
    q = body["quote"]
    assert q["price"] == 121.0 and q["change_pct"] == pytest.approx(0.83, abs=0.01)
    assert (q["high_52w"], q["low_52w"], q["market_cap"]) == (125.0, 98.0, 3.1e12) and q["as_of"]
    assert set(body["dividend"]) == {"profile", "rating", "rating_code", "rules"}
    assert body["dividend"]["profile"]["pays_dividend"] is False and body["dividend"]["rating"] == "n/a"
    assert body["events"]["earnings"]["date"] == "2026-10-28"
    assert [c["key"] for c in body["checks"]] == list(sp.CHECK_KEYS)
    for c in body["checks"]:
        assert set(c) == {"key", "status", "value", "detail_code", "params"}
        assert c["status"] in ("pass", "warn", "fail", "na")
    checks = _by_key(body["checks"])
    assert checks["uptrend"]["status"] == "pass" and checks["liquidity"]["status"] == "pass"
    assert body["followed"] == {"in_holdings": True, "in_watchlist": False}
    assert fakes.ai_calls == []  # never reached an @ai_guarded entry point


@pytest.mark.real_access
def test_shared_part_is_cached_followed_is_not(monkeypatch):
    fakes = Fakes(monkeypatch)
    c = _client(monkeypatch, "free")
    first = c.get("/api/v1/stocks/MSFT").json()
    second = c.get("/api/v1/stocks/MSFT").json()
    assert fakes.fetches == ["MSFT"]
    assert fakes.followed_calls == 2
    assert first["generated_at"] == second["generated_at"]


@pytest.mark.real_access
def test_unknown_symbol_is_404(monkeypatch):
    fakes = Fakes(monkeypatch, data={})
    r = _client(monkeypatch, "free").get("/api/v1/stocks/ZZZZ")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "not_found"
    assert fakes.fetches == ["ZZZZ", "ZZZZ.TO", "ZZZZ-USD"]


@pytest.mark.real_access
def test_invalid_symbol_is_400(monkeypatch):
    Fakes(monkeypatch)
    r = _client(monkeypatch, "free").get("/api/v1/stocks/BAD$$SYM")
    assert r.status_code == 400 and r.json()["detail"]["code"] == "invalid_symbol"


@pytest.mark.real_access
def test_bare_symbol_resolves_to_tsx(monkeypatch):
    etf_info = {"quoteType": "ETF", "longName": "iShares Core Equity ETF Portfolio", "exchange": "TOR",
                "currency": "CAD"}
    Fakes(monkeypatch, data={"XEQT.TO": {"history": _history(), "info": etf_info}})
    body = _client(monkeypatch, "free").get("/api/v1/stocks/XEQT").json()
    assert (body["symbol"], body["exchange"], body["asset_type"], body["currency"]) == ("XEQT.TO", "TSX", "etf", "CAD")
    assert _by_key(body["checks"])["earnings_soon"]["status"] == "na"
    assert body["events"]["earnings"] is None


@pytest.mark.real_access
def test_partial_data_degrades_to_nulls(monkeypatch):
    fakes = Fakes(monkeypatch, data={"MSFT": {"history": _history(n=30), "info": {}}})

    async def broken(h, today=None):
        raise RuntimeError("yahoo down")
    monkeypatch.setattr(hm, "earnings_info", broken)
    r = _client(monkeypatch, "free").get("/api/v1/stocks/MSFT")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] is None and body["quote"]["market_cap"] is None
    assert body["quote"]["price"] is not None  # from the price history
    checks = _by_key(body["checks"])
    assert checks["uptrend"]["status"] == "na"  # 30 bars: no SMA200
    assert checks["earnings_soon"]["status"] == "na"
    assert fakes.ai_calls == []
