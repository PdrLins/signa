"""Grok (xAI) client for live X + web sentiment analysis.

Uses the xAI Responses API (`POST {grok_base_url}/responses`) with the
server-side `x_search` (date-restricted to the last N hours) and
`web_search` tools, so the model reads real posts/articles instead of
hallucinating from training data.

A result is only usable when the API returned at least one citation.
Without citations the result is marked with `error` and `confidence=0`
so the router falls through and nothing downstream treats it as evidence.
Every URL the model puts in its JSON (breaking news, red flags) is kept
only if it appears in the API's citation list.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from loguru import logger

from app.ai.prompts import GROK_SENTIMENT_PROMPT, GROK_SENTIMENT_SYSTEM, clean_json_response
from app.core.config import settings

_client: Optional[httpx.AsyncClient] = None
_client_lock = asyncio.Lock()


async def _get_client() -> httpx.AsyncClient:
    """Get or create the shared HTTP client (async-safe)."""
    global _client
    if _client is not None:
        return _client
    async with _client_lock:
        if _client is not None:
            return _client
        _client = httpx.AsyncClient(timeout=settings.grok_timeout_s)
        logger.info("Grok (xAI Responses API) client initialized")
        return _client


def search_window(hours: int | None = None) -> tuple[str, str]:
    """Return (from_date, to_date) as YYYY-MM-DD strings (UTC)."""
    now = datetime.now(timezone.utc)
    hours = hours if hours is not None else settings.grok_search_window_hours
    return (now - timedelta(hours=hours)).date().isoformat(), now.date().isoformat()


def build_search_request(prompt: str, system: str | None = None, max_output_tokens: int = 4000) -> dict:
    """Build a Responses API body with live X + web search enabled."""
    from_date, to_date = search_window()
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return {
        "model": settings.grok_model,
        "input": messages,
        "tools": [
            {"type": "x_search", "from_date": from_date, "to_date": to_date},
            {"type": "web_search"},
        ],
        # Inline citation markers would corrupt the JSON body; sources are
        # still returned in `citations` / annotations.
        "include": ["no_inline_citations"],
        "max_turns": settings.grok_max_turns,
        "max_output_tokens": max_output_tokens,
    }


def extract_output_text(data: dict) -> str:
    """Concatenate all `output_text` blocks from a Responses API payload."""
    if isinstance(data.get("output_text"), str) and data["output_text"].strip():
        return data["output_text"]
    parts: list[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for block in item.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "output_text":
                parts.append(block.get("text") or "")
    return "\n".join(parts)


def extract_citations(data: dict) -> list[str]:
    """Collect cited source URLs (top-level `citations` + url_citation annotations)."""
    urls: list[str] = []

    def _add(u: Any) -> None:
        if isinstance(u, dict):
            u = u.get("url") or u.get("uri")
        if isinstance(u, str) and u.startswith(("http://", "https://")) and u not in urls:
            urls.append(u)

    for c in data.get("citations") or []:
        _add(c)
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        for block in item.get("content") or []:
            if not isinstance(block, dict):
                continue
            for ann in block.get("annotations") or []:
                if isinstance(ann, dict) and ann.get("type") == "url_citation":
                    _add(ann.get("url"))
    return urls


def _norm_url(u: str) -> str:
    return u.strip().rstrip("/").lower()


def _is_cited(url: Any, cited: set[str]) -> bool:
    return isinstance(url, str) and _norm_url(url) in cited


def _is_x_url(u: str) -> bool:
    host = (urlparse(u).hostname or "").lower()
    return host in ("x.com", "twitter.com") or host.endswith((".x.com", ".twitter.com"))


def _validate_sentiment(data: dict, ticker: str, citations: list[str]) -> dict:
    """Validate and normalize a parsed sentiment response against citations."""
    if not citations:
        return _error_response(ticker, "No citations returned by live search — sentiment unverified")

    cited = {_norm_url(u) for u in citations}

    breaking = data.get("breaking_news")
    breaking_url = data.get("breaking_news_url")
    if not (isinstance(breaking, str) and breaking.strip() and _is_cited(breaking_url, cited)):
        breaking, breaking_url = None, None

    red_flags = []
    for flag in data.get("red_flags") or []:
        if isinstance(flag, dict) and flag.get("text") and _is_cited(flag.get("url"), cited):
            red_flags.append({"text": str(flag["text"])[:200], "url": flag["url"]})

    try:
        mention_count = max(0, int(float(data.get("mention_count") or 0)))
    except (TypeError, ValueError):
        mention_count = 0
    x_citations = sum(1 for u in citations if _is_x_url(u))
    if x_citations == 0:
        # The model can't claim X volume it never retrieved.
        mention_count = 0

    label = str(data.get("label", "neutral")).lower()
    if label not in ("bullish", "neutral", "bearish"):
        label = "neutral"

    def _num(v: Any, default: float) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    return {
        "ticker": ticker,
        "score": max(0.0, min(100.0, _num(data.get("score"), 50.0))),
        "label": label,
        "confidence": max(0.0, min(100.0, _num(data.get("confidence"), 0.0))),
        "mention_count": mention_count,
        "top_themes": [str(t) for t in (data.get("top_themes") or [])][:3],
        "breaking_news": breaking,
        "breaking_news_url": breaking_url,
        "red_flags": red_flags,
        "notable_accounts": [str(a) for a in (data.get("notable_accounts") or [])][:5],
        "summary": str(data.get("summary") or ""),
        "citations": citations[:20],
        "x_citation_count": x_citations,
        "error": None,
    }


def _error_response(ticker: str, reason: str) -> dict:
    """Return a consistent neutral, zero-confidence fallback on failure."""
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
        "x_citation_count": 0,
        "error": reason,
    }


async def analyze_sentiment(ticker: str, max_retries: int = 3) -> dict:
    """Call Grok with live X + web search to analyze sentiment for a ticker.

    Returns the sentiment dict (score, label, confidence, mention_count,
    top_themes, breaking_news, red_flags, notable_accounts, summary,
    citations, error). `error` is set (and confidence=0) when the call
    failed or returned no citations.
    """
    client = await _get_client()
    from_date, to_date = search_window()
    prompt = GROK_SENTIMENT_PROMPT.format(ticker=ticker, from_date=from_date, to_date=to_date)
    body = build_search_request(prompt, system=GROK_SENTIMENT_SYSTEM)
    headers = {
        "Authorization": f"Bearer {settings.xai_api_key}",
        "Content-Type": "application/json",
    }
    last_error = ""
    parse_retry_used = False

    for attempt in range(1, max_retries + 1):
        try:
            resp = await client.post(f"{settings.grok_base_url}/responses", headers=headers, json=body)
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = 2 ** attempt
                last_error = f"HTTP {resp.status_code}"
                logger.warning(f"Grok {last_error} for {ticker} — waiting {wait}s (attempt {attempt}/{max_retries})")
                if attempt < max_retries:
                    await asyncio.sleep(wait)
                continue
            if resp.status_code >= 400:
                last_error = f"API error {resp.status_code}: {resp.text[:300]}"
                logger.error(f"Grok API status error for {ticker}: {last_error}")
                break

            data = resp.json()
            text = extract_output_text(data)
            citations = extract_citations(data)
            parsed = json.loads(clean_json_response(text))
            if not isinstance(parsed, dict):
                raise json.JSONDecodeError("not an object", text, 0)
            result = _validate_sentiment(parsed, ticker, citations)
            logger.debug(
                f"Grok [{ticker}] → {result['label']} score={result['score']} "
                f"conf={result['confidence']} mentions={result['mention_count']} "
                f"citations={len(citations)} err={result['error']} (attempt {attempt})"
            )
            return result

        except json.JSONDecodeError as e:
            last_error = f"JSON parse error: {e}"
            logger.warning(f"Failed to parse Grok response for {ticker}: {e}")
            if parse_retry_used:
                break
            parse_retry_used = True
            continue

        except httpx.HTTPError as e:
            last_error = f"HTTP error: {e}"
            logger.warning(f"Grok transport error for {ticker}: {e} (attempt {attempt}/{max_retries})")
            if attempt < max_retries:
                await asyncio.sleep(2 ** attempt)
            continue

        except Exception as e:
            last_error = f"Unexpected error: {e}"
            logger.error(f"Grok call failed for {ticker}: {e}")
            break

    logger.warning(f"Grok returning neutral fallback for {ticker} — {last_error}")
    return _error_response(ticker, last_error or "Grok failed")
