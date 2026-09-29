"""Google Gemini client — free-tier fallback for synthesis AND sentiment.

============================================================
WHAT THIS MODULE IS
============================================================

Gemini sits at the BOTTOM of both AI fallback chains:

  Synthesis: Claude Local → Claude API → Gemini  ← here
  Sentiment: Grok → Gemini  ← here

The Gemini Flash free tier allows 1,500 requests/day at $0 cost,
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
    GROK_SENTIMENT_PROMPT,
    GROK_SENTIMENT_SYSTEM,
    build_synthesis_prompt,
    clean_json_response,
    normalize_synthesis_result,
    synthesis_error_response,
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


# ─── Synthesis (replaces Claude) ───────────────────────────────

async def synthesize_signal(
    ticker: str,
    technical_data: dict,
    fundamental_data: dict,
    macro_data: dict,
    grok_data: dict,
    max_retries: int = 3,
) -> dict:
    """Call Gemini to synthesize all data into a final signal."""
    from google.genai import types

    prompt = build_synthesis_prompt(
        ticker, technical_data, fundamental_data, macro_data, grok_data,
    )
    current_price = (technical_data or {}).get("current_price")
    config = types.GenerateContentConfig(response_mime_type="application/json")

    last_error = ""
    parse_retry_used = False
    for attempt in range(1, max_retries + 1):
        try:
            async with _rate_semaphore:
                await asyncio.sleep(_MIN_DELAY)  # throttle
                client = _get_client()
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=settings.gemini_model,
                    contents=prompt,
                    config=config,
                )

            data = json.loads(clean_json_response(response.text or ""))
            result = normalize_synthesis_result(data, current_price=current_price)
            if result.get("error"):
                raise ValueError(result["error"])

            logger.debug(
                f"Gemini [{ticker}] → {result['signal']} "
                f"confidence={result['confidence']} (attempt {attempt})"
            )
            return result

        except (json.JSONDecodeError, ValueError) as e:
            last_error = f"Bad response: {e}"
            logger.warning(f"Unusable Gemini synthesis for {ticker}: {e}")
            if parse_retry_used:
                break
            parse_retry_used = True
            continue
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
    return synthesis_error_response(last_error)


# ─── Sentiment (replaces Grok) ─────────────────────────────────
#
# Gemini has no X/Twitter access. It is grounded with Google Search
# (restricted to the same 48h window) and the result is only accepted
# when the response carries grounding sources. `mention_count` is always
# 0 (no X data), so the signal engine collapses the sentiment weight.

def _sentiment_error(ticker: str, reason: str) -> dict:
    return {
        "ticker": ticker,
        "score": 50.0,
        "label": "neutral",
        "confidence": 0.0,
        "mention_count": 0,
        "top_themes": [],
        "breaking_news": None,
        "breaking_news_url": None,
        "red_flags": [],
        "notable_accounts": [],
        "summary": "",
        "citations": [],
        "error": reason,
    }


def _grounding_urls(response) -> list[str]:
    urls: list[str] = []
    for cand in getattr(response, "candidates", None) or []:
        meta = getattr(cand, "grounding_metadata", None)
        for chunk in getattr(meta, "grounding_chunks", None) or []:
            web = getattr(chunk, "web", None)
            uri = getattr(web, "uri", None)
            if uri and uri not in urls:
                urls.append(uri)
    return urls


async def analyze_sentiment(ticker: str, max_retries: int = 2) -> dict:
    """Call Gemini (Google Search grounded) to analyze news sentiment for a ticker."""
    from datetime import datetime, timedelta, timezone

    from google.genai import types

    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=settings.grok_search_window_hours)
    prompt = (
        f"{GROK_SENTIMENT_SYSTEM}\n\n"
        f"{GROK_SENTIMENT_PROMPT.format(ticker=ticker, from_date=start.date().isoformat(), to_date=now.date().isoformat())}\n"
        "You only have web search (no X access): set mention_count to 0 and "
        "notable_accounts to []."
    )
    config = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch(
            time_range_filter=types.Interval(start_time=start, end_time=now),
        ))],
    )

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
                    config=config,
                )

            citations = _grounding_urls(response)
            if not citations:
                return _sentiment_error(ticker, "No grounding sources returned — sentiment unverified")
            data = json.loads(clean_json_response(response.text or ""))
            if not isinstance(data, dict):
                raise json.JSONDecodeError("not an object", response.text or "", 0)

            # Grounding URIs are redirect links, so model-provided URLs can't
            # be matched against them. Keep cited items only when the model
            # attached a URL, and rely on grounding presence for the rest.
            news = data.get("breaking_news")
            news_url = data.get("breaking_news_url")
            if not (isinstance(news, str) and news.strip() and isinstance(news_url, str) and news_url.startswith("http")):
                news, news_url = None, None
            red_flags = [
                {"text": str(f["text"])[:200], "url": f["url"]}
                for f in (data.get("red_flags") or [])
                if isinstance(f, dict) and f.get("text") and isinstance(f.get("url"), str) and f["url"].startswith("http")
            ]
            label = str(data.get("label", "neutral")).lower()
            if label not in ("bullish", "neutral", "bearish"):
                label = "neutral"

            def _num(v, default):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return default

            result = {
                "ticker": ticker,
                "score": max(0.0, min(100.0, _num(data.get("score"), 50.0))),
                "label": label,
                "confidence": max(0.0, min(100.0, _num(data.get("confidence"), 0.0))),
                "mention_count": 0,
                "top_themes": [str(t) for t in (data.get("top_themes") or [])][:3],
                "breaking_news": news,
                "breaking_news_url": news_url,
                "red_flags": red_flags,
                "notable_accounts": [],
                "summary": str(data.get("summary") or ""),
                "citations": citations[:20],
                "error": None,
            }

            logger.debug(
                f"Gemini sentiment [{ticker}] → {result['label']} "
                f"score={result['score']} sources={len(citations)} (attempt {attempt})"
            )
            return result

        except json.JSONDecodeError as e:
            last_error = f"JSON parse error: {e}"
            logger.warning(f"Failed to parse Gemini sentiment for {ticker}: {e}")
            continue
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
