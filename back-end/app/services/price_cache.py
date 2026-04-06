"""In-memory price cache backed by yfinance (5-minute TTL).

Uses batch download for multiple symbols and asyncio.to_thread
to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from loguru import logger

from app.core.cache import TTLCache

_cache = TTLCache(max_size=500, default_ttl=300)


def _get_cached(symbol: str) -> tuple[bool, Optional[float], Optional[float]]:
    """Check cache. Returns (hit, price, change_pct)."""
    entry = _cache.get(symbol)
    if entry is not None:
        return True, entry[0], entry[1]
    return False, None, None


def _fetch_prices_batch(symbols: list[str]) -> dict[str, tuple[Optional[float], Optional[float]]]:
    """Fetch prices for multiple symbols in one yfinance call (synchronous).

    Returns dict of symbol → (price, change_pct).
    """
    import yfinance as yf

    result: dict[str, tuple[Optional[float], Optional[float]]] = {}

    if not symbols:
        return result

    try:
        # Batch download — 1 network call instead of N
        data = yf.download(symbols, period="2d", interval="1d", progress=False, threads=False)

        if data.empty:
            for sym in symbols:
                result[sym] = (None, None)
                _cache.set(sym, (None, None))
            return result

        import pandas as pd
        if isinstance(data.columns, pd.MultiIndex):
            for sym in symbols:
                try:
                    close_col = data["Close"][sym] if sym in data["Close"].columns else None
                    if close_col is not None and len(close_col.dropna()) >= 1:
                        prices = close_col.dropna()
                        price = float(prices.iloc[-1])
                        prev = float(prices.iloc[-2]) if len(prices) >= 2 else None
                        change = round(((price - prev) / prev) * 100, 2) if prev and prev > 0 else None
                        result[sym] = (price, change)
                        _cache.set(sym, (price, change))
                    else:
                        result[sym] = (None, None)
                        _cache.set(sym, (None, None))
                except Exception as e:
                    logger.debug(f"Price parse failed for {sym}: {e}")
                    result[sym] = (None, None)
                    _cache.set(sym, (None, None))
        else:
            # Single symbol case
            sym = symbols[0]
            try:
                prices = data["Close"].dropna()
                if len(prices) >= 1:
                    price = float(prices.iloc[-1])
                    prev = float(prices.iloc[-2]) if len(prices) >= 2 else None
                    change = round(((price - prev) / prev) * 100, 2) if prev and prev > 0 else None
                    result[sym] = (price, change)
                    _cache.set(sym, (price, change))
                else:
                    result[sym] = (None, None)
                    _cache.set(sym, (None, None))
            except Exception as e:
                logger.debug(f"Price parse failed for {sym}: {e}")
                result[sym] = (None, None)
                _cache.set(sym, (None, None))

    except Exception as e:
        logger.debug(f"Batch price fetch failed: {e}")
        for sym in symbols:
            result[sym] = (None, None)
            _cache.set(sym, (None, None))

    return result


async def enrich_signals_async(signals: list[dict]) -> list[dict]:
    """Add current_price, change_pct, and asset_type to signals. Non-blocking."""
    # Collect symbols that need fresh prices
    symbols_to_fetch = []
    for sig in signals:
        symbol = sig.get("symbol")
        if not symbol:
            continue
        hit, _, _ = _get_cached(symbol)
        if not hit:
            symbols_to_fetch.append(symbol)

    # Batch fetch uncached symbols in a thread (non-blocking)
    if symbols_to_fetch:
        unique = list(set(symbols_to_fetch))
        await asyncio.to_thread(_fetch_prices_batch, unique)

    # Now all prices are cached — apply to signals
    for sig in signals:
        symbol = sig.get("symbol")
        if not symbol:
            continue
        _, price, change = _get_cached(symbol)
        sig["current_price"] = price
        sig["change_pct"] = change
        if not sig.get("asset_type"):
            from app.scanners.universe import get_exchange
            exchange = get_exchange(symbol)
            sig["asset_type"] = "CRYPTO" if exchange == "CRYPTO" else "EQUITY"
            sig["exchange"] = exchange

    return signals


def enrich_signals(signals: list[dict]) -> list[dict]:
    """Synchronous wrapper for backward compatibility.

    Prefer enrich_signals_async in async contexts.
    """
    symbols_to_fetch = []
    for sig in signals:
        symbol = sig.get("symbol")
        if not symbol:
            continue
        hit, _, _ = _get_cached(symbol)
        if not hit:
            symbols_to_fetch.append(symbol)

    if symbols_to_fetch:
        _fetch_prices_batch(list(set(symbols_to_fetch)))

    for sig in signals:
        symbol = sig.get("symbol")
        if not symbol:
            continue
        _, price, change = _get_cached(symbol)
        sig["current_price"] = price
        sig["change_pct"] = change
        if not sig.get("asset_type"):
            from app.scanners.universe import get_exchange
            exchange = get_exchange(symbol)
            sig["asset_type"] = "CRYPTO" if exchange == "CRYPTO" else "EQUITY"
            sig["exchange"] = exchange

    return signals
