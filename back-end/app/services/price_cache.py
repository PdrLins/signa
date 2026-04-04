"""In-memory price cache backed by yfinance (5-minute TTL)."""

from __future__ import annotations

import time
from typing import Optional

from loguru import logger

_cache: dict[str, tuple[float, Optional[float], Optional[float]]] = {}  # symbol → (expires, price, change_pct)
_TTL = 300  # 5 minutes


def get_price(symbol: str) -> tuple[Optional[float], Optional[float]]:
    """Return (current_price, change_pct) for a symbol. Cached for 5 minutes.

    Returns (None, None) on any failure — never raises.
    """
    now = time.time()
    entry = _cache.get(symbol)
    if entry and entry[0] > now:
        return entry[1], entry[2]

    try:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        price = float(info.last_price) if info.last_price else None
        prev_close = float(info.previous_close) if info.previous_close else None

        change_pct = None
        if price is not None and prev_close and prev_close > 0:
            change_pct = round(((price - prev_close) / prev_close) * 100, 2)

        _cache[symbol] = (now + _TTL, price, change_pct)
        return price, change_pct
    except Exception:
        logger.debug(f"Price fetch failed for {symbol}")
        _cache[symbol] = (now + _TTL, None, None)
        return None, None


def enrich_signals(signals: list[dict]) -> list[dict]:
    """Add current_price, change_pct, and asset_type to each signal dict in-place."""
    for sig in signals:
        symbol = sig.get("symbol")
        if not symbol:
            continue
        price, change = get_price(symbol)
        sig["current_price"] = price
        sig["change_pct"] = change
        # Backfill asset_type/exchange for older signals that don't have it
        if not sig.get("asset_type"):
            from app.scanners.universe import get_exchange
            exchange = get_exchange(symbol)
            sig["asset_type"] = "CRYPTO" if exchange == "CRYPTO" else "EQUITY"
            sig["exchange"] = exchange
    return signals
