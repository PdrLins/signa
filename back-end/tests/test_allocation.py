"""Allocation: classification, mix, tiles, warnings, targets and the deposit
plan (pure) + the /portfolio/allocation endpoints with fakes (no network, no DB)."""

import pytest
from fastapi import HTTPException

from app.api.v1 import allocation as api
from app.services import allocation as alloc
from tests.portfolio_fakes import U1, FakePortfolioDB, make_client


def _q(price, prev=None, ccy="CAD"):
    return {"price": price, "prev_close": prev or price, "currency": ccy, "as_of": "2026-09-30T14:00:00+00:00"}


# ---------------------------------------------------------------- classification

@pytest.mark.parametrize("sym,name,at,cls", [
    ("BTC-USD", None, None, "crypto"),
    ("FBTC", None, "CRYPTO", "crypto"),
    ("CASH.TO", None, "ETF", "cash_like"),
    ("SGOV", None, "ETF", "cash_like"),
    ("XYZ", "Global X Money Market ETF", "ETF", "cash_like"),
    ("QYLD", None, "ETF", "option_income_etfs"),
    ("NVDY", None, "ETF", "option_income_etfs"),
    ("ABCD", "Some Covered Call ETF", "ETF", "option_income_etfs"),
    ("XEQT.TO", None, None, "broad_etfs"),
    ("VT", None, None, "broad_etfs"),
    ("ZZZZ", "Some sector ETF", "ETF", "broad_etfs"),
    ("GLD", None, "ETF", "other"),
    ("QQQQ", "Aggregate Bond ETF", "ETF", "other"),
    ("NVDA", None, "STOCK", "stocks"),
    ("RY.TO", None, None, "stocks"),
])
def test_classify(sym, name, at, cls):
    assert alloc.classify(sym, name, at) == cls


# ---------------------------------------------------------------- mix / tiles / warnings

def _pos(sym, value, change=None, gain=None, name=None, at=None):
    return {"symbol": sym, "value_home": value, "change_pct": change, "gain_pct": gain, "name": name,
            "asset_type": at}


def test_mix_tiles_and_cash():
    body = alloc.build_allocation([_pos("XEQT.TO", 600, 1.0, 10.0), _pos("NVDA", 200, -2.0, 50.0, at="STOCK"),
                                   _pos("NOPE", None)], cash_home=200)
    assert body["total_home"] == 1000 and body["invested_home"] == 800 and body["cash_home"] == 200
    mix = {m["class"]: m for m in body["mix"]}
    assert [m["class"] for m in body["mix"]] == list(alloc.CLASSES)
    assert mix["broad_etfs"]["pct"] == 60 and mix["stocks"]["pct"] == 20
    assert mix["cash_like"]["value_home"] == 200 and mix["cash_like"]["members"][0]["kind"] == "account_cash"
    assert mix["crypto"]["value_home"] == 0 and mix["crypto"]["members"] == []
    assert [t["symbol"] for t in body["tiles"]] == ["XEQT.TO", "NVDA"]
    assert body["tiles"][1] == {"symbol": "NVDA", "name": None, "class": "stocks", "value_home": 200,
                                "weight_pct": 20.0, "day_change_pct": -2.0, "total_gain_pct": 50.0}
    assert body["unpriced"] == ["NOPE"]


def test_warnings_each_with_params():
    body = alloc.build_allocation([_pos("QYLD", 300), _pos("NVDA", 250, at="STOCK"), _pos("MSFT", 100, at="STOCK"),
                                   _pos("SGOV", 150)], cash_home=200)
    w = {(x["code"], x["params"].get("symbol")): x["params"] for x in body["warnings"]}
    assert w[("top3_concentration", None)] == {"pct": 70.0, "limit": 40.0, "symbols": ["QYLD", "NVDA", "SGOV"]}
    assert w[("single_holding", "QYLD")] == {"symbol": "QYLD", "pct": 30.0, "limit": 20.0}
    assert w[("single_holding", "NVDA")]["pct"] == 25.0
    assert ("single_holding", "MSFT") not in w
    assert w[("cash_like_high", None)] == {"pct": 35.0, "limit": 10.0}
    assert w[("option_income_high", None)] == {"pct": 30.0, "limit": 25.0}


def test_no_warnings_when_diversified_and_empty():
    body = alloc.build_allocation([_pos(f"S{i}", 100, at="STOCK") for i in range(10)])
    assert body["warnings"] == []
    empty = alloc.build_allocation([])
    assert empty["total_home"] == 0 and empty["warnings"] == [] and empty["mix"][0]["pct"] is None


# ---------------------------------------------------------------- targets

def test_validate_targets():
    t = alloc.validate_targets({"broad_etfs": 80, "stocks": 20})
    assert t["broad_etfs"] == 80 and t["crypto"] == 0 and set(t) == set(alloc.CLASSES)
    assert alloc.validate_targets(None) is None
    assert alloc.validate_targets({"broad_etfs": 33.333, "stocks": 33.333, "cash_like": 33.334})
    for bad, code in (({"bonds": 100}, "invalid_targets"), ({"stocks": 101}, "invalid_targets"),
                      ({"stocks": -1, "broad_etfs": 101}, "invalid_targets"), ({"stocks": "x"}, "invalid_targets"),
                      ([], "invalid_targets"), ({"stocks": 50, "broad_etfs": 40}, "targets_sum")):
        with pytest.raises(HTTPException) as e:
            alloc.validate_targets(bad)
        assert e.value.status_code == 422 and e.value.detail["code"] == code


# ---------------------------------------------------------------- plan

def test_plan_splits_only_under_target_classes():
    body = alloc.build_allocation([_pos("XEQT.TO", 700), _pos("NVDA", 300, at="STOCK")])
    targets = alloc.validate_targets({"broad_etfs": 60, "stocks": 20, "cash_like": 10, "crypto": 10})
    plan = alloc.build_plan(body, targets, 1000, "CAD")
    items = {i["class"]: i for i in plan["items"]}
    # total after = 2000: broad gap 1200-700=500, stocks 400-300=100, cash 200, crypto 200 -> sum 1000
    assert items["broad_etfs"]["amount"] == 500 and items["stocks"]["amount"] == 100
    assert items["cash_like"]["amount"] == 200 and items["crypto"]["amount"] == 200
    assert plan["allocated"] == 1000 and plan["unallocated"] == 0
    assert items["broad_etfs"]["buy"] == {"symbol": "XEQT.TO", "source": "largest_holding", "code": None}
    assert items["stocks"]["buy"]["symbol"] == "NVDA"
    assert items["cash_like"]["buy"] == {"symbol": "CASH.TO", "source": "default", "code": None}
    assert items["crypto"]["buy"]["symbol"] == "BTC-USD"
    assert items["broad_etfs"]["after_pct"] == 60


def test_plan_never_sells_and_scales_to_amount():
    body = alloc.build_allocation([_pos("NVDA", 1000, at="STOCK")])
    targets = alloc.validate_targets({"broad_etfs": 50, "stocks": 50})
    plan = alloc.build_plan(body, targets, 100, "USD")
    assert [i["class"] for i in plan["items"]] == ["broad_etfs"]      # stocks is over target: nothing sold
    assert plan["items"][0]["amount"] == 100 and plan["items"][0]["buy"]["symbol"] == "VT"
    # gaps smaller than the amount: capped, rest unallocated; stocks default -> no_default
    body2 = alloc.build_allocation([_pos("XEQT.TO", 1000)])
    plan2 = alloc.build_plan(body2, alloc.validate_targets({"broad_etfs": 90, "stocks": 10}), 50, "CAD")
    st = plan2["items"][0]
    assert st["class"] == "stocks" and st["amount"] == pytest.approx(50 * 1.0, abs=0.01)
    assert st["buy"] == {"symbol": None, "source": None, "code": "no_default"}


def test_plan_capped_at_gaps():
    body = alloc.build_allocation([_pos("XEQT.TO", 900), _pos("NVDA", 100, at="STOCK")])
    plan = alloc.build_plan(body, alloc.validate_targets({"broad_etfs": 90, "stocks": 10}), 1000, "CAD")
    # after = 2000: broad gap 900, stocks gap 100 -> sum 1000 = amount
    assert plan["allocated"] == 1000
    plan_big = alloc.build_plan(body, alloc.validate_targets({"broad_etfs": 90, "stocks": 10}), 10, "CAD")
    assert plan_big["allocated"] == 10 and plan_big["unallocated"] == 0


# ---------------------------------------------------------------- API

@pytest.fixture
def db(monkeypatch):
    d = FakePortfolioDB(monkeypatch)
    a1 = d.add_account(U1, "TFSA", currency="CAD", cash_balance=100)
    a2 = d.add_account(U1, "US", currency="USD", cash_balance=100)   # 140 CAD
    d.add_holding(U1, "XEQT.TO", a1, shares=10, avg_cost=25, asset_type="ETF", name="iShares Core Equity")
    d.add_holding(U1, "NVDA", a2, shares=2, avg_cost=100, asset_type="STOCK")
    d.add_holding(U1, "NVDA", a1, shares=1, avg_cost=100, asset_type="STOCK")
    d.quotes = {"XEQT.TO": _q(30, 29.7), "NVDA": _q(200, 190, "USD")}
    d.a1, d.a2 = a1, a2
    return d


def test_get_allocation(monkeypatch, db):
    c = make_client(monkeypatch, api.router, level="free")
    body = c.get("/api/v1/portfolio/allocation").json()
    # XEQT 300 CAD, NVDA 3 x 200 x 1.4 = 840, cash 100 + 140 = 240
    assert body["home_currency"] == "CAD" and body["delayed_minutes"] == 15
    assert body["as_of"] == "2026-09-30T14:00:00+00:00"
    assert body["total_home"] == 1380 and body["cash_home"] == 240
    assert [t["symbol"] for t in body["tiles"]] == ["NVDA", "XEQT.TO"]    # NVDA merged across accounts
    assert body["tiles"][0]["value_home"] == 840 and body["tiles"][0]["total_gain_pct"] == 100
    assert body["targets"] is None
    codes = {w["code"] for w in body["warnings"]}
    assert {"single_holding", "cash_like_high"} <= codes
    assert "top3_concentration" not in codes   # one stock + XEQT: not 3 concentrated holdings
    assert [w["params"]["symbol"] for w in body["warnings"] if w["code"] == "single_holding"] == ["NVDA"]


def test_allocation_scope_filters(monkeypatch, db):
    c = make_client(monkeypatch, api.router)
    body = c.get(f"/api/v1/portfolio/allocation?account_id={db.a1}").json()
    assert body["total_home"] == 300 + 280 + 100
    assert body["scope"]["account_id"] == db.a1
    r = c.get("/api/v1/portfolio/allocation?account_id=00000000-0000-0000-0000-000000000009")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "account_not_found"


def test_targets_roundtrip_and_errors(monkeypatch, db):
    c = make_client(monkeypatch, api.router, level="premium")
    assert c.get("/api/v1/portfolio/allocation/targets").json()["targets"] is None
    r = c.put("/api/v1/portfolio/allocation/targets", json={"targets": {"broad_etfs": 70, "stocks": 20}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "targets_sum" and r.json()["detail"]["sum"] == 90
    r = c.put("/api/v1/portfolio/allocation/targets", json={"targets": {"bonds": 100}})
    assert r.json()["detail"]["code"] == "invalid_targets"
    r = c.put("/api/v1/portfolio/allocation/targets", json={"nope": 1})
    assert r.status_code == 422
    r = c.put("/api/v1/portfolio/allocation/targets", json={"targets": {"broad_etfs": 70, "stocks": 30}})
    assert r.status_code == 200 and r.json()["targets"]["broad_etfs"] == 70
    assert c.get("/api/v1/portfolio/allocation/targets").json()["targets"]["stocks"] == 30
    assert c.get("/api/v1/portfolio/allocation").json()["targets"]["broad_etfs"] == 70
    assert c.put("/api/v1/portfolio/allocation/targets", json={"targets": None}).json()["targets"] is None
    assert db.get_allocation_targets(U1) is None


def test_plan_endpoint(monkeypatch, db):
    c = make_client(monkeypatch, api.router)
    r = c.get("/api/v1/portfolio/allocation/plan?amount=500")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_targets"
    c.put("/api/v1/portfolio/allocation/targets", json={"targets": {"broad_etfs": 70, "stocks": 20, "cash_like": 10}})
    for bad in ("0", "-5", "abc", "2e9"):
        r = c.get(f"/api/v1/portfolio/allocation/plan?amount={bad}")
        assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_amount", bad
    assert c.get("/api/v1/portfolio/allocation/plan").json()["detail"]["code"] == "invalid_amount"
    body = c.get("/api/v1/portfolio/allocation/plan?amount=620").json()
    # total after = 2000: broad 1400-300 = 1100, stocks 400-840 <0, cash 200-240 <0 -> all to broad
    assert [i["class"] for i in body["items"]] == ["broad_etfs"]
    assert body["items"][0]["amount"] == 620 and body["items"][0]["buy"]["symbol"] == "XEQT.TO"
    assert body["allocated"] == 620 and body["home_currency"] == "CAD" and body["delayed_minutes"] == 15


def test_migration_missing_is_503(monkeypatch, db):
    c = make_client(monkeypatch, api.router)
    db.missing = True
    r = c.get("/api/v1/portfolio/allocation")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "migration_required"


def test_allocation_plan_is_premium(monkeypatch, db):
    """Targets + deposit plan need feature.allocation_plan (premium, migration 022);
    the mix itself stays free."""
    c = make_client(monkeypatch, api.router, level="free")
    for method, path in [("get", "/api/v1/portfolio/allocation/targets"),
                         ("put", "/api/v1/portfolio/allocation/targets"),
                         ("get", "/api/v1/portfolio/allocation/plan?amount=500")]:
        kw = {"json": {"targets": {"stocks": 100}}} if method == "put" else {}
        r = getattr(c, method)(path, **kw)
        assert r.status_code == 403, path
        assert r.json()["detail"]["code"] == "upgrade_required", path
    assert c.get("/api/v1/portfolio/allocation").status_code == 200



# ---------------------------------------------------------------- diversified funds aren't concentration

def _codes(body, code=None):
    ws = body["warnings"]
    return [w for w in ws if w["code"] == code] if code else {w["code"] for w in ws}


def test_all_in_one_fund_is_not_concentration():
    body = alloc.build_allocation([_pos("XEQT.TO", 99), _pos("VFV.TO", 1)])
    assert not _codes(body) & {"single_holding", "top3_concentration"}


def test_stock_flagged_fund_not():
    body = alloc.build_allocation([_pos("ENB.TO", 60, at="STOCK"), _pos("XEQT.TO", 40)])
    assert [w["params"]["symbol"] for w in _codes(body, "single_holding")] == ["ENB.TO"]


def test_three_stocks_still_flagged():
    body = alloc.build_allocation([_pos("ENB.TO", 50, at="STOCK"), _pos("TD.TO", 30, at="STOCK"),
                                   _pos("SHOP.TO", 20, at="STOCK")])
    assert "top3_concentration" in _codes(body)
    assert {w["params"]["symbol"] for w in _codes(body, "single_holding")} == {"ENB.TO", "TD.TO"}


def test_option_income_and_sector_etfs_are_not_diversified():
    body = alloc.build_allocation([_pos("ZWC.TO", 30), _pos("XEQT.TO", 70)])
    assert [w["params"]["symbol"] for w in _codes(body, "single_holding")] == ["ZWC.TO"]
    assert alloc.is_diversified_fund("XLK", "Technology Select Sector SPDR Fund", "ETF") is False
    assert alloc.is_diversified_fund("TQQQ", "ProShares UltraPro QQQ", "ETF") is False
    assert alloc.is_diversified_fund("VWCE.DE", "Vanguard FTSE All-World UCITS ETF", "ETF") is True
    assert alloc.is_diversified_fund("XAW.TO", None, "ETF") is True


def test_gaps_and_warnings_agree_on_diversified_funds():
    from app.services import suggestions as sg
    pool = {"XEQT.TO": {"symbol": "XEQT.TO", "name": "iShares Core Equity ETF Portfolio", "quote_type": "ETF",
                        "exchange": "TSX"},
            "ZWC.TO": {"symbol": "ZWC.TO", "name": "BMO Canadian High Dividend Covered Call ETF",
                       "quote_type": "ETF", "exchange": "TSX", "dividend_yield": 0.07},
            "ENB.TO": {"symbol": "ENB.TO", "name": "Enbridge", "quote_type": "EQUITY", "sector": "Energy",
                       "exchange": "TSX", "dividend_yield": 0.06}}
    pos = [{"symbol": "XEQT.TO", "value_home": 900}, {"symbol": "ENB.TO", "value_home": 50},
           {"symbol": "ZWC.TO", "value_home": 50}]
    gaps = {g["code"]: g for g in sg.find_gaps(pos, pool, "CAD", "CA")}
    assert "single_position_heavy" not in gaps                       # 90% XEQT: diversified
    pos2 = [{"symbol": "XEQT.TO", "value_home": 300}, {"symbol": "ENB.TO", "value_home": 100},
            {"symbol": "ZWC.TO", "value_home": 600}]
    gaps2 = {g["code"]: g for g in sg.find_gaps(pos2, pool, "CAD", "CA")}
    assert gaps2["single_position_heavy"]["params"]["symbol"] == "ZWC.TO"   # option income: not diversified
    body = alloc.build_allocation([_pos("XEQT.TO", 300), _pos("ENB.TO", 100, at="STOCK"), _pos("ZWC.TO", 600)])
    assert [w["params"]["symbol"] for w in _codes(body, "single_holding")] == ["ZWC.TO"]   # ENB.TO is 10%
