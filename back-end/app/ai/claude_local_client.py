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

from app.ai.prompts import (
    CLAUDE_SYNTHESIS_PROMPT,
    clean_json_response,
    format_fundamentals,
    format_macro,
    format_sentiment,
    format_technicals,
)


def _safe_int(value, default: int = 0) -> int:
    """Safely cast to int, returning default on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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

    Retries on transient failures (timeout, empty response, JSON parse error,
    CLI exit error). Does NOT retry FileNotFoundError since the binary missing
    won't fix itself. Backoff: 2^attempt seconds between attempts.
    """

    prompt = CLAUDE_SYNTHESIS_PROMPT.format(
        ticker=ticker,
        technicals=format_technicals(technical_data),
        fundamentals=format_fundamentals(fundamental_data),
        macro=format_macro(macro_data),
        sentiment=format_sentiment(grok_data),
        market_regime=grok_data.get("_market_regime", "TRENDING") if isinstance(grok_data, dict) else "TRENDING",
        regime_note=grok_data.get("_regime_note", "") if isinstance(grok_data, dict) else "",
        catalyst_context=grok_data.get("_catalyst_context", "No specific catalyst detected") if isinstance(grok_data, dict) else "No specific catalyst detected",
        knowledge_block=grok_data.get("_knowledge_block", "") if isinstance(grok_data, dict) else "",
    )

    last_error = ""

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Claude Local [{ticker}] — calling CLI (attempt {attempt}/{max_retries})...")

            process = await asyncio.create_subprocess_exec(
                "claude", "-p", prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=120,  # 2 min timeout
            )

            if process.returncode != 0:
                error_msg = stderr.decode().strip() if stderr else f"Exit code {process.returncode}"
                last_error = f"CLI error: {error_msg}"
                logger.warning(f"Claude Local [{ticker}] {last_error} (attempt {attempt}/{max_retries})")
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)
                continue

            raw_output = stdout.decode().strip()
            if not raw_output:
                last_error = "Empty CLI response"
                logger.warning(f"Claude Local [{ticker}] {last_error} (attempt {attempt}/{max_retries})")
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)
                continue

            content = clean_json_response(raw_output)
            data = json.loads(content)

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
                f"confidence={result['confidence']} rr={result['risk_reward_ratio']} "
                f"(attempt {attempt})"
            )
            return result

        except asyncio.TimeoutError:
            last_error = "CLI timeout (120s)"
            logger.warning(f"Claude Local [{ticker}] {last_error} (attempt {attempt}/{max_retries})")
            if attempt < max_retries:
                await asyncio.sleep(2 ** attempt)
            continue

        except json.JSONDecodeError as e:
            last_error = f"JSON parse error: {e}"
            logger.warning(f"Claude Local [{ticker}] {last_error} (attempt {attempt}/{max_retries})")
            if attempt < max_retries:
                await asyncio.sleep(2 ** attempt)
            continue

        except FileNotFoundError:
            # Binary missing — retrying won't help, fail fast
            logger.error("Claude CLI not found — is 'claude' installed and in PATH?")
            return _error_response(ticker, "Claude CLI not found in PATH")

        except Exception as e:
            last_error = f"Unexpected: {e}"
            logger.warning(f"Claude Local [{ticker}] {last_error} (attempt {attempt}/{max_retries})")
            if attempt < max_retries:
                await asyncio.sleep(2 ** attempt)
            continue

    logger.error(f"Claude Local [{ticker}] failed after {max_retries} attempts — {last_error}")
    return _error_response(ticker, f"Failed after {max_retries} retries: {last_error}")
