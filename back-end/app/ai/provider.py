"""AI provider router — synthesis + sentiment.

============================================================
WHAT THIS MODULE IS
============================================================

Signa uses two AI providers for the pipeline (plus Codex as an optional
independent reviewer, see app/ai/codex_client.py). This module is the
single entry point for the rest of the codebase to call AI —
`scan_service` only ever calls `provider.synthesize_signal()` and
`provider.analyze_sentiment()`, never the individual provider clients.

  1. Iterate through `settings.synthesis_providers` (["claude"]) or
     `settings.sentiment_providers` (["grok"]) and try each one.
  2. Skip any provider whose budget is exhausted.

Gemini was removed (2026-09): there is no free fallback. A failure or a
capped budget returns an explicit error result that downstream code treats
as ai_status="failed" (synthesis) or a sentiment data gap (sentiment).

============================================================
SYNTHESIS
============================================================

`settings.claude_local: bool = True` picks exactly ONE way to reach
Claude — they never mix:

  claude_local=True   the local `claude` CLI only (subscription, $0).
                      The Anthropic API is never called.
  claude_local=False  the paid Anthropic API only, budget-checked before
                      every call.

============================================================
SENTIMENT
============================================================

GROK (paid, see budget_service.COST_ESTIMATES): xAI Responses API with
live x_search + web_search (last 48h). Results without citations come
back with `error` set and are not used. Successful results are cached
per ticker for settings.sentiment_cache_hours (shared by scans, "Check a
stock" and the holdings monitor).

============================================================
BUDGET ENFORCEMENT
============================================================

Every paid call goes through `BudgetService.can_call()` (or a prior
`reserve()`, used by the scan to hand the daily Grok budget to its best
candidates first) BEFORE being made; `record_call()` updates the totals
and fires the 70/90/100% Telegram alerts.
"""

from loguru import logger

from app.core.cache import TTLCache
from app.core.config import settings

# Per-ticker AI result caches. Scans run several times a day and mostly see
# the same candidates; re-asking about an unchanged ticker is pure cost.
_sentiment_cache = TTLCache(max_size=500, default_ttl=3600)
_synthesis_cache = TTLCache(max_size=500, default_ttl=3600)
_decision_cache = TTLCache(max_size=200, default_ttl=3600)


def clear_ai_caches() -> None:
    _sentiment_cache.clear()
    _synthesis_cache.clear()
    _decision_cache.clear()


def _cached_synthesis(cache: TTLCache, ticker: str, current_price) -> dict | None:
    """A recent synthesis for `ticker`, unless price has since moved more
    than synthesis_cache_max_move_pct (stale levels / changed setup)."""
    entry = cache.get(ticker)
    if entry is None:
        return None
    result, price_then = entry
    try:
        move_pct = abs(float(current_price) / float(price_then) - 1) * 100
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if move_pct > settings.synthesis_cache_max_move_pct:
        return None
    return {**result, "_cached": True}


async def _record_local(provider_name: str, call_type: str, ticker: str, success: bool) -> None:
    """Log a local-CLI call ($0) for the usage breakdown; never raises."""
    try:
        budget = await _get_budget()
        await budget.record_call(provider_name, call_type, ticker, success=bool(success))
    except Exception as e:
        logger.debug(f"local usage record skipped ({provider_name}): {e}")


async def _get_budget():
    """Lazy-load budget service to avoid circular imports."""
    from app.services.budget_service import BudgetService
    return await BudgetService.get_instance()


async def synthesize_signal(
    ticker: str,
    technical_data: dict,
    fundamental_data: dict,
    macro_data: dict,
    grok_data: dict,
    tier: str = "routine",
) -> dict:
    """Route synthesis to the first available provider within budget.

    tier="routine" (default) uses settings.claude_model; tier="decision" is
    the final BUY confirmation on settings.claude_decision_model. Both tiers
    cache per ticker for synthesis_cache_hours, invalidated when price moves
    more than synthesis_cache_max_move_pct.

    claude_local=True:  Claude CLI ($0) only.
    claude_local=False: Claude API (paid, budget-checked) only.
    """
    cache = _decision_cache if tier == "decision" else _synthesis_cache
    current_price = (technical_data or {}).get("current_price")
    if settings.synthesis_cache_hours > 0:
        cached = _cached_synthesis(cache, ticker, current_price)
        if cached is not None:
            logger.debug(f"Synthesis cache hit for {ticker} ({tier})")
            return cached

    result = await _route_synthesis(
        ticker, technical_data, fundamental_data, macro_data, grok_data, tier,
    )
    if not result.get("error") and settings.synthesis_cache_hours > 0 and current_price:
        cache.set(ticker, (result, current_price), ttl=settings.synthesis_cache_hours * 3600)
    return result


async def _route_synthesis(
    ticker: str,
    technical_data: dict,
    fundamental_data: dict,
    macro_data: dict,
    grok_data: dict,
    tier: str,
) -> dict:
    decision = tier == "decision"
    providers = ["claude"] if decision else settings.synthesis_providers
    budget_call_type = "decision" if decision else "synthesis"
    provider_suffix = "-decision" if decision else ""
    budget = await _get_budget()

    for provider in providers:
        if provider == "claude":
            # Tier 1: Claude Local CLI (free, retried internally)
            if settings.claude_local:
                try:
                    from app.ai.claude_local_client import synthesize_signal as claude_local_synth
                    result = await claude_local_synth(
                        ticker, technical_data, fundamental_data, macro_data, grok_data, tier=tier,
                    )
                    await _record_local("claude-local", "decision" if decision else "synthesis",
                                        ticker, not result.get("error"))
                    if not result.get("error"):
                        result["_provider"] = "claude-local" + provider_suffix
                        return result
                    logger.warning(
                        f"Claude Local exhausted retries for {ticker}: {result.get('error')} "
                        f"— API disabled in local mode, trying next provider"
                    )
                except (KeyError, TypeError, AttributeError, ImportError, NameError) as e:
                    # Permanent code bugs (template mismatch, missing import, etc).
                    # Logged at ERROR so they're impossible to miss — historically a
                    # silent WARNING here masked a `KeyError: 'options_flow'` that
                    # caused EVERY synthesis call to silently cascade to the paid
                    # API, burning thousands of tokens before the user noticed.
                    logger.error(
                        f"Claude Local synthesis CODE BUG for {ticker}: {type(e).__name__}: {e} "
                        f"— this is NOT a transient error and will fail every call until fixed. "
                        f"Check claude_local_client.py vs prompts.py."
                    )
                except Exception as e:
                    logger.warning(f"Claude Local synthesis error for {ticker}: {e} — trying next provider")
                # Local mode never touches the paid API.
                continue

            # API mode (claude_local=False)
            allowed, reason = await budget.can_call("claude", budget_call_type)
            if not allowed:
                logger.warning(f"Budget blocked Claude API {budget_call_type} for {ticker}: {reason}")
            elif settings.anthropic_api_key:
                try:
                    from app.ai.claude_client import synthesize_signal as claude_synth
                    result = await claude_synth(
                        ticker, technical_data, fundamental_data, macro_data, grok_data, tier=tier,
                    )
                    if not result.get("error"):
                        result["_provider"] = "claude" + provider_suffix
                        await budget.record_call("claude", budget_call_type, ticker, success=True)
                        return result
                    logger.warning(f"Claude API failed for {ticker}: {result.get('error')} — trying next provider")
                    await budget.record_call("claude", budget_call_type, ticker, success=False)
                except Exception as e:
                    logger.warning(f"Claude API synthesis error for {ticker}: {e}")
            continue


    # All providers failed or over budget — return generic fallback
    logger.error(f"All synthesis providers failed/blocked for {ticker}")
    return {
        "signal": "HOLD",
        "confidence": 0,
        "p_win": None,
        "reasoning": "Analysis temporarily unavailable — all AI providers failed or budget exceeded",
        "risk_factors": [],
        "catalyst": None,
        "catalyst_date": None,
        "red_flags": [],
        "risk_reward_ratio": None,
        "target_price": None,
        "stop_loss": None,
        "sentiment_weight": 0,
        "error": "All providers failed or budget exceeded",
        "_provider": "none",
    }


def get_cached_sentiment(ticker: str) -> dict | None:
    """A cached (successful) sentiment result for `ticker`, or None. Never
    calls a provider — used by the holdings monitor to reuse the Grok
    answer a scan / check already paid for."""
    if settings.sentiment_cache_hours <= 0:
        return None
    cached = _sentiment_cache.get(ticker)
    return {**cached, "_cached": True} if cached is not None else None


def sentiment_unavailable(ticker: str, reason: str) -> dict:
    """Neutral, zero-confidence sentiment with `error` set: the prompt
    labels it a data gap (see prompts.format_sentiment)."""
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
        "_provider": "none",
    }


async def analyze_sentiment(
    ticker: str,
    market_cap: float | None = None,
    budget_reserved: bool = False,
) -> dict:
    """Route sentiment analysis to the first available provider within budget.

    Successful results are cached per ticker for sentiment_cache_hours — the
    search window is 48h, so re-searching X every scan buys almost nothing.

    budget_reserved=True: the caller already reserved one Grok sentiment
    call with BudgetService.reserve() (the scan does this in candidate-rank
    order). The reservation is consumed by the call, or released on a cache
    hit / when Grok is not reached.
    """
    if settings.sentiment_cache_hours > 0:
        cached = _sentiment_cache.get(ticker)
        if cached is not None:
            if budget_reserved:
                budget = await _get_budget()
                await budget.release("grok", "sentiment")
            return {**cached, "_cached": True}
    # _route_sentiment consumes or releases a reservation on every path.
    if budget_reserved:
        result = await _route_sentiment(ticker, market_cap, reserved=True)
    else:
        result = await _route_sentiment(ticker, market_cap)
    if not result.get("error") and settings.sentiment_cache_hours > 0:
        _sentiment_cache.set(ticker, result, ttl=settings.sentiment_cache_hours * 3600)
    return result


async def _route_sentiment(ticker: str, market_cap: float | None = None,
                           providers: list[str] | None = None, reserved: bool = False) -> dict:
    providers = providers if providers is not None else settings.sentiment_providers
    budget = await _get_budget()
    reservation_open = reserved

    try:
        for provider in providers:
            if provider != "grok":
                continue  # the only sentiment provider
            if not settings.xai_api_key:
                continue
            if reservation_open:
                # Budget was reserved up front; recording the call replaces it.
                reservation_open = False
                await budget.release("grok", "sentiment")
            else:
                allowed, reason = await budget.can_call("grok", "sentiment")
                if not allowed:
                    logger.warning(f"Budget blocked grok sentiment for {ticker}: {reason}")
                    return sentiment_unavailable(ticker, "Grok budget exhausted — sentiment unavailable")
            try:
                from app.ai.grok_client import analyze_sentiment as grok_sent
                result = await grok_sent(ticker, market_cap=market_cap)
                if not result.get("error"):
                    result["_provider"] = "grok"
                    await budget.record_call("grok", "sentiment", ticker, success=True)
                    return result
                logger.debug(f"Grok failed for {ticker}: {result.get('error')}")
                await budget.record_call("grok", "sentiment", ticker, success=False)
            except Exception as e:
                logger.warning(f"Provider grok sentiment error for {ticker}: {e}")
    finally:
        if reservation_open:
            await budget.release("grok", "sentiment")

    logger.warning(f"All sentiment providers failed/blocked for {ticker}")
    return sentiment_unavailable(ticker, "All providers failed or budget exceeded")


# ============================================================
# THESIS RE-EVALUATION (Stage 6)
# ============================================================
#
# Lighter than synthesize_signal — same CLAUDE_LOCAL routing (CLI only, or
# budget-checked API only). If Claude is unavailable we return None and the thesis tracker treats the position as "not
# re-evaluated this scan" (existing exit gates fall back to no thesis check).

async def re_evaluate_thesis(
    symbol: str,
    entry_date: str,
    entry_price: float,
    current_price: float,
    pnl_pct: float,
    days_held: int,
    entry_thesis: str,
    entry_conditions: dict,
    current_conditions: dict,
    prior_status: str | None = None,
    prior_reason: str | None = None,
) -> dict | None:
    """Ask Claude whether the original thesis for an open position still holds.

    Returns a parsed dict like:
        {"status": "valid"|"weakening"|"invalid",
         "confidence": int,
         "reason": str,
         "should_exit": bool,
         "current_thesis": str|None}

    Returns None on hard failure (both Claude tiers down). Callers must
    treat None as "no re-eval this scan" — leave any prior thesis_last_*
    fields in place; do NOT clear them.
    """
    from app.ai.prompts import (
        THESIS_REEVAL_JSON_SCHEMA,
        THESIS_REEVAL_PROMPT,
        UNTRUSTED_NOTICE,
        _safe_int,
        wrap_untrusted,
    )

    def _format_conditions(d: dict) -> str:
        if not d:
            return "(no data)"
        lines = []
        for k, v in d.items():
            if v is None:
                continue
            # Defense against prompt-injection via untrusted string fields
            # (e.g., Grok's sentiment_label could theoretically contain
            # "\n\nIGNORE PRIOR INSTRUCTIONS"). For strings, strip newlines
            # and truncate to a safe length. Numbers/bools pass through.
            if isinstance(v, str):
                v = v.replace("\n", " ").replace("\r", " ")[:100]
            lines.append(f"- {k}: {v}")
        return "\n".join(lines) if lines else "(no data)"

    if prior_status or prior_reason:
        safe_prior_reason = (prior_reason or "").replace("\n", " ").replace("\r", " ")[:500]
        prior_block = (
            f"Status: {prior_status or 'unknown'}\n"
            f"Reasoning: {safe_prior_reason or '(no reason recorded)'}"
        )
    else:
        prior_block = "(first re-evaluation — no prior state)"

    prompt = THESIS_REEVAL_PROMPT.format(
        symbol=symbol,
        entry_date=entry_date[:10] if entry_date else "?",
        days_held=days_held,
        entry_price=entry_price,
        current_price=current_price,
        pnl_pct=pnl_pct,
        untrusted_notice=UNTRUSTED_NOTICE,
        entry_thesis=wrap_untrusted("entry_thesis", entry_thesis or "(no thesis recorded)"),
        entry_conditions=wrap_untrusted("entry_conditions", _format_conditions(entry_conditions)),
        prior_reeval_block=wrap_untrusted("prior_reeval", prior_block),
        current_conditions=wrap_untrusted("current_conditions", _format_conditions(current_conditions)),
    )

    budget = await _get_budget()

    def _valid_reeval_shape(d) -> bool:
        """Sanity-check Claude's re-eval JSON: a dict whose `status` is one
        of valid/weakening/invalid. Normalizes status (lowercase) and
        confidence (int 0-100, missing → 0) in place so downstream gates
        never act on a garbage or partial parse."""
        if not isinstance(d, dict):
            return False
        status = str(d.get("status") or "").strip().lower()
        if status not in ("valid", "weakening", "invalid"):
            return False
        d["status"] = status
        d["confidence"] = max(0, min(100, _safe_int(d.get("confidence"), 0)))
        d["should_exit"] = status == "invalid"
        return True

    # ── Local mode: Claude CLI only ──
    if settings.claude_local:
        try:
            from app.ai.claude_local_client import call_with_prompt
            data = await call_with_prompt(prompt, json_schema=THESIS_REEVAL_JSON_SCHEMA)
            await _record_local("claude-local", "thesis", symbol, _valid_reeval_shape(data))
            if _valid_reeval_shape(data):
                data["_provider"] = "claude-local"
                logger.debug(
                    f"Thesis re-eval [{symbol}] → {data.get('status')} "
                    f"confidence={data.get('confidence')} (claude-local)"
                )
                return data
            if data is not None:
                logger.warning(
                    f"Thesis re-eval [{symbol}] Claude Local returned invalid shape "
                    f"({type(data).__name__}) — discarding"
                )
        except Exception as e:
            logger.debug(f"Thesis re-eval Claude Local failed for {symbol}: {e}")
        # Local mode never touches the paid API.
        return None

    # ── API mode (claude_local=False) ──
    allowed, _reason = await budget.can_call("claude", "synthesis")
    if not allowed or not settings.anthropic_api_key:
        logger.debug(f"Thesis re-eval skipped (no Claude API budget) for {symbol}")
        return None
    try:
        from app.ai.claude_client import create_structured
        data = await create_structured(prompt, THESIS_REEVAL_JSON_SCHEMA)
        if not _valid_reeval_shape(data):
            logger.warning(
                f"Thesis re-eval [{symbol}] Claude API returned invalid shape "
                f"({type(data).__name__}) — discarding"
            )
            await budget.record_call("claude", "synthesis", symbol, success=False)
            return None
        data["_provider"] = "claude"
        await budget.record_call("claude", "synthesis", symbol, success=True)
        logger.debug(
            f"Thesis re-eval [{symbol}] → {data.get('status')} "
            f"confidence={data.get('confidence')} (claude-api)"
        )
        return data
    except Exception as e:
        logger.warning(f"Thesis re-eval Claude API failed for {symbol}: {e}")
        await budget.record_call("claude", "synthesis", symbol, success=False)
        return None


# ============================================================
# LONG-TERM HOLDING ASSESSMENT ("Check a stock", long-term mode)
# ============================================================
#
# One decision-tier Claude call (settings.claude_decision_model) returning
# a free-form structured assessment (prompts.LONG_TERM_JSON_SCHEMA). Same
# CLAUDE_LOCAL routing as everything else: CLI only when claude_local=True,
# budget-checked API only otherwise — a long-term verdict is a
# decision-tier judgement. Returns None on any failure; the caller then
# falls back to the deterministic scorecard verdict.

async def assess_long_term(symbol: str, prompt: str) -> dict | None:
    from app.ai.prompts import LONG_TERM_JSON_SCHEMA, normalize_long_term_result

    if settings.claude_local:
        try:
            from app.ai.claude_local_client import call_with_prompt
            data = await call_with_prompt(prompt, json_schema=LONG_TERM_JSON_SCHEMA, tier="decision")
            result = normalize_long_term_result(data)
            await _record_local("claude-local", "long_term", symbol, result is not None)
            if result is not None:
                result["_provider"] = "claude-local-decision"
                return result
            if data is not None:
                logger.warning(f"Long-term assessment [{symbol}] Claude Local returned an invalid shape")
        except Exception as e:
            logger.warning(f"Long-term assessment Claude Local failed for {symbol}: {e}")
        # Local mode never touches the paid API.
        return None

    budget = await _get_budget()
    allowed, reason = await budget.can_call("claude", "decision")
    if not allowed:
        logger.warning(f"Budget blocked long-term assessment for {symbol}: {reason}")
        return None
    if not settings.anthropic_api_key:
        return None
    try:
        from app.ai.claude_client import create_structured
        data = await create_structured(prompt, LONG_TERM_JSON_SCHEMA, tier="decision")
        result = normalize_long_term_result(data)
        await budget.record_call("claude", "decision", symbol, success=result is not None)
        if result is None:
            logger.warning(f"Long-term assessment [{symbol}] Claude API returned an invalid shape")
            return None
        result["_provider"] = "claude-decision"
        return result
    except Exception as e:
        logger.warning(f"Long-term assessment Claude API failed for {symbol}: {e}")
        await budget.record_call("claude", "decision", symbol, success=False)
        return None


# ============================================================
# STOCK COMPARISON SUMMARY (Check a stock -> Compare)
# ============================================================
#
# One decision-tier Claude call over the computed comparison block
# (services/stock_compare.py). Same routing as assess_long_term: the local
# CLI only when claude_local=True (recorded at $0), the budget-checked API
# only otherwise. Never Gemini. Returns the raw parsed dict (+ "_provider")
# or None; the caller validates and falls back to a deterministic ranking.

async def compare_stocks(prompt: str, schema: dict, label: str) -> dict | None:
    if settings.claude_local:
        try:
            from app.ai.claude_local_client import call_with_prompt
            data = await call_with_prompt(prompt, json_schema=schema, tier="decision")
            await _record_local("claude-local", "compare", label, isinstance(data, dict))
            if isinstance(data, dict):
                return {**data, "_provider": "claude-local-decision"}
        except Exception as e:
            logger.warning(f"Compare summary Claude Local failed for {label}: {e}")
        # Local mode never touches the paid API.
        return None

    budget = await _get_budget()
    allowed, reason = await budget.can_call("claude", "decision")
    if not allowed:
        logger.warning(f"Budget blocked compare summary for {label}: {reason}")
        return None
    if not settings.anthropic_api_key:
        return None
    try:
        from app.ai.claude_client import create_structured
        data = await create_structured(prompt, schema, tier="decision")
        await budget.record_call("claude", "decision", label, success=isinstance(data, dict))
        return {**data, "_provider": "claude-decision"} if isinstance(data, dict) else None
    except Exception as e:
        logger.warning(f"Compare summary Claude API failed for {label}: {e}")
        await budget.record_call("claude", "decision", label, success=False)
        return None


# ============================================================
# GENERIC STRUCTURED CLAUDE CALL (learning analysis, tools)
# ============================================================

async def claude_structured(prompt: str, schema: dict, label: str = "",
                            tier: str = "routine") -> dict | None:
    """One Claude call constrained to `schema`, routed like everything else:
    CLI only when claude_local=True, budget-checked API only otherwise.
    Returns the parsed dict or None on any failure."""
    if settings.claude_local:
        try:
            from app.ai.claude_local_client import call_with_prompt
            return await call_with_prompt(prompt, json_schema=schema, tier=tier)
        except Exception as e:
            logger.warning(f"Claude Local call failed ({label}): {e}")
            return None

    budget = await _get_budget()
    call_type = "decision" if tier == "decision" else "synthesis"
    allowed, reason = await budget.can_call("claude", call_type)
    if not allowed or not settings.anthropic_api_key:
        logger.warning(f"Claude API call skipped ({label}): {reason if not allowed else 'no API key'}")
        return None
    try:
        from app.ai.claude_client import create_structured
        data = await create_structured(prompt, schema, tier=tier)
        await budget.record_call("claude", call_type, label, success=True)
        return data
    except Exception as e:
        logger.warning(f"Claude API call failed ({label}): {e}")
        await budget.record_call("claude", call_type, label, success=False)
        return None
