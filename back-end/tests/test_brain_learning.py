"""Behavioral tests: strict hypothesis matching, direction-aware outcomes,
and the n>=30 / interval evidence bar for graduating anything."""

from tests.brain_fakes import FakeDB, patch_db  # noqa: I001

import pytest

from app.services import virtual_portfolio as vp
from app.services.daily_learning import cohort_analyzer, hypothesis_manager, stats
from app.services.knowledge_events import OUTCOME_CONTRADICTING, OUTCOME_NEUTRAL, OUTCOME_SUPPORTING

TRADE = {"id": "t1", "symbol": "AAA", "bucket": "HIGH_RISK", "market_regime": "TRENDING",
         "signal_style": "MOMENTUM", "entry_tier": 1, "entry_score": 82, "direction": "LONG",
         "source": "brain", "entry_price": 100.0, "entry_date": "2026-09-01T14:00:00+00:00"}


class TestStrictMatching:
    @pytest.mark.parametrize("pm,expected", [
        ({"signal_style": "MOMENTUM"}, True),
        ({"signal_style": "NEUTRAL"}, False),
        ({"entry_tier": 1, "signal_style": "MOMENTUM"}, True),
        ({"entry_tier": 2}, False),
        ({"entry_score_min": 80, "entry_score_max": 84}, True),
        ({"entry_score_min": 85, "entry_score_max": 999}, False),
        ({"bucket": "HIGH_RISK", "signal_style": "MOMENTUM"}, True),
        ({"exit_reason": "STOP_HIT"}, True),
        ({"exit_reason": "TARGET_HIT"}, False),
        ({"exit_reason_family": "STOP"}, True),
        ({"exit_reason_family": "WATCHDOG"}, False),
        # unknown / descriptor keys no longer widen the match to everything
        ({"exit_reason_family": "STOP", "window_days": 14}, False),
        ({"signal_style": "MOMENTUM", "count_threshold": 3}, False),
        ({"new_cohorts": []}, False),
        ({}, False),
    ])
    def test_every_key_must_match(self, pm, expected):
        assert vp._trade_matches_pattern(TRADE, pm, "STOP_HIT") is expected

    def test_cohort_pattern_shapes_match_trades(self):
        pm = cohort_analyzer._build_crosstab_pattern_match("signal_style", "MOMENTUM", "score_band", "80-84")
        assert vp._trade_matches_pattern(TRADE, pm)
        pm = cohort_analyzer._build_pattern_match("signal_style", "UNCLASSIFIED")
        assert vp._trade_matches_pattern(dict(TRADE, signal_style=None), pm)

    def test_outcome_and_descriptor_patterns_do_not_become_hypotheses(self):
        assert hypothesis_manager._is_trade_predictive({"signal_style": "MOMENTUM", "entry_tier": 1})
        assert not hypothesis_manager._is_trade_predictive({"exit_reason": "STOP_HIT"})
        assert not hypothesis_manager._is_trade_predictive({"exit_reason_family": "WATCHDOG", "window_days": 14})


class TestObservationDirection:
    def test_underperform_hypothesis(self):
        assert vp._classify_observation("", -3.0, "loss") == OUTCOME_SUPPORTING
        assert vp._classify_observation("", 3.0, "loss") == OUTCOME_CONTRADICTING

    def test_overperform_hypothesis(self):
        assert vp._classify_observation("", 3.0, "win") == OUTCOME_SUPPORTING
        assert vp._classify_observation("", -3.0, "win") == OUTCOME_CONTRADICTING

    def test_direction_inferred_from_prediction_text(self):
        text = "Future trades matching {...} will OVER-perform (positive expectancy) unless invalidated."
        assert vp._classify_observation(text, 2.0) == OUTCOME_SUPPORTING
        assert vp._classify_observation("", 0.5, "win") == OUTCOME_NEUTRAL


class TestEvidenceBar:
    def test_small_samples_never_decide(self):
        v = stats.evidence_verdict([-5.0] * 29, "loss")
        assert v["verdict"] == "insufficient"

    def test_clear_negative_expectancy_supports_loss_hypothesis(self):
        pnls = [-3.0] * 24 + [2.0] * 8
        assert stats.evidence_verdict(pnls, "loss")["verdict"] == "supported"
        assert stats.evidence_verdict(pnls, "win")["verdict"] == "refuted"

    def test_noise_is_inconclusive(self):
        pnls = [2.0, -2.1] * 20
        assert stats.evidence_verdict(pnls, "loss")["verdict"] == "inconclusive"

    def test_wilson(self):
        lo, hi = stats.wilson_interval(4, 5)
        assert lo < 0.5 < hi  # 4/5 is not evidence

    def test_graduation_uses_matched_trade_pnls(self):
        events = [{"id": f"e{i}", "thinking_id": "h1", "event_type": "thinking_observation_added",
                   "payload": {"pnl_pct": p}} for i, p in enumerate([-3.0] * 25 + [1.5] * 7)]
        hyp = {"id": "h1", "status": "active", "hypothesis": "x", "prediction": "UNDER-perform",
               "pattern_match": {"signal_style": "MOMENTUM"}, "observations_supporting": 25,
               "observations_contradicting": 7, "graduation_threshold": 5, "expected_direction": "loss"}
        db = FakeDB({"signal_thinking": [hyp], "knowledge_events": events, "signal_knowledge": []})
        with patch_db(db), \
                pytest.MonkeyPatch.context() as mp:
            mp.setattr(hypothesis_manager, "get_client", lambda: db)
            out = hypothesis_manager.evaluate_active_hypotheses()
        assert [g["id"] for g in out["graduated"]] == ["h1"]
        (k,) = db.rows("signal_knowledge")
        assert "SUGGESTION ONLY" in k["explanation"]

    def test_graduation_threshold_floor_is_30(self):
        events = [{"id": f"e{i}", "thinking_id": "h1", "event_type": "thinking_observation_added",
                   "payload": {"pnl_pct": -3.0}} for i in range(10)]
        hyp = {"id": "h1", "status": "active", "prediction": "", "pattern_match": {"bucket": "X"},
               "graduation_threshold": 5, "expected_direction": "loss"}
        db = FakeDB({"signal_thinking": [hyp], "knowledge_events": events})
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(hypothesis_manager, "get_client", lambda: db)
            out = hypothesis_manager.evaluate_active_hypotheses()
        assert out == {"graduated": [], "rejected": [], "inconclusive": []}


class TestDirectionAwareOutcome:
    def test_short_outcome_sign(self):
        db = FakeDB({"trade_outcomes": []})
        from app.services import learning_service
        with patch_db(db):
            learning_service.record_outcome(
                signal_id=None, symbol="AAA", action="SHORT", score=30, bucket="HIGH_RISK",
                signal_date="2026-09-01", entry_price=100.0, exit_price=90.0, days_held=3,
                target_price=85.0, stop_loss=106.0,
            )
        (row,) = db.rows("trade_outcomes")
        assert row["pnl_pct"] == pytest.approx(10.0)
        assert row["signal_correct"] is True and row["hit_stop"] is False

    def test_brain_close_records_short_action(self):
        db = FakeDB({"trade_outcomes": [], "signal_thinking": []})
        trade = dict(TRADE, direction="SHORT")
        with patch_db(db):
            vp._record_brain_outcome(trade, 90.0, None, "TARGET_HIT", 9.5)
        (row,) = db.rows("trade_outcomes")
        assert row["action"] == "SHORT" and row["pnl_pct"] == pytest.approx(9.5)
