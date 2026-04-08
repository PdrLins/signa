"""AI provider router — tries providers in configured order with automatic fallback.

Reads synthesis_providers and sentiment_providers from settings.
Falls through to the next provider when the current one fails.
Checks budget limits before each call — skips provider if over budget.
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
