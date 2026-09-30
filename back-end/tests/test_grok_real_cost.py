"""Real Grok cost: parsed from usage.cost_in_usd_ticks and fed to the budget."""

import asyncio

import pytest

from app.ai.grok_client import extract_cost_usd
from app.services import budget_service as bs


def test_extract_cost_usd():
    assert extract_cost_usd({"usage": {"cost_in_usd_ticks": 350_000_000}}) == pytest.approx(0.035)
    assert extract_cost_usd({"usage": {"input_tokens": 10}}) is None
    assert extract_cost_usd({}) is None
    assert extract_cost_usd({"usage": {"cost_in_usd_ticks": "bad"}}) is None


@pytest.fixture
def budget(monkeypatch):
    b = bs.BudgetService()
    b._initialized = True

    class _NoDB:
        def table(self, *_):
            raise RuntimeError("no db in tests")

    monkeypatch.setattr("app.db.supabase.get_client", lambda: _NoDB())
    return b


def test_real_cost_recorded_and_replaces_estimate(budget):
    assert budget.estimate_cost("grok", "sentiment") == bs.COST_ESTIMATES["grok"]["sentiment"]
    asyncio.run(budget.record_call("grok", "sentiment", "AAA", cost_usd=0.04))
    asyncio.run(budget.record_call("grok", "sentiment", "BBB", cost_usd=0.06))
    assert budget.get_daily_spend("grok") == pytest.approx(0.10)
    assert budget.estimate_cost("grok", "sentiment") == pytest.approx(0.05)
    # No reported cost -> the running estimate is charged.
    asyncio.run(budget.record_call("grok", "sentiment", "CCC"))
    assert budget.get_daily_spend("grok") == pytest.approx(0.15)


def test_reservations_count_calls_not_dollars(budget):
    asyncio.run(budget.reserve("grok", "sentiment"))
    assert budget._pending_locked("grok") == pytest.approx(0.15)
    # Estimate drops while the call is in flight: release still clears it.
    asyncio.run(budget.record_call("grok", "sentiment", "AAA", cost_usd=0.02))
    asyncio.run(budget.release("grok", "sentiment"))
    assert budget._pending_locked("grok") == 0
    asyncio.run(budget.release("grok", "sentiment"))  # extra release is harmless
    assert budget._reserved_calls[("grok", "sentiment")] == 0


def test_local_providers_stay_free(budget):
    asyncio.run(budget.record_call("claude-local", "synthesis", "AAA", cost_usd=1.0))
    assert budget.get_daily_spend("claude-local") == 0


def test_out_of_credits_pauses_grok(monkeypatch):
    from app.ai import grok_client as g
    monkeypatch.setattr(g, "_account_blocked_until", None)
    g._note_account_error(403, '{"code":"permission-denied","error":"used all available credits"}')
    assert "console.x.ai" in (g.account_block() or "")
    r = asyncio.run(g.analyze_sentiment("MSFT"))
    assert r["error"] and r["_cost_usd"] == 0.0
    g._note_account_error(429, "rate limited")  # not an account error: no change
    monkeypatch.setattr(g, "_account_blocked_until", None)
    assert g.account_block() is None
