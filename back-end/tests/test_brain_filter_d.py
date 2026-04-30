"""Regression tests for Filter D admission gates (Day 20).

Filter D is the historical winner from the 52-trade backtest:
    Score >= 75 + SHORT horizon + drop Financial Services / Industrials sectors

These tests pin the gate behavior so a future refactor of the tier
evaluators can't silently re-admit blocked sectors or re-enable the
LONG horizon. Each test is ~3 lines plus a fixture — fast unit-level
checks that don't require Supabase or real signal data.
"""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("DEBUG", "true")

from app.services.virtual_portfolio import (
    BRAIN_MIN_SCORE,
    FILTER_D_BLOCKED_SECTORS,
    _eval_brain_short_tier,
    _eval_brain_trust_tier,
)


def _long_sig(score: int, sector: str, ai_status: str = "validated") -> dict:
    return {
        "score": score,
        "ai_status": ai_status,
        "fundamental_data": {"sector": sector} if sector else {},
        "technical_data": {},
    }


def _short_sig(score: int, sector: str) -> dict:
    return {
        "score": score,
        "ai_status": "validated",
        "action": "AVOID",
        "price_at_signal": 100.0,
        "target_price": 90.0,
        "stop_loss": 110.0,
        "fundamental_data": {"sector": sector} if sector else {},
    }


class TestBrainMinScore:
    def test_brain_min_score_is_75(self):
        # Pinned at 75 after the Day-20 rollback. If raised, the docstring
        # invalidation criterion (75-79 cohort win rate < 35% across n>=15
        # wallet-era trades) must be documented in the bump commit.
        assert BRAIN_MIN_SCORE == 75


class TestFilterDSectorExclusion:
    def test_blocked_sectors_are_pinned(self):
        # Day-20 ship: only Financial Services + Industrials are blocked.
        # Adding new sectors needs both backtest evidence + an updated
        # docstring with invalidation criteria.
        assert FILTER_D_BLOCKED_SECTORS == frozenset(
            {"Financial Services", "Industrials"}
        )

    def test_long_path_blocks_financial_services(self):
        tier, _, reason = _eval_brain_trust_tier(_long_sig(80, "Financial Services"))
        assert tier == 0
        assert "filter_d_sector_excluded" in reason
        assert "financial_services" in reason

    def test_long_path_blocks_industrials(self):
        tier, _, reason = _eval_brain_trust_tier(_long_sig(80, "Industrials"))
        assert tier == 0
        assert "filter_d_sector_excluded" in reason
        assert "industrials" in reason

    def test_long_path_admits_technology_at_min_score(self):
        # Tech sector at the new BRAIN_MIN_SCORE floor must reach Tier 1.
        # If this fails, the gate ordering is wrong (sector check must
        # be AFTER ai_failed but BEFORE the score-tier branches).
        tier, mult, reason = _eval_brain_trust_tier(_long_sig(75, "Technology"))
        assert tier == 1
        assert mult == 1.0
        assert reason == "validated"

    def test_long_path_admits_when_sector_missing(self):
        # Yahoo's fundamental_data.sector can be missing for some tickers.
        # We must NOT block on missing data — that would silently kill
        # entries that the gate has no opinion on.
        tier, _, _ = _eval_brain_trust_tier(_long_sig(80, ""))
        assert tier == 1

    def test_short_path_blocks_financial_services(self):
        # brain_short_max_score is 40 — use score 30 so the score check
        # passes and we exercise the Filter D check.
        tier, _, reason = _eval_brain_short_tier(_short_sig(30, "Financial Services"))
        assert tier == 0
        assert "sector_excluded" in reason

    def test_short_path_admits_technology(self):
        tier, _, reason = _eval_brain_short_tier(_short_sig(30, "Technology"))
        assert tier == 1
        assert reason == "short_validated_bearish"


class TestFilterDOrderingInvariants:
    def test_ai_failed_check_runs_before_sector_check(self):
        # ai_failed is a transient retry signal — it must NOT consume the
        # filter_d_sector_excluded reason slot, otherwise the retry queue
        # logic (which keys off "ai_failed") breaks.
        sig = _long_sig(80, "Financial Services", ai_status="failed")
        tier, _, reason = _eval_brain_trust_tier(sig)
        assert tier == 0
        assert reason == "ai_failed"

    def test_sector_check_runs_before_portfolio_heat(self):
        # Portfolio heat gating returns "portfolio_locked" / etc.
        # Filter D is a stronger structural signal — a Fin sector entry
        # should report sector_excluded, not heat. If this flips, the
        # operator can't tell why the entry was rejected.
        sig = _long_sig(80, "Financial Services")
        tier, _, reason = _eval_brain_trust_tier(sig, portfolio_heat=3)
        assert tier == 0
        assert "filter_d_sector_excluded" in reason
