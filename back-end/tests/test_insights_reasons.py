"""describe_reason: raw brain_decisions reasons -> {code, params, text}."""

import pytest

from app.core.config import settings
from app.services.insights_service import describe_reason


def test_entered_carries_size_and_risk():
    r = describe_reason("ai_buy", {"alloc_usd": 412.0, "risk_usd": 50.61}, decision="ENTER")
    assert r["code"] == "entered"
    assert r["params"]["size_usd"] == 412.0
    assert r["params"]["risk_usd"] == 50.61
    assert "$412" in r["text"]


def test_correlation_pairwise():
    det = {"correlation": {"rule": "pairwise", "max_corr": 0.84, "max_corr_symbol": "NVDA",
                           "max_pairwise": 0.8, "cluster_threshold": 0.7, "cluster_symbols": ["NVDA"]}}
    r = describe_reason("correlation_limit", det)
    assert r["code"] == "correlation_limit"
    assert r["params"]["corr"] == 0.84 and r["params"]["symbol"] == "NVDA" and r["params"]["limit"] == 0.8
    assert "0.84" in r["text"] and "NVDA" in r["text"] and "0.8" in r["text"]


def test_correlation_cluster():
    det = {"correlation": {"rule": "correlated_cluster", "max_corr": 0.72, "max_corr_symbol": "AVGO",
                           "cluster_symbols": ["AVGO", "NVDA"], "cluster_threshold": 0.7}}
    r = describe_reason("correlation_limit", det)
    assert r["params"]["cluster"] == "AVGO, NVDA"
    assert "2 holdings" in r["text"]


def test_rr_below_min():
    r = describe_reason("rr_below_min_1.40", {})
    assert r["code"] == "rr_below_min"
    assert r["params"] == {"rr": 1.4, "min": settings.brain_min_rr}
    assert "1.4" in r["text"]


def test_earnings_blackout_from_reasoning():
    sig = {"reasoning": "x\n[Earnings blackout] Earnings blackout: next report in 2 trading day(s) (2026-10-01), limit 3"}
    r = describe_reason("earnings_blackout", {}, sig)
    assert r["code"] == "earnings_blackout"
    assert r["params"] == {"days": 2, "limit": 3}
    assert "2 trading days" in r["text"]


def test_earnings_blackout_from_fundamentals():
    r = describe_reason("earnings_blackout", {}, {"fundamental_data": {"trading_days_to_next_earnings": 1}})
    assert r["params"]["days"] == 1


def test_technical_filter_overextended_computes_value():
    sig = {"technical_data": {"last_close": 122.0, "sma_50": 100.0, "sma_200": 90.0}}
    r = describe_reason("technical_filter:overextended_vs_sma50", {}, sig)
    assert r["code"] == "technical_filter"
    assert r["params"]["check"] == "overextended_vs_sma50"
    assert r["params"]["value"] == 22.0
    assert r["params"]["limit"] == settings.tech_filter_max_ext_sma50_pct
    assert "22%" in r["text"]


def test_technical_filter_rsi_and_no_colon_uses_details():
    sig = {"technical_data": {"rsi": 78.2}}
    r = describe_reason("technical_filter", {"tech_filter": {"passed": False, "reasons": ["rsi_overbought"]}}, sig)
    assert r["params"]["check"] == "rsi_overbought"
    assert r["params"]["value"] == 78.2


def test_breaker_pause():
    r = describe_reason("drawdown_breaker_pause", {"breaker": {"days_remaining": 4}})
    assert r["code"] == "drawdown_breaker_pause"
    assert r["params"]["days_remaining"] == 4
    assert "4" in r["text"]


@pytest.mark.parametrize("raw,code", [
    ("not_ai_buy_skipped_None", "ai_not_called"),
    ("not_ai_buy_rejected_HOLD", "ai_rejected"),
    ("not_ai_buy_failed_None", "ai_failed"),
    ("ai_failed", "ai_failed"),
    ("not_ai_buy_low_confidence_BUY", "ai_low_confidence"),
])
def test_ai_reasons(raw, code):
    assert describe_reason(raw, {}, {"confidence": 55})["code"] == code


def test_rejected_signal_param():
    assert describe_reason("not_ai_buy_rejected_HOLD", {})["params"]["signal"] == "HOLD"


def test_decision_veto_takes_precedence():
    r = describe_reason("not_ai_buy_rejected_HOLD", {}, {"decision_overturned": True, "ai_signal": "HOLD"})
    assert r["code"] == "decision_veto"
    assert r["params"]["decision_signal"] == "HOLD"


@pytest.mark.parametrize("raw,code,key,val", [
    ("max_open_positions_8", "max_open_positions", "max", 8),
    ("sector_cap_technology", "sector_cap", "sector", "Technology"),
    ("reentry_cooldown_3d", "reentry_cooldown", "days", 3),
    ("fx_unavailable_CAD", "fx_unavailable", "currency", "CAD"),
])
def test_parametrised_limits(raw, code, key, val):
    r = describe_reason(raw, {})
    assert r["code"] == code
    assert r["params"][key] == val


@pytest.mark.parametrize("raw,code", [
    ("crypto_cap", "crypto_cap"),
    ("already_held", "already_held"),
    ("market_closed", "market_closed"),
    ("action_sell", "action_sell"),
    ("action_avoid_market_closed", "action_avoid"),
    ("size_below_minimum", "size_below_minimum"),
    ("no_price", "no_price"),
    ("portfolio_beta_limit", "portfolio_beta_limit"),
    ("short:shorts_disabled", "other"),
    ("something_brand_new", "other"),
])
def test_simple_codes(raw, code):
    r = describe_reason(raw, {})
    assert r["code"] == code
    assert r["raw"] == raw
    assert r["text"]


def test_none_reason():
    r = describe_reason(None, None)
    assert r["code"] == "other" and r["raw"] is None
