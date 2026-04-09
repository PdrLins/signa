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
the paid API is the FALLBACK. This module produces the same response
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

from loguru import logger

from app.ai.prompts import build_synthesis_prompt, clean_json_response


def _safe_int(value, default: int = 0) -> int:
    """Safely cast to int, returning default on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


async def _run_claude_cli(
    prompt: str,
    max_retries: int = 3,
    timeout: int = 120,
    log_context: str = "",
) -> dict | None:
    """Run a prompt through the local Claude CLI and return the parsed JSON.

    This is the SHARED subprocess-shell used by BOTH `synthesize_signal`
    and `call_with_prompt`. Handles the retry loop, exponential backoff,
    subprocess lifecycle, stdout decoding, and JSON parsing. Returns a
    parsed dict on success or None on hard failure — callers layer their
    own field normalization / error responses on top.

    Args:
        prompt: The full prompt to send to `claude -p`.
        max_retries: Retry budget for transient failures. Use 3 for
            first-class synthesis calls and 2 for "extra" calls.
        timeout: Per-attempt timeout in seconds.
        log_context: A short tag (e.g. ticker symbol) to include in log
            lines so multi-call failures can be correlated back to the
            caller. Empty string for generic calls.

    Returns:
        Parsed JSON dict on success. None on:
            - FileNotFoundError (binary missing — doesn't retry)
            - Retry budget exhausted after all transient failures
    """
    tag = f"[{log_context}] " if log_context else ""
    last_error = ""
    for attempt in range(1, max_retries + 1):
        try:
            process = await asyncio.create_subprocess_exec(
                "claude", "-p", prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )
            if process.returncode != 0:
                err = stderr.decode().strip() if stderr else f"exit {process.returncode}"
                last_error = f"CLI error: {err}"
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
            return json.loads(clean_json_response(raw))
        except asyncio.TimeoutError:
            last_error = f"CLI timeout ({timeout}s)"
            logger.warning(
                f"Claude Local {tag}{last_error} (attempt {attempt}/{max_retries})"
            )
            if attempt < max_retries:
                await asyncio.sleep(2 ** attempt)
            continue
        except json.JSONDecodeError as e:
            last_error = f"JSON parse error: {e}"
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


async def call_with_prompt(prompt: str, max_retries: int = 2) -> dict | None:
    """Run an arbitrary prompt through the local Claude CLI and return parsed JSON.

    Used by features beyond `synthesize_signal` that need a one-off Claude
    call without the synthesis prompt boilerplate (e.g., thesis re-evaluation
    in Stage 6, future post-mortem analyses). Returns None on hard failure —
    callers must treat None as "Claude Local unavailable" and decide whether
    to fall back.

    Lower default retry count (2) than `synthesize_signal` because the
    callers of this function are typically lower-priority "extra" calls
    that we don't want to spend much time retrying.
    """
    return await _run_claude_cli(prompt, max_retries=max_retries)


def _error_response(ticker: str, reason: str) -> dict:
    """Return a safe fallback on failure."""
    return {
        "signal": "HOLD",
        "confidence": 0,
        "reasoning": "Analysis temporarily unavailable",
        "risk_factors": [],
        "catalyst": None,
        "catalyst_date": None,
        "red_flags": [],
        "risk_reward_ratio": None,
        "target_price": None,
        "stop_loss": None,
        "sentiment_weight": 0,
        "error": reason,
    }


async def synthesize_signal(
    ticker: str,
    technical_data: dict,
    fundamental_data: dict,
    macro_data: dict,
    grok_data: dict,
    max_retries: int = 3,
) -> dict:
    """Call Claude via local CLI to synthesize all data into a final signal.

    Delegates the subprocess + retry + JSON parse shell to `_run_claude_cli`,
    then layers on the synthesis-specific field normalization (action whitelist,
    confidence/sentiment_weight int coercion, `error: None` on success).

    Retries on transient failures (timeout, empty response, JSON parse error,
    CLI exit error). Does NOT retry FileNotFoundError since the binary missing
    won't fix itself. Backoff: 2^attempt seconds between attempts.
    """
    logger.info(f"Claude Local [{ticker}] — calling CLI (up to {max_retries} attempts)...")

    prompt = build_synthesis_prompt(
        ticker, technical_data, fundamental_data, macro_data, grok_data,
    )
    data = await _run_claude_cli(prompt, max_retries=max_retries, log_context=ticker)
    if data is None:
        return _error_response(ticker, f"Claude Local failed after {max_retries} retries")

    # Synthesis-specific normalization: action whitelist + int coercion.
    raw_signal = data.get("signal", "HOLD").upper()
    if raw_signal not in ("BUY", "HOLD", "SELL", "AVOID"):
        raw_signal = "HOLD"

    result = {
        "signal": raw_signal,
        "confidence": _safe_int(data.get("confidence"), 50),
        "reasoning": data.get("reasoning", ""),
        "risk_factors": data.get("risk_factors", []),
        "catalyst": data.get("catalyst"),
        "catalyst_date": data.get("catalyst_date"),
        "red_flags": data.get("red_flags", []),
        "risk_reward_ratio": data.get("risk_reward_ratio"),
        "target_price": data.get("target_price"),
        "stop_loss": data.get("stop_loss"),
        "sentiment_weight": _safe_int(data.get("sentiment_weight"), 0),
        "error": None,
    }
    logger.debug(
        f"Claude Local [{ticker}] → {result['signal']} "
        f"confidence={result['confidence']} rr={result['risk_reward_ratio']}"
    )
    return result
