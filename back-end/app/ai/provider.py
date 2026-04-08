"""AI provider router — fallback chain for synthesis + sentiment.

============================================================
WHAT THIS MODULE IS
============================================================

Signa uses three AI providers and falls back between them when one
fails or runs out of budget. This module is the single entry point for
the rest of the codebase to call AI — `scan_service` only ever calls
`provider.synthesize_signal()` and `provider.analyze_sentiment()`,
never the individual provider clients directly.

The router has two responsibilities:

  1. Iterate through `settings.synthesis_providers` (or
     `settings.sentiment_providers`) in order and try each one.
  2. Skip any provider whose budget is exhausted, and fall through
     to the next on transient failures.

============================================================
THE SYNTHESIS FALLBACK CHAIN
============================================================

Configuration: `settings.synthesis_providers = ["claude", "gemini"]`
plus `settings.claude_local: bool = True`.

When `claude_local=True`, the chain is:

  1. CLAUDE LOCAL CLI (free, $0)
       Calls `claude -p ...` as a subprocess. Uses the user's Pro Max
       subscription via the local CLI binary. Up to 3 retries with
       2s/4s/8s exponential backoff for transient errors (timeout,
       empty response, JSON parse errors).
       Failure mode → cascade to step 2.

  2. CLAUDE API (paid, ~$0.012/call)
       Direct Anthropic API call. Costs real money but more reliable
       than the CLI. Budget-checked before each call.
       Failure mode → cascade to step 3.

  3. GEMINI (free tier, $0)
       Google Gemini 2.0 Flash. Free up to 1500 calls/day. Less
       sophisticated than Claude but a workable last-resort.
       Failure mode → return generic error (the brain treats this
       as ai_status="failed" and queues the ticker for retry).

When `claude_local=False`, the chain skips step 1 and goes straight
to Claude API → Gemini.

CRITICAL HISTORICAL BUG (now fixed): in an earlier version, when
claude_local was enabled and the CLI failed, the loop's `continue`
statement jumped straight to the NEXT iteration of the providers list
(i.e., gemini), completely skipping the paid Claude API. This left a
massive reliability gap. The current code lifts both Claude tiers into
the same iteration so a Claude Local failure properly cascades to the
Claude API in the same loop body.

============================================================
THE SENTIMENT FALLBACK CHAIN
============================================================

Configuration: `settings.sentiment_providers = ["grok", "gemini"]`.

  1. GROK (paid, ~$0.0002/call)
       Grok-3-mini via xAI API. The ONLY provider with live X/Twitter
       access — critical for accurate sentiment.
       Failure mode → cascade to step 2.

  2. GEMINI (free, $0)
       Google Gemini for sentiment. Doesn't have live social media
       access but can read recent web content. Lower quality but free.

If both fail, the router returns a neutral fallback (score=50,
confidence=0) with `error="All providers failed or budget exceeded"`.
The downstream code treats this as ai_status="failed" and the brain
queues the ticker for retry.

============================================================
BUDGET ENFORCEMENT
============================================================

Every paid provider call goes through `BudgetService.can_call()` BEFORE
being made. If the daily limit (default $1) or the monthly limit
(default $5/provider) would be exceeded, the call is skipped and the
loop falls through to the next provider.

This is what protects the user from runaway costs — even if every
ticker fails AI synthesis and triggers retries, the budget cap stops
the bleeding.

After each successful call, `BudgetService.record_call()` updates the
running totals AND triggers tiered Telegram alerts at 70/90/100% so the
user can top up before the brain goes blind.
"""

from loguru import logger

from app.core.config import settings


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
) -> dict:
    """Route synthesis to the first available provider within budget.

    Fallback chain when claude_local=True:
        Claude Local CLI ($0)  →  Claude API (paid)  →  Gemini (free tier)
    Fallback chain when claude_local=False:
        Claude API (paid)  →  Gemini (free tier)

    Previous bug: when claude_local was enabled and the CLI failed, the paid
    Claude API was skipped entirely (the `continue` jumped to gemini). Now
    Claude Local failure properly cascades to the paid Claude API first.
    """
    providers = settings.synthesis_providers
    budget = await _get_budget()

    for provider in providers:
        if provider == "claude":
            # Tier 1: Claude Local CLI (free, retried internally)
            if settings.claude_local:
                try:
                    from app.ai.claude_local_client import synthesize_signal as claude_local_synth
                    result = await claude_local_synth(ticker, technical_data, fundamental_data, macro_data, grok_data)
                    if not result.get("error"):
                        result["_provider"] = "claude-local"
                        return result
                    logger.warning(
                        f"Claude Local exhausted retries for {ticker}: {result.get('error')} "
                        f"— falling through to paid Claude API"
                    )
                except (KeyError, TypeError, AttributeError, ImportError, NameError) as e:
                    # Permanent code bugs (template mismatch, missing import, etc).
                    # Logged at ERROR so they're impossible to miss — historically a
                    # silent WARNING here masked a `KeyError: 'options_flow'` that
                    # caused EVERY synthesis call to silently cascade to the paid
                    # API, burning thousands of tokens before the user noticed.
                    logger.error(
                        f"Claude Local synthesis CODE BUG for {ticker}: {type(e).__name__}: {e} "
                        f"— this is NOT a transient error and will keep burning tokens via the paid API "
                        f"until fixed. Check claude_local_client.py vs prompts.py."
                    )
                except Exception as e:
                    logger.warning(f"Claude Local synthesis error for {ticker}: {e} — falling through to paid Claude API")

            # Tier 2: Paid Claude API (always tried after local fails OR when local disabled)
            allowed, reason = await budget.can_call("claude", "synthesis")
            if not allowed:
                logger.warning(f"Budget blocked Claude API synthesis for {ticker}: {reason}")
            elif settings.anthropic_api_key:
                try:
                    from app.ai.claude_client import synthesize_signal as claude_synth
                    result = await claude_synth(ticker, technical_data, fundamental_data, macro_data, grok_data)
                    if not result.get("error"):
                        result["_provider"] = "claude"
                        await budget.record_call("claude", "synthesis", ticker, success=True)
                        return result
                    logger.warning(f"Claude API failed for {ticker}: {result.get('error')} — trying next provider")
                    await budget.record_call("claude", "synthesis", ticker, success=False)
                except Exception as e:
                    logger.warning(f"Claude API synthesis error for {ticker}: {e}")
            continue

        elif provider == "gemini":
            allowed, reason = await budget.can_call("gemini", "synthesis")
            if not allowed:
                logger.warning(f"Budget blocked Gemini synthesis for {ticker}: {reason}")
                continue
            if not settings.gemini_api_key:
                continue
            try:
                from app.ai.gemini_client import synthesize_signal as gemini_synth
                result = await gemini_synth(ticker, technical_data, fundamental_data, macro_data, grok_data)
                if not result.get("error"):
                    result["_provider"] = "gemini"
                    await budget.record_call("gemini", "synthesis", ticker, success=True)
                    return result
                logger.warning(f"Gemini synthesis failed for {ticker}: {result.get('error')}")
            except Exception as e:
                logger.warning(f"Gemini synthesis error for {ticker}: {e}")
            continue

    # All providers failed or over budget — return generic fallback
    logger.error(f"All synthesis providers failed/blocked for {ticker}")
    return {
        "signal": "HOLD",
        "confidence": 0,
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


async def analyze_sentiment(ticker: str) -> dict:
    """Route sentiment analysis to the first available provider within budget."""
    providers = settings.sentiment_providers
    budget = await _get_budget()

    for provider in providers:
        # Budget check
        allowed, reason = await budget.can_call(provider, "sentiment")
        if not allowed:
            logger.warning(f"Budget blocked {provider} sentiment for {ticker}: {reason}")
            continue

        try:
            if provider == "grok" and settings.xai_api_key:
                from app.ai.grok_client import analyze_sentiment as grok_sent
                result = await grok_sent(ticker)
                if not result.get("error"):
                    result["_provider"] = "grok"
                    await budget.record_call("grok", "sentiment", ticker, success=True)
                    return result
                logger.debug(f"Grok failed for {ticker}: {result.get('error')}, trying next...")
                await budget.record_call("grok", "sentiment", ticker, success=False)

            elif provider == "gemini" and settings.gemini_api_key:
                from app.ai.gemini_client import analyze_sentiment as gemini_sent
                result = await gemini_sent(ticker)
                if not result.get("error"):
                    result["_provider"] = "gemini"
                    await budget.record_call("gemini", "sentiment", ticker, success=True)
                    return result
                logger.debug(f"Gemini sentiment failed for {ticker}: {result.get('error')}, trying next...")

        except Exception as e:
            logger.warning(f"Provider {provider} sentiment error for {ticker}: {e}")
            continue

    # All failed
    logger.warning(f"All sentiment providers failed/blocked for {ticker}")
    return {
        "ticker": ticker,
        "score": 50.0,
        "label": "neutral",
        "confidence": 0.0,
        "top_themes": [],
        "breaking_news": None,
        "notable_accounts": [],
        "summary": "",
        "error": "All providers failed or budget exceeded",
        "_provider": "none",
    }
