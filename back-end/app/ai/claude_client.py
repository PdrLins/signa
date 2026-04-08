"""Claude (Anthropic) client for signal synthesis.

Takes all collected data and asks Claude to produce a final investment signal.
"""

import asyncio
import json
from typing import Optional

import anthropic
from loguru import logger

from app.ai.prompts import (
    CLAUDE_SYNTHESIS_PROMPT,
    clean_json_response,
    format_fundamentals,
    format_macro,
    format_options_flow,
    format_sentiment,
    format_technicals,
)
from app.core.config import settings

_client: Optional[anthropic.AsyncAnthropic] = None
_client_lock = asyncio.Lock()


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
    """Call Claude to synthesize all data into a final signal.

    Includes retry logic with exponential backoff for rate limits.
    """
    client = await _get_client()

    prompt = CLAUDE_SYNTHESIS_PROMPT.format(
        ticker=ticker,
        technicals=format_technicals(technical_data),
        fundamentals=format_fundamentals(fundamental_data),
        macro=format_macro(macro_data),
        sentiment=format_sentiment(grok_data),
        options_flow=format_options_flow(grok_data),
        market_regime=grok_data.get("_market_regime", "TRENDING") if isinstance(grok_data, dict) else "TRENDING",
        regime_note=grok_data.get("_regime_note", "") if isinstance(grok_data, dict) else "",
        catalyst_context=grok_data.get("_catalyst_context", "No specific catalyst detected") if isinstance(grok_data, dict) else "No specific catalyst detected",
        knowledge_block=grok_data.get("_knowledge_block", "") if isinstance(grok_data, dict) else "",
    )

    last_error = ""

    for attempt in range(1, max_retries + 1):
        try:
            response = await client.messages.create(
                model=settings.claude_model,
                max_tokens=settings.claude_max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )

            content = clean_json_response(response.content[0].text)
            data = json.loads(content)

            # Validate signal against allowed values
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
                f"Claude [{ticker}] → {result['signal']} "
                f"confidence={result['confidence']} rr={result['risk_reward_ratio']} "
                f"(attempt {attempt})"
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
            logger.error(f"Claude API status error for {ticker}: {last_error}")
            break

        except json.JSONDecodeError as e:
            last_error = f"JSON parse error: {e}"
            logger.error(f"Failed to parse Claude response for {ticker}: {e}")
            break

        except Exception as e:
            last_error = f"Unexpected: {e}"
            logger.error(f"Claude call failed for {ticker}: {e}")
            break

    logger.warning(f"Claude returning fallback for {ticker} — {last_error}")
    return _error_response(ticker, last_error)
