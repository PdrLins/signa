"""Budget days follow ET; scans are Grok-first with the daily Grok budget
reserved in candidate-rank order; a missing Grok result is retried once
before the decision model; missing sentiment is labelled a data gap."""

import asyncio
from datetime import datetime, timezone

from app.ai import prompts
from app.core.config import settings
from app.services import budget_service, scan_service


# ── 1. Budget day boundary is US/Eastern ─────────────────────────────

def test_evening_et_usage_counts_for_same_et_day():
    # 01:46 UTC on Sep 29 = 21:46 ET on Sep 28
    assert budget_service._et_day_month("2026-09-29T01:46:44.423+00:00") == ("2026-09-28", "2026-09")


def test_month_boundary_in_et():
    # 02:00 UTC Oct 1 is still Sep 30 in ET
    assert budget_service._et_day_month("2026-10-01T02:00:00+00:00") == ("2026-09-30", "2026-09")


def test_bad_timestamp_falls_back():
    assert budget_service._et_day_month("not-a-date") == ("not-a-date", "not-a-d")


def test_skipped_sentiment_not_upgraded(monkeypatch):
    gd = {"_skipped": True, "summary": "Sentiment skipped for Safe Income"}
    assert _run_upgrade(monkeypatch, gd, {"_provider": "grok"}) == []


def test_skipped_sentiment_prompt_text():
    text = prompts.format_sentiment({"_skipped": True, "confidence": 0, "summary": "Sentiment skipped for Safe Income"})
    assert "not used" in text and "UNAVAILABLE" not in text


# ── 2. Grok retried before the decision model when it was missing ────

def _run_upgrade(monkeypatch, grok_data, fresh, enabled=True):
    calls = []

    async def fake_sent(ticker, market_cap=None, **kw):
        calls.append(kw)
        return dict(fresh)

    monkeypatch.setattr(settings, "scan_grok_on_buy", enabled)
    monkeypatch.setattr(scan_service.ai_provider, "analyze_sentiment", fake_sent)
    asyncio.run(scan_service._upgrade_sentiment_for_decision("ABC", {"market_cap": 1e9}, grok_data))
    return calls


def test_missing_sentiment_upgraded_to_grok_keeping_context(monkeypatch):
    gd = {"_provider": "none", "error": "Grok daily budget used", "score": 50, "_market_regime": "TRENDING", "_knowledge_block": "kb"}
    calls = _run_upgrade(monkeypatch, gd, {"_provider": "grok", "score": 70, "citations": ["x"], "confidence": 80})
    assert calls == [{}]                       # default = Grok-first path
    assert gd["_provider"] == "grok" and gd["score"] == 70
    assert gd["_market_regime"] == "TRENDING" and gd["_knowledge_block"] == "kb"


def test_existing_grok_not_refetched(monkeypatch):
    gd = {"_provider": "grok", "score": 60}
    assert _run_upgrade(monkeypatch, gd, {"_provider": "grok"}) == []


def test_grok_failure_keeps_original(monkeypatch):
    gd = {"_provider": "none", "error": "x", "score": 50}
    _run_upgrade(monkeypatch, gd, {"error": "budget", "_provider": "none"})
    assert gd == {"_provider": "none", "error": "x", "score": 50}


def test_upgrade_can_be_disabled(monkeypatch):
    gd = {"_provider": "none", "error": "x"}
    assert _run_upgrade(monkeypatch, gd, {"_provider": "grok"}, enabled=False) == []


def test_upgrade_runs_only_for_validated_buys(monkeypatch):
    seen = []

    async def fake_upgrade(*a, **k):
        seen.append(1)

    async def fake_synth(*a, tier="routine", **k):
        return {"signal": "BUY", "confidence": 80}

    monkeypatch.setattr(settings, "ai_decision_escalation", True)
    monkeypatch.setattr(scan_service, "_upgrade_sentiment_for_decision", fake_upgrade)
    monkeypatch.setattr(scan_service.ai_provider, "synthesize_signal", fake_synth)
    asyncio.run(scan_service._confirm_buy_with_decision_model("ABC", {"signal": "HOLD", "confidence": 90}, {}, {}, {}, {}))
    assert seen == []
    asyncio.run(scan_service._confirm_buy_with_decision_model("ABC", {"signal": "BUY", "confidence": 80}, {}, {}, {}, {}))
    assert seen == [1]


# ── 3. Missing sentiment is a data gap, not a signal ─────────────────

def test_missing_sentiment_labelled_unknown():
    text = prompts.format_sentiment({"error": "All providers failed or budget exceeded", "confidence": 0})
    assert "UNAVAILABLE" in text and "UNKNOWN" in text and "not a signal" in text
