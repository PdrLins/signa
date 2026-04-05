"""AI provider router — tries providers in configured order with automatic fallback.

Reads synthesis_providers and sentiment_providers from settings.
Falls through to the next provider when the current one fails.
"""

from loguru import logger

from app.core.config import settings


async def synthesize_signal(
    ticker: str,
    technical_data: dict,
    fundamental_data: dict,
    macro_data: dict,
    grok_data: dict,
) -> dict:
    """Route synthesis to the first available provider."""
    providers = settings.synthesis_providers

    for provider in providers:
        try:
            if provider == "claude" and settings.anthropic_api_key:
                from app.ai.claude_client import synthesize_signal as claude_synth
                result = await claude_synth(ticker, technical_data, fundamental_data, macro_data, grok_data)
                if not result.get("error"):
                    result["_provider"] = "claude"
                    return result
                logger.debug(f"Claude failed for {ticker}: {result.get('error')}, trying next...")

            elif provider == "gemini" and settings.gemini_api_key:
                from app.ai.gemini_client import synthesize_signal as gemini_synth
                result = await gemini_synth(ticker, technical_data, fundamental_data, macro_data, grok_data)
                if not result.get("error"):
                    result["_provider"] = "gemini"
                    return result
                logger.debug(f"Gemini failed for {ticker}: {result.get('error')}, trying next...")

        except Exception as e:
            logger.warning(f"Provider {provider} synthesis error for {ticker}: {e}")
            continue

    # All providers failed — return generic fallback
    logger.warning(f"All synthesis providers failed for {ticker}")
    return {
        "signal": "HOLD",
        "confidence": 0,
        "reasoning": "Analysis temporarily unavailable — all AI providers failed",
        "risk_factors": [],
        "catalyst": None,
        "catalyst_date": None,
        "red_flags": [],
        "risk_reward_ratio": None,
        "target_price": None,
        "stop_loss": None,
        "sentiment_weight": 0,
        "error": "All providers failed",
        "_provider": "none",
    }


async def analyze_sentiment(ticker: str) -> dict:
    """Route sentiment analysis to the first available provider."""
    providers = settings.sentiment_providers

    for provider in providers:
        try:
            if provider == "grok" and settings.xai_api_key:
                from app.ai.grok_client import analyze_sentiment as grok_sent
                result = await grok_sent(ticker)
                if not result.get("error"):
                    result["_provider"] = "grok"
                    return result
                logger.debug(f"Grok failed for {ticker}: {result.get('error')}, trying next...")

            elif provider == "gemini" and settings.gemini_api_key:
                from app.ai.gemini_client import analyze_sentiment as gemini_sent
                result = await gemini_sent(ticker)
                if not result.get("error"):
                    result["_provider"] = "gemini"
                    return result
                logger.debug(f"Gemini sentiment failed for {ticker}: {result.get('error')}, trying next...")

        except Exception as e:
            logger.warning(f"Provider {provider} sentiment error for {ticker}: {e}")
            continue

    # All failed
    logger.warning(f"All sentiment providers failed for {ticker}")
    return {
        "ticker": ticker,
        "score": 50.0,
        "label": "neutral",
        "confidence": 0.0,
        "top_themes": [],
        "breaking_news": None,
        "notable_accounts": [],
        "summary": "",
        "error": "All providers failed",
        "_provider": "none",
    }
