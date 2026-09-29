"""Claude API + CLI clients: structured output, retry on bad JSON, CLI isolation."""

import asyncio
import json
from types import SimpleNamespace

from app.ai import claude_client, claude_local_client
from app.ai.prompts import SYNTHESIS_JSON_SCHEMA

VALID = {
    "signal": "BUY", "confidence": 72, "p_win": 0.58, "reasoning": "r",
    "risk_factors": [], "catalyst": None, "catalyst_date": None, "red_flags": [],
    "target_price": 120.0, "stop_loss": 95.0, "sentiment_weight": 20,
    "self_check": {"reasoning_supports_signal": True, "contains_wait_instruction": False,
                   "contains_bearish_descriptors": False, "self_check_notes": "ok"},
}


def _msg(text: str, stop_reason: str = "end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
    )


class _FakeBetaMessages:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.replies.pop(0)


def _install_fake(monkeypatch, replies):
    fake = _FakeBetaMessages(replies)
    client = SimpleNamespace(beta=SimpleNamespace(messages=fake))
    monkeypatch.setattr(claude_client, "_client", client)
    return fake


def test_api_retries_once_on_bad_json_then_succeeds(monkeypatch):
    fake = _install_fake(monkeypatch, [_msg("not json at all"), _msg(json.dumps(VALID))])
    r = asyncio.run(claude_client.synthesize_signal("ACME", {"current_price": 100}, {}, {}, {}))
    assert r["error"] is None
    assert r["signal"] == "BUY"
    assert r["risk_reward_ratio"] == 4.0  # reward 20 / risk 5, computed in code
    assert len(fake.calls) == 2
    call = fake.calls[0]
    assert call["output_config"]["format"] == {"type": "json_schema", "schema": SYNTHESIS_JSON_SCHEMA}
    assert call["thinking"] == {"type": "adaptive"}
    assert call["model"] == claude_client.settings.claude_model


def test_api_gives_up_after_second_bad_json(monkeypatch):
    fake = _install_fake(monkeypatch, [_msg("nope"), _msg("{still nope")])
    r = asyncio.run(claude_client.synthesize_signal("ACME", {"current_price": 100}, {}, {}, {}))
    assert r["error"]
    assert r["confidence"] == 0
    assert len(fake.calls) == 2


def test_api_missing_signal_is_failure(monkeypatch):
    bad = dict(VALID)
    bad.pop("signal")
    _install_fake(monkeypatch, [_msg(json.dumps(bad)), _msg(json.dumps(bad))])
    r = asyncio.run(claude_client.synthesize_signal("ACME", {"current_price": 100}, {}, {}, {}))
    assert r["error"] and r["confidence"] == 0


def test_cli_args_are_pinned_and_isolated():
    args = claude_local_client.build_cli_args(SYNTHESIS_JSON_SCHEMA)
    assert args[:2] == ["claude", "-p"]
    assert "hello" not in args
    assert args[args.index("--model") + 1] == claude_local_client.settings.claude_model
    assert args[args.index("--output-format") + 1] == "json"
    assert args[args.index("--tools") + 1] == ""
    assert json.loads(args[args.index("--json-schema") + 1]) == SYNTHESIS_JSON_SCHEMA


def test_cli_envelope_parsing():
    env = {"type": "result", "is_error": False, "result": "x", "structured_output": {"signal": "HOLD"}}
    assert claude_local_client.parse_cli_output(json.dumps(env)) == {"signal": "HOLD"}
    env2 = {"type": "result", "is_error": False, "result": 'Sure: {"signal": "AVOID"} done'}
    assert claude_local_client.parse_cli_output(json.dumps(env2)) == {"signal": "AVOID"}


def test_cli_runs_in_empty_temp_dir(monkeypatch):
    captured = {}

    class _Proc:
        returncode = 0

        async def communicate(self, input=None):
            captured["stdin"] = input
            env = {"type": "result", "is_error": False, "result": "", "structured_output": VALID}
            return json.dumps(env).encode(), b""

    async def _fake_exec(*args, **kwargs):
        captured["args"] = args
        captured["cwd"] = kwargs.get("cwd")
        import os
        captured["listing"] = os.listdir(kwargs["cwd"])
        return _Proc()

    monkeypatch.setattr(claude_local_client.asyncio, "create_subprocess_exec", _fake_exec)
    r = asyncio.run(claude_local_client.synthesize_signal("ACME", {"current_price": 100}, {}, {}, {}))
    assert r["error"] is None and r["signal"] == "BUY"
    assert captured["listing"] == []
    assert "back-end" not in captured["cwd"]
    assert b"ACME" in captured["stdin"]
    assert not any("ACME" in a for a in captured["args"])
