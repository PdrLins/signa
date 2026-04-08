"""Backtest configuration."""

BACKTEST_CONFIG = {
    "start_date": "2021-04-05",
    "end_date": "2026-04-05",
    "tickers": {
        "US": [
            # Mega Cap
            "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA",
            # Financials
            "JPM", "BAC", "GS", "V", "MA", "PNC", "SCHW",
            # Healthcare
            "JNJ", "UNH", "PFE", "ABBV", "LLY",
            # Consumer / Industrial
            "WMT", "HD", "CAT", "GE", "HON",
            # Energy
            "XOM", "COP", "VLO",
            # Tech / Semis
            "AVGO", "AMD", "CRM", "ADBE", "QCOM",
        ],
        "TSX": [
            # Banks
            "RY.TO", "TD.TO", "BNS.TO", "BMO.TO", "CM.TO", "NA.TO",
            # Energy / Resources
            "ENB.TO", "SU.TO", "CNQ.TO", "CP.TO", "CNR.TO",
            # Insurance / Financials
            "MFC.TO", "SLF.TO", "IFC.TO",
            # Telecom / Utilities
            "BCE.TO", "T.TO", "FTS.TO",
            # Tech
            "SHOP.TO", "CSU.TO",
            # ETFs
            "XEQT.TO", "VFV.TO", "XIU.TO", "XIC.TO", "ZEB.TO", "TEC.TO",
        ],
        "CRYPTO": [
            "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD",
            "ADA-USD", "AVAX-USD", "DOGE-USD", "LINK-USD",
        ],
    },
    "signal_thresholds": {
        "buy": 65,
        "hold": 50,
        "ceiling": 72,
    },
    "gem_conditions": {
        "min_score": 85,
        "min_risk_reward": 3.0,
    },
    "safe_income_weights": {
        "dividend_reliability": 0.35,
        "fundamental_health": 0.30,
        "macro_environment": 0.25,
        "technical": 0.10,
    },
    "high_risk_weights": {
        "technical_momentum": 0.40,
        "catalyst_detection": 0.30,
        "fundamental": 0.30,
    },
    "eval_windows": [5, 10, 20],
    "grok_enabled": False,
    "dry_run": True,
    "claude_model": "claude-sonnet-4-20250514",
    "claude_max_tokens": 1000,
    "use_cache": True,
    "cache_dir": "backtest/data/cache",
    "claude_cache_dir": "backtest/data/cache/claude",
    "fred_api_key": "",  # Loaded from .env if empty
}
