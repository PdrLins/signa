"""Unit tests for app.services.daily_learning.cohort_analyzer pure helpers.

DB-touching paths are NOT covered here (the orchestrator integration test
is the right place for that). These tests fence the math + dataclass +
threshold rules, so a future change to drift detection has a tripwire.
"""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("BRAIN_TOKEN_SECRET", "test-brain-secret-32chars-min-len-test")
os.environ.setdefault("AUTH_ENABLED", "false")

from app.services.daily_learning.cohort_analyzer import (  # noqa: E402
    CROSSTAB_PAIRS,
    CohortFinding,
    DRIFT_THRESHOLD,
    MIN_N_BASELINE,
    MIN_N_FOR_FLAG,
    SCORE_BANDS,
    WR_HIGH,
    WR_LOW,
    _aggregate_cell,
    _build_crosstab_pattern_match,
    _build_pattern_match,
    _classify_severity,
    _score_band,
)


class TestScoreBand:
    def test_below_lowest_band_returns_none(self):
        assert _score_band(60) is None
        assert _score_band(64) is None

    def test_inside_each_band(self):
        assert _score_band(65) == "65-69"
        assert _score_band(70) == "70-74"
        assert _score_band(75) == "75-79"
        assert _score_band(80) == "80-84"
        assert _score_band(85) == "85+"
        assert _score_band(100) == "85+"

    def test_none_input(self):
        assert _score_band(None) is None


class TestAggregateCell:
    def test_empty(self):
        assert _aggregate_cell([]) == (0, 0.0, 0.0)

    def test_all_wins(self):
        rows = [{"pnl_amount": 10}, {"pnl_amount": 20}]
        n, wr, net = _aggregate_cell(rows)
        assert n == 2
        assert wr == 1.0
        assert net == 30.0

    def test_mixed(self):
        rows = [
            {"pnl_amount": 10},
            {"pnl_amount": -5},
            {"pnl_amount": 7},
            {"pnl_amount": -3},
        ]
        n, wr, net = _aggregate_cell(rows)
        assert n == 4
        assert wr == 0.5
        assert net == 9.0

    def test_zero_pnl_treated_as_loss(self):
        # The function defines "win" as pnl > 0 strictly. Document that contract.
        rows = [{"pnl_amount": 0}, {"pnl_amount": 1}]
        _, wr, _ = _aggregate_cell(rows)
        assert wr == 0.5


class TestClassifySeverity:
    def test_critical_on_large_drift(self):
        assert _classify_severity(0.30, 0.50) == "CRITICAL"
        assert _classify_severity(-0.30, 0.50) == "CRITICAL"

    def test_critical_on_tail_winrate(self):
        # drift small but win rate at tail → still CRITICAL
        assert _classify_severity(0.05, 0.20) == "CRITICAL"
        assert _classify_severity(0.05, 0.85) == "CRITICAL"

    def test_warn_on_moderate_drift(self):
        assert _classify_severity(0.18, 0.45) == "WARN"

    def test_info_otherwise(self):
        assert _classify_severity(0.05, 0.50) == "INFO"


class TestBuildPatternMatch:
    def test_simple_dimension(self):
        pm = _build_pattern_match("signal_style", "MOMENTUM")
        assert pm == {"signal_style": "MOMENTUM"}

    def test_entry_tier(self):
        pm = _build_pattern_match("entry_tier", 1)
        assert pm == {"entry_tier": 1}

    def test_score_band_translated_to_range(self):
        # Score band labels are translated to a numeric range so the
        # pattern_match can be checked against a signal's entry_score
        # directly without a label lookup.
        pm = _build_pattern_match("score_band", "75-79")
        assert pm == {"entry_score_min": 75, "entry_score_max": 79}

    def test_score_band_85plus(self):
        pm = _build_pattern_match("score_band", "85+")
        assert pm == {"entry_score_min": 85, "entry_score_max": 999}

    def test_unknown_score_band_returns_empty(self):
        assert _build_pattern_match("score_band", "unknown") == {}


class TestCohortFinding:
    def test_headline_format(self):
        f = CohortFinding(
            dimension="signal_style",
            value="MOMENTUM",
            n_30d=17,
            wr_30d=0.29,
            n_90d=33,
            wr_90d=0.58,
            drift=-0.29,
            direction="under",
            net_pnl_30d=-60.53,
            severity="CRITICAL",
            pattern_match={"signal_style": "MOMENTUM"},
        )
        h = f.headline()
        assert "MOMENTUM" in h
        assert "n=17" in h
        assert "29%" in h
        assert "-29pp" in h
        assert "$-60.53" in h or "-60.53" in h

    def test_to_dict_roundtrips_fields(self):
        f = CohortFinding(
            dimension="entry_tier",
            value=1,
            n_30d=10,
            wr_30d=0.30,
            n_90d=20,
            wr_90d=0.55,
            drift=-0.25,
            direction="under",
            net_pnl_30d=-20.0,
            severity="CRITICAL",
            pattern_match={"entry_tier": 1},
        )
        d = f.to_dict()
        assert d["dimension"] == "entry_tier"
        assert d["value"] == "1"  # stringified for JSON safety
        assert d["n_30d"] == 10
        assert d["pattern_match"] == {"entry_tier": 1}
        assert d["severity"] == "CRITICAL"


class TestThresholdContracts:
    """Pin the threshold constants. Changing them should require a
    documented backtest per feedback_backtest_before_brain_changes."""

    def test_min_n_for_flag(self):
        assert MIN_N_FOR_FLAG == 5

    def test_min_n_baseline(self):
        assert MIN_N_BASELINE == 5

    def test_wr_tails(self):
        assert WR_LOW == 0.40
        assert WR_HIGH == 0.70

    def test_drift_threshold(self):
        assert DRIFT_THRESHOLD == 0.15

    def test_score_bands_cover_brain_floor(self):
        # BRAIN_MIN_SCORE=75 must fall in a band so admission-floor cohort
        # analysis works.
        assert _score_band(75) == "75-79"
        # And the bands together must cover 65..89 contiguously without gaps.
        boundaries = [(lo, hi) for _, lo, hi in SCORE_BANDS]
        for i in range(len(boundaries) - 1):
            assert boundaries[i][1] == boundaries[i + 1][0]


class TestCrossTab:
    """Cross-tab support (Day-55 addition). Tests the pattern_match
    builder and the curated-pair list contract."""

    def test_crosstab_pairs_is_curated_not_combinatorial(self):
        # Adding a pair without an operational reason is a smell. The
        # constant must stay small. C(5,2) = 10 — we cap at 5.
        assert len(CROSSTAB_PAIRS) <= 5

    def test_crosstab_pairs_contain_known_findings(self):
        # The Day-47 MOMENTUM tier-1 finding and Day-55 NEUTRAL ≥85
        # finding must be representable by SOME pair in the list.
        assert ("signal_style", "entry_tier") in CROSSTAB_PAIRS
        assert ("signal_style", "score_band") in CROSSTAB_PAIRS

    def test_crosstab_pattern_match_merges_two_dims(self):
        pm = _build_crosstab_pattern_match(
            "signal_style", "NEUTRAL", "score_band", "85+"
        )
        # Should combine both — the brain matches a signal that has
        # signal_style=NEUTRAL AND score in 85..999.
        assert pm["signal_style"] == "NEUTRAL"
        assert pm["entry_score_min"] == 85
        assert pm["entry_score_max"] == 999

    def test_crosstab_pattern_match_signal_style_x_entry_tier(self):
        # The Day-47 finding shape — must round-trip through pattern_match.
        pm = _build_crosstab_pattern_match(
            "signal_style", "MOMENTUM", "entry_tier", 1
        )
        assert pm == {"signal_style": "MOMENTUM", "entry_tier": 1}

    def test_crosstab_pattern_match_bucket_x_signal_style(self):
        pm = _build_crosstab_pattern_match(
            "bucket", "HIGH_RISK", "signal_style", "MOMENTUM"
        )
        assert pm == {"bucket": "HIGH_RISK", "signal_style": "MOMENTUM"}

    def test_crosstab_pattern_match_entry_tier_x_score_band(self):
        # The "high score + amplified" mechanism — captures the deep
        # cause behind both MOMENTUM and NEUTRAL caps.
        pm = _build_crosstab_pattern_match(
            "entry_tier", 1, "score_band", "85+"
        )
        assert pm["entry_tier"] == 1
        assert pm["entry_score_min"] == 85
