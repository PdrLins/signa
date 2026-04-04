"""Grok (xAI) client for X/Twitter sentiment analysis.

Uses the OpenAI-compatible API at api.x.ai/v1.
"""

import asyncio
import json
from typing import Optional

from loguru import logger
from openai import APIStatusError, AsyncOpenAI, RateLimitError

from app.ai.prompts import GROK_SENTIMENT_PROMPT, GROK_SENTIMENT_SYSTEM, clean_json_response
from app.core.config import settings

_client: Optional[AsyncOpenAI] = None
_client_lock = asyncio.Lock()


async def _get_client() -> AsyncOpenAI:
    """Get or create the Grok API client (async-safe double-checked locking)."""
    global _client
    if _client is not None:
        return _client
    async with _client_lock:
        if _client is not None:
            return _client
        _client = AsyncOpenAI(
            api_key=settings.xai_api_key,
            base_url=settings.grok_base_url,
        )
        logger.info("Grok API client initialized")
        return _client


def _validate_sentiment(data: dict, ticker: str) -> dict:
    """Validate and normalize a parsed sentiment response."""
    return {
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


def _error_response(ticker: str, reason: str) -> dict:
    """Return a consistent neutral fallback on failure."""
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


async def analyze_sentiment(ticker: str, max_retries: int = 3) -> dict:
    """Call Grok to analyze X/Twitter sentiment for a ticker.

    Args:
        ticker: Stock symbol (e.g., 'AAPL', 'SHOP.TO').
        max_retries: Maximum retry attempts on rate-limit errors.

    Returns:
        Dict with ticker, score, label, confidence, top_themes,
        breaking_news, notable_accounts, summary, error.
    """
    client = await _get_client()
    last_error = ""

    for attempt in range(1, max_retries + 1):
        try:
            response = await client.chat.completions.create(
                model=settings.grok_model,
                messages=[
                    {"role": "system", "content": GROK_SENTIMENT_SYSTEM},
                    {"role": "user", "content": GROK_SENTIMENT_PROMPT.format(ticker=ticker)},
                ],
                temperature=0.3,
                max_tokens=800,
            )

            content = clean_json_response(response.choices[0].message.content)
            data = json.loads(content)
            result = _validate_sentiment(data, ticker)

            logger.debug(
                f"Grok [{ticker}] → {result['label']} "
                f"score={result['score']} conf={result['confidence']} "
                f"(attempt {attempt})"
            )
            return result

        except RateLimitError as e:
            wait = 2 ** attempt
            logger.warning(
                f"Grok rate limited for {ticker} — "
                f"waiting {wait}s (attempt {attempt}/{max_retries})"
            )
            last_error = f"Rate limit: {e}"
            if attempt < max_retries:
                await asyncio.sleep(wait)
            continue

        except APIStatusError as e:
            last_error = f"API error {e.status_code}: {e.message}"
            logger.error(f"Grok API status error for {ticker}: {last_error}")
            break

        except json.JSONDecodeError as e:
            last_error = f"JSON parse error: {e}"
            logger.error(f"Failed to parse Grok response for {ticker}: {e}")
            break

        except Exception as e:
            last_error = f"Unexpected error: {e}"
            logger.error(f"Grok call failed for {ticker}: {e}")
            break

    logger.warning(f"Grok returning neutral fallback for {ticker} — {last_error}")
    return _error_response(ticker, last_error)
