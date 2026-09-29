"""compute_score enrichment contributions (+ disable switch) and the
red-flag materiality blocker matrix."""

import pytest

from app.ai.signal_engine import (
    ENRICHMENT_CAP,
    _score_enrichment,
    check_blockers,
    compute_score,
    red_flag_block_reason,
)
from app.core.config import settings

TECH = {"rsi": 58, "macd_histogram": 0.4, "atr": 2.0, "volume_zscore": 1.2,
        "momentum_3m": 18.0, "momentum_6m": 30.0}
BASE_FUND = {"eps_growth": 0.2, "revenue_growth": 0.1, "market_cap": 5e11, "sector": "Technology"}
GOOD = {
    "eps_revision_momentum": 6.0, "eps_revisions_up_30d": 8, "eps_revisions_down_30d": 1,
    "rs_benchmark": "XLK", "rs_benchmark_return_3m": 4.0, "rs_benchmark_return_6m": 10.0,
    "spy_return_3m": 3.0, "spy_return_6m": 8.0,
    "insider_net_shares_6m": 50_000, "insider_buy_count_6m": 3,
}
BAD = {
    "eps_revision_momentum": -8.0, "eps_revisions_up_30d": 0, "eps_revisions_down_30d": 6,
    "rs_benchmark": "XLK", "rs_benchmark_return_3m": 35.0, "rs_benchmark_return_6m": 50.0,
    "short_interest_change_pct": 40.0,
}


@pytest.fixture
def scoring_on(monkeypatch):
    monkeypatch.setattr(settings, "enrichment_scoring_enabled", True)


class TestEnrichmentScore:
    def test_positive_parts_and_cap(self):
        total, detail = _score_enrichment(GOOD, TECH)
        # revisions: +2 (>=5%) +1 (net +7) = 3; RS avg (14+20)/2=17 → +2; insider +1
        assert detail == {"revisions": 3.0, "relative_strength": 2.0, "insider_buying": 1.0}
        assert total == ENRICHMENT_CAP  # 6 capped at 5

    def test_negative_parts(self):
        total, detail = _score_enrichment(BAD, TECH)
        # revisions -2 -1 = -3; RS avg (-17,-20) → -2; short +40% → -1
        assert detail == {"revisions": -3.0, "relative_strength": -2.0, "short_interest": -1.0}
        assert total == -ENRICHMENT_CAP

    def test_missing_data_is_neutral(self):
        assert _score_enrichment({}, {}) == (0.0, {})
        assert _score_enrichment(None, None) == (0.0, {})

    def test_rs_falls_back_to_spy(self):
        _, detail = _score_enrichment({"spy_return_3m": 2.0, "spy_return_6m": 2.0},
                                      {"momentum_3m": 7.0, "momentum_6m": 7.0})
        assert detail == {"relative_strength": 1.0}

    def test_insider_selling_not_penalized(self):
        _, detail = _score_enrichment({"insider_net_shares_6m": -1_000_000, "insider_buy_count_6m": 0}, {})
        assert detail == {}

    @pytest.mark.parametrize("bucket", ["HIGH_RISK", "SAFE_INCOME"])
    def test_compute_score_adds_bonus(self, scoring_on, bucket):
        base, bd0 = compute_score(TECH, BASE_FUND, {}, {}, {}, bucket)
        good, bd1 = compute_score(TECH, {**BASE_FUND, **GOOD}, {}, {}, {}, bucket)
        bad, bd2 = compute_score(TECH, {**BASE_FUND, **BAD}, {}, {}, {}, bucket)
        assert bd0["enrichment_bonus"] == 0
        assert bd1["enrichment_bonus"] == 5 and bd1["enrichment_detail"]
        assert bd2["enrichment_bonus"] == -5
        assert good - base in (4, 5, 6)  # rounding of the base total
        assert base - bad in (4, 5, 6)

    def test_disable_switch(self, monkeypatch):
        monkeypatch.setattr(settings, "enrichment_scoring_enabled", False)
        base, _ = compute_score(TECH, BASE_FUND, {}, {}, {}, "HIGH_RISK")
        good, bd = compute_score(TECH, {**BASE_FUND, **GOOD}, {}, {}, {}, "HIGH_RISK")
        assert good == base
        assert bd["enrichment_bonus"] == 0
        assert "enrichment_detail" not in bd

    def test_not_applied_to_etf_or_crypto(self, scoring_on):
        for asset in ("ETF", "CRYPTO"):
            _, bd = compute_score(TECH, {**BASE_FUND, **GOOD}, {}, {}, {}, "HIGH_RISK", "TRENDING", asset)
            assert bd["enrichment_bonus"] == 0

    def test_backward_compatible_positional_call(self):
        # Backtest calls with the original 6-8 positional args.
        score, bd = compute_score({}, {}, {}, {}, {}, "HIGH_RISK")
        assert isinstance(score, int) and "enrichment_bonus" in bd


# ── Red-flag materiality ───────────────────────────────────────────

AAPL_CAP = 5e12
URL = "https://www.reuters.com/legal/x"


def _grok(*flags, **kw):
    return {"confidence": 70, "error": None, "red_flags": list(flags), **kw}


class TestRedFlagMatrix:
    def test_aapl_patent_verdict_does_not_block(self):
        # $5.7B patent verdict at a ~$5T company — immaterial.
        for sev in ("low", "medium"):
            flag = {"text": "Jury orders Apple to pay $5.7B in patent lawsuit", "url": URL,
                    "category": "litigation", "severity": sev, "estimated_impact_usd": 5.7e9}
            blocked, _ = check_blockers(_grok(flag), {"market_cap": AAPL_CAP}, {}, {})
            assert blocked is False
        # Even if the model over-rates it "high", the stated impact is 0.11% of cap.
        flag = {"text": "Jury orders Apple to pay $5.7B in patent lawsuit", "url": URL,
                "category": "litigation", "severity": "high", "estimated_impact_usd": 5.7e9}
        blocked, _ = check_blockers(_grok(flag), {"market_cap": AAPL_CAP}, {}, {})
        assert blocked is False

    def test_legacy_lawsuit_flag_without_severity_does_not_block(self):
        flag = {"text": "Jury orders Apple to pay $5.7B in patent lawsuit", "url": URL}
        blocked, _ = check_blockers(_grok(flag), {"market_cap": AAPL_CAP}, {}, {})
        assert blocked is False

    def test_cited_high_severity_fraud_blocks(self):
        flag = {"text": "SEC charges company with accounting fraud", "url": URL,
                "category": "fraud", "severity": "high"}
        blocked, reasons = check_blockers(_grok(flag), {"market_cap": 2e9}, {}, {})
        assert blocked is True
        assert "fraud" in reasons[0].lower()

    def test_uncited_never_blocks(self):
        for flag in (
            {"text": "SEC charges company with fraud", "category": "fraud", "severity": "critical"},
            {"text": "SEC charges company with fraud", "url": "", "severity": "critical"},
            {"text": "ponzi scheme alleged"},
        ):
            blocked, _ = check_blockers(_grok(flag), {}, {}, {})
            assert blocked is False
        # Uncited summary text never counts either.
        blocked, _ = check_blockers({"confidence": 70, "summary": "fraud ponzi scam"}, {}, {}, {})
        assert blocked is False

    @pytest.mark.parametrize("category,severity,impact,cap,expected", [
        # integrity categories block from medium up
        ("fraud", "low", None, None, False),
        ("fraud", "medium", None, None, True),
        ("accounting", "medium", None, None, True),
        ("going_concern", "medium", None, None, True),
        # integrity categories ignore the materiality fraction
        ("accounting", "high", 1e6, 1e12, True),
        # other categories need high/critical
        ("litigation", "low", None, None, False),
        ("litigation", "medium", None, None, False),
        ("regulatory", "medium", None, None, False),
        ("litigation", "high", None, None, True),
        ("regulatory", "critical", None, None, True),
        ("other", "high", None, 1e12, True),              # no stated impact
        ("litigation", "high", 5e9, None, True),          # no market cap
        ("litigation", "high", 5e9, 1e11, True),          # 5% of cap — material
        ("litigation", "critical", 5e8, 1e11, False),     # 0.5% of cap — immaterial
    ])
    def test_matrix(self, category, severity, impact, cap, expected):
        flag = {"text": "Issue", "url": URL, "category": category, "severity": severity}
        if impact is not None:
            flag["estimated_impact_usd"] = impact
        assert (red_flag_block_reason(flag, cap) is not None) is expected

    @pytest.mark.parametrize("text,expected", [
        ("SEC investigation opened", True),
        ("Insider trading charges filed", True),
        ("Alleged Ponzi scheme", True),
        ("Class action lawsuit filed", False),
        ("Delisting notice received", False),
    ])
    def test_legacy_keyword_fallback(self, text, expected):
        assert (red_flag_block_reason({"text": text, "url": URL}) is not None) is expected

    def test_failed_sentiment_contributes_nothing(self):
        flag = {"text": "fraud", "url": URL, "category": "fraud", "severity": "critical"}
        blocked, _ = check_blockers({"error": "timeout", "confidence": 0, "red_flags": [flag]}, {}, {}, {})
        assert blocked is False
