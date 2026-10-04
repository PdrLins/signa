"""Dividend summary (expected/received, grades, growth, months, upcoming,
why-changed), withholding tax rules, income forecast snapshots and income
quality. Fakes only: no network, no DB."""

import asyncio
from datetime import date, timedelta

import pandas as pd
import pytest

from app.api.v1 import dividend_summary as api
from app.db import queries
from app.services import dividend_calendar, dividend_summary as ds, dividend_tax as tax, dividends
from app.services import income_forecast as fc, income_quality as iq
from tests.portfolio_fakes import U1, FakePortfolioDB, make_client

TODAY = date(2026, 9, 30)


def payer(sym, ccy, rate, per_payment, step_days, first_ex, n=None, pay_offset=14, history=None, **kw):
    n = n or max(1, int(365 // step_days))
    upcoming = []
    for k in range(n):
        ex = first_ex + timedelta(days=k * step_days)
        upcoming.append({"ex_date": ex.isoformat(), "pay_date": (ex + timedelta(days=pay_offset)).isoformat(),
                         "amount": per_payment, "estimated": k > 0, "pay_estimated": True})
    if history is None:   # 2+ years of flat payments
        history = []
        d = first_ex - timedelta(days=step_days)
        while (TODAY - d).days <= 800:
            history.append({"ex_date": d.isoformat(), "amount": per_payment, "special": False})
            d -= timedelta(days=step_days)
        history.reverse()
    p = {**dividends.empty_profile(sym), "pays_dividend": True, "reason": None, "currency": ccy,
         "annual_rate": rate, "yield": kw.pop("yield_", 0.03), "upcoming": upcoming, "history": history,
         "frequency": {30: "monthly", 91: "quarterly"}.get(step_days, "quarterly"),
         "next_ex_date": upcoming[0]["ex_date"], "next_pay_date": upcoming[0]["pay_date"]}
    p.update(kw)
    return p


MSFT = payer("MSFT", "USD", 3.64, 0.91, 91, date(2026, 11, 18), growth_5y_cagr=0.10, years_without_cut=20.0,
             payout_ratio=0.25)
ENB = payer("ENB.TO", "CAD", 3.66, 0.305, 30, date(2026, 10, 14), payout_ratio=0.60)   # steady
XEQT = payer("XEQT.TO", "CAD", 0.80, 0.20, 91, date(2026, 12, 22), is_fund=True)


def scope(holdings, accounts=None, **kw):
    s = {"user_id": U1, "level": "free", "country": "CA", "home_currency": "CAD", "tax_view": "before",
         "tax_eligible": False, "compare_index": None, "all_accounts": accounts or [], "accounts": accounts or [],
         "account_ids": None, "holdings": holdings, "transactions": [], "quotes": {}, "usdcad": 1.4}
    s.update(kw)
    return s


def H(sym, shares, account_id=None, avg_cost=None, **kw):
    return {"symbol": sym, "shares": shares, "account_id": account_id, "avg_cost": avg_cost,
            "currency": "CAD" if sym.endswith(".TO") else "USD", **kw}


# ---------------------------------------------------------------- tax rules

@pytest.mark.parametrize("sym,ccy,atype,country,code,rate,recov", [
    ("MSFT", "USD", "TFSA", "CA", "lost", 0.15, False),
    ("MSFT", "USD", "FHSA", "CA", "lost", 0.15, False),
    ("MSFT", "USD", "RESP", "CA", "lost", 0.15, False),
    ("MSFT", "USD", "RRSP", "CA", "treaty_exempt", 0.0, False),
    ("MSFT", "USD", "NON_REGISTERED", "CA", "recoverable", 0.15, True),
    ("MSFT", "USD", "OTHER", "CA", "recoverable", 0.15, True),
    ("ENB.TO", "CAD", "TFSA", "CA", "none", 0.0, False),
    ("ENB.TO", "CAD", "TAXABLE", "US", "recoverable", 0.15, True),
    ("ENB.TO", "CAD", "ROTH_IRA", "US", "lost", 0.15, False),
    ("ENB.TO", "CAD", "401K", "US", "lost", 0.15, False),
    ("MSFT", "USD", "ROTH_IRA", "US", "none", 0.0, False),
])
def test_withholding_rules(sym, ccy, atype, country, code, rate, recov):
    r = tax.rule_for(sym, ccy, atype, country)
    assert (r["code"], r["rate"], r["recoverable"]) == (code, rate, recov)


def test_untyped_account_gets_no_tax():
    r = tax.rule_for("MSFT", "USD", None, "CA")
    assert r["applies"] is False and tax.apply(100.0, r)["after_tax"] == 100.0


def test_inside_fund_share_and_heuristic():
    assert tax.fund_us_share("XEQT.TO") == 0.45 and tax.fund_us_share("VFV.TO") == 1.0
    assert tax.fund_us_share("SPY") == 0.0            # US-listed: not "inside a Canadian fund"
    assert tax.fund_us_share("ABCD.TO", {"is_fund": True, "name": "Some S&P 500 Index ETF"}) == 1.0
    assert tax.fund_us_share("ABCD.TO", {"is_fund": True, "name": "Canadian Banks ETF"}) == 0.0
    parts = tax.apply(85.0, tax.rule_for("VFV.TO", "CAD", "RRSP", "CA"))
    # inside-fund tax is estimated, not subtracted (the distribution is already net)
    assert parts["inside_fund"] == pytest.approx(15.0) and parts["after_tax"] == 85.0


def test_apply_splits_lost_and_recoverable():
    lost = tax.apply(100.0, tax.rule_for("MSFT", "USD", "TFSA", "CA"))
    assert lost["lost"] == pytest.approx(15) and lost["after_tax"] == pytest.approx(85)
    rec = tax.apply(100.0, tax.rule_for("MSFT", "USD", "NON_REGISTERED", "CA"))
    assert rec["recoverable"] == pytest.approx(15) and rec["after_tax"] == 100 and rec["cash_received"] == 85


# ---------------------------------------------------------------- grades

def test_safety_grades():
    assert ds.safety_grade({**MSFT, "recent_cut": True}, "STOCK", TODAY)[0] == "cut"
    assert ds.safety_grade({**MSFT, "suspended": True, "pays_dividend": False}, "STOCK", TODAY) == ("cut", "suspended")
    assert ds.safety_grade({**MSFT, "payout_ratio": 1.3}, "STOCK", TODAY) == ("watch", "payout_over_100")
    assert ds.safety_grade({**MSFT, "yield": 0.08, "five_year_avg_yield": 0.04, "payout_ratio": 0.5},
                           "STOCK", TODAY) == ("watch", "yield_trap")
    assert ds.safety_grade(MSFT, "STOCK", TODAY) == ("growing", "grows_5y")
    assert ds.safety_grade(ENB, "STOCK", TODAY) == ("steady", "steady_payer")
    hist = [{"ex_date": (TODAY - timedelta(days=30 * k)).isoformat(), "amount": a, "special": False}
            for k, a in enumerate([0.5, 0.2, 0.9, 0.3, 0.7])]
    assert ds.safety_grade({**ENB, "history": hist}, "STOCK", TODAY) == ("variable", "volatile_payouts")
    # Broad index ETF: uneven distributions are normal -> steady (noted).
    assert ds.safety_grade({**XEQT, "history": hist}, "ETF", TODAY) == ("steady", "fund_distributions_vary")
    # Option-income fund with the same volatility -> variable.
    assert ds.safety_grade({**XEQT, "history": hist}, "ETF", TODAY, option_income=True) == ("variable", "volatile_distributions")
    assert ds.safety_grade(XEQT, "ETF", TODAY) == ("steady", "steady_distributions")
    assert ds.safety_grade(dividends.empty_profile("AMZN"), "STOCK", TODAY) == (None, "no_dividend")


def test_growth_1y_and_months_pattern():
    hist = [{"ex_date": (TODAY - timedelta(days=91 * k + 10)).isoformat(), "amount": 1.1 if k < 4 else 1.0,
             "special": False} for k in range(9)]
    assert ds.growth_1y({"history": hist}, TODAY) == pytest.approx(0.10)
    assert ds.growth_1y({"history": hist[:4]}, TODAY) is None          # no prior year
    # a quarter that slipped out of the last 12 months (3 payments vs 4) is
    # a timing gap, not a 27% cut
    slipped = [h for i, h in enumerate(hist) if i != 0]
    slipped = [{**h, "ex_date": (TODAY - timedelta(days=91 * k + 100)).isoformat()} for k, h in enumerate(slipped)]
    assert ds.growth_1y({"history": slipped}, TODAY) is None
    evs = dividend_calendar.profile_events(MSFT, TODAY)
    months = ds.months_pattern(evs, MSFT, TODAY)
    assert sum(months) == 4 and months[11] is True                      # Dec 2 pay date


# ---------------------------------------------------------------- expected income

def test_expected_summary_math():
    s = scope([H("MSFT", 10, avg_cost=300), H("ENB.TO", 100), H("AMZN", 5)],
              quotes={"MSFT": {"price": 400.0, "prev_close": 400.0, "currency": "USD", "as_of": "2026-09-30T14:00:00+00:00"},
                      "ENB.TO": {"price": 60.0, "currency": "CAD", "as_of": "2026-09-30T13:00:00+00:00"},
                      "AMZN": {"price": 200.0, "currency": "USD", "as_of": "2026-09-30T14:00:00+00:00"}})
    out = ds.build_summary(s, {"MSFT": MSFT, "ENB.TO": ENB, "AMZN": dividends.empty_profile("AMZN")}, TODAY)
    msft_12m = 10 * 0.91 * 4 * 1.4          # 4 quarterly events inside the next 365 days, USD -> CAD
    enb_12m = sum(1 for u in ENB["upcoming"] if date.fromisoformat(u["pay_date"]) <= TODAY + timedelta(days=365)) \
        * 100 * 0.305
    assert out["kind"] == "expected" and out["total"] == pytest.approx(msft_12m + enb_12m, abs=0.02)
    assert out["steady_total"] == out["total"] and out["variable_total"] == 0      # growing + steady
    assert len(out["months"]) == 12 and out["months"][0]["month"] == "2026-09"
    dec = next(m for m in out["months"] if m["month"] == "2026-12")
    assert dec["days"][0]["date"] == "2026-12-02" and dec["days"][0]["amount"] == pytest.approx(10 * 0.91 * 1.4, abs=0.01)
    assert out["non_payers"] == ["AMZN"]
    mv = 10 * 400 * 1.4 + 100 * 60 + 5 * 200 * 1.4
    assert out["yield_pct"] == pytest.approx(out["forward_income"] / mv * 100, abs=0.01)
    assert out["yield_on_cost_pct"] == pytest.approx(msft_12m / (10 * 300 * 1.4) * 100, abs=0.01)
    assert out["as_of"] == "2026-09-30T13:00:00+00:00" and out["delayed_minutes"] == 15
    msft = next(p for p in out["payers"] if p["symbol"] == "MSFT")
    assert msft["safety"] == "growing" and msft["growth_5y_pct"] == 10.0 and sum(msft["months"]) == 4
    # growth weighted by income: only MSFT has a 5y figure
    assert out["growth"]["growth_5y_pct"] == 10.0
    assert out["growth"]["coverage_5y_pct"] == pytest.approx(msft_12m / out["forward_income"] * 100, abs=0.05)
    # upcoming: next 60 days only, sorted by date
    assert [u["symbol"] for u in out["upcoming"]] == ["ENB.TO", "ENB.TO"]
    assert out["upcoming"][0]["cash"] == pytest.approx(30.5) and out["upcoming"][0]["per_share"] == 0.305
    assert out["tax"] is None and out["tax_reason"] == "not_eligible"


def test_variable_income_split():
    cut = {**ENB, "recent_cut": True}
    out = ds.build_summary(scope([H("MSFT", 10), H("ENB.TO", 100)]), {"MSFT": MSFT, "ENB.TO": cut}, TODAY)
    assert out["variable_total"] > 0 and out["steady_total"] == pytest.approx(10 * 0.91 * 4 * 1.4, abs=0.02)
    oct_ = next(m for m in out["months"] if m["month"] == "2026-10")
    assert oct_["variable"] == pytest.approx(30.5) and oct_["steady"] == 0


def test_received_year_from_ledger():
    txs = [{"type": "dividend", "symbol": "MSFT", "trade_date": "2025-03-12", "amount": 9.1, "currency": "USD"},
           {"type": "dividend", "symbol": "ENB.TO", "trade_date": "2025-03-01", "amount": 30.5, "currency": "CAD"},
           {"type": "dividend", "symbol": "ENB.TO", "trade_date": "2024-12-01", "amount": 30.5, "currency": "CAD"},
           {"type": "buy", "symbol": "MSFT", "trade_date": "2025-01-02", "amount": 3000}]
    out = ds.build_summary(scope([H("MSFT", 10), H("ENB.TO", 100)], transactions=txs),
                           {"MSFT": MSFT, "ENB.TO": ENB}, TODAY, "2025")
    assert out["kind"] == "received" and out["total"] == pytest.approx(9.1 * 1.4 + 30.5)
    mar = next(m for m in out["months"] if m["month"] == "2025-03")
    assert mar["total"] == out["total"] and len(mar["days"]) == 2
    assert next(p for p in out["payers"] if p["symbol"] == "ENB.TO")["period_amount"] == 30.5
    empty = ds.build_summary(scope([H("MSFT", 10)]), {"MSFT": MSFT}, TODAY, "2024")
    assert empty["total"] == 0 and empty["notes"] == ["no_dividend_transactions"]


def test_invalid_period():
    with pytest.raises(Exception) as e:
        ds.parse_period("2099", TODAY)
    assert e.value.detail["code"] == "invalid_period"
    with pytest.raises(Exception):
        ds.parse_period("last5y", TODAY)


# ---------------------------------------------------------------- tax in the summary

ACCTS = [{"id": "a-tfsa", "name": "WS TFSA", "account_type": "TFSA"},
         {"id": "a-nr", "name": "Questrade", "account_type": "NON_REGISTERED"},
         {"id": "a-none", "name": "Old", "account_type": None}]


def test_after_tax_view_ca():
    s = scope([H("MSFT", 10, "a-tfsa"), H("MSFT", 10, "a-nr"), H("MSFT", 10, "a-none"), H("XEQT.TO", 100, "a-tfsa")],
              ACCTS, level="premium", tax_eligible=True, tax_view="after")
    soon = payer("MSFT", "USD", 3.64, 0.91, 91, date(2026, 10, 10))   # pays within the 60-day window
    out = ds.build_summary(s, {"MSFT": soon, "XEQT.TO": XEQT}, TODAY)
    t = out["tax"]
    per = 10 * 0.91 * 4 * 1.4
    assert t["lost"] == pytest.approx(per * 0.15, abs=0.02)
    assert t["recoverable"] == pytest.approx(per * 0.15, abs=0.02)
    xeqt = 100 * 0.20 * sum(1 for u in XEQT["upcoming"] if date.fromisoformat(u["pay_date"]) <= TODAY + timedelta(days=365))
    assert t["inside_fund"] == pytest.approx(xeqt * 0.45 * 0.15 / 0.85, abs=0.02)
    assert out["after_tax_total"] == pytest.approx(out["total"] - per * 0.15, abs=0.03)
    types = {b["account_type"]: b for b in t["by_account_type"]}
    assert set(types) == {"TFSA", "NON_REGISTERED"} and types["TFSA"]["lost"] == pytest.approx(per * 0.15, abs=0.02)
    assert t["untyped_accounts"] == [{"account_id": "a-none", "name": "Old", "gross": pytest.approx(per, abs=0.02)}]
    up = next(u for u in out["upcoming"] if u["account_id"] == "a-tfsa" and u["symbol"] == "MSFT")
    assert up["withholding_code"] == "lost" and up["after_tax"] == pytest.approx(up["cash"] * 0.85, abs=0.01)


def test_after_tax_view_us():
    accts = [{"id": "t", "name": "Brokerage", "account_type": "TAXABLE"},
             {"id": "r", "name": "Roth", "account_type": "ROTH_IRA"}]
    s = scope([H("ENB.TO", 100, "t"), H("ENB.TO", 100, "r")], accts, country="US", home_currency="USD",
              level="premium", tax_eligible=True, tax_view="after")
    out = ds.build_summary(s, {"ENB.TO": ENB}, TODAY)
    types = {b["account_type"]: b for b in out["tax"]["by_account_type"]}
    assert types["ROTH_IRA"]["lost"] > 0 and types["TAXABLE"]["lost"] == 0 and types["TAXABLE"]["recoverable"] > 0


@pytest.mark.parametrize("kw,reason", [
    ({"level": "free", "tax_eligible": False, "tax_view": "before"}, "not_eligible"),
    ({"level": "premium", "country": "BR", "tax_eligible": False, "tax_view": "before"}, "country_not_supported"),
    ({"level": "premium", "tax_eligible": True, "tax_view": "before"}, "view_before"),
])
def test_tax_not_applied(kw, reason):
    out = ds.build_summary(scope([H("MSFT", 10, "a-tfsa")], ACCTS, **kw), {"MSFT": MSFT}, TODAY)
    assert out["tax"] is None and out["tax_reason"] == reason and out["after_tax_total"] is None


# ---------------------------------------------------------------- forecast + why changed

def _snap(d, usdcad, per):
    return {"snapshot_date": d, "usdcad": usdcad, "currency": "CAD", "per_symbol": per,
            "total_home": sum(v["annual_home"] for v in per.values())}


def _ps(shares, rate, ccy, fx=1.4):
    native = shares * rate
    return {"shares": shares, "annual_rate": rate, "currency": ccy, "annual_native": native,
            "annual_home": native * (fx if ccy == "USD" else 1)}


def test_compute_forecast_merges_accounts():
    out = fc.compute_forecast([H("MSFT", 10, "a"), H("MSFT", 5, "b"), H("AMZN", 3)],
                              {"MSFT": MSFT, "AMZN": dividends.empty_profile("AMZN")}, "CAD", 1.4)
    assert set(out["per_symbol"]) == {"MSFT"} and out["per_symbol"]["MSFT"]["shares"] == 15
    assert out["total_home"] == pytest.approx(15 * 3.64 * 1.4)


def test_income_change_components_add_up():
    base = _snap("2026-08-30", 1.30, {"MSFT": _ps(10, 3.32, "USD"), "T": _ps(100, 1.11, "USD"),
                                      "ENB.TO": _ps(100, 3.66, "CAD"), "BNS.TO": _ps(50, 4.24, "CAD")})
    now = fc.compute_forecast([H("MSFT", 12), H("T", 100), H("ENB.TO", 100), H("RY.TO", 20)],
                              {"MSFT": {**MSFT, "annual_rate": 3.64},
                               "T": {**MSFT, "currency": "USD", "annual_rate": 0.9},
                               "ENB.TO": ENB, "RY.TO": {**ENB, "annual_rate": 6.0}}, "CAD", 1.40)
    out = ds.income_change([base], now, "CAD", TODAY, scoped=False)
    c = out["components"]
    assert out["full_period"] and out["from_date"] == "2026-08-30" and out["available_from"] is None
    assert c["raises"] == pytest.approx(12 * (3.64 - 3.32) * 1.30, abs=0.01)
    assert c["cuts"] == pytest.approx(100 * (0.9 - 1.11) * 1.30, abs=0.01)
    assert c["new_shares"] == pytest.approx(2 * 3.32 * 1.30 + 20 * 6.0, abs=0.01)
    assert c["removed_shares"] == pytest.approx(-50 * 4.24, abs=0.01)
    usd_now = 12 * 3.64 + 100 * 0.9
    assert c["fx"] == pytest.approx(usd_now * (1.40 - 1.30), abs=0.01)
    assert sum(c.values()) == pytest.approx(out["change"], abs=0.05)
    kinds = {i["kind"] for i in out["items"]}
    assert {"raise", "cut", "new_position", "removed_position", "more_shares"} <= kinds


def test_income_change_history_states():
    now = fc.compute_forecast([H("ENB.TO", 100)], {"ENB.TO": ENB}, "CAD", 1.4)
    recent = _snap("2026-09-20", 1.4, {"ENB.TO": _ps(90, 3.66, "CAD")})
    part = ds.income_change([recent], now, "CAD", TODAY, scoped=False)
    assert part["full_period"] is False and part["available_from"] == "2026-10-20"
    assert part["components"]["new_shares"] == pytest.approx(10 * 3.66) and part["reason"] == "partial_history"
    none = ds.income_change([], now, "CAD", TODAY, scoped=False)
    assert none["components"] is None and none["available_from"] == "2026-10-30"
    assert ds.income_change(None, now, "CAD", TODAY, False, missing=True)["available_from"] is None
    assert ds.income_change([recent], now, "CAD", TODAY, scoped=True)["reason"] == "whole_portfolio_only"
    # the snapshot closest to 30 days ago (latest one <= today-30) is used
    older = _snap("2026-08-01", 1.4, {"ENB.TO": _ps(10, 3.66, "CAD")})
    mid = _snap("2026-08-29", 1.4, {"ENB.TO": _ps(50, 3.66, "CAD")})
    assert ds.income_change([older, mid, recent], now, "CAD", TODAY, False)["from_date"] == "2026-08-29"


def test_run_income_snapshots(monkeypatch):
    written = {}
    monkeypatch.setattr(queries, "get_all_holdings", lambda: [
        {"user_id": "u1", "symbol": "MSFT", "shares": 10}, {"user_id": "u2", "symbol": "ENB.TO", "shares": 100}])
    monkeypatch.setattr(queries, "get_user_home_currencies", lambda ids: {"u1": "USD"})
    monkeypatch.setattr(queries, "upsert_income_snapshot", lambda uid, d, row: written.update({(uid, d): row}) or 1)
    monkeypatch.setattr("app.services.price_cache.get_usdcad_rate", lambda *a, **k: 1.4)
    calls = []

    async def fetch(sym):
        calls.append(sym)
        return {"MSFT": MSFT, "ENB.TO": ENB}[sym]
    r = asyncio.run(fc.run_income_snapshots(TODAY, fetch=fetch))
    assert r["status"] == "ok" and r["rows"] == 2 and sorted(calls) == ["ENB.TO", "MSFT"]
    assert written[("u1", "2026-09-30")]["total_home"] == pytest.approx(36.4)
    assert written[("u2", "2026-09-30")]["currency"] == "CAD"

    def missing(*a):
        raise RuntimeError('relation "income_forecast_snapshots" does not exist')
    monkeypatch.setattr(queries, "upsert_income_snapshot", missing)
    assert asyncio.run(fc.run_income_snapshots(TODAY, fetch=fetch)) == {"status": "unavailable"}


# ---------------------------------------------------------------- API

@pytest.fixture
def db(monkeypatch):
    d = FakePortfolioDB(monkeypatch)
    monkeypatch.setattr(dividends, "today_et", lambda: TODAY)

    async def fake_profiles(symbols, fetch=None, **k):
        return {s: {"MSFT": MSFT, "ENB.TO": ENB}.get(s) for s in symbols}
    monkeypatch.setattr(dividend_calendar, "fetch_profiles", fake_profiles)
    return d


def test_api_summary(monkeypatch, db):
    aid = db.add_account(U1, "WS", account_type="TFSA")
    db.add_holding(U1, "MSFT", aid, shares=10, currency="USD")
    db.add_holding(U1, "ENB.TO", None, shares=100, currency="CAD")
    db.quotes["MSFT"] = {"price": 400.0, "currency": "USD", "as_of": "2026-09-30T14:00:00+00:00"}
    db.income_snaps[(U1, "2026-08-25")] = _snap("2026-08-25", 1.4, {"MSFT": _ps(10, 3.64, "USD")})
    db.upsert_profile_settings(U1, {"country": "CA", "dividend_tax_view": "after"})
    c = make_client(monkeypatch, api.router, level="premium")
    body = c.get("/api/v1/dividends/summary").json()
    assert body["kind"] == "expected" and body["total"] > 0 and body["tax"]["by_account_type"][0]["account_type"] == "TFSA"
    assert body["income_change"]["components"]["new_shares"] == pytest.approx(100 * 3.66)
    scoped = c.get(f"/api/v1/dividends/summary?account_id={aid}").json()
    assert {p["symbol"] for p in scoped["payers"]} == {"MSFT"}
    assert scoped["income_change"]["reason"] == "whole_portfolio_only"
    assert c.get("/api/v1/dividends/summary?period=abc").json()["detail"]["code"] == "invalid_period"
    assert c.get("/api/v1/dividends/summary?account_id=00000000-0000-0000-0000-000000000009").status_code == 404
    free = make_client(monkeypatch, api.router, level="free").get("/api/v1/dividends/summary").json()
    assert free["tax"] is None and free["tax_reason"] == "not_eligible"


def test_api_summary_without_014(monkeypatch, db):
    db.add_holding(U1, "MSFT", None, shares=10, currency="USD")

    def missing(*a, **k):
        raise RuntimeError('relation "public.income_forecast_snapshots" does not exist (42P01)')
    monkeypatch.setattr(queries, "get_income_snapshot_bounds", missing)
    body = make_client(monkeypatch, api.router).get("/api/v1/dividends/summary").json()
    assert body["income_change"]["reason"] == "migration_required" and body["income_change"]["available_from"] is None


# ---------------------------------------------------------------- income quality

def test_income_class_and_source():
    assert iq.income_class("JEPI", {}) == "option_income" and iq.income_class("QQCL.TO", {}) == "option_income"
    assert iq.income_class("SGOV", {}) == "cash_like"
    assert iq.income_class("ABC", {"name": "XYZ Money Market ETF"}) == "cash_like"
    assert iq.income_class("ENB.TO", {}) == "steady"
    assert iq.yield_source("option_income", {"yield": 0.60}) == ("option_premiums", ["return_of_capital_possible"])
    assert iq.yield_source("option_income", {"yield": 0.08}) == ("option_premiums", [])
    assert iq.yield_source("cash_like", {})[0] == "interest"
    assert iq.yield_source("steady", {"payout_ratio": 1.4})[0] == "dividends_exceed_earnings"
    assert iq.yield_source("steady", {"is_fund": True})[0] == "fund_distributions"


def test_underlying_mapping():
    assert iq.UNDERLYING["QYLD"] == "QQQ" and iq.UNDERLYING["NVDY"] == "NVDA" and iq.UNDERLYING["ZWT.TO"] == "XLK"
    assert iq.UNDERLYING.get("ENB.TO") is None


def _closes(start_val, end_val, years=6):
    idx = pd.bdate_range(end="2026-09-30", periods=int(252 * years))
    return pd.Series([start_val + (end_val - start_val) * i / (len(idx) - 1) for i in range(len(idx))], index=idx)


def test_build_quality_with_and_without_underlying():
    hist = [{"ex_date": (TODAY - timedelta(days=30 * k)).isoformat(), "amount": a, "special": False}
            for k, a in enumerate([0.50, 0.40, 0.60, 0.60])]
    prof = {**dividends.empty_profile("JEPQ"), "pays_dividend": True, "yield": 0.10, "history": hist}
    out = iq.build_quality("JEPQ", prof, {"JEPQ": _closes(50, 60), "QQQ": _closes(300, 600)}, TODAY)
    ph = out["payout_history"]
    assert [p["amount"] for p in ph["payments"]] == [0.6, 0.6, 0.4, 0.5]
    assert ph["min_change_pct"] == pytest.approx(-33.33, abs=0.01) and ph["max_change_pct"] == 25.0
    assert out["underlying"] == "QQQ" and out["income_class"] == "option_income"
    tr = out["total_return_5y"]
    assert tr["years"] == pytest.approx(5.0, abs=0.1) and tr["symbol_pct"] < tr["underlying_pct"]
    assert out["comparison"]["difference_pct"] == pytest.approx(tr["symbol_pct"] - tr["underlying_pct"], abs=0.01)
    assert out["comparison"]["currency_mismatch"] is False
    plain = iq.build_quality("ENB.TO", {**ENB}, {"ENB.TO": _closes(40, 60)}, TODAY)
    assert plain["underlying"] is None and plain["comparison"] is None and plain["total_return_5y"]["symbol_pct"] > 0


def test_api_income_quality(monkeypatch):
    iq._cache.clear()
    monkeypatch.setattr(dividends, "today_et", lambda: TODAY)

    async def prof(sym, info=None, price=None):
        return {**ENB, "symbol": sym}
    monkeypatch.setattr(dividends, "get_dividend_profile", prof)
    monkeypatch.setattr("app.services.price_cache.fetch_daily_closes",
                        lambda syms, period="1y": {s: _closes(10, 12) for s in syms})
    free = make_client(monkeypatch, api.income_router, level="free")
    r = free.get("/api/v1/portfolio/income-quality/qqcl.to")   # premium since migration 022
    assert r.status_code == 403 and r.json()["detail"]["code"] == "upgrade_required"
    c = make_client(monkeypatch, api.income_router, level="premium")
    body = c.get("/api/v1/portfolio/income-quality/qqcl.to").json()
    assert body["symbol"] == "QQCL.TO" and body["underlying"] == "QQQ" and body["comparison"]["currency_mismatch"]
    assert c.get("/api/v1/portfolio/income-quality/$$$").json()["detail"]["code"] == "invalid_symbol"


def test_funds_skip_the_earnings_calendar():
    from app.services.dividends import skip_calendar
    assert skip_calendar({"quoteType": "ETF"}) and skip_calendar({"quoteType": "MUTUALFUND"})
    assert not skip_calendar({"quoteType": "EQUITY"}) and not skip_calendar({}) and not skip_calendar(None)
