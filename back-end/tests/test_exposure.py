"""What you really own (GET /portfolio/exposure, app/services/exposure.py)."""

import pytest

from app.services import exposure as ex


def _fund(holdings, sectors=None, assets=None, regions=None, fof=False, underlying=None):
    return {"holdings": [{"symbol": s, "name": n, "weight": w} for s, n, w in holdings],
            "sector_weights": sectors or {}, "asset_classes": assets or {}, "regions": regions or {},
            "fund_of_funds": fof, **({"underlying": underlying} if underlying else {})}


def test_keys_and_regions():
    assert ex.sector_key("Financial Services") == "financial_services" and ex.sector_key("realestate") == "realestate"
    assert ex.sector_key("Consumer Staples") == "consumer_defensive" and ex.sector_key(None) is None
    assert ex.region_of("AAPL") == "us" and ex.region_of("RY.TO") == "canada"
    assert ex.region_of("PETR4.SA") == "emerging" and ex.region_of("SAP.DE") == "intl_developed"
    assert ex.region_of("SHOP.TO", "Canada") == "canada" and ex.region_of("BABA", "China") == "emerging"
    assert ex.region_of("BTC-USD") is None
    # same company across listings merges; same ticker, different company doesn't
    assert ex.company_key("SHOP.TO", "Shopify Inc.") == ex.company_key("SHOP", "Shopify Inc Class A")
    assert ex.company_key("T", "AT&T Inc.") != ex.company_key("T.TO", "TELUS Corporation")


def test_direct_stock_and_fund_combine():
    items = [{"symbol": "AAPL", "name": "Apple Inc.", "value_home": 2000.0, "kind": "stock",
              "sector": "technology", "region": "us"},
             {"symbol": "XUS.TO", "name": "iShares US", "value_home": 6000.0, "kind": "fund"},
             {"symbol": "BTC-USD", "name": "Bitcoin", "value_home": 1000.0, "kind": "crypto"}]
    funds = {"XUS.TO": _fund([("AAPL", "Apple Inc", 7.0), ("MSFT", "Microsoft Corp", 6.0)],
                             sectors={"technology": 30.0, "healthcare": 70.0},
                             assets={"stockPosition": 0.98, "cashPosition": 0.02}, regions={"us": 100.0})}
    out = ex.build(items, funds, cash=1000.0, fixed=0.0, currency="CAD")
    assert out["total"] == 10000.0
    apple = out["companies"][0]
    # 20% direct + 60% x 7% through the fund
    assert apple["symbol"] == "AAPL" and apple["pct"] == pytest.approx(24.2) and apple["direct_pct"] == 20.0
    assert apple["via"] == [{"fund": "XUS.TO", "pct": 4.2}] and apple["value_home"] == pytest.approx(2420.0)
    assert out["companies"][1]["symbol"] == "MSFT" and out["companies"][1]["direct_pct"] == 0
    # coverage: 20 direct + 60 x 13% listed
    assert out["coverage_pct"] == pytest.approx(27.8)
    assets = {a["key"]: a["pct"] for a in out["asset_classes"]}
    assert assets["stock"] == pytest.approx(20 + 60 * 0.98) and assets["cash"] == pytest.approx(10 + 60 * 0.02)
    assert assets["other"] == 10.0 and sum(assets.values()) == pytest.approx(100, abs=0.05)
    sectors = {s["key"]: s["pct"] for s in out["sectors"]}
    assert sum(sectors.values()) == pytest.approx(100, abs=0.05)   # over the known part only
    assert out["regions"] == [{"key": "us", "pct": 100.0}]
    assert out["funds"] == [{"symbol": "XUS.TO", "name": "iShares US", "pct": 60.0, "holdings_known_pct": 13.0,
                             "fund_of_funds": False}]
    assert out["overlaps"] == [] and out["estimated"] is False


def test_fund_of_funds_opens_its_underlying_funds():
    items = [{"symbol": "XEQT.TO", "name": "All-Equity", "value_home": 1000.0, "kind": "fund"}]
    xeqt = _fund([("XUS", "iShares Core S&P US ETF", 50.0), ("XEF", "iShares MSCI EAFE ETF", 30.0)], fof=True,
                 underlying={"XUS": [{"symbol": "AAPL", "name": "Apple", "weight": 6.0}]})
    out = ex.build(items, {"XEQT.TO": xeqt}, 0.0, 0.0, "CAD")
    # Apple = 100% x 50% x 6%; XEF couldn't be opened: no companies from it
    assert out["companies"] == [{"symbol": "AAPL", "name": "Apple", "pct": 3.0, "value_home": 30.0,
                                 "direct_pct": 0.0, "via": [{"fund": "XEQT.TO", "pct": 3.0}]}]
    assert out["funds"][0]["holdings_known_pct"] == 3.0 and out["funds"][0]["fund_of_funds"] is True


def test_overlap_between_funds():
    items = [{"symbol": "A.TO", "name": "A", "value_home": 500.0, "kind": "fund"},
             {"symbol": "B.TO", "name": "B", "value_home": 500.0, "kind": "fund"},
             {"symbol": "C.TO", "name": "C", "value_home": 500.0, "kind": "fund"}]
    funds = {"A.TO": _fund([("AAPL", "Apple", 10.0), ("MSFT", "Microsoft", 8.0)]),
             "B.TO": _fund([("AAPL", "Apple Inc", 6.0), ("MSFT", "Microsoft Corp", 9.0), ("NVDA", "Nvidia", 5.0)]),
             "C.TO": _fund([("RY.TO", "Royal Bank", 9.0)])}
    out = ex.build(items, funds, 0.0, 0.0, "CAD")
    assert len(out["overlaps"]) == 1
    o = out["overlaps"][0]
    assert (o["a"], o["b"], o["overlap_pct"]) == ("A.TO", "B.TO", 14.0)   # min(10,6) + min(8,9)
    assert o["common"][0] == {"symbol": "MSFT", "weight_a": 8.0, "weight_b": 9.0}


def test_missing_fund_data_and_empty_portfolio():
    items = [{"symbol": "ZZZ.TO", "name": "Unknown fund", "value_home": 100.0, "kind": "fund"},
             {"symbol": "NOPRICE", "name": "No price", "value_home": None, "kind": "stock"}]
    out = ex.build(items, {}, 0.0, 0.0, "CAD")
    assert out["estimated"] is True and out["funds"][0]["holdings_known_pct"] is None
    assert out["companies"] == [] and out["coverage_pct"] == 0.0
    empty = ex.build([], {}, 0.0, 0.0, "CAD")
    assert empty["total"] == 0.0 and empty["funds"] == [] and empty["overlaps"] == []


def test_route_is_premium_and_combines(monkeypatch):
    from app.api.v1 import portfolio_home
    from app.services import stock_page, suggestions
    from tests.portfolio_fakes import U1, FakePortfolioDB, make_client
    from tests.test_portfolio_home import _setup

    db = FakePortfolioDB(monkeypatch)
    db.settings[U1] = {"user_id": U1, "home_currency": "CAD"}
    _setup(db)   # XEQT.TO (fund) + NVDA in two accounts
    pool = {"XEQT.TO": {"symbol": "XEQT.TO", "quote_type": "ETF", "name": "iShares Core Equity"},
            "NVDA": {"symbol": "NVDA", "quote_type": "EQUITY", "sector": "Technology", "country": "United States"}}
    monkeypatch.setattr(suggestions, "load_pool", lambda: pool)
    monkeypatch.setattr("app.services.quotes.get_extended", lambda syms: {})
    monkeypatch.setattr(stock_page, "_fetch_fund", lambda s: {
        "holdings": [{"symbol": "NVDA", "name": "NVIDIA Corp", "weight": 5.0}],
        "sector_weights": {"technology": 40.0, "financial_services": 60.0},
        "asset_classes": {"stockPosition": 1.0}} if s == "XEQT.TO" else {})
    ex._cache.clear()
    r = make_client(monkeypatch, portfolio_home.router, level="free").get("/api/v1/portfolio/exposure")
    assert r.status_code == 403 and r.json()["detail"]["feature"] == "feature.exposure"
    body = make_client(monkeypatch, portfolio_home.router, level="premium").get("/api/v1/portfolio/exposure").json()
    nvda = next(c for c in body["companies"] if c["symbol"] == "NVDA")
    assert nvda["direct_pct"] > 0 and nvda["via"][0]["fund"] == "XEQT.TO"   # direct + through the fund, merged
    assert body["funds"][0]["symbol"] == "XEQT.TO" and body["currency"] == "CAD"
    assert {a["key"] for a in body["asset_classes"]} >= {"stock", "cash"}


def test_a_fund_listed_inside_a_fund_is_not_a_company():
    items = [{"symbol": "XEF.TO", "name": "EAFE", "value_home": 100.0, "kind": "fund"}]
    xef = _fund([("ASML.AS", "ASML Holding NV", 2.7), ("IEFA", "iShares Core MSCI EAFE ETF", 2.3)])
    out = ex.build(items, {"XEF.TO": xef}, 0.0, 0.0, "CAD")
    assert [c["symbol"] for c in out["companies"]] == ["ASML.AS"]


def test_wrapper_fund_is_opened_one_more_level(monkeypatch):
    from app.services import stock_page
    data = {"XEQT.TO": [{"symbol": "XTOT.TO", "name": "iShares Core S&P Total US ETF", "weight": 50.0}],
            "XTOT.TO": [{"symbol": "ITOT", "name": "iShares Core S&P Total U.S. Stock Market ETF", "weight": 100.0}],
            "ITOT": [{"symbol": "AAPL", "name": "Apple Inc", "weight": 6.0}]}
    monkeypatch.setattr(stock_page, "_fetch_fund", lambda s: {"holdings": data.get(s, [])})
    under = ex._open_underlying("XEQT.TO", data["XEQT.TO"], depth=1)
    assert under == {"XTOT.TO": [{"symbol": "AAPL", "name": "Apple Inc", "weight": 6.0}]}
