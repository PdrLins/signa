"""Market mood: Grok first, Claude (local CLI + WebSearch only) as fallback."""

import asyncio

from app.ai import claude_local_client, macro_pulse
from app.core.config import settings


def test_cli_args_enable_only_named_tools():
    plain = claude_local_client.build_cli_args()
    assert plain[plain.index("--tools") + 1] == "" and "--allowedTools" not in plain
    web = claude_local_client.build_cli_args(tools=("WebSearch",))
    assert web[web.index("--tools") + 1] == "WebSearch"
    assert web[web.index("--allowedTools") + 1] == "WebSearch"
    assert "--strict-mcp-config" in web


def test_build_claude_pulse_keeps_only_sourced_trends():
    data = {"trends": [
        {"topic": "BoC holds rates", "impact": "NEUTRAL", "sectors": "banks", "sources": ["https://example.com/boc"]},
        {"topic": "No source", "impact": "BULLISH", "sources": []},
        {"topic": "Bad url", "impact": "BEARISH", "sources": ["javascript:alert(1)"]},
        {"topic": "Chips rally", "impact": "BULLISH", "sources": ["https://example.com/chips"]},
    ]}
    r = macro_pulse.build_claude_pulse(data)
    assert [t["topic"] for t in r["trends"]] == ["BoC holds rates", "Chips rally"]
    assert r["source"] == "claude" and r["citations"] == ["https://example.com/boc", "https://example.com/chips"]
    assert "error" not in r
    assert macro_pulse.build_claude_pulse({"trends": [{"topic": "x", "impact": "BULLISH", "sources": []}]})["error"]
    assert macro_pulse.build_claude_pulse(None)["error"]


def _run(monkeypatch, grok, claude, local=True):
    macro_pulse._pulse_cache.clear()
    monkeypatch.setattr(settings, "claude_local", local)
    monkeypatch.setattr(settings, "macro_pulse_claude_fallback", True)
    calls = []

    async def fake_grok():
        calls.append("grok")
        return grok

    async def fake_claude():
        calls.append("claude")
        return claude

    monkeypatch.setattr(macro_pulse, "_grok_pulse", fake_grok)
    monkeypatch.setattr(macro_pulse, "_claude_pulse", fake_claude)
    return asyncio.run(macro_pulse.get_macro_pulse()), calls


def test_falls_back_to_claude_when_grok_fails(monkeypatch):
    ok = {"trends": [{"topic": "t"}], "summary": "Mixed market news", "citations": ["https://x"], "source": "claude"}
    r, calls = _run(monkeypatch, macro_pulse._unavailable("no credit"), ok)
    assert calls == ["grok", "claude"] and r["source"] == "claude"
    assert macro_pulse._pulse_cache.get("pulse") == r  # cached


def test_grok_success_skips_claude(monkeypatch):
    ok = {"trends": [{"topic": "t"}], "summary": "s", "citations": ["https://x"], "source": "grok"}
    r, calls = _run(monkeypatch, ok, None)
    assert calls == ["grok"] and r["source"] == "grok"


def test_no_fallback_without_local_claude_and_nothing_cached(monkeypatch):
    r, calls = _run(monkeypatch, macro_pulse._unavailable("no credit"), None, local=False)
    assert calls == ["grok"] and r["error"]
    assert macro_pulse._pulse_cache.get("pulse") is None
