"""Google Gemini client — free-tier fallback for synthesis AND sentiment.

============================================================
WHAT THIS MODULE IS
============================================================

Gemini sits at the BOTTOM of both AI fallback chains:

  Synthesis: Claude Local → Claude API → Gemini  ← here
  Sentiment: Grok → Gemini  ← here

The Gemini 2.0 Flash free tier allows 1,500 requests/day at $0 cost,
which is more than enough headroom for Signa's 60 synthesis calls/day.
This makes Gemini a reliable last-resort that doesn't burn budget.

The trade-off is quality: Gemini is less sophisticated than Claude
for nuanced financial analysis, and it has NO live X/Twitter access
(unlike Grok), so its sentiment analysis falls back to recent web
content rather than real-time social media. The brain reflects this
quality difference by treating low-confidence Gemini synthesis the
same as low-confidence Claude synthesis (Tier 2 instead of Tier 1).

============================================================
RATE LIMITING
============================================================

Despite the 1,500/day cap, Gemini has a per-MINUTE rate limit too
(15 req/min for 2.0-flash). When the entire scan pipeline cascades
to Gemini (e.g., Claude API outage + Claude Local broken), the burst
of ~15 parallel synthesis calls would hit the rate limit.

This module uses an asyncio.Semaphore(5) + 1-second delay between
calls to keep the rate well under the limit. The downside is slower
fallback runs (~3 seconds extra per scan); the upside is no 429s.

============================================================
RESPONSE SCHEMA
============================================================

Both `synthesize_signal` and `analyze_sentiment` return the same dict
shapes as their Claude/Grok counterparts so the router can swap them
transparently. See `claude_client.py` for the synthesis schema and
`grok_client.py` for the sentiment schema.
"""

import asyncio
import json
from typing import Optional

from loguru import logger

from app.ai.prompts import (
    CLAUDE_SYNTHESIS_PROMPT,
    GROK_SENTIMENT_PROMPT,
    GROK_SENTIMENT_SYSTEM,
    clean_json_response,
    format_fundamentals,
    format_macro,
    format_options_flow,
    format_sentiment,
    format_technicals,
)
from app.core.config import settings

_client = None
_client_lock = asyncio.Lock()

# Rate limiter: Gemini free tier = 5 req/min for 2.5-flash, 15/min for 2.0-flash.
# We use a semaphore + delay to stay under limit.
_rate_semaphore = asyncio.Semaphore(5)  # max 5 concurrent
_MIN_DELAY = 1.0  # seconds between requests (15/min limit on 2.0-flash)


def _get_client():
    """Get or create the Gemini client."""
    global _client
    if _client is not None:
        return _client

    from google import genai

    _client = genai.Client(api_key=settings.gemini_api_key)
    logger.info("Gemini API client initialized")
    return _client


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ─── Synthesis (replaces Claude) ───────────────────────────────

def _synthesis_error(ticker: str, reason: str) -> dict:
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
    """Call Gemini to synthesize all data into a final signal."""
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
            async with _rate_semaphore:
                await asyncio.sleep(_MIN_DELAY)  # throttle
                client = _get_client()
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=settings.gemini_model,
                    contents=prompt,
                )

            content = clean_json_response(response.text)
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
                f"Gemini [{ticker}] → {result['signal']} "
                f"confidence={result['confidence']} (attempt {attempt})"
            )
            return result

        except json.JSONDecodeError as e:
            last_error = f"JSON parse error: {e}"
            logger.error(f"Failed to parse Gemini response for {ticker}: {e}")
            break
        except Exception as e:
            last_error = str(e)
            is_rate_limit = "429" in last_error or "RESOURCE_EXHAUSTED" in last_error
            if is_rate_limit:
                # If daily quota exhausted, don't retry -- it won't recover
                if "FreeTier" in last_error or "quota" in last_error.lower():
                    logger.warning(f"Gemini daily quota exhausted for {ticker} -- skipping retries")
                    break
                wait = 15 * attempt
                logger.warning(f"Gemini rate limited for {ticker} -- waiting {wait}s (attempt {attempt})")
                if attempt < max_retries:
                    await asyncio.sleep(wait)
                continue
            logger.error(f"Gemini synthesis failed for {ticker}: {e}")
            if attempt < max_retries:
                await asyncio.sleep(2)
            continue

    logger.warning(f"Gemini returning synthesis fallback for {ticker} — {last_error}")
    return _synthesis_error(ticker, last_error)


# ─── Sentiment (replaces Grok) ─────────────────────────────────

def _sentiment_error(ticker: str, reason: str) -> dict:
    return {
        "ticker": ticker,
        "score": 50.0,
        "label": "neutral",
        "confidence": 0.0,
        "top_themes": [],
        "breaking_news": None,
        "notable_accounts": [],
        "summary": "",
        "error": reason,
    }


async def analyze_sentiment(ticker: str, max_retries: int = 2) -> dict:
    """Call Gemini to analyze sentiment for a ticker."""
    prompt = f"{GROK_SENTIMENT_SYSTEM}\n\n{GROK_SENTIMENT_PROMPT.format(ticker=ticker)}"

    last_error = ""
    for attempt in range(1, max_retries + 1):
        try:
            async with _rate_semaphore:
                await asyncio.sleep(_MIN_DELAY)
                client = _get_client()
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=settings.gemini_model,
                    contents=prompt,
                )

            content = clean_json_response(response.text)
            data = json.loads(content)

            result = {
                "ticker": ticker,
                "score": max(0.0, min(100.0, float(data.get("score", 50)))),
                "label": str(data.get("label", "neutral")).lower(),
                "confidence": max(0.0, min(100.0, float(data.get("confidence", 0)))),
                "top_themes": list(data.get("top_themes", []))[:3],
                "breaking_news": data.get("breaking_news"),
                "notable_accounts": list(data.get("notable_accounts", []))[:5],
                "summary": str(data.get("summary", "")),
                "error": None,
            }

            logger.debug(
                f"Gemini sentiment [{ticker}] → {result['label']} "
                f"score={result['score']} (attempt {attempt})"
            )
            return result

        except json.JSONDecodeError as e:
            last_error = f"JSON parse error: {e}"
            logger.error(f"Failed to parse Gemini sentiment for {ticker}: {e}")
            break
        except Exception as e:
            last_error = str(e)
            is_rate_limit = "429" in last_error or "RESOURCE_EXHAUSTED" in last_error
            if is_rate_limit:
                if "FreeTier" in last_error or "quota" in last_error.lower():
                    logger.warning(f"Gemini daily quota exhausted for sentiment {ticker} -- skipping retries")
                    break
                wait = 15 * attempt
                logger.warning(f"Gemini sentiment rate limited for {ticker} -- waiting {wait}s")
                if attempt < max_retries:
                    await asyncio.sleep(wait)
                continue
            logger.error(f"Gemini sentiment failed for {ticker}: {e}")
            if attempt < max_retries:
                await asyncio.sleep(2)
            continue

    logger.warning(f"Gemini returning sentiment fallback for {ticker} — {last_error}")
    return _sentiment_error(ticker, last_error)
