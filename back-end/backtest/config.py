"""Backtest configuration."""

BACKTEST_CONFIG = {
    "start_date": "2024-10-01",
    "end_date": "2025-04-01",
    "tickers": {
        "US": [
            "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
            "META", "TSLA", "JPM", "JNJ", "V",
            "PFE", "BAC", "XOM", "WMT", "UNH",
        ],
        "TSX": [
            "SHOP.TO", "RY.TO", "TD.TO", "BNS.TO", "CNR.TO",
            "ENB.TO", "SU.TO", "BMO.TO", "CP.TO", "MFC.TO",
            "DGS.TO", "BCE.TO", "T.TO", "CM.TO", "BAM.TO",
        ],
        "CRYPTO": [
            "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD",
            "ADA-USD", "AVAX-USD", "DOGE-USD", "LINK-USD", "MATIC-USD",
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
