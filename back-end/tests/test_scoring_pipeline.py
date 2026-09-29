"""End-to-end PASS-2 candidate processing with all I/O stubbed.

Pins the decision rules at the call site: AI HOLD never yields a BUY,
the contrarian bypass is gone, the earnings blackout holds, and the AI
verdict columns are written.
"""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("DEBUG", "true")

import asyncio

import pytest

from app.services import scan_service


TECH = {
    "current_price": 100.0, "atr": 2.0, "rsi": 58, "macd_histogram": 0.8,
    "macd_hist_atr": 0.4, "volume_zscore": 1.5, "volume_avg": 2_000_000,
    "sma_cross": "golden_cross", "momentum_3m": 20, "momentum_6m": 25, "adx": 32,
    "vs_sma200": 10,
}


@pytest.fixture
def run(monkeypatch):
    from app.services import ai_retry_queue, pattern_stats

    monkeypatch.setattr(ai_retry_queue, "record_failure", lambda *a, **k: None)
    monkeypatch.setattr(ai_retry_queue, "clear_success", lambda *a, **k: None)
    monkeypatch.setattr(pattern_stats, "get_pattern_warning", lambda *a, **k: "")

    async def _opts(_t):
        return None
    monkeypatch.setattr(scan_service.barchart_scanner, "get_options_flow", _opts)

    async def _sent(_t, market_cap=None):
        return {"score": 80, "label": "bullish", "confidence": 70, "mention_count": 300,
                "citations": ["https://x.com/a/status/1"], "red_flags": [], "top_themes": []}
    monkeypatch.setattr(scan_service.ai_provider, "analyze_sentiment", _sent)

    def _go(synthesis, fundamentals=None, tech=None):
        async def _synth(*a, **k):
            return dict(synthesis)
        monkeypatch.setattr(scan_service.ai_provider, "synthesize_signal", _synth)
        pre = {
            "price_df": None,
            "fundamental_data": dict(fundamentals or {}),
            "technical_data": dict(tech or TECH),
            "bucket": "HIGH_RISK",
            "asset_class": "STOCK",
        }
        return asyncio.run(scan_service._process_candidate(
            "ZZTEST", {"environment": "favorable", "vix": 14}, {}, {}, "scan-1",
            asyncio.Semaphore(1), asyncio.Semaphore(1), "TRENDING", "", set(), pre,
        ))
    return _go


BUY_SYNTH = {
    "signal": "BUY", "confidence": 80, "reasoning": "ok", "catalyst": "product launch",
    "target_price": 112.0, "stop_loss": 96.0, "risk_reward_ratio": 3.0, "p_win": 0.58,
    "_provider": "claude_local", "self_check": {"_present": True, "reasoning_supports_signal": True},
}


def test_validated_buy_records_verdict_columns(run):
    sig = run(BUY_SYNTH)
    assert sig["score"] >= 65, sig["score"]
    assert sig["action"] == "BUY"
    assert sig["ai_status"] == "validated"
    assert sig["ai_signal"] == "BUY"
    assert sig["ai_provider"] == "claude_local"
    assert sig["p_win"] == 0.58
    assert sig["risk_reward"] == 3.0
    assert sig["sentiment_citations"] == 1


def test_confident_ai_hold_downgrades_score_buy(run):
    sig = run({**BUY_SYNTH, "signal": "HOLD", "confidence": 85})
    assert sig["ai_status"] == "rejected"
    assert sig["action"] == "HOLD"
    assert sig["ai_signal"] == "HOLD"


def test_earnings_blackout_holds_validated_buy(run):
    sig = run(BUY_SYNTH, fundamentals={"trading_days_to_next_earnings": 2,
                                        "next_earnings_date": "2026-10-01"})
    assert sig["ai_status"] == "validated"
    assert sig["action"] == "HOLD"
    assert "Earnings blackout" in sig["reasoning"]


def test_missing_ai_levels_filled_from_atr(run):
    sig = run({**BUY_SYNTH, "target_price": None, "stop_loss": None, "risk_reward_ratio": None})
    assert sig["stop_loss"] == 96.0 and sig["target_price"] == 108.0
    assert sig["risk_reward"] == 2.0


def test_contrarian_setup_does_not_bypass_threshold(run):
    # Beaten-down, oversold, volume, MACD turning: 4/4 contrarian. Old code
    # made this BUY at score >= 55 regardless of the 65 HIGH_RISK bar.
    tech = {"current_price": 50.0, "atr": 1.5, "rsi": 38, "macd_histogram": 0.05,
            "macd_hist_atr": 0.03, "volume_ratio": 1.6, "vs_sma200": -20,
            "volume_avg": 1_000_000, "volume_zscore": 0.5}
    sig = run({**BUY_SYNTH, "catalyst": None, "target_price": 55, "stop_loss": 47},
              tech=tech)
    assert sig["signal_style"] == "CONTRARIAN"
    if sig["score"] < 65:
        assert sig["action"] != "BUY"
