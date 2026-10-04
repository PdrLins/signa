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
from app.market import earnings as hm
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
    def __init__(self, monkeypatch, data=None, real_user_db=False):
        self.data = data if data is not None else {"MSFT": {"history": _history(), "info": dict(INFO)}}
        self.fetches: list[str] = []
        self.followed_calls = 0
        self.ai_calls: list[str] = []
        monkeypatch.setattr(sp, "_fetch_market", self.fetch)
        monkeypatch.setattr(sp, "followed", self.followed)
        if not real_user_db:   # the user's DB part (position, slots) is faked too
            monkeypatch.setattr(sp, "position", lambda user, symbols: None)
            monkeypatch.setattr(sp, "slots", lambda user: {"used": 3, "limit": 10, "remaining": 7})
        monkeypatch.setattr(hm, "earnings_info", self.earnings)
        self.live: dict[str, dict] = {}       # shared quotes rows (no DB)
        self.funds: dict[str, dict] = {}      # funds_data per symbol (no network)
        self.fund_fetches: list[str] = []
        monkeypatch.setattr(sp, "_stored_quote", lambda symbol: self.live.get(symbol))

        def fund(symbol):
            self.fund_fetches.append(symbol)
            return self.funds.get(symbol, {})
        monkeypatch.setattr("app.market.funds.fetch_funds_data", lambda symbol, ticker=None: fund(symbol))

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
    Fakes(monkeypatch)
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
    assert body["position"] is None and body["slots"] == {"used": 3, "limit": 10, "remaining": 7}
    st = body["statistics"]
    assert set(st) == {"day_low", "day_high", "low_52w", "high_52w", "market_cap", "pe_ratio", "forward_pe",
                       "dividend_yield", "avg_volume", "volume", "beta"}
    assert (st["low_52w"], st["high_52w"], st["market_cap"]) == (98.0, 125.0, 3.1e12)
    assert st["volume"] == 2_000_000 and st["avg_volume"] == 2_000_000   # from the bars (no info keys)
    assert st["day_high"] > st["day_low"] and st["pe_ratio"] is None


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


# ---------------------------------------------------------------- statistics / position

def test_statistics_prefer_info_and_drop_negative_pe():
    info = {"regularMarketDayLow": 118.5, "regularMarketDayHigh": 122.25, "trailingPE": -3.0, "forwardPE": 28.456,
            "averageVolume": 1_500_000, "regularMarketVolume": 900_000, "beta": 0.912}
    quote = {"low_52w": 98.0, "high_52w": 125.0, "market_cap": 3.1e12}
    st = sp.build_statistics(_history(), info, quote, {"yield": 0.0312})
    assert (st["day_low"], st["day_high"]) == (118.5, 122.25)
    assert st["pe_ratio"] is None and st["forward_pe"] == 28.46
    assert (st["avg_volume"], st["volume"], st["beta"]) == (1_500_000, 900_000, 0.91)
    assert st["dividend_yield"] == 0.0312
    empty = sp.build_statistics(None, {}, {}, None)
    assert all(v is None for v in empty.values())


def _scope(holdings, txs=None, quotes=None, accounts=None):
    return {"home_currency": "CAD", "usdcad": 1.4, "holdings": holdings, "transactions": txs or [],
            "quotes": quotes or {}, "all_accounts": accounts or [], "accounts": accounts or []}


def test_position_none_when_not_held():
    assert sp.build_position({"MSFT"}, _scope([{"symbol": "NVDA", "shares": 1, "avg_cost": 1}])) is None
    assert sp.build_position({"MSFT"}, _scope([{"symbol": "MSFT", "shares": 0}])) is None


def test_position_sums_accounts_weighted_cost_weight_and_ledger():
    accounts = [{"id": "a1", "name": "TFSA"}, {"id": "a2", "name": "Margin"}]
    holdings = [
        {"symbol": "MSFT", "account_id": "a1", "shares": 10, "avg_cost": 100, "currency": "USD"},
        {"symbol": "MSFT", "account_id": "a2", "shares": 30, "avg_cost": 120, "currency": "USD"},
        {"symbol": "ENB.TO", "account_id": "a1", "shares": 100, "avg_cost": 50, "currency": "CAD"},
    ]
    quotes = {"MSFT": {"price": 150.0, "prev_close": 140.0, "currency": "USD", "as_of": "2026-09-30T14:00:00Z"},
              "ENB.TO": {"price": 56.0, "prev_close": 56.0, "currency": "CAD"}}
    txs = [
        {"account_id": "a1", "symbol": "MSFT", "type": "buy", "quantity": 10, "amount": 1000, "trade_date": "2026-01-02"},
        {"account_id": "a1", "symbol": "MSFT", "type": "dividend", "amount": 8.3, "trade_date": "2026-06-12"},
        {"account_id": "a1", "symbol": "ENB.TO", "type": "dividend", "amount": 90, "trade_date": "2026-06-01"},
    ]
    p = sp.build_position({"MSFT"}, _scope(holdings, txs, quotes, accounts))
    assert p["shares"] == 40 and p["avg_cost"] == 115.0 and p["currency"] == "USD"
    assert p["market_value"] == 6000.0 and p["market_value_home"] == 8400.0
    # portfolio = 8400 (MSFT, CAD) + 5600 (ENB) = 14000
    assert p["weight_pct"] == 60.0
    assert p["today_pl"] == {"abs": 400.0, "pct": 7.14, "abs_home": 560.0}
    assert p["open_pl"] == {"abs": 1400.0, "pct": 30.43, "abs_home": 1960.0}
    assert p["dividends_received"] == 8.3 and p["realized_pl"] == 0.0 and p["has_transactions"] is True
    assert p["total_gain"]["abs"] == 1408.3
    assert [(a["account_name"], a["shares"], a["value"]) for a in p["per_account"]] == [
        ("Margin", 30, 4500.0), ("TFSA", 10, 1500.0)]


def test_position_without_transactions_has_no_ledger_numbers():
    p = sp.build_position({"MSFT"}, _scope([{"symbol": "MSFT", "shares": 2, "avg_cost": None}],
                                           quotes={"MSFT": {"price": 10.0, "currency": "USD"}}))
    assert p["dividends_received"] is None and p["realized_pl"] is None and p["has_transactions"] is False
    assert p["avg_cost"] is None and p["open_pl"]["abs"] is None and p["total_gain"]["abs"] is None
    assert p["market_value"] == 20.0 and p["today_pl"]["abs"] is None


@pytest.mark.real_access
def test_api_position_and_slots_from_the_users_db(monkeypatch):
    from tests.portfolio_fakes import FakePortfolioDB
    db = FakePortfolioDB(monkeypatch)
    acc = db.add_account(U1, "TFSA")
    db.add_holding(U1, "MSFT", account_id=acc, shares=5, avg_cost=100, currency="USD")
    db.quotes["MSFT"] = {"symbol": "MSFT", "price": 121.0, "prev_close": 120.0, "currency": "USD"}
    Fakes(monkeypatch, real_user_db=True)
    body = _client(monkeypatch, "free").get("/api/v1/stocks/MSFT").json()
    assert body["position"]["shares"] == 5 and body["position"]["weight_pct"] == 100.0
    assert body["position"]["per_account"][0]["account_name"] == "TFSA"
    assert body["slots"] == {"used": 1, "limit": 15, "remaining": 14}


# ---------------------------------------------------------------- fund / about / live quote / growth

ETF_INFO = {"quoteType": "ETF", "longName": "iShares Core Equity ETF Portfolio", "exchange": "TOR",
            "currency": "CAD", "netExpenseRatio": 0.2, "totalAssets": 5.2e9, "fundFamily": "BlackRock",
            "category": "Global Equity Balanced", "longBusinessSummary": "  The ETF seeks long-term\n growth.  "}
FUND_DATA = {"overview": {"legalType": "Exchange Traded Fund"},
             "holdings": [{"symbol": "XUS.TO", "name": "iShares Core S&P 500 Index ETF", "weight": 45.1},
                          {"symbol": "XIC.TO", "name": "iShares Core S&P/TSX Capped Composite ETF", "weight": 25.0}],
             "sector_weights": {"technology": 24.5}, "asset_classes": {"stockPosition": 99.6}}


@pytest.mark.real_access
def test_etf_page_has_fund_and_about_and_fund_is_cached(monkeypatch):
    fakes = Fakes(monkeypatch, data={"XEQT.TO": {"history": _history(), "info": dict(ETF_INFO)}})
    fakes.funds["XEQT.TO"] = FUND_DATA
    c = _client(monkeypatch, "free")
    body = c.get("/api/v1/stocks/XEQT.TO").json()
    f = body["fund"]
    assert f["expense_ratio"] == 0.2 and f["aum"] == 5.2e9 and f["family"] == "BlackRock"
    assert f["legal_type"] == "Exchange Traded Fund" and f["top_holdings"][0]["weight"] == 45.1
    assert f["holdings_listed"] == 2 and f["top10_weight"] == 70.1 and f["fund_of_funds"] is True
    assert f["sector_weights"] == {"technology": 24.5} and f["asset_classes"] == {"stockPosition": 99.6}
    assert body["about"]["description"] == "The ETF seeks long-term growth."
    assert body["about"]["employees"] is None
    sp._page_cache.clear()          # page rebuilt -> fund data from its own 12h cache
    c.get("/api/v1/stocks/XEQT.TO")
    assert fakes.fund_fetches == ["XEQT.TO"]


@pytest.mark.real_access
def test_stock_page_has_no_fund_and_about_from_info(monkeypatch):
    info = {**INFO, "longBusinessSummary": "Microsoft develops software.", "country": "United States",
            "city": "Redmond", "state": "WA", "website": "https://www.microsoft.com", "fullTimeEmployees": 228000}
    fakes = Fakes(monkeypatch, data={"MSFT": {"history": _history(), "info": info}})
    body = _client(monkeypatch, "free").get("/api/v1/stocks/MSFT").json()
    assert body["fund"] is None and fakes.fund_fetches == []
    assert body["about"] == {"description": "Microsoft develops software.", "country": "United States",
                             "city": "Redmond", "state": "WA", "website": "https://www.microsoft.com",
                             "employees": 228000}


@pytest.mark.real_access
def test_fund_failure_and_timeout_fail_soft(monkeypatch):
    fakes = Fakes(monkeypatch, data={"XEQT.TO": {"history": _history(), "info": {"quoteType": "ETF",
                                                                                   "exchange": "TOR"}}})

    def boom(symbol, ticker=None):
        raise RuntimeError("yahoo down")
    monkeypatch.setattr("app.market.funds.fetch_funds_data", boom)
    r = _client(monkeypatch, "free").get("/api/v1/stocks/XEQT.TO")
    assert r.status_code == 200 and r.json()["fund"] is None and r.json()["about"] is None

    import time as _time
    sp.clear_cache()
    monkeypatch.setattr(sp, "FUND_TIMEOUT_S", 0.05)
    monkeypatch.setattr("app.market.funds.fetch_funds_data",
                        lambda symbol, ticker=None: _time.sleep(0.5) or FUND_DATA)
    r = _client(monkeypatch, "free").get("/api/v1/stocks/XEQT.TO")
    assert r.status_code == 200 and r.json()["fund"] is None
    assert fakes.ai_calls == []


def test_about_caps_long_descriptions():
    a = sp.build_about({"longBusinessSummary": "word " * 2000})
    assert len(a["description"]) <= sp.ABOUT_MAX_CHARS + 1 and a["description"].endswith("…")
    assert sp.build_about({}) is None


@pytest.mark.real_access
def test_header_quote_overlaid_with_newer_shared_quote(monkeypatch):
    fakes = Fakes(monkeypatch)
    c = _client(monkeypatch, "free")
    fakes.live["MSFT"] = {"symbol": "MSFT", "price": 130.0, "prev_close": 125.0, "as_of": "2099-01-01T15:00:00+00:00"}
    q = c.get("/api/v1/stocks/MSFT").json()["quote"]
    assert (q["price"], q["change_pct"], q["as_of"]) == (130.0, 4.0, "2099-01-01T15:00:00+00:00")
    assert q["high_52w"] == 125.0                   # the rest stays from the page
    fakes.live["MSFT"] = {"symbol": "MSFT", "price": 1.0, "prev_close": 1.0, "as_of": "2000-01-01T15:00:00+00:00"}
    q = c.get("/api/v1/stocks/MSFT").json()["quote"]
    assert q["price"] == 121.0                      # an older shared row never wins


def test_position_cost_only_over_lots_with_cost_and_today_needs_live_quote():
    holdings = [{"symbol": "MSFT", "account_id": "a1", "shares": 10, "avg_cost": 100, "currency": "USD"},
                {"symbol": "MSFT", "account_id": "a2", "shares": 30, "avg_cost": None, "currency": "USD"}]
    p = sp.build_position({"MSFT"}, _scope(holdings, quotes={"MSFT": {"price": 150.0, "prev_close": 140.0,
                                                                      "currency": "USD"}}))
    assert p["avg_cost"] == 100.0 and p["market_value"] == 6000.0
    assert p["open_pl"]["abs"] == 500.0 and p["open_pl"]["pct"] == 50.0
    stale = [{**h, "holding_status": {"price": 150.0, "prev_close": 140.0}} for h in holdings]
    p = sp.build_position({"MSFT"}, _scope(stale))
    assert p["price_source"] == "last_close" and p["today_pl"]["abs"] is None


def test_dividend_growth_windows():
    from datetime import date
    # quarterly, +10%/yr for 12 years
    pays = []
    for y in range(2014, 2026):
        for m in (3, 6, 9, 12):
            pays.append((date(y, m, 15), round(1.0 * 1.1 ** (y - 2014), 6)))
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d, _ in pays])
    raw = pd.Series([a for _, a in pays], index=idx)
    prof = dividends.build_profile("KO", {"quoteType": "EQUITY", "dividendRate": 3.0}, raw, {},
                                   date(2026, 1, 10), price=60.0)
    for k in ("growth_1y_pct", "growth_3y_pct", "growth_5y_pct", "growth_10y_pct"):
        assert prof[k] == pytest.approx(10.0, abs=0.3), k
    assert prof["growth_5y_pct"] == pytest.approx(prof["growth_5y_cagr"] * 100, abs=0.01)
    short = dividends.build_profile("NEW", {"quoteType": "EQUITY"}, raw[-8:], {}, date(2026, 1, 10))
    assert short["growth_1y_pct"] is not None and short["growth_3y_pct"] is None and short["growth_10y_pct"] is None
    fund = dividends.build_profile("XEQT.TO", {"quoteType": "ETF"}, raw, {}, date(2026, 1, 10))
    assert fund["growth_1y_pct"] is None
