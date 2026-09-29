"""2026-09 knowledge audit follow-ups:

- the synthesis prompt reads ONE curated knowledge set (PROMPT_CORE)
- scoring no longer boosts RECOVERY or high short interest, and no longer
  invents a "probability of beating SPY"
- approving a learning suggestion never pretends to change a rule
"""

from tests.brain_fakes import FakeDB  # noqa: I001  (sets test env vars first)

import asyncio
import inspect
from unittest.mock import patch

import pytest

from app.ai import signal_engine
from app.services import knowledge_service as ks_mod
from app.services import learning_service
from app.services.knowledge_service import (
    PROMPT_KNOWLEDGE_CONCEPTS,
    KnowledgeService,
    build_prompt_core_rows,
)

OLD_PROMPT_CONCEPTS = ("score_ranges_and_actions", "backtest_key_findings", "gem_conditions",
                       "bubble_detection_framework", "contrarian_sentiment_in_commodities",
                       "supply_deficit_asymmetry")


@pytest.fixture(autouse=True)
def _clear_cache():
    ks_mod.invalidate_cache()
    yield
    ks_mod.invalidate_cache()


def _block(db: FakeDB) -> str:
    with patch("app.services.knowledge_service.get_client", return_value=db):
        return asyncio.run(KnowledgeService().get_prompt_knowledge_block())


class TestPromptKnowledge:
    def test_rows_are_short_and_cover_the_five_topics(self):
        rows = build_prompt_core_rows()
        assert [r["key_concept"] for r in rows] == PROMPT_KNOWLEDGE_CONCEPTS
        assert all(r["topic"] == "PROMPT_CORE" and r["source_type"] == "curated_2026_09" for r in rows)
        # ~300-450 tokens at ~4 chars/token (was ~6,000 chars / 1,500 tokens)
        assert sum(len(r["explanation"]) for r in rows) < 1900

    def test_enforced_row_uses_live_settings(self):
        text = {r["key_concept"]: r["explanation"] for r in build_prompt_core_rows()}["prompt_enforced_by_code"]
        with patch.object(ks_mod.settings, "brain_min_rr", 3.0):
            text3 = {r["key_concept"]: r["explanation"] for r in build_prompt_core_rows()}["prompt_enforced_by_code"]
        assert "reward:risk >= 2 " in text and "reward:risk >= 3 " in text3

    def test_falls_back_to_builtin_text_and_never_uses_old_rows(self):
        # DB has only the old stale rows (script not run yet): the prompt must
        # still be the curated set, in order, and none of the old concepts.
        db = FakeDB({"signal_knowledge": [
            {"id": c, "key_concept": c, "topic": "SCORING", "explanation": "STALE", "is_active": True}
            for c in OLD_PROMPT_CONCEPTS
        ], "signal_thinking": []})
        block = _block(db)
        positions = [block.index(f"## {c}") for c in PROMPT_KNOWLEDGE_CONCEPTS]
        assert positions == sorted(positions)
        assert "STALE" not in block
        assert not any(c in block for c in OLD_PROMPT_CONCEPTS)

    def test_db_text_wins_when_row_is_active(self):
        db = FakeDB({"signal_knowledge": [
            {"id": "x", "key_concept": "prompt_horizon", "topic": "PROMPT_CORE",
             "explanation": "EDITED IN BRAIN EDITOR", "is_active": True},
        ], "signal_thinking": []})
        assert "EDITED IN BRAIN EDITOR" in _block(db)

    def test_scan_service_uses_the_single_source(self):
        from app.services import scan_service
        src = inspect.getsource(scan_service)
        assert "get_prompt_knowledge_block()" in src
        assert "score_ranges_and_actions" not in src


def _hr_inputs(short_float=None):
    tech = {"rsi": 60, "macd_histogram": 0.5, "atr": 2.0, "vs_sma50": 3.0, "vs_sma200": 10.0,
            "volume_zscore": 1.2, "momentum_5d": 2.0}
    fund = {"short_percent_of_float": short_float} if short_float is not None else {}
    return tech, fund


class TestScoringFixes:
    def test_recovery_has_no_high_risk_boost(self):
        # Was x1.10: rebounds from deep drawdowns are when momentum crashes.
        tech, fund = _hr_inputs()
        trending, _ = signal_engine.compute_score(tech, fund, {}, {}, {}, "HIGH_RISK", "TRENDING")
        recovery, bd = signal_engine.compute_score(tech, fund, {}, {}, {}, "HIGH_RISK", "RECOVERY")
        assert recovery == trending
        assert not bd.get("regime_adjustment_applied")

    def test_high_short_interest_adds_nothing(self):
        # Was up to +20: high short interest predicts LOWER returns.
        tech, fund = _hr_inputs()
        base, _ = signal_engine.compute_score(tech, fund, {}, {}, {}, "HIGH_RISK")
        tech2, fund2 = _hr_inputs(short_float=0.30)
        squeezed, bd = signal_engine.compute_score(tech2, fund2, {}, {}, {}, "HIGH_RISK")
        assert squeezed <= base
        assert "short_squeeze_bonus" not in bd
        assert not hasattr(signal_engine, "_score_short_squeeze")

    def test_probability_vs_spy_is_not_invented(self):
        # The old table claimed 45-68%; 2021-2026 data: ~40% beat SPY in every band.
        for score in (30, 60, 85):
            assert signal_engine.compute_probability_vs_spy(score, "HIGH_RISK", has_ai=True) is None


class TestSuggestionApprovalIsHonest:
    def _db(self, status="APPROVED"):
        return FakeDB({
            "brain_suggestions": [{"id": "s1", "status": status, "suggestion_type": "MODIFY_RULE",
                                   "rule_id": "r1", "rule_name": "rsi_overbought_blocker",
                                   "proposed_value": {"threshold_max": 80}}],
            "investment_rules": [{"id": "r1", "name": "rsi_overbought_blocker", "threshold_max": 75}],
        })

    @pytest.mark.parametrize("status", ["PENDING", "APPROVED"])
    def test_records_approval_and_changes_no_rule(self, status):
        db = self._db(status)
        with patch("app.services.learning_service.get_client", return_value=db), \
             patch("app.services.knowledge_service.get_client", return_value=db):
            out = learning_service.apply_suggestion("s1", "user-1")
        assert out["requires_code_change"] is True and out["applied"] is False
        assert "requires code/config change" in out["message"]
        assert db.ops("investment_rules", "update") == []
        assert db.rows("investment_rules")[0]["threshold_max"] == 75
        sug = db.rows("brain_suggestions")[0]
        assert sug["status"] == "APPROVED" and sug["reviewed_by"] == "user-1"

    def test_rejected_cannot_be_approved(self):
        db = self._db("REJECTED")
        with patch("app.services.learning_service.get_client", return_value=db):
            assert "error" in learning_service.apply_suggestion("s1", "user-1")
        assert db.ops("brain_suggestions", "update") == []

    def test_weekly_prompt_shows_live_thresholds_not_investment_rules(self):
        db = FakeDB({
            "trade_outcomes": [{"symbol": "AAA", "action": "BUY", "score": 70, "pnl_pct": 1.0,
                                "days_held": 3, "signal_correct": True, "bucket": "HIGH_RISK",
                                "signal_date": "2099-01-01T00:00:00+00:00"}],
            "investment_rules": [{"id": "r1", "name": "momentum_trap", "is_active": True, "rule_type": "TECHNICAL"}],
            "signal_knowledge": [], "brain_suggestions": [],
        })
        captured = {}

        async def _claude(prompt, schema, label="", tier="routine"):
            captured["prompt"] = prompt
            return {"suggestions": []}

        with patch("app.services.learning_service.get_client", return_value=db), \
             patch("app.services.knowledge_service.get_client", return_value=db), \
             patch("app.ai.provider.claude_structured", _claude):
            asyncio.run(learning_service.run_weekly_analysis(period_days=7))
        prompt = captured["prompt"]
        assert "CURRENT INVESTMENT RULES" not in prompt and "momentum_trap" not in prompt
        assert "LIVE THRESHOLDS" in prompt and "tech_filter_max_rsi=75" in prompt
        assert "## prompt_evidence_2021_2026" in prompt
