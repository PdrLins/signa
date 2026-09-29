"""claude_local picks exactly one path to Claude: CLI or API, never both."""

import asyncio
import types
import sys

import pytest

from app.ai import provider
from app.core.config import settings


class _Budget:
    async def can_call(self, *a):
        return True, "ok"

    async def record_call(self, *a, **k):
        pass


@pytest.fixture
def calls(monkeypatch):
    seen = []

    async def cli(*a, tier="routine", **k):
        seen.append(("cli", tier))
        return {"error": "cli down"}

    async def api(*a, tier="routine", **k):
        seen.append(("api", tier))
        return {"signal": "BUY", "confidence": 80}

    async def budget():
        return _Budget()

    monkeypatch.setattr(provider, "_get_budget", budget)
    monkeypatch.setitem(sys.modules, "app.ai.claude_local_client", types.SimpleNamespace(synthesize_signal=cli))
    monkeypatch.setitem(sys.modules, "app.ai.claude_client", types.SimpleNamespace(synthesize_signal=api))
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")
    monkeypatch.setattr(settings, "synthesis_providers", ["claude"])
    return seen


def _run(tier="routine"):
    return asyncio.run(provider._route_synthesis("ABC", {}, {}, {}, {}, tier))


def test_local_mode_never_calls_api_even_with_key(monkeypatch, calls):
    monkeypatch.setattr(settings, "claude_local", True)
    result = _run()
    assert ("api", "routine") not in calls
    assert calls == [("cli", "routine")]
    assert result.get("error") and result["_provider"] == "none"


def test_local_mode_decision_fails_instead_of_using_api(monkeypatch, calls):
    monkeypatch.setattr(settings, "claude_local", True)
    result = _run("decision")
    assert calls == [("cli", "decision")]
    assert result.get("error")


def test_api_mode_never_calls_cli(monkeypatch, calls):
    monkeypatch.setattr(settings, "claude_local", False)
    result = _run()
    assert calls == [("api", "routine")]
    assert result["_provider"] == "claude"
