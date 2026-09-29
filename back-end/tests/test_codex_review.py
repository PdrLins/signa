"""Codex second opinion: CLI argv, availability detection, parsing /
normalization, record vs veto vs off in _confirm_buy_with_decision_model,
errors never block, Grok budget reserved in candidate-rank order.
Subprocess / SDK / budget are all mocked — no live AI calls."""

import asyncio
import json
import os
import types

import pytest

from app.ai import codex_client
from app.core.config import settings
from app.services import scan_service


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    codex_client.clear_caches()
    monkeypatch.setattr(settings, "codex_enabled", True)
    monkeypatch.setattr(settings, "codex_local", True)
    monkeypatch.setattr(settings, "codex_model", "")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "codex_decision_mode", "record")
    yield
    codex_client.clear_caches()


# ── CLI argv ────────────────────────────────────────────────────────

def test_cli_args_read_only_stdin_schema_and_output_file():
    args = codex_client.build_cli_args("/tmp/w", "/tmp/schema.json", "/tmp/out.txt", binary="codex")
    assert args[:3] == ["codex", "exec", "-"]                    # prompt on stdin
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert args[args.index("--cd") + 1] == "/tmp/w"
    assert args[args.index("--output-schema") + 1] == "/tmp/schema.json"
    assert args[args.index("-o") + 1] == "/tmp/out.txt"
    for flag in ("--skip-git-repo-check", "--ephemeral", "--ignore-user-config", "--ignore-rules"):
        assert flag in args
    assert not any("dangerously" in a for a in args)
    assert "-m" not in args                                      # empty CODEX_MODEL = CLI default


def test_cli_args_model_when_set(monkeypatch):
    monkeypatch.setattr(settings, "codex_model", "some-model")
    args = codex_client.build_cli_args("/w", "/s", "/o")
    assert args[args.index("-m") + 1] == "some-model"


class _Proc:
    def __init__(self, rc=0, stdout=b"", stderr=b"", on_run=None, hang=False):
        self.returncode = None
        self._rc, self._out, self._err, self._on_run, self._hang = rc, stdout, stderr, on_run, hang
        self.stdin_data = None
        self.killed = False

    async def communicate(self, input=None):
        self.stdin_data = input
        if self._hang:
            await asyncio.sleep(10)
        if self._on_run:
            self._on_run()
        self.returncode = self._rc
        return self._out, self._err

    def kill(self):
        self.killed = True
        self.returncode = -9

    async def wait(self):
        return self.returncode


def test_run_cli_writes_schema_passes_prompt_on_stdin_and_reads_o_file(monkeypatch):
    seen = {}
    answer = {"signal": "HOLD", "confidence": 55, "p_win": 0.5, "reasoning": "r", "key_risks": []}

    async def fake_exec(*args, **kw):
        seen["args"], seen["kw"] = list(args), kw
        out_path = args[args.index("-o") + 1]
        schema_path = args[args.index("--output-schema") + 1]
        seen["schema"] = json.load(open(schema_path))
        seen["cd_empty"] = os.listdir(args[args.index("--cd") + 1]) == []

        def write():
            with open(out_path, "w") as f:
                f.write(json.dumps(answer))
        proc = _Proc(on_run=write, stdout=b"noise")
        seen["proc"] = proc
        return proc

    monkeypatch.setattr(codex_client.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(codex_client.shutil, "which", lambda name: "/usr/bin/codex")
    data = asyncio.run(codex_client._run_cli("PROMPT TEXT"))
    assert data == answer
    assert seen["proc"].stdin_data == b"PROMPT TEXT"
    assert "PROMPT TEXT" not in " ".join(seen["args"])            # never in argv
    assert seen["schema"] == codex_client.CODEX_REVIEW_SCHEMA and seen["cd_empty"]
    assert seen["kw"]["cwd"] == seen["args"][seen["args"].index("--cd") + 1]
    assert not os.path.exists(os.path.dirname(seen["args"][seen["args"].index("-o") + 1]))  # temp dir removed


def test_run_cli_falls_back_to_stdout(monkeypatch):
    async def fake_exec(*args, **kw):
        return _Proc(stdout=b'{"signal": "BUY", "confidence": 70}')
    monkeypatch.setattr(codex_client.asyncio, "create_subprocess_exec", fake_exec)
    assert asyncio.run(codex_client._run_cli("p"))["signal"] == "BUY"


def test_run_cli_timeout_kills_process(monkeypatch):
    procs = []

    async def fake_exec(*args, **kw):
        procs.append(_Proc(hang=True))
        return procs[-1]
    monkeypatch.setattr(codex_client.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(settings, "codex_timeout_s", 0.05)
    with pytest.raises(TimeoutError):
        asyncio.run(codex_client._run_cli("p"))
    assert procs[0].killed


# ── availability ────────────────────────────────────────────────────

def _login(monkeypatch, which, rc=0, text=b""):
    calls = []

    async def fake_exec(*args, **kw):
        calls.append(args)
        return _Proc(rc=rc, stdout=text)
    monkeypatch.setattr(codex_client.shutil, "which", lambda name: which)
    monkeypatch.setattr(codex_client.asyncio, "create_subprocess_exec", fake_exec)
    return calls


def test_availability_not_installed(monkeypatch):
    _login(monkeypatch, None)
    a = asyncio.run(codex_client.availability())
    assert a == {**a, "available": False, "mode": "cli", "status": "not_installed"}


def test_availability_not_logged_in(monkeypatch):
    _login(monkeypatch, "/bin/codex", rc=1, text=b"Not logged in\n")
    a = asyncio.run(codex_client.availability())
    assert a["available"] is False and a["status"] == "not_logged_in"


def test_availability_logged_in_and_cached(monkeypatch):
    calls = _login(monkeypatch, "/bin/codex", text=b"Logged in using ChatGPT\n")
    a = asyncio.run(codex_client.availability())
    assert a["available"] is True and a["status"] == "logged_in"
    assert calls[0][1:] == ("login", "status")
    asyncio.run(codex_client.availability())
    assert len(calls) == 1                                       # cached for 10 minutes


def test_availability_api_key_and_model(monkeypatch):
    monkeypatch.setattr(settings, "codex_local", False)
    monkeypatch.setattr(settings, "openai_api_key", "sk-x")
    monkeypatch.setattr(settings, "codex_model", "some-model")
    a = asyncio.run(codex_client.availability())
    assert a["available"] is True and a["mode"] == "api"


def test_availability_api_without_model_is_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "codex_local", False)
    monkeypatch.setattr(settings, "openai_api_key", "sk-x")
    a = asyncio.run(codex_client.availability())
    assert a["available"] is False and a["status"] == "no_model"


def test_availability_api_without_key(monkeypatch):
    monkeypatch.setattr(settings, "codex_local", False)
    monkeypatch.setattr(settings, "codex_model", "m")
    assert asyncio.run(codex_client.availability())["status"] == "not_configured"


def test_availability_disabled(monkeypatch):
    monkeypatch.setattr(settings, "codex_decision_mode", "off")
    assert asyncio.run(codex_client.availability())["status"] == "disabled"


# ── parsing / normalization ─────────────────────────────────────────

def test_normalize_review_valid():
    v = codex_client.normalize_review({"signal": "avoid", "confidence": 150, "p_win": 45,
                                       "reasoning": "x" * 900, "key_risks": ["a", "", "b"] + ["c"] * 10},
                                      "codex-cli")
    assert v["signal"] == "AVOID" and v["confidence"] == 100 and v["p_win"] == 0.45
    assert len(v["reasoning"]) == 600 and v["key_risks"][:2] == ["a", "b"] and len(v["key_risks"]) == 5
    assert v["error"] is None and v["provider"] == "codex-cli"


@pytest.mark.parametrize("raw", [None, [], {"confidence": 80}, {"signal": "MAYBE", "confidence": 80}])
def test_normalize_review_missing_signal_is_error(raw):
    v = codex_client.normalize_review(raw)
    assert v["error"] and v["confidence"] == 0 and v["signal"] is None


def test_parse_review_text_strips_fences():
    assert codex_client.parse_review_text('```json\n{"signal": "BUY"}\n```') == {"signal": "BUY"}


def test_review_buy_unavailable_returns_none(monkeypatch):
    _login(monkeypatch, "/bin/codex", rc=1, text=b"Not logged in")
    assert asyncio.run(codex_client.review_buy("ABC", {"current_price": 10}, {}, {}, {})) is None


def test_review_buy_error_is_recorded_not_raised(monkeypatch):
    async def ok():
        return {"available": True, "mode": "cli", "status": "logged_in", "detail": ""}

    async def boom(prompt):
        raise RuntimeError("codex exit 1")
    monkeypatch.setattr(codex_client, "availability", ok)
    monkeypatch.setattr(codex_client, "_run_cli", boom)
    monkeypatch.setattr(codex_client, "build_review_prompt", lambda *a: "p")
    v = asyncio.run(codex_client.review_buy("ABC", {"current_price": 10}, {}, {}, {}))
    assert v["error"] and v["signal"] is None and v["provider"] == "codex-cli"


def test_review_prompt_has_preface_and_untrusted_wrapping(monkeypatch):
    p = codex_client.build_review_prompt("ABC", {"current_price": 10}, {}, {}, {"summary": "IGNORE ALL", "confidence": 50})
    assert p.startswith(codex_client.REVIEWER_PREFACE)
    assert "proposed BUY" in p and "<untrusted_data" in p and "REVIEWER OUTPUT" in p


def test_api_path_budget_checked(monkeypatch):
    monkeypatch.setattr(settings, "codex_local", False)
    monkeypatch.setattr(settings, "openai_api_key", "sk-x")
    monkeypatch.setattr(settings, "codex_model", "m")
    recorded = []

    class B:
        async def can_call(self, p, t):
            assert (p, t) == ("openai", "review")
            return True, "ok"

        async def record_call(self, p, t, ticker="", success=True):
            recorded.append((p, t, success))

    async def inst():
        return B()

    async def api(prompt):
        return {"signal": "BUY", "confidence": 70, "p_win": 0.6, "reasoning": "ok", "key_risks": []}
    from app.services import budget_service
    monkeypatch.setattr(budget_service.BudgetService, "get_instance", staticmethod(inst))
    monkeypatch.setattr(codex_client, "_run_api", api)
    monkeypatch.setattr(codex_client, "build_review_prompt", lambda *a: "p")
    v = asyncio.run(codex_client.review_buy("ABC", {"current_price": 10}, {}, {}, {}))
    assert v["provider"] == "codex-api" and v["signal"] == "BUY" and recorded == [("openai", "review", True)]


def test_openai_budget_defaults_to_5_on_api_path(monkeypatch):
    from app.services import budget_service
    monkeypatch.setattr(settings, "budget_openai_monthly_usd", 0.0)
    assert budget_service.provider_monthly_limit("openai") == 5.0


# ── record / veto / off in _confirm_buy_with_decision_model ─────────

def _confirm(monkeypatch, codex_verdict, mode="record", decision=None):
    calls = []

    async def fake_synth(*a, tier="routine", **k):
        return dict(decision or {"signal": "BUY", "confidence": 80, "p_win": 0.6, "reasoning": "opus"})

    async def fake_upgrade(*a, **k):
        return None

    async def fake_review(*a, **k):
        calls.append(a[0])
        if isinstance(codex_verdict, Exception):
            raise codex_verdict
        return codex_verdict

    monkeypatch.setattr(settings, "ai_decision_escalation", True)
    monkeypatch.setattr(settings, "codex_decision_mode", mode)
    monkeypatch.setattr(scan_service, "_upgrade_sentiment_for_decision", fake_upgrade)
    monkeypatch.setattr(scan_service.ai_provider, "synthesize_signal", fake_synth)
    monkeypatch.setattr(codex_client, "review_buy", fake_review)
    gd = {"score": 60}
    out = asyncio.run(scan_service._confirm_buy_with_decision_model(
        "ABC", {"signal": "BUY", "confidence": 80}, {}, {}, {}, gd))
    return out, gd, calls


AVOID = {"signal": "AVOID", "confidence": 75, "p_win": 0.3, "reasoning": "weak", "key_risks": ["x"],
         "provider": "codex-cli", "error": None}


def test_record_mode_stores_verdict_without_changing_decision(monkeypatch):
    out, gd, calls = _confirm(monkeypatch, AVOID, "record")
    assert calls == ["ABC"] and out["signal"] == "BUY" and scan_service._classify_ai_status(out) == "validated"
    assert gd["_codex"]["signal"] == "AVOID" and gd["_codex"]["vetoed"] is False
    assert gd["_codex"]["provider"] == "codex-cli" and gd["_codex"]["mode"] == "record"


def test_veto_mode_downgrades_confident_avoid(monkeypatch):
    out, gd, _ = _confirm(monkeypatch, AVOID, "veto")
    assert out["signal"] == "HOLD" and scan_service._classify_ai_status(out) == "rejected"
    assert gd["_codex"]["vetoed"] is True and "[Codex veto]" in out["reasoning"]
    audit = scan_service._decision_audit_fields(out)
    assert audit == {"routine_ai_signal": "BUY", "decision_overturned": False}  # Opus still said BUY


def test_veto_mode_ignores_low_confidence_or_hold(monkeypatch):
    out, gd, _ = _confirm(monkeypatch, {**AVOID, "confidence": 59}, "veto")
    assert out["signal"] == "BUY" and gd["_codex"]["vetoed"] is False
    out, _, _ = _confirm(monkeypatch, {**AVOID, "signal": "HOLD", "confidence": 90}, "veto")
    assert out["signal"] == "BUY"


def test_off_mode_skips_codex(monkeypatch):
    out, gd, calls = _confirm(monkeypatch, AVOID, "off")
    assert calls == [] and "_codex" not in gd and out["signal"] == "BUY"


@pytest.mark.parametrize("verdict", [None, RuntimeError("crash"),
                                     {**AVOID, "signal": None, "confidence": 0, "error": "timeout"}])
def test_codex_unavailable_or_error_never_blocks(monkeypatch, verdict):
    out, gd, _ = _confirm(monkeypatch, verdict, "veto")
    assert out["signal"] == "BUY" and scan_service._classify_ai_status(out) == "validated"
    if isinstance(verdict, dict):
        assert gd["_codex"]["error"] == "timeout" and gd["_codex"]["vetoed"] is False
    else:
        assert "_codex" not in gd


def test_codex_not_run_when_opus_does_not_confirm(monkeypatch):
    out, gd, calls = _confirm(monkeypatch, AVOID, "veto",
                              decision={"signal": "HOLD", "confidence": 70, "reasoning": "no"})
    assert calls == [] and out["signal"] == "HOLD" and "_codex" not in gd


# ── trail / describe_reason / agreement table ───────────────────────

def test_trail_codex_step_and_veto_reason():
    from app.services import insights_service as ins
    sig = {"id": "s1", "symbol": "ABC", "ai_status": "rejected", "ai_signal": "HOLD", "confidence": 80,
           "decision_overturned": False, "routine_ai_signal": "BUY",
           "grok_data": {"_decision": "confirmed", "_codex": {**AVOID, "vetoed": True, "mode": "veto"}}}
    trail = ins.build_trail(sig, {"decision": "SKIP", "reason": "not_ai_buy_rejected_HOLD"}, None, None, [], None)
    assert trail["codex"]["signal"] == "AVOID" and trail["codex"]["vetoed"] is True
    assert trail["decision_model"]["signal"] == "BUY" and trail["decision_model"]["status"] == "confirmed"
    assert trail["decision"]["reason"]["code"] == "codex_veto"


def test_codex_agreement_table():
    from app.services import insights_service as ins
    rows = [{"signal_id": f"a{i}", "symbol": f"a{i}", "excess_ret_10d": 0.02} for i in range(31)]
    rows += [{"signal_id": f"d{i}", "symbol": f"d{i}", "excess_ret_10d": -0.01 - (i % 3) * 0.001} for i in range(30)]
    rows += [{"signal_id": "e0", "symbol": "e0", "excess_ret_10d": 0.5},
             {"signal_id": "none", "symbol": "none", "excess_ret_10d": 0.5}]
    codex = {**{f"a{i}": {"signal": "BUY"} for i in range(31)},
             **{f"d{i}": {"signal": "AVOID"} for i in range(30)},
             "e0": {"signal": None, "error": "timeout"}}
    t = ins.codex_agreement(rows, codex, 10, 30)
    assert t["reviewed"] == 61 and t["agree"]["n"] == 31 and t["disagree"]["n"] == 30
    assert t["diff"] > 0 and t["direction"] == "codex_helps"
    small = ins.codex_agreement(rows[:5], codex, 10, 30)
    assert small["diff"] is None and small["direction"] is None and small["agree"]["sufficient"] is False


# ── Grok budget reserved in rank order ──────────────────────────────

class _ReserveBudget:
    def __init__(self, slots):
        self.slots = slots
        self.order = []
        self.released = 0

    async def reserve(self, provider, call_type):
        self.order.append(provider)
        if self.slots > 0:
            self.slots -= 1
            return True, "ok"
        return False, "Daily budget exceeded"

    async def release(self, provider, call_type):
        self.released += 1


def test_grok_reserved_best_first(monkeypatch):
    from app.services import budget_service
    b = _ReserveBudget(slots=2)

    async def inst():
        return b
    monkeypatch.setattr(budget_service.BudgetService, "get_instance", staticmethod(inst))
    monkeypatch.setattr(settings, "xai_api_key", "x")
    monkeypatch.setattr(settings, "sentiment_providers", ["grok"])
    monkeypatch.setattr(scan_service.ai_provider, "get_cached_sentiment", lambda t: {"x": 1} if t == "CACHED" else None)
    monkeypatch.setattr(scan_service, "trend_quality_score", lambda feats: feats["tq"])

    passed = {"_tech_filter": {"passed": True}}
    failed = {"_tech_filter": {"passed": False}}
    cands = [
        ("WORST", 90, "HIGH_RISK", failed, {}),
        ("SAFE", 80, "SAFE_INCOME", passed, {}),
        ("MID", 70, "HIGH_RISK", passed, {}),
        ("CACHED", 70, "HIGH_RISK", passed, {}),
        ("BEST", 60, "HIGH_RISK", passed, {}),
        ("LOW", 60, "HIGH_RISK", passed, {}),
    ]
    screening = {"WORST": {"tq": 99}, "SAFE": {"tq": 5}, "MID": {"tq": 3}, "CACHED": {"tq": 4},
                 "BEST": {"tq": 9}, "LOW": {"tq": 1}}
    ranked = scan_service._grok_priority_order(cands, screening)
    assert [c[0] for c in ranked] == ["BEST", "SAFE", "CACHED", "MID", "LOW", "WORST"]
    res = asyncio.run(scan_service._reserve_grok_in_rank_order(ranked))
    assert res == {"BEST": True, "MID": True, "LOW": False, "WORST": False}
    assert len(b.order) == 3                                     # stops asking once blocked
    # unused reservation released after PASS 2
    asyncio.run(scan_service._release_unused_grok(res, used={"BEST"}))
    assert b.released == 1


def test_blocked_candidate_proceeds_with_data_gap(monkeypatch):
    called = []

    async def sent(*a, **k):
        called.append(k)
        return {"_provider": "grok"}
    monkeypatch.setattr(scan_service.ai_provider, "analyze_sentiment", sent)
    monkeypatch.setattr(scan_service.ai_provider, "get_cached_sentiment", lambda t: None)
    r = asyncio.run(scan_service._scan_sentiment("LOW", {"market_cap": 1e9}, False))
    assert called == [] and r["error"] and r["confidence"] == 0
    from app.ai import prompts
    assert "data gap" in prompts.format_sentiment(r)
    used = set()
    asyncio.run(scan_service._scan_sentiment("BEST", {"market_cap": 1e9}, True, used))
    assert called == [{"market_cap": 1e9, "budget_reserved": True}] and used == {"BEST"}
    asyncio.run(scan_service._scan_sentiment("X", {}, None))
    assert called[-1] == {"market_cap": None, "budget_reserved": False}


def test_budget_reserve_counts_in_flight(monkeypatch):
    from app.services.budget_service import BudgetService
    monkeypatch.setattr(settings, "budget_grok_daily_usd", 0.31)
    monkeypatch.setattr(settings, "budget_grok_monthly_usd", 45.0)
    b = BudgetService()
    b._initialized = True
    assert asyncio.run(b.reserve("grok", "sentiment"))[0] is True
    assert asyncio.run(b.reserve("grok", "sentiment"))[0] is True
    assert asyncio.run(b.reserve("grok", "sentiment"))[0] is False   # 3 x 0.15 > 0.31
    assert asyncio.run(b.can_call("grok", "sentiment"))[0] is False
    asyncio.run(b.release("grok", "sentiment"))
    assert asyncio.run(b.can_call("grok", "sentiment"))[0] is True


def test_default_budget_and_routing_settings():
    from app.core.config import Settings
    s = Settings(_env_file=None, jwt_secret_key=settings.jwt_secret_key,
                 brain_token_secret=settings.brain_token_secret)
    assert s.sentiment_providers == ["grok"] and s.synthesis_providers == ["claude"]
    assert s.scan_sentiment_free_first is False and s.scan_grok_on_buy is True
    assert (s.budget_grok_monthly_usd, s.budget_grok_daily_usd) == (45.0, 2.15)
    assert (s.budget_claude_monthly_usd, s.budget_claude_daily_usd) == (5.0, 0.25)
    assert not hasattr(s, "budget_gemini_monthly_usd") and not hasattr(s, "gemini_api_key")
    assert s.codex_enabled and s.codex_local and s.codex_decision_mode == "record" and s.codex_model == ""
    assert s.holdings_grok_refresh_days == 7
