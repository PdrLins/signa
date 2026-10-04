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

_cache = TTLCache(max_size=500, default_ttl=600)  # 10 min — signal prices don't need sub-minute freshness


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
            from app.market.universe import get_exchange
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
            from app.market.universe import get_exchange
            exchange = get_exchange(symbol)
            sig["asset_type"] = "CRYPTO" if exchange == "CRYPTO" else "EQUITY"
            sig["exchange"] = exchange

    return signals


# ── FX (brain wallet base currency = USD) ────────────────────────────
#
# TSX names (.TO etc.) are quoted in CAD. The brain wallet is USD, so every
# cash movement for a CAD-quoted trade is converted with USDCAD from Yahoo
# ("CAD=X" = CAD per 1 USD, ~1.35). Prices stored on virtual_trades stay in
# the instrument's NATIVE currency so stop/target/peak comparisons against
# live quotes never mix currencies; only cash (position_size_usd, pnl_amount,
# wallet debits/credits) is USD.
#
# If the rate is unavailable, `fx_to_usd` returns None and the brain SKIPS
# new CAD entries rather than silently treating CAD as USD.

_fx_cache = TTLCache(max_size=8, default_ttl=3600)  # 1h — FX drift intraday is small

CAD_SUFFIXES = (".TO", ".V", ".NE", ".CN")


def native_currency(symbol: str | None) -> str:
    """'CAD' for Canadian listings, else 'USD' (US equities + -USD crypto)."""
    if symbol and symbol.upper().endswith(CAD_SUFFIXES):
        return "CAD"
    return "USD"


def get_usdcad_rate(force_refresh: bool = False) -> Optional[float]:
    """CAD per 1 USD (Yahoo 'CAD=X'), cached 1h. None when unavailable.

    A sanity band (1.0-2.0) rejects obviously broken quotes so a bad
    print can't mis-size a position by 10x.
    """
    if not force_refresh:
        cached = _fx_cache.get("USDCAD")
        if cached is not None:
            return cached or None  # 0.0 = cached failure
    rate: Optional[float] = None
    try:
        import yfinance as yf

        data = yf.download("CAD=X", period="5d", interval="1d", progress=False, threads=False)
        if data is not None and not data.empty:
            close = data["Close"]
            if hasattr(close, "columns"):  # MultiIndex (newer yfinance)
                close = close.iloc[:, 0]
            close = close.dropna()
            if len(close):
                value = float(close.iloc[-1])
                if 1.0 < value < 2.0:
                    rate = value
                else:
                    logger.warning(f"USDCAD quote {value} outside sanity band — ignored")
    except Exception as e:
        logger.warning(f"USDCAD fetch failed: {e}")
    # Cache failures briefly (5 min) so we don't hammer Yahoo every call.
    _fx_cache.set("USDCAD", rate or 0.0, ttl=3600 if rate else 300)
    return rate


def fx_to_usd(symbol: str | None) -> Optional[float]:
    """Multiplier converting a native-currency amount for `symbol` into USD.

    1.0 for USD instruments; 1/USDCAD for CAD listings; None if the CAD
    rate can't be fetched (caller must not mix currencies).
    """
    if native_currency(symbol) == "USD":
        return 1.0
    rate = get_usdcad_rate()
    return (1.0 / rate) if rate else None


# ── Daily close history (portfolio risk: correlation / beta / vol) ────
#
# ~1y of daily closes per symbol, cached 6h (correlations over 120 trading
# days barely move intraday). A failed/empty symbol is cached as None for
# 30 min so one bad ticker doesn't trigger a Yahoo call on every scan.

_history_cache = TTLCache(max_size=1000, default_ttl=6 * 3600)
_HISTORY_MISS_TTL = 1800


def _close_series_from_download(data, sym: str, multi: bool):
    """Pull a clean Close series for `sym` out of a yf.download frame."""
    try:
        if multi:
            close = data["Close"]
            if sym not in close.columns:
                return None
            s = close[sym]
        else:
            s = data["Close"]
            if hasattr(s, "columns"):  # MultiIndex single ticker (newer yfinance)
                s = s.iloc[:, 0]
        s = s.dropna()
        s = s[s > 0]
        if s.empty:
            return None
        import pandas as pd

        idx = pd.DatetimeIndex(s.index)
        if idx.tz is not None:  # crypto bars come back tz-aware
            idx = idx.tz_localize(None)
        s.index = idx.normalize()
        s = s[~s.index.duplicated(keep="last")]
        s.name = sym
        return s
    except Exception as e:
        logger.debug(f"History parse failed for {sym}: {e}")
        return None


def fetch_daily_closes(symbols: list[str], period: str = "1y") -> dict:
    """Daily closes per symbol → {symbol: pandas.Series indexed by date}.

    One batched yf.download for all uncached symbols (synchronous — call
    via asyncio.to_thread from async code). Symbols with no data are
    simply absent from the result; never raises.
    """
    out: dict = {}
    missing: list[str] = []
    for sym in dict.fromkeys(s for s in symbols if s):
        entry = _history_cache.get(f"hist:{period}:{sym}")
        if entry is None:
            missing.append(sym)
        elif entry is not False:
            out[sym] = entry
    if not missing:
        return out
    try:
        import pandas as pd
        import yfinance as yf

        from app.services import usage_metrics
        usage_metrics.record("provider_calls.daily_history")
        data = yf.download(missing, period=period, interval="1d", progress=False,
                           threads=False, auto_adjust=True)
        multi = data is not None and not data.empty and isinstance(data.columns, pd.MultiIndex) \
            and len(missing) > 1
        for sym in missing:
            s = None
            if data is not None and not data.empty:
                s = _close_series_from_download(data, sym, multi)
            if s is None:
                _history_cache.set(f"hist:{period}:{sym}", False, ttl=_HISTORY_MISS_TTL)
            else:
                _history_cache.set(f"hist:{period}:{sym}", s)
                out[sym] = s
    except Exception as e:
        logger.warning(f"Daily history fetch failed for {len(missing)} symbols: {e}")
        for sym in missing:
            _history_cache.set(f"hist:{period}:{sym}", False, ttl=_HISTORY_MISS_TTL)
    return out
