"""Macro news pulse -- fetches trending market topics from X + web via Grok.

Called once per scan to give the brain awareness of market-moving events
before they show up in price data. Uses the xAI Responses API with live
`x_search` (last N hours) + `web_search`; a response with no citations is
discarded (treated as unavailable) so hallucinated "trends" never reach
the synthesis prompt.
"""

from loguru import logger

from app.core.cache import TTLCache
from app.core.config import settings

_pulse_cache = TTLCache(max_size=1, default_ttl=1800)


MACRO_PULSE_PROMPT = (
    "Using your X search and web search tools (only posts/articles from "
    "{from_date} to {to_date} UTC), what are the top 5 market-moving trends right now? "
    "Only report trends you found in retrieved sources; if fewer than 5, list fewer. "
    "Focus on: geopolitical events (wars, sanctions, trade deals), "
    "Fed/central bank actions, major earnings surprises, sector rotation signals, "
    "and any viral financial news. For each trend, give: "
    "1) The topic (1 line), "
    "2) Market impact: BULLISH / BEARISH / NEUTRAL, "
    "3) Affected sectors or tickers. "
    "Be concise. No disclaimers."
)


async def get_macro_pulse() -> dict:
    """Fetch trending market topics from Grok. Cached for 30 min.

    Returns dict with:
    - trends: list of {topic, impact, sectors}
    - summary: one-line market mood
    - raw: full Grok response text
    """
    cached = _pulse_cache.get("pulse")
    if cached is not None:
        return cached

    try:
        from app.ai.grok_client import (
            _get_client,
            build_search_request,
            extract_citations,
            extract_output_text,
            search_window,
        )

        from_date, to_date = search_window()
        body = build_search_request(
            MACRO_PULSE_PROMPT.format(from_date=from_date, to_date=to_date),
            max_output_tokens=3000,
        )
        client = await _get_client()
        resp = await client.post(
            f"{settings.grok_base_url}/responses",
            headers={
                "Authorization": f"Bearer {settings.xai_api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
        content = extract_output_text(data)
        citations = extract_citations(data)
        if not citations or not content.strip():
            raise ValueError("live search returned no citations — pulse unverified")

        # Parse trends from response
        trends = []
        lines = content.strip().split("\n")
        current_trend = {}
        for line in lines:
            line = line.strip()
            if not line:
                if current_trend:
                    trends.append(current_trend)
                    current_trend = {}
                continue
            lower = line.lower()
            if any(lower.startswith(f"{i})") or lower.startswith(f"{i}.") for i in range(1, 6)):
                if current_trend:
                    trends.append(current_trend)
                current_trend = {"topic": line.lstrip("0123456789.)- ").strip()}
            elif "bullish" in lower:
                current_trend["impact"] = "BULLISH"
                current_trend["detail"] = line
            elif "bearish" in lower:
                current_trend["impact"] = "BEARISH"
                current_trend["detail"] = line
            elif "neutral" in lower:
                current_trend["impact"] = "NEUTRAL"
                current_trend["detail"] = line
            elif "sector" in lower or "ticker" in lower or "affect" in lower:
                current_trend["sectors"] = line
            elif current_trend and "topic" in current_trend and "impact" not in current_trend:
                current_trend["topic"] += " " + line
        if current_trend:
            trends.append(current_trend)

        # Generate summary
        bullish = sum(1 for t in trends if t.get("impact") == "BULLISH")
        bearish = sum(1 for t in trends if t.get("impact") == "BEARISH")
        if bullish > bearish:
            mood = "Mostly bullish trends on X/Twitter"
        elif bearish > bullish:
            mood = "Mostly bearish trends on X/Twitter"
        else:
            mood = "Mixed sentiment on X/Twitter"

        result = {
            "trends": trends[:5],
            "summary": mood,
            "bullish_count": bullish,
            "bearish_count": bearish,
            "raw": content,
            "citations": citations[:20],
        }

        logger.info(f"Macro pulse: {mood} ({bullish} bullish, {bearish} bearish, {len(trends)} trends)")
        _pulse_cache.set("pulse", result)
        return result

    except Exception as e:
        logger.warning(f"Macro pulse failed: {e}")
        return {
            "trends": [],
            "summary": "Macro pulse unavailable",
            "bullish_count": 0,
            "bearish_count": 0,
            "raw": "",
            "citations": [],
            "error": str(e)[:200],
        }
