"""Shared test fixtures."""

import os

import pytest

# Strong dummy secrets for tests. Forced (not setdefault) so a weak value in the
# shell (e.g. JWT_SECRET_KEY=x) or a placeholder in back-end/.env can't trip the
# Settings security validator. Must run before any `app.*` import.
os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-0123456789abcdef0123456789abcdef"
os.environ["BRAIN_TOKEN_SECRET"] = "test-brain-secret-fedcba9876543210fedcba9876543210"
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")


@pytest.fixture(autouse=True)
def _no_live_codex(monkeypatch):
    """Codex is on by default and the owner's CLI may be logged in: never let
    a test reach the real `codex` binary. Codex tests re-enable it and mock
    the subprocess / SDK."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "codex_enabled", False)


@pytest.fixture(autouse=True)
def _no_live_dividends(monkeypatch):
    """Check a stock fetches a dividend profile: never let a test reach
    yfinance for it (empty data -> "no dividend"). Tests that need data
    patch dividends._fetch_raw themselves."""
    from app.services import dividends
    monkeypatch.setattr(dividends, "_fetch_raw", lambda symbol, info=None: {"info": info or {}, "dividends": None,
                                                                             "calendar": {}})
    dividends._cache.clear()


@pytest.fixture
def sample_indicators():
    """Sample technical indicators for a healthy stock."""
    return {
        "rsi": 55.0,
        "macd_line": 1.5,
        "macd_signal": 0.8,
        "macd_hist": 0.7,
        "bb_upper": 155.0,
        "bb_mid": 150.0,
        "bb_lower": 145.0,
        "bb_pct": 0.6,
        "sma50": 148.0,
        "sma200": 140.0,
        "sma_cross": "none",
        "close": 152.0,
        "vs_sma50": 0.027,
        "vs_sma200": 0.086,
        "volume_ratio": 1.2,
        "volume_avg": 500000,
        "volume_zscore": 0.8,
        "momentum_5d": 0.02,
        "momentum_20d": 0.05,
        "atr": 3.5,
        "current_price": 152.0,
    }


@pytest.fixture
def sample_fundamentals_safe():
    """Sample fundamentals for a safe income stock (bank)."""
    return {
        "pe_ratio": 12.5,
        "eps_growth": 0.08,
        "debt_to_equity": 45.0,
        "profit_margin": 0.28,
        "revenue_growth": 0.05,
        "dividend_yield": 0.045,
        "market_cap": 150_000_000_000,
        "sector": "Financial Services",
        "beta": 0.9,
        "data_quality": 100.0,
    }


@pytest.fixture
def sample_fundamentals_risk():
    """Sample fundamentals for a high risk stock (tech)."""
    return {
        "pe_ratio": 45.0,
        "eps_growth": 0.30,
        "debt_to_equity": 80.0,
        "profit_margin": 0.22,
        "revenue_growth": 0.25,
        "dividend_yield": None,
        "market_cap": 500_000_000_000,
        "sector": "Technology",
        "beta": 1.6,
        "data_quality": 88.9,
    }


@pytest.fixture
def sample_macro():
    """Sample macro snapshot."""
    import pandas as pd
    ff = pd.Series([4.5, 4.5, 4.5, 4.5, 4.33], name="fed_funds_rate")
    return {
        "fed_funds_rate": ff,
        "fed_rate": 4.33,
        "cpi": 3.2,
        "vix": 18.5,
        "fed_trend": "falling",
    }


@pytest.fixture(autouse=True)
def _clear_ai_caches():
    """AI result caches are module-level; keep tests from seeing each other's results."""
    from app.ai.provider import clear_ai_caches
    clear_ai_caches()
    yield
    clear_ai_caches()


@pytest.fixture(autouse=True)
def _reset_grok_account_block(monkeypatch):
    """A faked 401/403 pauses Grok module-wide; never leak that across tests."""
    from app.ai import grok_client
    monkeypatch.setattr(grok_client, "_account_blocked_until", None)
