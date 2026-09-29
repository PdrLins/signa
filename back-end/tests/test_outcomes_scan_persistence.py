"""scan_service persists routine_ai_signal / decision_overturned (migration 008)."""

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
BUY = {
    "signal": "BUY", "confidence": 80, "reasoning": "ok", "catalyst": "product launch",
    "target_price": 112.0, "stop_loss": 96.0, "risk_reward_ratio": 3.0, "p_win": 0.58,
    "_provider": "claude_local", "self_check": {"_present": True, "reasoning_supports_signal": True},
}


# ── pure helper ─────────────────────────────────────────────────

def test_audit_fields_not_escalated():
    assert scan_service._decision_audit_fields({"signal": "HOLD"}) == {
        "routine_ai_signal": "HOLD", "decision_overturned": None}
    assert scan_service._decision_audit_fields({}) == {
        "routine_ai_signal": None, "decision_overturned": None}


def test_audit_fields_confirmed_and_overturned():
    confirmed = {"signal": "BUY", "_routine_signal": "BUY", "_decision": "confirmed"}
    vetoed = {"signal": "HOLD", "_routine_signal": "BUY", "_decision": "confirmed"}
    assert scan_service._decision_audit_fields(confirmed) == {
        "routine_ai_signal": "BUY", "decision_overturned": False}
    assert scan_service._decision_audit_fields(vetoed) == {
        "routine_ai_signal": "BUY", "decision_overturned": True}


def test_audit_fields_decision_unavailable():
    out = scan_service._decision_audit_fields({"signal": "BUY", "_decision": "unavailable"})
    assert out == {"routine_ai_signal": "BUY", "decision_overturned": None}


# ── end-to-end through _process_candidate ───────────────────────

@pytest.fixture
def run(monkeypatch):
    from app.services import ai_retry_queue, pattern_stats

    monkeypatch.setattr(ai_retry_queue, "record_failure", lambda *a, **k: None)
    monkeypatch.setattr(ai_retry_queue, "clear_success", lambda *a, **k: None)
    monkeypatch.setattr(pattern_stats, "get_pattern_warning", lambda *a, **k: "")
    monkeypatch.setattr(scan_service.settings, "ai_decision_escalation", True)

    async def _opts(_t):
        return None
    monkeypatch.setattr(scan_service.barchart_scanner, "get_options_flow", _opts)

    async def _sent(_t, market_cap=None, **_kw):
        return {"score": 80, "label": "bullish", "confidence": 70, "mention_count": 300,
                "citations": [], "red_flags": [], "top_themes": []}
    monkeypatch.setattr(scan_service.ai_provider, "analyze_sentiment", _sent)

    def _go(routine: dict, decision: dict | None):
        async def _synth(*a, tier=None, **k):
            if tier == "decision":
                return dict(decision)
            return dict(routine)
        monkeypatch.setattr(scan_service.ai_provider, "synthesize_signal", _synth)
        pre = {"price_df": None, "fundamental_data": {}, "technical_data": dict(TECH),
               "bucket": "HIGH_RISK", "asset_class": "STOCK"}
        return asyncio.run(scan_service._process_candidate(
            "ZZTEST", {"environment": "favorable", "vix": 14}, {}, {}, "scan-1",
            asyncio.Semaphore(1), asyncio.Semaphore(1), "TRENDING", "", set(), pre,
        ))
    return _go


def test_decision_veto_persisted(run):
    sig = run(BUY, {**BUY, "signal": "HOLD", "_provider": "claude_decision"})
    assert sig["ai_signal"] == "HOLD"
    assert sig["routine_ai_signal"] == "BUY"
    assert sig["decision_overturned"] is True
    assert sig["grok_data"]["_decision"] == "confirmed"


def test_decision_confirm_persisted(run):
    sig = run(BUY, dict(BUY))
    assert sig["ai_signal"] == "BUY"
    assert sig["routine_ai_signal"] == "BUY"
    assert sig["decision_overturned"] is False


def test_routine_hold_not_escalated(run):
    sig = run({**BUY, "signal": "HOLD"}, None)
    assert sig["routine_ai_signal"] == "HOLD"
    assert sig["decision_overturned"] is None


def test_decision_unavailable_persisted(run):
    sig = run(BUY, {"error": "timeout"})
    assert sig["routine_ai_signal"] == "BUY"
    assert sig["decision_overturned"] is None
    assert sig["grok_data"]["_decision"] == "unavailable"


# ── insert fallback when migration 008 isn't applied ────────────

def test_persist_signals_retries_without_new_columns(monkeypatch):
    calls = []

    def fake_insert(rows):
        calls.append(rows)
        if any("routine_ai_signal" in r for r in rows):
            raise RuntimeError("Could not find the 'routine_ai_signal' column of 'signals'")
        return rows
    monkeypatch.setattr(scan_service.queries, "insert_signals_batch", fake_insert)
    rows = [{"symbol": "A", "routine_ai_signal": "BUY", "decision_overturned": False}]
    out = scan_service._persist_signals(rows)
    assert len(calls) == 2
    assert out == [{"symbol": "A"}]


def test_persist_signals_reraises_unrelated_errors(monkeypatch):
    def boom(rows):
        raise RuntimeError("connection reset")
    monkeypatch.setattr(scan_service.queries, "insert_signals_batch", boom)
    with pytest.raises(RuntimeError):
        scan_service._persist_signals([{"symbol": "A"}])
