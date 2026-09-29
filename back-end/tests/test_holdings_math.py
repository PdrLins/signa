"""My holdings — position math (CAD conversion, concentration), review
summary, weekly review-all limit, allocate ranking, overlap notes."""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.services import holdings_service as hs


def _h(hid, sym, price, shares=None, cost=None, ccy=None, **extra):
    return {"id": hid, "symbol": sym, "currency": ccy, "shares": shares, "avg_cost": cost,
            "holding_status": {"price": price} if price is not None else None, **extra}


# ── currency ──

def test_to_cad():
    assert hs.to_cad(100.0, "CAD", None) == 100.0
    assert hs.to_cad(100.0, "USD", 1.40) == pytest.approx(140.0)
    assert hs.to_cad(100.0, "USD", None) is None


def test_holding_currency_from_suffix():
    assert hs.holding_currency({"symbol": "XEQT.TO"}) == "CAD"
    assert hs.holding_currency({"symbol": "NVDA"}) == "USD"
    assert hs.holding_currency({"symbol": "NVDA", "currency": "CAD"}) == "CAD"


# ── portfolio math ──

def test_portfolio_math_cad_totals_and_weights():
    rows = [
        _h("a", "XEQT.TO", 30.0, shares=100, cost=25.0, ccy="CAD"),     # 3000 CAD, book 2500
        _h("b", "NVDA", 100.0, shares=10, cost=50.0, ccy="USD"),        # 1000 USD = 1400 CAD, book 700 CAD
        _h("c", "COST", 900.0, ccy="USD"),                              # no shares
    ]
    per, tot = hs.portfolio_math(rows, usdcad=1.4, max_weight_pct=50)
    assert per["a"]["value_cad"] == 3000.0
    assert per["b"]["value"] == 1000.0 and per["b"]["value_cad"] == 1400.0
    assert per["b"]["unrealized"] == 500.0 and per["b"]["unrealized_pct"] == 100.0
    assert per["c"]["value"] is None and per["c"]["weight_pct"] is None
    assert tot["value_cad"] == 4400.0
    assert tot["book_value_cad"] == pytest.approx(3200.0)
    assert tot["unrealized_cad"] == pytest.approx(1200.0)
    assert per["a"]["weight_pct"] == pytest.approx(68.18, abs=0.01)
    assert per["a"]["overweight"] is True and per["b"]["overweight"] is False
    assert tot["count_with_shares"] == 2 and tot["currency"] == "CAD"


def test_portfolio_math_uses_setting_default(monkeypatch):
    monkeypatch.setattr(settings, "holdings_max_weight_pct", 15.0)
    rows = [_h("a", "A.TO", 10.0, shares=20, ccy="CAD"), _h("b", "B.TO", 10.0, shares=80, ccy="CAD")]
    per, tot = hs.portfolio_math(rows, None)
    assert per["a"]["weight_pct"] == 20.0 and per["a"]["overweight"] is True
    assert tot["max_weight_pct"] == 15.0


def test_portfolio_math_missing_fx_excludes_usd_and_flags():
    rows = [_h("a", "A.TO", 10.0, shares=10, ccy="CAD"), _h("b", "NVDA", 100.0, shares=1, ccy="USD")]
    per, tot = hs.portfolio_math(rows, None)
    assert per["b"]["value"] == 100.0 and per["b"]["value_cad"] is None
    assert tot["fx_missing"] is True and tot["value_cad"] == 100.0
    assert per["a"]["weight_pct"] == 100.0


def test_portfolio_math_without_any_shares():
    per, tot = hs.portfolio_math([_h("a", "XEQT.TO", 30.0)], 1.4)
    assert tot["value_cad"] is None and per["a"]["weight_pct"] is None


# ── review summary / limit ──

def test_review_summary_prefers_ai_concern():
    res = {"verdict": "SOLID", "verdict_source": "ai", "asset_type": "ETF", "checked_at": "2026-09-28T00:00:00+00:00",
           "ai_assessment": {"summary": "Broad and cheap.", "concerns": ["Home bias"], "confidence": 70},
           "scorecard": [{"key": "cost", "rating": "good", "reason": "x"}], "red_flags": []}
    s = hs.review_summary(res)
    assert s["verdict"] == "SOLID" and s["key_concern"] == "Home bias" and s["key_concern_source"] == "ai"
    assert s["scorecard"] == [{"key": "cost", "rating": "good"}]


def test_review_summary_falls_back_to_poor_rating():
    res = {"verdict": "NOT_A_GOOD_FIT", "ai_assessment": None,
           "scorecard": [{"key": "cost", "rating": "poor", "reason": "Expense ratio 0.95%"}], "red_flags": []}
    s = hs.review_summary(res)
    assert s["key_concern"] == "Expense ratio 0.95%" and s["key_concern_source"] == "poor:cost"


def test_review_all_allowed_weekly():
    now = datetime(2026, 9, 28, tzinfo=timezone.utc)
    assert hs.review_all_allowed(None, now, days=7) == (True, None)
    ok, nxt = hs.review_all_allowed((now - timedelta(days=3)).isoformat(), now, days=7)
    assert ok is False and nxt.startswith("2026-10-02")
    ok, _ = hs.review_all_allowed((now - timedelta(days=8)).isoformat(), now, days=7)
    assert ok is True


# ── allocate ranking ──

def _row(hid, sym, verdict=None, dd=None, vs200=None, trend_break=False, flags=None, **st):
    return {"id": hid, "symbol": sym, "name": sym,
            "holding_status": {"price": 10.0, "drawdown_pct": dd, "pct_vs_sma200": vs200,
                               "trend_break": trend_break, "red_flags": flags or [], **st},
            "last_review": {"verdict": verdict} if verdict else None}


def test_allocate_ranking_order_and_tiers():
    rows = [
        _row("1", "XEQT.TO", "SOLID", dd=-8, vs200=4),                       # 3 + 1.5 + 0.5 = 5
        _row("2", "NVDA", "SOLID", dd=-1, vs200=40),                          # 3 + 0 - 1 = 2
        _row("3", "RGTI", "NOT_A_GOOD_FIT", dd=-50, vs200=-20, trend_break=True),
        _row("4", "COST", "SOLID", dd=-9, vs200=5),                           # overweight below
        _row("5", "QYLD", "REASONABLE_WITH_CAVEATS", dd=-5, vs200=3),         # covered call
    ]
    weights = {"4": {"weight_pct": 30.0, "overweight": True}}
    out = hs.allocate_ideas(rows, weights)
    order = [i["symbol"] for i in out["ideas"]]
    assert order[0] == "XEQT.TO"
    assert order[-1] == "RGTI"
    assert order.index("COST") > order.index("NVDA")
    ideas = {i["symbol"]: i for i in out["ideas"]}
    assert ideas["XEQT.TO"]["tier"] == "consider" and ideas["RGTI"]["tier"] == "caution"
    assert "overweight" in [f["code"] for f in ideas["COST"]["factors"]]
    assert "covered_call" in [f["code"] for f in ideas["QYLD"]["factors"]]
    assert ideas["XEQT.TO"]["rank"] == 1 and ideas["XEQT.TO"]["reason"]
    assert "not financial advice" in out["caveat"].lower()


def test_allocate_never_outputs_amounts_or_buy_words():
    out = hs.allocate_ideas([_row("1", "XEQT.TO", "SOLID", dd=-8, vs200=4)], {})
    text = " ".join(i["reason"] for i in out["ideas"]).lower()
    assert "buy" not in text and "$" not in text


def test_allocate_unreviewed_and_no_data():
    out = hs.allocate_ideas([{"id": "1", "symbol": "ZZZ", "holding_status": None, "last_review": None}], {})
    codes = [f["code"] for f in out["ideas"][0]["factors"]]
    assert "not_reviewed" in codes and "no_data" in codes


# ── overlap notes ──

def test_overlap_notes_for_owner_holdings():
    syms = ["XEQT.TO", "VFV.TO", "QQQ", "TQQQ", "QQCL.TO", "QYLD", "NVDA", "MSFT", "ENB.TO", "ENS.TO",
            "BTCQ.TO", "FBTC", "CBIL.TO", "ZMMK.TO", "RY.TO", "BMO.TO", "CM.TO", "XGD.TO", "SVR.TO", "ZWT.TO"]
    notes = {n["code"]: n for n in hs.overlap_notes([{"symbol": s} for s in syms])}
    assert set(notes["overlap_us_large_tech"]["symbols"]) >= {"XEQT.TO", "VFV.TO", "QQQ", "TQQQ", "QQCL.TO"}
    assert "NVDA" in notes["overlap_mega_caps"]["symbols"]
    assert set(notes["covered_call"]["symbols"]) >= {"QYLD", "QQCL.TO", "ZWT.TO"}
    assert notes["leveraged"]["symbols"] == ["TQQQ"]
    for g in ("bitcoin", "enbridge", "cash_like", "canadian_banks", "precious_metals"):
        assert f"group_{g}" in notes


def test_overlap_notes_single_fund_no_overlap():
    assert not [n for n in hs.overlap_notes([{"symbol": "XEQT.TO"}]) if n["code"].startswith("overlap")]
