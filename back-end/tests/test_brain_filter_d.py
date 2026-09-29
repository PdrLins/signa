"""Filter D admission gates (Day 20) after the 2026-09 decision-quality reset.

Filter D (Fin/Industrials sector block + LONG-horizon suspension) was fit
on a 52-trade backtest where the excluded cohorts had n=9 and n=15. With
the brain's data reset and sizing/stops now principled, both gates are OFF
by default (`brain_filter_d_sectors_enabled`, `brain_long_horizon_suspended`).
The code is kept behind the flags; these tests pin both states. The
entry gate itself now requires an AI BUY (ai_status=validated AND
ai_signal=BUY) before anything else is considered.
"""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("DEBUG", "true")

from app.core.config import settings  # noqa: E402
from app.services.virtual_portfolio import (  # noqa: E402
    BRAIN_MIN_SCORE,
    FILTER_D_BLOCKED_SECTORS,
    _eval_brain_short_tier,
    _eval_brain_trust_tier,
)


def _long_sig(score: int, sector: str, ai_status: str = "validated", ai_signal: str = "BUY") -> dict:
    return {
        "score": score,
        "ai_status": ai_status,
        "ai_signal": ai_signal,
        "fundamental_data": {"sector": sector} if sector else {},
        "technical_data": {},
    }


def _short_sig(score: int, sector: str) -> dict:
    return {
        "score": score, "ai_status": "rejected", "ai_signal": "SELL", "action": "AVOID",
        "price_at_signal": 100.0, "target_price": 90.0, "stop_loss": 110.0,
        "fundamental_data": {"sector": sector} if sector else {},
    }


class TestDefaults:
    def test_brain_min_score_is_75(self):
        assert BRAIN_MIN_SCORE == 75

    def test_filter_d_gates_off_by_default(self):
        assert settings.brain_filter_d_sectors_enabled is False
        assert settings.brain_long_horizon_suspended is False

    def test_blocked_sector_list_still_pinned(self):
        assert FILTER_D_BLOCKED_SECTORS == frozenset({"Financial Services", "Industrials"})

    def test_financials_admitted_by_default(self):
        tier, mult, reason = _eval_brain_trust_tier(_long_sig(80, "Financial Services"))
        assert (tier, mult, reason) == (1, 1.0, "ai_buy")

    def test_shorts_disabled_by_default(self):
        tier, _, reason = _eval_brain_short_tier(_short_sig(30, "Technology"))
        assert tier == 0 and reason == "shorts_disabled"


class TestWhenReEnabled:
    def test_long_path_blocks_sector(self, monkeypatch):
        monkeypatch.setattr(settings, "brain_filter_d_sectors_enabled", True)
        tier, _, reason = _eval_brain_trust_tier(_long_sig(80, "Industrials"))
        assert tier == 0 and "filter_d_sector_excluded_industrials" == reason

    def test_short_path_blocks_sector(self, monkeypatch):
        monkeypatch.setattr(settings, "brain_filter_d_sectors_enabled", True)
        monkeypatch.setattr(settings, "brain_short_entries_enabled", True)
        tier, _, reason = _eval_brain_short_tier(_short_sig(30, "Financial Services"))
        assert tier == 0 and "sector_excluded" in reason
        tier, _, reason = _eval_brain_short_tier(_short_sig(30, "Technology"))
        assert tier == 1 and reason == "short_ai_bearish"


class TestOrdering:
    def test_ai_failed_reported_first(self):
        tier, _, reason = _eval_brain_trust_tier(_long_sig(80, "Financial Services", ai_status="failed"))
        assert tier == 0 and reason == "ai_failed"

    def test_non_ai_buy_rejected_before_any_sector_logic(self, monkeypatch):
        monkeypatch.setattr(settings, "brain_filter_d_sectors_enabled", True)
        tier, _, reason = _eval_brain_trust_tier(_long_sig(90, "Technology", ai_status="skipped", ai_signal=None))
        assert tier == 0 and reason.startswith("not_ai_buy")
