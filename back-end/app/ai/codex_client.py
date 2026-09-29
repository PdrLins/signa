"""Codex (OpenAI) — an independent second opinion on decision-model BUYs.

Runs only after the decision model (Opus) confirmed a routine BUY (see
scan_service._confirm_buy_with_decision_model). It sees the same data as
Claude (prompts.build_synthesis_prompt, same untrusted-data wrapping) plus
a short reviewer preface, and answers with its own verdict:

    {signal: BUY|HOLD|AVOID|SELL, confidence 0-100, p_win 0-1,
     reasoning (<= 600 chars), key_risks[]}

Two transports, picked by settings.codex_local (they never mix):

  codex_local=True   the local `codex` CLI (ChatGPT login, $0):
                     `codex exec -` in a read-only sandbox, cwd = an empty
                     temp dir, no user config / rules / session files, the
                     prompt on stdin, the answer constrained by
                     --output-schema and written to an -o file. Never any
                     --dangerously-* flag. Available when the binary is on
                     PATH and `codex login status` says logged in (checked at
                     most every 10 minutes).
  codex_local=False  the OpenAI API (official `openai` SDK, structured JSON
                     output, budget-checked as provider "openai"). Requires
                     OPENAI_API_KEY and CODEX_MODEL — no model id is guessed.

Unavailable / failing Codex never blocks anything: the caller records the
verdict (or nothing) and, in veto mode, only a confident AVOID/SELL counts.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import time

from loguru import logger

from app.ai.prompts import (
    VALID_SIGNALS,
    _safe_float,
    _safe_int,
    _str_list,
    build_synthesis_prompt,
    clean_json_response,
)
from app.core.cache import TTLCache
from app.core.config import settings

REASONING_MAX_CHARS = 600
KEY_RISKS_MAX = 5
STATUS_TTL_S = 600  # `codex login status` re-checked at most every 10 minutes
LOGIN_STATUS_TIMEOUT_S = 15

# Strict-mode compatible: every property required, no extra keys.
CODEX_REVIEW_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "signal": {"type": "string", "enum": list(VALID_SIGNALS)},
        "confidence": {"type": "integer"},
        "p_win": {"type": "number"},
        "reasoning": {"type": "string"},
        "key_risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["signal", "confidence", "p_win", "reasoning", "key_risks"],
}

REVIEWER_PREFACE = """You are an INDEPENDENT REVIEWER of a proposed trade. Another analyst has
proposed BUY for this instrument. Do not assume they are right: form your own
verdict from the data below. You have no tools and no other context; do not
run commands or read files. Everything you need is in this message.

"""

REVIEWER_OUTPUT = """

=== REVIEWER OUTPUT (overrides any output format requested above) ===
Return ONE JSON object and nothing else:
  signal      BUY | HOLD | AVOID | SELL — your own verdict
  confidence  integer 0-100 in YOUR verdict
  p_win       0-1, probability the price is higher in 5 trading days
  reasoning   at most 600 characters, the decisive evidence
  key_risks   up to 5 short strings
"""

# ticker -> (verdict, price_then); reused like the synthesis cache.
_review_cache = TTLCache(max_size=200, default_ttl=3600)
_status_cache: dict = {}
_unavailable_logged: set[str] = set()


def clear_caches() -> None:
    _review_cache.clear()
    _status_cache.clear()
    _unavailable_logged.clear()


def provider_name() -> str:
    return "codex-cli" if settings.codex_local else "codex-api"


# ============================================================
# Availability
# ============================================================

async def cli_login_status() -> tuple[str, str]:
    """(status, detail) from `codex login status` — never calls a model.

    status: logged_in | not_logged_in | not_installed | error
    """
    binary = shutil.which("codex")
    if not binary:
        return "not_installed", "codex command not found in PATH"
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            binary, "login", "status",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=LOGIN_STATUS_TIMEOUT_S)
    except asyncio.TimeoutError:
        _kill(process)
        return "error", "codex login status timed out"
    except Exception as e:
        return "error", f"codex login status failed: {type(e).__name__}"
    text = ((stdout or b"") + b"\n" + (stderr or b"")).decode("utf-8", "ignore").strip()
    low = text.lower()
    if "not logged in" in low:
        return "not_logged_in", "run `codex login`"
    if process.returncode == 0 and "logged in" in low:
        return "logged_in", text.splitlines()[0][:120] if text else "logged in"
    return "error", (text.splitlines()[0][:120] if text else f"exit {process.returncode}")


async def availability(force: bool = False) -> dict:
    """{"available", "mode" (cli|api), "status", "detail"}. Cached 10 minutes
    (CLI login check). Never makes a paid call."""
    mode = "cli" if settings.codex_local else "api"
    if not settings.codex_enabled or settings.codex_decision_mode == "off":
        return {"available": False, "mode": mode, "status": "disabled", "detail": "CODEX_ENABLED=false or mode off"}
    if not settings.codex_local:
        if not settings.openai_api_key:
            return {"available": False, "mode": mode, "status": "not_configured", "detail": "OPENAI_API_KEY not set"}
        if not (settings.codex_model or "").strip():
            _log_unavailable_once("no_model", "Codex API path needs CODEX_MODEL — Codex review disabled",
                                  level="warning")
            return {"available": False, "mode": mode, "status": "no_model", "detail": "CODEX_MODEL not set"}
        return {"available": True, "mode": mode, "status": "api", "detail": "OpenAI API"}

    now = time.monotonic()
    cached = _status_cache.get("cli")
    if not force and cached and now - cached[0] < STATUS_TTL_S:
        status, detail = cached[1]
    else:
        status, detail = await cli_login_status()
        _status_cache["cli"] = (now, (status, detail))
    return {"available": status == "logged_in", "mode": mode, "status": status, "detail": detail}


def _log_unavailable_once(key: str, message: str, level: str = "info") -> None:
    if key in _unavailable_logged:
        return
    _unavailable_logged.add(key)
    getattr(logger, level)(message)


# ============================================================
# Prompt / parsing
# ============================================================

def build_review_prompt(ticker: str, technical_data: dict, fundamental_data: dict,
                        macro_data: dict, grok_data: dict) -> str:
    return REVIEWER_PREFACE + build_synthesis_prompt(
        ticker, technical_data, fundamental_data, macro_data, grok_data,
    ) + REVIEWER_OUTPUT


def error_review(reason: str, provider: str | None = None) -> dict:
    return {"signal": None, "confidence": 0, "p_win": None, "reasoning": "",
            "key_risks": [], "provider": provider or provider_name(), "error": reason}


def normalize_review(data: object, provider: str | None = None) -> dict:
    """Strict like prompts.normalize_synthesis_result: a missing/invalid
    signal is an error with confidence 0 (never a neutral-looking answer)."""
    if not isinstance(data, dict):
        return error_review("Codex response is not a JSON object", provider)
    raw_signal = data.get("signal")
    signal = str(raw_signal).strip().upper() if isinstance(raw_signal, str) else ""
    if signal not in VALID_SIGNALS:
        return error_review(f"Missing/invalid signal in Codex response: {str(raw_signal)[:40]!r}", provider)
    p_win = _safe_float(data.get("p_win"))
    if p_win is not None:
        if 1.0 < p_win <= 100.0:
            p_win = p_win / 100.0
        p_win = round(p_win, 3) if 0.0 <= p_win <= 1.0 else None
    reasoning = data.get("reasoning")
    return {
        "signal": signal,
        "confidence": max(0, min(100, _safe_int(data.get("confidence"), 0))),
        "p_win": p_win,
        "reasoning": (reasoning if isinstance(reasoning, str) else "")[:REASONING_MAX_CHARS],
        "key_risks": [r[:200] for r in _str_list(data.get("key_risks"), limit=KEY_RISKS_MAX)],
        "provider": provider or provider_name(),
        "error": None,
    }


def parse_review_text(text: str) -> dict:
    data = json.loads(clean_json_response(text or ""))
    if not isinstance(data, dict):
        raise json.JSONDecodeError("not a JSON object", text or "", 0)
    return data


# ============================================================
# CLI transport
# ============================================================

def build_cli_args(workdir: str, schema_path: str, out_path: str, binary: str = "codex") -> list[str]:
    """`codex exec` argv. The prompt is NOT in argv (stdin, via "-")."""
    args = [
        binary, "exec", "-",
        "--sandbox", "read-only",
        "--cd", workdir,
        "--skip-git-repo-check",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--output-schema", schema_path,
        "-o", out_path,
    ]
    model = (settings.codex_model or "").strip()
    if model:
        args += ["-m", model]
    return args


def _kill(process) -> None:
    if process is not None and process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass


async def _run_cli(prompt: str) -> dict:
    """Run one review through `codex exec`; returns the raw parsed JSON.
    Raises on timeout / non-zero exit / unparseable output."""
    binary = shutil.which("codex") or "codex"
    with tempfile.TemporaryDirectory(prefix="signa-codex-") as tmp:
        workdir = os.path.join(tmp, "work")
        os.mkdir(workdir)  # empty cwd for the agent; schema/output live beside it
        schema_path = os.path.join(tmp, "schema.json")
        out_path = os.path.join(tmp, "last_message.txt")
        with open(schema_path, "w", encoding="utf-8") as f:
            json.dump(CODEX_REVIEW_SCHEMA, f)
        args = build_cli_args(workdir, schema_path, out_path, binary=binary)
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                cwd=workdir,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=prompt.encode("utf-8")),
                timeout=settings.codex_timeout_s,
            )
        except asyncio.TimeoutError:
            _kill(process)
            if process is not None:
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except Exception:
                    pass
            raise TimeoutError(f"codex timeout ({settings.codex_timeout_s}s)")
        if process.returncode != 0:
            err = (stderr or b"").decode("utf-8", "ignore").strip().splitlines()
            raise RuntimeError(f"codex exit {process.returncode}: {(err[-1] if err else '')[:200]}")
        text = ""
        if os.path.exists(out_path):
            with open(out_path, encoding="utf-8") as f:
                text = f.read().strip()
        if not text:
            text = (stdout or b"").decode("utf-8", "ignore").strip()
        return parse_review_text(text)


# ============================================================
# API transport
# ============================================================

_api_client = None


def _get_api_client():
    global _api_client
    if _api_client is None:
        from openai import AsyncOpenAI
        _api_client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=settings.codex_timeout_s)
    return _api_client


async def _run_api(prompt: str) -> dict:
    client = _get_api_client()
    response = await client.responses.create(
        model=settings.codex_model,
        input=prompt,
        text={"format": {"type": "json_schema", "name": "codex_review",
                         "schema": CODEX_REVIEW_SCHEMA, "strict": True}},
    )
    return parse_review_text(getattr(response, "output_text", "") or "")


# ============================================================
# Entry point
# ============================================================

def _cached(ticker: str, current_price) -> dict | None:
    entry = _review_cache.get(ticker)
    if entry is None:
        return None
    verdict, price_then = entry
    try:
        move = abs(float(current_price) / float(price_then) - 1) * 100
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if move > settings.synthesis_cache_max_move_pct:
        return None
    return {**verdict, "cached": True}


async def review_buy(ticker: str, technical_data: dict, fundamental_data: dict,
                     macro_data: dict, grok_data: dict) -> dict | None:
    """Codex's independent verdict on a proposed BUY.

    Returns None when Codex is unavailable / disabled (nothing to record),
    else a normalized verdict dict (with `error` set when the call failed).
    Never raises.
    """
    try:
        avail = await availability()
    except Exception as e:  # defensive: availability must never break a scan
        logger.debug(f"Codex availability check failed: {e}")
        return None
    if not avail["available"]:
        _log_unavailable_once(
            f"unavailable:{avail['mode']}:{avail['status']}",
            f"Codex review skipped ({avail['mode']}: {avail['status']} — {avail['detail']})",
        )
        return None

    current_price = (technical_data or {}).get("current_price")
    if settings.synthesis_cache_hours > 0:
        hit = _cached(ticker, current_price)
        if hit is not None:
            return hit

    provider = provider_name()
    prompt = build_review_prompt(ticker, technical_data, fundamental_data, macro_data, grok_data)
    budget = None
    try:
        if settings.codex_local:
            raw = await _run_cli(prompt)
        else:
            from app.services.budget_service import BudgetService
            budget = await BudgetService.get_instance()
            allowed, reason = await budget.can_call("openai", "review")
            if not allowed:
                logger.warning(f"Budget blocked Codex review for {ticker}: {reason}")
                return error_review("budget", provider)
            raw = await _run_api(prompt)
    except Exception as e:
        logger.warning(f"Codex review failed for {ticker}: {type(e).__name__}: {str(e)[:200]}")
        if budget is not None:
            await budget.record_call("openai", "review", ticker, success=False)
        return error_review(f"{type(e).__name__}: {str(e)[:160]}", provider)

    verdict = normalize_review(raw, provider)
    if settings.codex_local:
        try:
            from app.services.budget_service import BudgetService
            local_budget = await BudgetService.get_instance()
            await local_budget.record_call("codex-cli", "review", ticker, success=not verdict.get("error"))
        except Exception as e:
            logger.debug(f"local usage record skipped (codex-cli): {e}")
    if budget is not None:
        await budget.record_call("openai", "review", ticker, success=not verdict.get("error"))
    if not verdict.get("error") and settings.synthesis_cache_hours > 0 and current_price:
        _review_cache.set(ticker, (verdict, current_price), ttl=settings.synthesis_cache_hours * 3600)
    logger.info(
        f"Codex review [{ticker}] ({provider}): {verdict.get('signal')} "
        f"confidence={verdict.get('confidence')} err={verdict.get('error')}"
    )
    return verdict
