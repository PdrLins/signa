"""Macro news pulse -- trending market topics from X + web via Grok, with
Claude (local CLI + web search, $0) as the fallback when Grok is unavailable.

Called once per scan to give the brain awareness of market-moving events
before they show up in price data. Uses the xAI Responses API with live
`x_search` (last N hours) + `web_search`; a response with no citations is
discarded (treated as unavailable) so hallucinated "trends" never reach
the synthesis prompt.
"""

from loguru import logger

from app.core.access import ai_guarded
from app.core.cache import TTLCache
from app.core.config import settings

_pulse_cache = TTLCache(max_size=1, default_ttl=1800)  # TTL set per call from settings


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


@ai_guarded("get_macro_pulse")
async def get_macro_pulse() -> dict:
    """Trending market topics, cached for settings.macro_pulse_cache_hours.

    Grok first (X + web). When it can't answer (no credit, paused, budget,
    error) and CLAUDE_LOCAL is on, Claude with web search answers instead.
    Either way a result without cited sources is discarded.

    Returns dict with:
    - trends: list of {topic, impact, sectors, detail}
    - summary: one-line market mood
    - citations: source URLs
    - source: "grok" | "claude"
    - error: set (and trends empty) when no source could answer
    """
    cached = _pulse_cache.get("pulse")
    if cached is not None:
        return cached

    result = await _grok_pulse()
    if result.get("error") and settings.claude_local and settings.macro_pulse_claude_fallback:
        logger.info(f"Macro pulse: Grok unavailable ({result['error'][:80]}) — asking Claude with web search")
        fallback = await _claude_pulse()
        if not fallback.get("error"):
            result = fallback
    if not result.get("error"):
        _pulse_cache.set("pulse", result, ttl=settings.macro_pulse_cache_hours * 3600)
    return result


async def _grok_pulse() -> dict:
    """Grok live-search market mood (budget-checked, cost recorded)."""
    from app.services.budget_service import BudgetService

    budget = await BudgetService.get_instance()
    allowed, reason = await budget.can_call("grok", "macro_pulse")
    if not allowed:
        logger.info(f"Macro pulse skipped — {reason}")
        return _unavailable(f"Grok budget: {reason}")

    from app.ai.grok_client import account_block

    blocked = account_block()
    if blocked:
        return _unavailable(blocked)

    recorded = False
    try:
        from app.ai.grok_client import (
            _get_client,
            build_search_request,
            extract_citations,
            extract_cost_usd,
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
        if resp.status_code >= 400:
            from app.ai.grok_client import _note_account_error
            _note_account_error(resp.status_code, resp.text)
            recorded = True  # rejected before any work: not billed
        resp.raise_for_status()
        data = resp.json()
        cost = extract_cost_usd(data)
        await budget.record_call("grok", "macro_pulse", "", success=True,
                                 **({"cost_usd": cost} if cost is not None else {}))
        recorded = True
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
            "source": "grok",
        }

        logger.info(f"Macro pulse: {mood} ({bullish} bullish, {bearish} bearish, {len(trends)} trends)")
        return result

    except Exception as e:
        logger.warning(f"Macro pulse failed: {e}")
        if not recorded:
            # A timeout may still be billed: count the estimate.
            await budget.record_call("grok", "macro_pulse", "", success=False)
        return _unavailable(str(e))


def _unavailable(error: str) -> dict:
    return {
        "trends": [],
        "summary": "Macro pulse unavailable",
        "bullish_count": 0,
        "bearish_count": 0,
        "raw": "",
        "citations": [],
        "error": error[:200],
    }


CLAUDE_PULSE_PROMPT = (
    "Search the web for news published between {from_date} and {to_date} UTC and "
    "list up to 5 market-moving trends for stock investors in Canada and the US: "
    "central bank decisions, inflation and jobs data, major earnings surprises, "
    "trade and geopolitical events, sector rotation. Report only trends you found "
    "in sources you actually retrieved, and give each one its source URLs. For each: "
    "topic (one line), impact on stocks (BULLISH, BEARISH or NEUTRAL), affected "
    "sectors or tickers, and one sentence of detail. If you find nothing reliable, "
    "return an empty list."
)

CLAUDE_PULSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "trends": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "impact": {"type": "string", "enum": ["BULLISH", "BEARISH", "NEUTRAL"]},
                    "sectors": {"type": "string"},
                    "detail": {"type": "string"},
                    "sources": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["topic", "impact", "sources"],
            },
        },
    },
    "required": ["trends"],
}


def build_claude_pulse(data: dict | None) -> dict:
    """Turn Claude's JSON into the pulse shape. Trends without an http(s)
    source are dropped; no sourced trend at all → unavailable."""
    trends = []
    citations: list[str] = []
    for t in (data or {}).get("trends") or []:
        if not isinstance(t, dict):
            continue
        urls = [u for u in (t.get("sources") or []) if isinstance(u, str) and u.startswith(("http://", "https://"))]
        if not urls or not str(t.get("topic") or "").strip():
            continue
        impact = t.get("impact") if t.get("impact") in ("BULLISH", "BEARISH", "NEUTRAL") else "NEUTRAL"
        trends.append({"topic": str(t["topic"]).strip()[:200], "impact": impact,
                       "sectors": str(t.get("sectors") or "")[:200], "detail": str(t.get("detail") or "")[:300]})
        citations.extend(u for u in urls if u not in citations)
    if not trends:
        return _unavailable("Claude web search returned no sourced trends")
    bullish = sum(1 for t in trends if t["impact"] == "BULLISH")
    bearish = sum(1 for t in trends if t["impact"] == "BEARISH")
    mood = ("Mostly bullish market news" if bullish > bearish
            else "Mostly bearish market news" if bearish > bullish else "Mixed market news")
    return {"trends": trends[:5], "summary": mood, "bullish_count": bullish, "bearish_count": bearish,
            "raw": "", "citations": citations[:20], "source": "claude"}


async def _claude_pulse() -> dict:
    """Market mood from Claude (local CLI) with only the WebSearch tool enabled."""
    from app.ai import claude_local_client
    from app.ai.grok_client import search_window
    from app.ai.provider import _record_local

    from_date, to_date = search_window()
    data = None
    try:
        data = await claude_local_client.call_with_prompt(
            CLAUDE_PULSE_PROMPT.format(from_date=from_date, to_date=to_date),
            max_retries=1, json_schema=CLAUDE_PULSE_SCHEMA, tools=("WebSearch",),
            timeout=settings.macro_pulse_claude_timeout_s,
        )
    except Exception as e:
        logger.warning(f"Macro pulse (Claude) failed: {e}")
    result = build_claude_pulse(data)
    await _record_local("claude-local", "macro_pulse", "", not result.get("error"))
    if not result.get("error"):
        logger.info(f"Macro pulse (Claude): {result['summary']} ({len(result['trends'])} trends)")
    return result
