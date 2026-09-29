"""Local CLI calls are $0 and never part of the paid month total."""

import asyncio

from app.services import budget_service, insights_service as svc


def test_breakdown_orders_paid_then_local_and_zeroes_local():
    rows = {"grok": {"calls": 588, "cost_usd": 5.81}, "claude": {"calls": 416, "cost_usd": 4.99},
            "claude-local": {"calls": 45, "cost_usd": 0.9}, "codex-cli": {"calls": 2}}
    out = svc.ai_usage_breakdown(rows)
    assert [r["provider"] for r in out] == ["grok", "claude", "claude-local", "codex-cli"]
    assert out[0] == {"provider": "grok", "calls": 588, "cost_usd": 5.81, "local": False}
    assert all(r["cost_usd"] == 0.0 for r in out if r["local"])


def test_openai_shown_only_when_used():
    assert "openai" not in [r["provider"] for r in svc.ai_usage_breakdown({})]
    assert "openai" in [r["provider"] for r in svc.ai_usage_breakdown({"openai": {"calls": 1, "cost_usd": 0.05}})]


def test_local_calls_cost_nothing_and_stay_out_of_summary(monkeypatch):
    monkeypatch.setattr(budget_service.BudgetService, "_load_from_db", lambda self: asyncio.sleep(0))
    b = budget_service.BudgetService()
    b._initialized = True
    monkeypatch.setattr(b, "_persist", lambda *a, **k: None, raising=False)
    asyncio.run(b.record_call("claude-local", "synthesis", "ABC"))
    asyncio.run(b.record_call("codex-cli", "review", "ABC"))
    assert b.get_monthly_spend("claude-local") == 0.0 and b.get_monthly_spend("codex-cli") == 0.0
    summary = b.get_budget_summary()
    assert "claude-local" not in summary["providers"] and "codex-cli" not in summary["providers"]
