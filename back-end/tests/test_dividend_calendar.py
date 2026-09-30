"""Dividend calendar (services/dividend_calendar.py + GET /dividends/calendar).

Fakes only: profiles are hand-built dicts, no network, no AI."""

import asyncio
from datetime import date

import pytest

from app.services import dividend_calendar as dc
from app.services import dividends

TODAY = date(2026, 9, 29)
USDCAD = 1.40


def _profile(symbol, currency="USD", upcoming=(), last=(), annual=None, freq="quarterly", yld=None):
    p = dividends.empty_profile(symbol, None)
    p.update({"pays_dividend": True, "currency": currency, "frequency": freq, "annual_rate": annual,
              "yield": yld, "upcoming": list(upcoming), "last_payments": list(last)})
    if upcoming:
        p["next_ex_date"] = upcoming[0]["ex_date"]
        p["next_pay_date"] = upcoming[0]["pay_date"]
    return p


def _up(ex, pay, amount, estimated=True, pay_est=True):
    return {"ex_date": ex, "pay_date": pay, "amount": amount, "estimated": estimated, "pay_estimated": pay_est}


MSFT = _profile("MSFT", "USD", annual=3.64, yld=0.008, upcoming=[
    _up("2026-11-18", "2026-12-10", 0.91, estimated=False, pay_est=False),
    _up("2027-02-18", "2027-03-12", 0.91),
    _up("2027-05-20", "2027-06-11", 0.91),
    _up("2027-08-19", "2027-09-10", 0.91),   # pay after the 12-month window end
])
ENB = _profile("ENB.TO", "CAD", annual=3.88, freq="quarterly", upcoming=[
    _up("2026-11-14", "2026-12-01", 0.97),
    _up("2027-02-14", "2027-03-01", 0.97),
], last=[{"ex_date": "2026-09-15", "amount": 2.50, "special": True},
         {"ex_date": "2026-08-14", "amount": 0.97, "special": False}])
XEQT = _profile("XEQT.TO", "CAD", annual=0.6, upcoming=[_up("2026-12-22", "2026-12-30", 0.15)])


def _h(symbol, shares=None, price=None, currency=None, account="TFSA", name=None):
    return {"symbol": symbol, "name": name or symbol, "shares": shares, "currency": currency,
            "account": account, "holding_status": {"price": price} if price else None}


def _build(holdings, profiles, watchlist=None, months=12, usdcad=USDCAD):
    return dc.build_calendar(holdings, watchlist, profiles, TODAY, months, usdcad)


# ---------------------------------------------------------------- window / months

def test_window_is_calendar_months():
    assert dc.window_for(TODAY, 12) == (TODAY, date(2027, 8, 31))
    assert dc.window_for(TODAY, 1) == (TODAY, date(2026, 9, 30))
    assert dc.window_for(date(2026, 12, 5), 2) == (date(2026, 12, 5), date(2027, 1, 31))
    assert dc.month_keys(*dc.window_for(TODAY, 12))[0] == "2026-09"
    assert len(dc.month_keys(*dc.window_for(TODAY, 12))) == 12


# ---------------------------------------------------------------- events

def test_events_built_sorted_and_cash_computed():
    out = _build([_h("MSFT", 10, 500.0, "USD", "RRSP")], {"MSFT": MSFT})
    evs = out["events"]
    assert [e["date"] for e in evs] == ["2026-12-10", "2027-03-12", "2027-06-11"]
    first = evs[0]
    assert first["expected_cash"] == 9.1 and first["expected_cash_cad"] == round(9.1 * USDCAD, 2)
    assert first["estimated"] is False and first["pay_date_estimated"] is False
    assert evs[1]["estimated"] is True and first["special"] is False
    assert first["account"] == "RRSP" and first["owned"] is True and first["shares"] == 10
    assert out["summary"]["next_payment"]["pay_date"] == "2026-12-10"
    assert out["summary"]["next_ex_date"]["ex_date"] == "2026-11-18"


def test_recent_ex_date_awaiting_payment_and_special_flag():
    out = _build([_h("ENB.TO", 50, 60.0, "CAD")], {"ENB.TO": ENB})
    evs = out["events"]
    # 2026-09-15 ex + 17d offset = 10-02 (still to be paid); 08-14 + 17 = 08-31 (paid: dropped)
    assert evs[0]["ex_date"] == "2026-09-15" and evs[0]["pay_date"] == "2026-10-02"
    assert evs[0]["special"] is True and evs[0]["ex_passed"] is True
    assert evs[0]["pay_date_estimated"] is True and evs[0]["estimated"] is False
    assert evs[0]["expected_cash"] == 125.0
    assert all(e["ex_date"] != "2026-08-14" for e in evs)
    # next ex-date skips the passed one
    assert out["summary"]["next_ex_date"]["ex_date"] == "2026-11-14"
    assert out["summary"]["next_payment"]["date"] == "2026-10-02"


def test_month_grouping_and_currency_totals_with_cad():
    holdings = [_h("MSFT", 10, 500.0, "USD"), _h("ENB.TO", 50, 60.0, "CAD")]
    out = _build(holdings, {"MSFT": MSFT, "ENB.TO": ENB})
    months = {m["month"]: m for m in out["months"]}
    assert len(out["months"]) == 12 and months["2026-09"]["events"] == []
    dec = months["2026-12"]
    assert [e["symbol"] for e in dec["events"]] == ["ENB.TO", "MSFT"]  # 12-01 then 12-10
    assert dec["total"]["by_currency"] == {"CAD": 48.5, "USD": 9.1}
    assert dec["total"]["total_cad"] == round(48.5 + 9.1 * USDCAD, 2)
    inc = out["summary"]["income_window"]
    # MSFT: 3 payments in window (Sep 2027 pay is outside); ENB: special 125 + 2 x 48.5
    assert inc["by_currency"] == {"CAD": 222.0, "USD": 27.3}
    assert inc["total_cad"] == round(222.0 + 27.3 * USDCAD, 2) and inc["fx_missing"] is False
    # rolling 12 months (to 2027-09-29) also has MSFT's 2027-09-10 payment
    assert out["summary"]["income_next_12m"]["by_currency"] == {"CAD": 222.0, "USD": 36.4}
    ann = out["summary"]["annual_income"]
    assert ann["by_currency"] == {"CAD": 194.0, "USD": 36.4}
    # forward yield: annual CAD / market value CAD
    mv = 10 * 500 * USDCAD + 50 * 60
    assert out["summary"]["market_value_cad"] == round(mv, 2)
    assert out["summary"]["forward_yield_pct"] == round((36.4 * USDCAD + 194.0) / mv * 100, 2)


def test_shorter_window_keeps_next_12m():
    out = _build([_h("MSFT", 10, None, "USD")], {"MSFT": MSFT}, months=3)
    assert out["window"] == {"start": "2026-09-29", "end": "2026-11-30", "months": 3}
    assert out["events"] == [] or all(e["date"] <= "2026-11-30" for e in out["events"])
    assert out["summary"]["income_window"]["total_cad"] is None
    assert out["summary"]["income_next_12m"]["by_currency"] == {"USD": 36.4}


def test_missing_fx_rate_flags_and_keeps_currency_split():
    out = _build([_h("MSFT", 10, 500.0, "USD")], {"MSFT": MSFT}, usdcad=None)
    inc = out["summary"]["income_window"]
    assert inc["by_currency"] == {"USD": 27.3} and inc["fx_missing"] is True
    assert out["events"][0]["expected_cash_cad"] is None


def test_missing_shares_listed_and_no_cash():
    out = _build([_h("XEQT.TO", None, 30.0, "CAD"), _h("MSFT", 10, 500.0, "USD")],
                 {"XEQT.TO": XEQT, "MSFT": MSFT})
    x = [e for e in out["events"] if e["symbol"] == "XEQT.TO"]
    assert x and x[0]["expected_cash"] is None and x[0]["shares"] is None
    assert out["missing_shares"] == [{"symbol": "XEQT.TO", "name": "XEQT.TO"}]
    assert out["summary"]["missing_shares"] == 1
    assert "CAD" not in out["summary"]["income_window"]["by_currency"]


def test_non_payers_crypto_and_failures_degrade():
    holdings = [_h("BTC-USD", 0.5, 90000.0, "USD"), _h("AMZN", 3, 200.0, "USD"), _h("BAD", 1, 10.0, "USD"),
                _h("MSFT", 10, 500.0, "USD")]
    profiles = {"BTC-USD": dividends.empty_profile("BTC-USD", "crypto"),
                "AMZN": dividends.empty_profile("AMZN"), "BAD": None, "MSFT": MSFT}
    out = _build(holdings, profiles)
    s = out["summary"]
    assert (s["payers"], s["non_payers"], s["unknown"], s["holdings"]) == (1, 2, 1, 4)
    assert {n["symbol"]: n["reason"] for n in out["non_payers"]} == {"BTC-USD": "crypto", "AMZN": "no_dividend"}
    assert out["unknown"] == [{"symbol": "BAD", "name": "BAD", "owned": True}]
    assert {e["symbol"] for e in out["events"]} == {"MSFT"}
    # non-payers count in the yield denominator
    mv = (0.5 * 90000 + 3 * 200 + 10 + 10 * 500) * USDCAD
    assert s["market_value_cad"] == round(mv, 2)
    pos = {p["symbol"]: p for p in out["positions"]}
    assert pos["MSFT"]["status"] == "payer" and pos["BAD"]["status"] == "unknown"
    assert out["positions"][0]["symbol"] == "MSFT"  # owned payers first


def test_unavailable_profile_is_unknown():
    out = _build([_h("X", 1)], {"X": dividends.empty_profile("X", "unavailable")})
    assert out["unknown"][0]["symbol"] == "X" and out["non_payers"] == []


def test_watchlist_events_not_owned_and_not_totalled():
    out = _build([_h("MSFT", 10, 500.0, "USD")], {"MSFT": MSFT, "ENB.TO": ENB},
                 watchlist=[{"symbol": "ENB.TO"}, {"symbol": "MSFT"}])
    enb = [e for e in out["events"] if e["symbol"] == "ENB.TO"]
    assert enb and all(not e["owned"] and e["expected_cash"] is None and e["shares"] is None for e in enb)
    assert "CAD" not in out["summary"]["income_window"]["by_currency"]
    assert out["summary"]["holdings"] == 1 and out["include_watchlist"] is True
    assert sum(1 for p in out["positions"] if p["symbol"] == "MSFT") == 1  # held wins over watchlist
    assert out["summary"]["next_payment"]["symbol"] == "MSFT"


def test_empty_input_is_valid():
    out = _build([], {})
    assert out["events"] == [] and len(out["months"]) == 12
    assert all(m["events"] == [] and m["total"]["total_cad"] is None for m in out["months"])
    s = out["summary"]
    assert s["next_payment"] is None and s["next_ex_date"] is None and s["forward_yield_pct"] is None
    assert s["income_window"] == {"by_currency": {}, "total_cad": None, "fx_missing": False}
    assert out["include_watchlist"] is False


# ---------------------------------------------------------------- async fetch

def test_get_calendar_fetch_failures_and_concurrency():
    active, peak = 0, 0

    async def fetch(sym):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        if sym == "BOOM":
            raise RuntimeError("network down")
        return {"MSFT": MSFT}.get(sym) or dividends.empty_profile(sym)

    holdings = [_h("MSFT", 10)] + [_h(f"S{i}", 1) for i in range(8)] + [_h("BOOM", 1)]
    out = asyncio.run(dc.get_calendar(holdings, None, 12, USDCAD, TODAY, fetch))
    assert peak <= dc.CONCURRENCY
    assert out["unknown"] == [{"symbol": "BOOM", "name": "BOOM", "owned": True}]
    assert out["summary"]["payers"] == 1


def test_get_calendar_default_fetch_uses_shared_profile(monkeypatch):
    """The default path goes through dividends.get_dividend_profile (patched
    _fetch_raw in conftest -> no network): no dividend, no crash."""
    out = asyncio.run(dc.get_calendar([_h("MSFT", 10), _h("BTC-USD", 1)], None, 12, None, TODAY))
    assert {n["symbol"]: n["reason"] for n in out["non_payers"]} == {"MSFT": "no_dividend", "BTC-USD": "crypto"}


# ---------------------------------------------------------------- API

@pytest.mark.real_access
def test_free_user_can_call_calendar(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1 import dividends as api
    from app.core import access
    from app.core.security import create_access_token
    from app.db import queries
    from app.middleware import auth as auth_mw

    free = lambda _uid: {"level": "free", "slot_bonus": 0}  # noqa: E731
    monkeypatch.setattr(access, "get_user_access", free)
    monkeypatch.setattr(auth_mw, "get_user_access", free)
    monkeypatch.setattr(access, "get_feature_levels",
                        lambda: {k: v[0] for k, v in access.FEATURE_CATALOG.items()})
    access.clear_access_cache()
    monkeypatch.setattr(auth_mw, "is_token_blacklisted", lambda _jti: False)
    monkeypatch.setattr(auth_mw, "insert_audit_log", lambda **_: None)
    monkeypatch.setattr(queries, "get_holdings", lambda _uid: [_h("MSFT", 10, 500.0, "USD")])
    monkeypatch.setattr(queries, "get_watchlist", lambda _uid: [{"symbol": "ENB.TO"}])
    monkeypatch.setattr(api, "_usdcad", lambda: asyncio.sleep(0, USDCAD))

    async def fake_profile(sym, info=None, price=None):
        return {"MSFT": MSFT, "ENB.TO": ENB}[sym]

    monkeypatch.setattr(dividends, "get_dividend_profile", fake_profile)

    app = FastAPI()
    app.add_middleware(auth_mw.AuthMiddleware)
    app.include_router(api.router, prefix="/api/v1")
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {create_access_token('11111111-1111-1111-1111-111111111111', 'u')}"

    r = c.get("/api/v1/dividends/calendar?months=12&include_watchlist=true")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["payers"] == 1 and body["include_watchlist"] is True
    assert any(e["symbol"] == "ENB.TO" and not e["owned"] for e in body["events"])
    assert c.get("/api/v1/dividends/calendar?months=13").status_code == 422
