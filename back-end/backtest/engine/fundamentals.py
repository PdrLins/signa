"""Fundamental data extraction and bucket classification for backtest."""

NUMERIC_FIELDS = [
    "pe_ratio",
    "eps_growth",
    "debt_to_equity",
    "profit_margin",
    "revenue_growth",
    "dividend_yield",
    "market_cap",
    "beta",
]

ALL_FIELDS = NUMERIC_FIELDS + ["sector"]

SAFE_SECTORS = {"Utilities", "Financial Services", "Consumer Defensive", "Real Estate"}


def extract_fundamentals(info: dict) -> dict:
    """Extract fundamental fields from a yfinance .info dict.

    Includes a data_quality score (0-100) indicating completeness.
    Never raises — returns best-effort dict always.
    """
    result = {
        "pe_ratio": info.get("trailingPE") or info.get("pe_ratio"),
        "eps_growth": info.get("earningsGrowth") or info.get("eps_growth"),
        "debt_to_equity": info.get("debtToEquity") or info.get("debt_to_equity"),
        "profit_margin": info.get("profitMargins") or info.get("profit_margin"),
        "revenue_growth": info.get("revenueGrowth") or info.get("revenue_growth"),
        "dividend_yield": info.get("dividendYield") or info.get("dividend_yield"),
        "market_cap": info.get("marketCap") or info.get("market_cap"),
        "sector": info.get("sector"),
        "beta": info.get("beta"),
    }

    # Normalize dividend_yield: yfinance returns 0.41 meaning 0.41%
    # Our thresholds use decimal form (0.04 = 4%), so divide by 100
    dy = result.get("dividend_yield")
    if dy is not None and dy > 0.20:
        result["dividend_yield"] = dy / 100

    # Normalize profit_margin if returned as percentage
    pm = result.get("profit_margin")
    if pm is not None and pm > 1.0:
        result["profit_margin"] = pm / 100

    present = sum(1 for k in ALL_FIELDS if result.get(k) is not None)
    result["data_quality"] = round((present / len(ALL_FIELDS)) * 100, 1)

    return result


def classify_bucket(fundamentals: dict) -> str:
    """Classify a ticker into SAFE_INCOME or HIGH_RISK.

    Rules in priority order:
    1. dividend_yield > 4% → SAFE_INCOME
    2. beta > 1.4 → HIGH_RISK
    3. market_cap < $2B → HIGH_RISK
    4. sector in safe sectors → SAFE_INCOME
    5. Default → HIGH_RISK
    """
    dy = fundamentals.get("dividend_yield")
    if dy is not None and dy > 0.04:
        return "SAFE_INCOME"

    beta = fundamentals.get("beta")
    if beta is not None and beta > 1.4:
        return "HIGH_RISK"

    mc = fundamentals.get("market_cap")
    if mc is not None and mc < 2_000_000_000:
        return "HIGH_RISK"

    sector = fundamentals.get("sector")
    if sector in SAFE_SECTORS:
        return "SAFE_INCOME"

    return "HIGH_RISK"
