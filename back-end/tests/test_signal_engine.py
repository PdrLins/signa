"""Tests for live signal engine — scoring, GEM, blockers, status."""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("DEBUG", "true")

from app.ai.signal_engine import (
    check_blockers,
    check_gem,
    determine_status,
    score_to_action,
)


class TestScoreToAction:
    def test_buy(self):
        assert score_to_action(80) == "BUY"

    def test_hold(self):
        assert score_to_action(60) == "HOLD"

    def test_avoid(self):
        assert score_to_action(40) == "AVOID"

    def test_ceiling(self):
        assert score_to_action(95) == "HOLD"  # Above 90 ceiling


class TestBlockers:
    def test_fraud_detected(self):
        grok = {"summary": "SEC investigation into fraud allegations", "top_themes": []}
        blocked, reasons = check_blockers(grok, {}, {}, {})
        assert blocked is True
        assert any("fraud" in r.lower() for r in reasons)

    def test_hostile_macro(self):
        blocked, reasons = check_blockers(
            {"summary": "", "top_themes": []},
            {},
            {"environment": "hostile", "vix": 35, "fed_funds_rate": 5.5},
            {},
        )
        assert blocked is True
        assert any("hostile" in r.lower() for r in reasons)

    def test_overbought_rsi(self):
        blocked, reasons = check_blockers(
            {"summary": "", "top_themes": []}, {}, {}, {"rsi": 78},
        )
        assert blocked is True
        assert any("RSI" in r for r in reasons)

    def test_low_volume(self):
        blocked, reasons = check_blockers(
            {"summary": "", "top_themes": []}, {}, {},
            {"volume_zscore": -2.5},
        )
        assert blocked is True

    def test_no_blockers(self):
        blocked, reasons = check_blockers(
            {"summary": "all good", "top_themes": ["growth"]},
            {},
            {"environment": "favorable"},
            {"rsi": 55, "volume_zscore": 0.5, "volume_avg": 200000},
        )
        assert blocked is False
        assert len(reasons) == 0


class TestGEM:
    def test_all_conditions_met(self):
        from datetime import date, timedelta
        future_date = (date.today() + timedelta(days=15)).isoformat()
        is_gem, conditions = check_gem(
            score=88,
            grok_data={"label": "bullish", "confidence": 90},
            synthesis={
                "catalyst": "Earnings beat",
                "catalyst_date": future_date,
                "red_flags": [],
                "risk_reward_ratio": 4.0,
            },
        )
        assert is_gem is True
        assert all("[PASS]" in c for c in conditions)

    def test_score_too_low(self):
        is_gem, _ = check_gem(
            score=70,
            grok_data={"label": "bullish", "confidence": 90},
            synthesis={"catalyst": "test", "catalyst_date": "2025-05-01", "red_flags": [], "risk_reward_ratio": 4.0},
        )
        assert is_gem is False

    def test_red_flags_block(self):
        is_gem, _ = check_gem(
            score=90,
            grok_data={"label": "bullish", "confidence": 90},
            synthesis={"catalyst": "test", "catalyst_date": "2025-05-01", "red_flags": ["insider selling"], "risk_reward_ratio": 4.0},
        )
        assert is_gem is False


class TestStatus:
    def test_first_signal_confirmed(self):
        assert determine_status("BUY", 80, None) == "CONFIRMED"

    def test_cancelled(self):
        assert determine_status("AVOID", 40, {"action": "BUY", "score": 80}) == "CANCELLED"

    def test_weakening(self):
        assert determine_status("BUY", 60, {"action": "BUY", "score": 80}) == "WEAKENING"

    def test_upgraded(self):
        assert determine_status("BUY", 85, {"action": "HOLD", "score": 60}) == "UPGRADED"

    def test_confirmed_stable(self):
        assert determine_status("BUY", 78, {"action": "BUY", "score": 75}) == "CONFIRMED"
