"""Shared test fixtures."""

import pytest


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
