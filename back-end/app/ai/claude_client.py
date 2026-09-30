"""Claude (Anthropic) API client — used only when settings.claude_local=False.

============================================================
WHAT THIS MODULE IS
============================================================

The paid path to Claude (see `provider.py`). Called only when
`settings.claude_local=False`; in local mode the router never reaches
this module. Uses the official Anthropic Python SDK.

Unlike Claude Local (which is free via Pro Max subscription), every
call here costs money (see budget_service.COST_ESTIMATES).
The router's budget service blocks calls that would exceed the daily
or monthly limit, so this client never has to worry about runaway costs.

============================================================
WHY BOTH CLAUDE LOCAL AND CLAUDE API EXIST
============================================================

  • Claude Local: free, slower (subprocess overhead), occasionally flaky
  • Claude API:   paid, faster, more reliable, has retries built into SDK

The two are mutually exclusive, chosen by settings.claude_local: local
machine → CLI only; a server without the CLI → API only.

============================================================
RESPONSE SCHEMA
============================================================

This client returns the same dict shape as `claude_local_client.py`
so the router can swap between them transparently:

  {
    "signal": "BUY" | "HOLD" | "SELL" | "AVOID",
    "confidence": int (0-100),
    "p_win": float (0-1) | None,  # P(price higher in ai_pwin_horizon_days trading days)
    "reasoning": str (2-3 sentences),
    "risk_factors": list[str],
    "catalyst": str | None,
    "catalyst_date": str | None,  # YYYY-MM-DD
    "red_flags": list[str],
    "risk_reward_ratio": float | None,  # computed in code from levels
    "target_price": float | None,
    "stop_loss": float | None,
    "sentiment_weight": int (0-100),
    "error": str | None,  # set on failure, null on success
  }

The downstream `_process_candidate` in scan_service classifies any
response with `error` set as `ai_status="failed"`.
"""

import asyncio
import json
from typing import Optional

import anthropic
from loguru import logger

from app.ai.prompts import (
    SYNTHESIS_JSON_SCHEMA,
    build_synthesis_prompt,
    clean_json_response,
    normalize_synthesis_result,
    synthesis_error_response,
)
from app.core.config import settings

_client: Optional[anthropic.AsyncAnthropic] = None
_client_lock = asyncio.Lock()

# Server-side refusal fallback (Claude API only): if the primary model
# declines, the API re-runs the request on a fallback model in the same call.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


async def _get_client() -> anthropic.AsyncAnthropic:
    """Get or create the Anthropic client (async-safe)."""
    global _client
    if _client is not None:
        return _client
    async with _client_lock:
        if _client is not None:
            return _client
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        logger.info("Claude API client initialized")
        return _client


def model_for_tier(tier: str) -> tuple[str, str]:
    """(model, effort) for a call tier: "routine" (default) or "decision"."""
    if tier == "decision":
        return settings.claude_decision_model, settings.claude_decision_effort
    return settings.claude_model, settings.claude_effort


async def create_structured(prompt: str, schema: dict, tier: str = "routine") -> dict:
    """One Claude API call constrained to `schema`; returns the parsed dict.

    Raises anthropic errors as-is, `json.JSONDecodeError` on unparseable
    output, and `ValueError` on refusal / truncation (callers retry or fail).
    """
    client = await _get_client()
    model, effort = model_for_tier(tier)
    response = await client.beta.messages.create(
        model=model,
        max_tokens=settings.claude_max_tokens,
        thinking={"type": "adaptive"},
        output_config={
            "effort": effort,
            "format": {"type": "json_schema", "schema": schema},
        },
        betas=[_FALLBACK_BETA],
        fallbacks="default",
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "refusal":
        raise ValueError("Claude refused the request")
    if response.stop_reason == "max_tokens":
        raise ValueError("Claude response truncated (max_tokens)")
    text = next((b.text for b in response.content if b.type == "text"), "")
    data = json.loads(clean_json_response(text))
    if not isinstance(data, dict):
        raise json.JSONDecodeError("not a JSON object", text, 0)
    return data


async def synthesize_signal(
    ticker: str,
    technical_data: dict,
    fundamental_data: dict,
    macro_data: dict,
    grok_data: dict,
    max_retries: int = 3,
    tier: str = "routine",
) -> dict:
    """Call Claude to synthesize all data into a final signal.

    Uses structured outputs (JSON schema). Retries rate limits / 5xx with
    exponential backoff and retries a malformed/truncated response once.
    """
    prompt = build_synthesis_prompt(
        ticker, technical_data, fundamental_data, macro_data, grok_data,
    )
    current_price = (technical_data or {}).get("current_price")

    last_error = ""
    parse_retry_used = False

    for attempt in range(1, max_retries + 1):
        try:
            data = await create_structured(prompt, SYNTHESIS_JSON_SCHEMA, tier=tier)
            result = normalize_synthesis_result(data, current_price=current_price)
            if result.get("error"):
                raise ValueError(result["error"])

            logger.debug(
                f"Claude [{ticker}] → {result['signal']} "
                f"confidence={result['confidence']} p_win={result['p_win']} "
                f"rr={result['risk_reward_ratio']} (attempt {attempt})"
            )
            return result

        except anthropic.RateLimitError:
            wait = 2 ** attempt
            logger.warning(f"Claude rate limited for {ticker} — waiting {wait}s (attempt {attempt})")
            last_error = "Rate limit exceeded"
            if attempt < max_retries:
                await asyncio.sleep(wait)
            continue

        except anthropic.APIStatusError as e:
            last_error = f"API error {e.status_code}"
            if e.status_code >= 500 and attempt < max_retries:
                logger.warning(f"Claude {last_error} for {ticker} — retrying")
                await asyncio.sleep(2 ** attempt)
                continue
            logger.error(f"Claude API status error for {ticker}: {last_error}")
            break

        except (json.JSONDecodeError, ValueError) as e:
            last_error = f"Bad response: {e}"
            logger.warning(f"Unusable Claude response for {ticker}: {e}")
            if parse_retry_used or "refused" in str(e):
                break
            parse_retry_used = True
            continue

        except Exception as e:
            last_error = f"Unexpected: {e}"
            logger.error(f"Claude call failed for {ticker}: {e}")
            break

    logger.warning(f"Claude returning fallback for {ticker} — {last_error}")
    return synthesis_error_response(last_error)
