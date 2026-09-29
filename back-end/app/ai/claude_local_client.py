"""Claude local client — invokes the Claude CLI binary as a subprocess.

============================================================
WHAT THIS MODULE IS
============================================================

Most AI clients in this project hit a paid HTTP API. This one is
different: it shells out to the local `claude` CLI binary (installed
via the user's Pro Max subscription) and gets the same Claude model
quality at zero marginal cost.

The trade-off is reliability. The CLI is a subprocess, which means:
  • It can timeout (we cap at 120s)
  • It can return empty output (transient flake)
  • It can return malformed JSON (rare but happens)
  • It can fail with a non-zero exit code
  • The binary might not even be in PATH on the production server

For all of these EXCEPT "binary not in PATH", we retry. The retry
strategy is exponential backoff: 2s, 4s, 8s between attempts, up to
3 attempts total. After 3 failures, we return an error response and
let `provider.synthesize_signal` cascade to the paid Claude API.

The retry logic was added because users were seeing "all AI providers
failed" alerts that were actually caused by single transient CLI
hiccups. With retries, those hiccups never escalate.

============================================================
WHY THIS EXISTS
============================================================

The signal pipeline runs ~15 AI synthesis calls per scan, 4 scans per
day = 60 calls/day. At Claude API rates (~$0.012/call) that's
~$22/month. Using Claude Local takes that to $0.

Claude Local is the DEFAULT (`settings.claude_local: bool = True`) and
the paid API is never used in local mode. This module produces the same response
schema as `claude_client.py` so they're interchangeable from the
router's perspective.

============================================================
ERROR HANDLING
============================================================

Retried (each attempt waits 2^attempt seconds):
  • asyncio.TimeoutError    — process took > 120s
  • Empty stdout            — CLI returned nothing
  • json.JSONDecodeError    — malformed response
  • Non-zero exit code      — CLI errored
  • Generic Exception       — anything else unexpected

NOT retried (fail-fast):
  • FileNotFoundError       — binary missing, won't fix itself
"""

import asyncio
import json
import tempfile

from loguru import logger

from app.ai.prompts import (
    SYNTHESIS_JSON_SCHEMA,
    build_synthesis_prompt,
    clean_json_response,
    normalize_synthesis_result,
    synthesis_error_response,
)
from app.core.config import settings

# Replaces Claude Code's default agent system prompt: these calls are pure
# analysis requests, not coding sessions.
_CLI_SYSTEM_PROMPT = (
    "You are a financial analysis engine. Answer only from the data in the "
    "user message and return exactly one JSON object matching the requested schema."
)


def build_cli_args(json_schema: dict | None = None, tier: str = "routine") -> list[str]:
    """Build the `claude -p` argv: pinned model, JSON envelope, no tools/MCP.

    The prompt itself is NOT in argv (it is written to stdin) so untrusted
    text never reaches the process table / shell parsing, and all built-in
    tools are disabled so prompt-injected instructions cannot read files
    (e.g. .env) or fetch URLs.
    """
    args = [
        "claude", "-p",
        "--model", settings.claude_decision_model if tier == "decision" else settings.claude_model,
        "--output-format", "json",
        "--tools", "",              # disable all built-in tools
        "--strict-mcp-config",      # no MCP servers
        "--no-session-persistence",
        "--system-prompt", _CLI_SYSTEM_PROMPT,
    ]
    if json_schema is not None:
        args += ["--json-schema", json.dumps(json_schema)]
    return args


def parse_cli_output(raw: str) -> dict:
    """Parse `--output-format json` stdout into the model's JSON object.

    The CLI prints an envelope: {"type":"result","is_error":bool,
    "result":"<text>","structured_output":{...}|absent,...}. Prefers
    `structured_output` (validated against --json-schema), else extracts
    the first JSON object from `result`. Raises ValueError on CLI-level
    errors and json.JSONDecodeError on unparseable output.
    """
    envelope = json.loads(raw)
    if isinstance(envelope, dict) and envelope.get("type") == "result":
        if envelope.get("is_error"):
            raise ValueError(f"CLI result error: {str(envelope.get('result'))[:200]}")
        structured = envelope.get("structured_output")
        if isinstance(structured, dict):
            return structured
        text = envelope.get("result") or ""
        data = json.loads(clean_json_response(text))
    else:
        data = envelope
    if not isinstance(data, dict):
        raise json.JSONDecodeError("not a JSON object", raw, 0)
    return data


async def _run_claude_cli(
    prompt: str,
    max_retries: int = 3,
    timeout: int | None = None,
    log_context: str = "",
    json_schema: dict | None = None,
    tier: str = "routine",
) -> dict | None:
    """Run a prompt through the local Claude CLI and return the parsed JSON.

    Shared subprocess shell for `synthesize_signal` and `call_with_prompt`.
    The CLI runs with a pinned `--model`, `--output-format json`, all tools
    disabled, and cwd set to an empty temp dir so no project CLAUDE.md /
    settings leak into trading prompts. Returns None on hard failure.
    """
    tag = f"[{log_context}] " if log_context else ""
    timeout = timeout or settings.claude_local_timeout_s
    args = build_cli_args(json_schema, tier=tier)
    prompt_bytes = prompt.encode("utf-8")
    last_error = ""
    for attempt in range(1, max_retries + 1):
        process = None
        try:
            with tempfile.TemporaryDirectory(prefix="signa-claude-") as workdir:
                process = await asyncio.create_subprocess_exec(
                    *args,
                    cwd=workdir,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(input=prompt_bytes),
                    timeout=timeout,
                )
            if process.returncode != 0:
                err = stderr.decode().strip() if stderr else f"exit {process.returncode}"
                last_error = f"CLI error: {err[:300]}"
                logger.warning(
                    f"Claude Local {tag}{last_error} "
                    f"(attempt {attempt}/{max_retries})"
                )
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)
                continue
            raw = stdout.decode().strip()
            if not raw:
                last_error = "Empty CLI response"
                logger.warning(
                    f"Claude Local {tag}{last_error} "
                    f"(attempt {attempt}/{max_retries})"
                )
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)
                continue
            return parse_cli_output(raw)
        except asyncio.TimeoutError:
            if process is not None and process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            last_error = f"CLI timeout ({timeout}s)"
            logger.warning(
                f"Claude Local {tag}{last_error} (attempt {attempt}/{max_retries})"
            )
            if attempt < max_retries:
                await asyncio.sleep(2 ** attempt)
            continue
        except (json.JSONDecodeError, ValueError) as e:
            last_error = f"Bad CLI output: {e}"
            logger.warning(
                f"Claude Local {tag}{last_error} (attempt {attempt}/{max_retries})"
            )
            if attempt < max_retries:
                await asyncio.sleep(2 ** attempt)
            continue
        except FileNotFoundError:
            # Binary missing — retries won't help, fail fast
            logger.error(
                f"Claude Local {tag}CLI not found in PATH — is 'claude' installed?"
            )
            return None
        except Exception as e:
            last_error = f"Unexpected: {e}"
            logger.warning(
                f"Claude Local {tag}{last_error} (attempt {attempt}/{max_retries})"
            )
            if attempt < max_retries:
                await asyncio.sleep(2 ** attempt)
            continue
    logger.warning(
        f"Claude Local {tag}exhausted {max_retries} retries — {last_error}"
    )
    return None


async def call_with_prompt(
    prompt: str,
    max_retries: int = 2,
    json_schema: dict | None = None,
    tier: str = "routine",
) -> dict | None:
    """Run an arbitrary prompt through the local Claude CLI and return parsed JSON.

    Used by features beyond `synthesize_signal` (e.g. thesis re-evaluation).
    Returns None on hard failure — callers treat None as "Claude Local
    unavailable". Pass `json_schema` to get CLI-validated structured output
    and `tier="decision"` to run on settings.claude_decision_model.
    """
    return await _run_claude_cli(prompt, max_retries=max_retries, json_schema=json_schema, tier=tier)


async def synthesize_signal(
    ticker: str,
    technical_data: dict,
    fundamental_data: dict,
    macro_data: dict,
    grok_data: dict,
    max_retries: int = 3,
    tier: str = "routine",
) -> dict:
    """Call Claude via local CLI to synthesize all data into a final signal.

    Structured output is enforced with `--json-schema`; the result is then
    normalized (signal whitelist, confidence default 0, level validation +
    R:R computed in code). A response without a valid signal is retried
    once before failing.
    """
    logger.info(f"Claude Local [{ticker}] — calling CLI (up to {max_retries} attempts)...")

    prompt = build_synthesis_prompt(
        ticker, technical_data, fundamental_data, macro_data, grok_data,
    )
    current_price = (technical_data or {}).get("current_price")
    result = synthesis_error_response(f"Claude Local failed after {max_retries} retries")
    for _ in range(2):  # one extra try when the JSON parses but is invalid
        data = await _run_claude_cli(
            prompt, max_retries=max_retries, log_context=ticker,
            json_schema=SYNTHESIS_JSON_SCHEMA, tier=tier,
        )
        if data is None:
            return synthesis_error_response(f"Claude Local failed after {max_retries} retries")
        result = normalize_synthesis_result(data, current_price=current_price)
        if not result.get("error"):
            break
        logger.warning(f"Claude Local [{ticker}] invalid synthesis: {result['error']}")

    logger.debug(
        f"Claude Local [{ticker}] → {result['signal']} "
        f"confidence={result['confidence']} p_win={result.get('p_win')} "
        f"rr={result['risk_reward_ratio']} err={result.get('error')}"
    )
    return result
