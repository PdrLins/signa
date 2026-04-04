"""Tests for backtest scorer — scoring helpers and main functions."""

from backtest.engine.scorer import (
    _score_dividend,
    _score_macd,
    _score_momentum,
    _score_rsi_risk,
    _score_rsi_safe,
    _score_trend,
    _score_volume_risk,
    _score_volume_safe,
    check_gem_conditions,
    determine_signal,
    score_high_risk,
    score_safe_income,
)


# ============================================================
# RSI SCORING
# ============================================================

class TestRSISafe:
    def test_deep_oversold(self):
        assert _score_rsi_safe(25) == 90.0

    def test_moderate_oversold(self):
        assert _score_rsi_safe(35) == 80.0

    def test_ideal_entry(self):
        assert _score_rsi_safe(45) == 70.0

    def test_neutral(self):
        assert _score_rsi_safe(55) == 60.0

    def test_overbought(self):
        assert _score_rsi_safe(75) == 20.0


class TestRSIRisk:
    def test_falling_knife(self):
        assert _score_rsi_risk(25) == 30.0

    def test_sweet_spot(self):
        assert _score_rsi_risk(58) == 80.0

    def test_getting_hot(self):
        assert _score_rsi_risk(70) == 50.0

    def test_overbought(self):
        assert _score_rsi_risk(80) == 20.0


# ============================================================
# MACD SCORING
# ============================================================

class TestMACD:
    def test_strong_bullish(self):
        assert _score_macd(2.0, 1.0, 3.0) == 90.0

    def test_moderate_bullish(self):
        assert _score_macd(2.0, 1.0, 1.0) == 75.0

    def test_weak_bullish(self):
        assert _score_macd(1.5, 1.0, 0.2) == 65.0

    def test_turning_bullish(self):
        assert _score_macd(0.5, 1.0, 0.3) == 45.0

    def test_mildly_bearish(self):
        assert _score_macd(0.5, 1.0, -0.3) == 30.0

    def test_strong_bearish(self):
        assert _score_macd(0.5, 1.0, -1.0) == 15.0


# ============================================================
# TREND SCORING
# ============================================================

class TestTrend:
    def test_strong_uptrend(self):
        score = _score_trend(0.05, 0.20)
        assert score >= 85

    def test_moderate_uptrend(self):
        score = _score_trend(0.02, 0.08)
        assert 65 <= score <= 85

    def test_downtrend(self):
        score = _score_trend(-0.05, -0.10)
        assert score <= 20

    def test_none_values(self):
        score = _score_trend(None, None)
        assert score <= 45  # Slight downtrend with zero values


# ============================================================
# VOLUME SCORING
# ============================================================

class TestVolume:
    def test_safe_low_volume_wins(self):
        assert _score_volume_safe(0.6) >= 70

    def test_safe_high_volume_bad(self):
        assert _score_volume_safe(2.0) <= 35

    def test_risk_needs_volume(self):
        assert _score_volume_risk(1.5) >= 70

    def test_risk_no_volume_bad(self):
        assert _score_volume_risk(0.5) <= 30

    def test_none_handling(self):
        assert _score_volume_safe(None) == 55.0
        assert _score_volume_risk(None) == 40.0


# ============================================================
# DIVIDEND SCORING
# ============================================================

class TestDividend:
    def test_high_yield(self):
        assert _score_dividend(0.09) == 100.0

    def test_moderate_yield(self):
        assert _score_dividend(0.04) == 60.0

    def test_no_yield(self):
        assert _score_dividend(0) == 0.0

    def test_none(self):
        assert _score_dividend(None) == 0.0


# ============================================================
# MOMENTUM SCORING
# ============================================================

class TestMomentum:
    def test_sweet_spot(self):
        score = _score_momentum(0.02, 0.05)
        assert score >= 70

    def test_overextended_trap(self):
        score = _score_momentum(0.06, 0.10)
        assert score <= 50

    def test_bounce_opportunity(self):
        score = _score_momentum(-0.02, 0.03)
        assert score >= 65

    def test_falling_hard(self):
        score = _score_momentum(-0.05, -0.08)
        assert score <= 40


# ============================================================
# MAIN SCORING FUNCTIONS
# ============================================================

class TestScoreSafeIncome:
    def test_returns_dict(self, sample_indicators, sample_fundamentals_safe, sample_macro):
        result = score_safe_income(sample_indicators, sample_fundamentals_safe, sample_macro)
        assert "total_score" in result
        assert "bucket" in result
        assert "components" in result
        assert result["bucket"] == "SAFE_INCOME"

    def test_score_in_range(self, sample_indicators, sample_fundamentals_safe, sample_macro):
        result = score_safe_income(sample_indicators, sample_fundamentals_safe, sample_macro)
        assert 0 <= result["total_score"] <= 100

    def test_components_present(self, sample_indicators, sample_fundamentals_safe, sample_macro):
        result = score_safe_income(sample_indicators, sample_fundamentals_safe, sample_macro)
        components = result["components"]
        assert "dividend" in components
        assert "fundamental" in components
        assert "macro" in components
        assert "technical" in components


class TestScoreHighRisk:
    def test_returns_dict(self, sample_indicators, sample_fundamentals_risk, sample_macro):
        result = score_high_risk(sample_indicators, sample_fundamentals_risk, sample_macro)
        assert result["bucket"] == "HIGH_RISK"
        assert 0 <= result["total_score"] <= 100

    def test_components_present(self, sample_indicators, sample_fundamentals_risk, sample_macro):
        result = score_high_risk(sample_indicators, sample_fundamentals_risk, sample_macro)
        components = result["components"]
        assert "trend_macd" in components
        assert "momentum" in components
        assert "fundamental" in components
        assert "macro" in components


# ============================================================
# SIGNAL DETERMINATION
# ============================================================

class TestDetermineSignal:
    def test_buy(self):
        assert determine_signal(70) == "BUY"

    def test_hold(self):
        assert determine_signal(55) == "HOLD"

    def test_avoid(self):
        assert determine_signal(40) == "AVOID"

    def test_ceiling_safe_income(self):
        assert determine_signal(71, "SAFE_INCOME") == "HOLD"

    def test_ceiling_high_risk(self):
        assert determine_signal(73, "HIGH_RISK") == "HOLD"

    def test_custom_thresholds(self):
        assert determine_signal(60, "", {"buy": 60, "hold": 40, "ceiling": 80}) == "BUY"


# ============================================================
# GEM CONDITIONS
# ============================================================

class TestGEM:
    def test_all_conditions_met(self, sample_indicators):
        indicators = {**sample_indicators, "rsi": 55, "macd_line": 2.0, "macd_signal": 0.5, "macd_hist": 2.5, "vs_sma200": 0.10, "volume_ratio": 1.5}
        score_result = {"total_score": 80}
        is_gem, reason = check_gem_conditions(score_result, indicators, {})
        assert is_gem is True
        assert reason is not None

    def test_score_too_low(self, sample_indicators):
        score_result = {"total_score": 70}
        is_gem, reason = check_gem_conditions(score_result, sample_indicators, {})
        assert is_gem is False

    def test_rsi_out_of_range(self, sample_indicators):
        indicators = {**sample_indicators, "rsi": 75, "macd_line": 2.0, "macd_signal": 0.5, "macd_hist": 2.5, "vs_sma200": 0.10}
        score_result = {"total_score": 80}
        is_gem, reason = check_gem_conditions(score_result, indicators, {})
        assert is_gem is False
