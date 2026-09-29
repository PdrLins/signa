"""ai_status 'validated' requires Claude to actually say BUY.

Regression: validated only required confidence >= 50, so a confident
HOLD/AVOID from Claude still validated a score-driven BUY and the brain
auto-bought it.
"""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("DEBUG", "true")

import pytest

from app.core.config import settings
from app.services.scan_service import _classify_ai_status, _clean_p_win, _tech_only_action


def test_buy_with_high_confidence_is_validated():
    assert _classify_ai_status({"signal": "BUY", "confidence": 75}) == "validated"


def test_threshold_comes_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "ai_validated_min_confidence", 60)
    assert _classify_ai_status({"signal": "BUY", "confidence": 60}) == "validated"
    assert _classify_ai_status({"signal": "BUY", "confidence": 59}) == "low_confidence"


@pytest.mark.parametrize("sig", ["HOLD", "AVOID", "SELL", "", None])
def test_confident_non_buy_is_rejected_not_validated(sig):
    assert _classify_ai_status({"signal": sig, "confidence": 90}) == "rejected"


def test_old_threshold_50_no_longer_validates():
    assert _classify_ai_status({"signal": "BUY", "confidence": 55}) == "low_confidence"


def test_error_is_failed():
    assert _classify_ai_status({"error": "timeout", "signal": "BUY", "confidence": 80}) == "failed"


def test_zero_confidence_bad_parse_is_failed():
    assert _classify_ai_status({"signal": "BUY", "confidence": 0}) == "failed"
    assert _classify_ai_status({}) == "failed"


def test_lowercase_signal_accepted():
    assert _classify_ai_status({"signal": "buy", "confidence": 80}) == "validated"


def test_p_win_normalisation():
    assert _clean_p_win(0.62) == 0.62
    assert _clean_p_win(62) == 0.62
    assert _clean_p_win(-1) is None
    assert _clean_p_win("x") is None
    assert _clean_p_win(None) is None


class TestTechOnly:
    """Tech-only signals now run blockers (they used to skip them)."""

    def test_overbought_tech_only_is_avoid(self):
        action, reasons = _tech_only_action(80, "HIGH_RISK", {"rsi": 80}, {}, {})
        assert action == "AVOID"
        assert any("RSI" in r for r in reasons)

    def test_clean_tech_only_keeps_score_action(self):
        action, reasons = _tech_only_action(
            70, "HIGH_RISK", {"rsi": 55, "volume_avg": 1e6, "volume_zscore": 0.2}, {}, {},
        )
        assert action == "BUY" and reasons == []

    def test_tech_only_earnings_blackout_holds(self):
        action, reasons = _tech_only_action(
            70, "HIGH_RISK", {"rsi": 55}, {"trading_days_to_next_earnings": 1}, {},
        )
        assert action == "HOLD"
        assert "Earnings blackout" in reasons[0]


class TestTradeLevels:
    from app.services.scan_service import _resolve_trade_levels as _r
    _r = staticmethod(_r)

    def test_ai_levels_kept_and_rr_recomputed(self):
        t, s, rr, src = self._r(100, 2, 112, 96, 9.9)  # AI's rr ignored
        assert (t, s, rr, src) == (112, 96, 3.0, "ai")

    def test_missing_levels_filled_from_atr(self):
        t, s, rr, src = self._r(100, 2, None, None, None)
        assert (t, s, rr, src) == (108, 96, 2.0, "atr_fallback")

    def test_wrong_side_stop_replaced(self):
        t, s, rr, src = self._r(100, 2, 110, 101, None)
        assert s == 96 and t == 110 and rr == 2.5

    def test_no_atr_no_levels(self):
        assert self._r(100, None, None, None, None) == (None, None, None, "none")
