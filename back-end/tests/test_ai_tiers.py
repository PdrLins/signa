"""Routine (Sonnet) vs decision (Opus) tiers, BUY escalation, and AI caches."""

import asyncio

import pytest

from app.ai import claude_client, claude_local_client, provider
from app.core.config import settings
from app.services import scan_service


@pytest.fixture(autouse=True)
def _fresh_caches(monkeypatch):
    provider.clear_ai_caches()
    monkeypatch.setattr(settings, "synthesis_cache_hours", 3)
    monkeypatch.setattr(settings, "synthesis_cache_max_move_pct", 2.0)
    monkeypatch.setattr(settings, "sentiment_cache_hours", 24)
    yield
    provider.clear_ai_caches()


def test_model_for_tier():
    assert claude_client.model_for_tier("routine") == (settings.claude_model, settings.claude_effort)
    assert claude_client.model_for_tier("decision") == (
        settings.claude_decision_model, settings.claude_decision_effort,
    )


def test_defaults_are_sonnet_routine_opus_decision():
    assert settings.claude_model == "claude-sonnet-5-5"
    assert settings.claude_decision_model == "claude-opus-5-5"


def test_cli_args_pick_model_by_tier():
    routine = claude_local_client.build_cli_args(None)
    decision = claude_local_client.build_cli_args(None, tier="decision")
    assert routine[routine.index("--model") + 1] == settings.claude_model
    assert decision[decision.index("--model") + 1] == settings.claude_decision_model


def _stub_router(monkeypatch, results):
    calls = []

    async def fake_route(ticker, tech, fund, macro, grok, tier):
        calls.append(tier)
        return dict(results[tier])

    monkeypatch.setattr(provider, "_route_synthesis", fake_route)
    return calls


def _synth(price, tier="routine"):
    return asyncio.run(provider.synthesize_signal(
        "ABC", {"current_price": price}, {}, {}, {}, tier=tier,
    ))


def test_synthesis_cached_until_price_moves(monkeypatch):
    calls = _stub_router(monkeypatch, {"routine": {"signal": "HOLD", "confidence": 70}})
    _synth(100.0)
    assert _synth(101.5)["_cached"] is True      # +1.5% — reuse
    assert calls == ["routine"]
    assert "_cached" not in _synth(103.0)         # +3% — re-ask
    assert calls == ["routine", "routine"]


def test_errors_are_not_cached(monkeypatch):
    calls = _stub_router(monkeypatch, {"routine": {"error": "down", "confidence": 0}})
    _synth(100.0)
    _synth(100.0)
    assert calls == ["routine", "routine"]


def test_decision_tier_has_its_own_cache(monkeypatch):
    calls = _stub_router(monkeypatch, {
        "routine": {"signal": "BUY", "confidence": 80},
        "decision": {"signal": "HOLD", "confidence": 70},
    })
    _synth(100.0)
    assert _synth(100.0, tier="decision")["signal"] == "HOLD"
    assert _synth(100.0, tier="decision")["_cached"] is True
    assert calls == ["routine", "decision"]


def test_sentiment_cached_per_ticker(monkeypatch):
    calls = []

    async def fake_route(ticker, market_cap=None):
        calls.append(ticker)
        return {"score": 60, "confidence": 0.8}

    monkeypatch.setattr(provider, "_route_sentiment", fake_route)
    asyncio.run(provider.analyze_sentiment("ABC"))
    assert asyncio.run(provider.analyze_sentiment("ABC"))["_cached"] is True
    asyncio.run(provider.analyze_sentiment("XYZ"))
    assert calls == ["ABC", "XYZ"]


def _escalate(monkeypatch, routine, decision):
    seen = []

    async def fake_synth(*args, tier="routine", **kwargs):
        seen.append(tier)
        return dict(decision)

    monkeypatch.setattr(scan_service.ai_provider, "synthesize_signal", fake_synth)
    result = asyncio.run(scan_service._confirm_buy_with_decision_model("ABC", routine, {}, {}, {}, {}))
    return result, seen


def test_routine_buy_escalates_and_decision_overrides(monkeypatch):
    monkeypatch.setattr(settings, "ai_decision_escalation", True)
    result, seen = _escalate(
        monkeypatch, {"signal": "BUY", "confidence": 80}, {"signal": "HOLD", "confidence": 75},
    )
    assert seen == ["decision"]
    assert scan_service._classify_ai_status(result) == "rejected"
    assert result["_routine_signal"] == "BUY"


def test_confirmed_buy_stays_validated(monkeypatch):
    monkeypatch.setattr(settings, "ai_decision_escalation", True)
    result, _ = _escalate(
        monkeypatch, {"signal": "BUY", "confidence": 80}, {"signal": "BUY", "confidence": 72},
    )
    assert scan_service._classify_ai_status(result) == "validated"


def test_non_buy_never_escalates(monkeypatch):
    monkeypatch.setattr(settings, "ai_decision_escalation", True)
    result, seen = _escalate(
        monkeypatch, {"signal": "HOLD", "confidence": 80}, {"signal": "BUY", "confidence": 90},
    )
    assert seen == []
    assert result["signal"] == "HOLD"


def test_unavailable_decision_caps_to_low_confidence(monkeypatch):
    monkeypatch.setattr(settings, "ai_decision_escalation", True)
    result, _ = _escalate(
        monkeypatch, {"signal": "BUY", "confidence": 80}, {"error": "budget", "confidence": 0},
    )
    assert scan_service._classify_ai_status(result) == "low_confidence"


def test_escalation_can_be_disabled(monkeypatch):
    monkeypatch.setattr(settings, "ai_decision_escalation", False)
    result, seen = _escalate(
        monkeypatch, {"signal": "BUY", "confidence": 80}, {"signal": "HOLD", "confidence": 90},
    )
    assert seen == []
    assert scan_service._classify_ai_status(result) == "validated"


def test_market_cap_reaches_sentiment_provider(monkeypatch):
    seen = []

    async def fake_route(ticker, market_cap=None):
        seen.append(market_cap)
        return {"score": 60, "confidence": 0.8}

    monkeypatch.setattr(provider, "_route_sentiment", fake_route)
    asyncio.run(provider.analyze_sentiment("ABC", market_cap=5e12))
    assert seen == [5e12]
