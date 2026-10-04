"""Shared market data helpers backed by yfinance: FX rates (cached 1 h),
daily closes and exchange/currency lookups."""

from __future__ import annotations

import threading
from typing import Optional

from loguru import logger

from app.core.executors import download_threads

from app.core.cache import TTLCache

_fx_cache = TTLCache(max_size=256, default_ttl=3600)  # 1h — FX drift intraday is small; every currency
# Last rate Yahoo gave per currency: served when a refresh fails, so totals never
# drop holdings because of one failed FX download.
_last_good: dict[str, float] = {}

CAD_SUFFIXES = (".TO", ".V", ".NE", ".CN")


def native_currency(symbol: str | None) -> str:
    """Currency the listing trades in, from its suffix (app/market/currency.py):
    .TO -> CAD, .SA -> BRL, .L -> GBP, no suffix -> USD ..."""
    from app.market.currency import currency_for
    return currency_for(symbol)


# ── Any-currency FX (Yahoo "{CCY}=X" = units of CCY per 1 USD), cached 1h ──

FX_TTL = 3600
FX_MISS_TTL = 300


def _download_fx(codes: list[str]) -> dict[str, float]:
    """{CCY: units per 1 USD} for `codes` (one yfinance call). Never raises."""
    out: dict[str, float] = {}
    if not codes:
        return out
    try:
        import yfinance as yf

        tickers = [f"{c}=X" for c in codes]
        data = yf.download(tickers, period="5d", interval="1d", progress=False, threads=download_threads(len(tickers)))
        if data is None or data.empty:
            return out
        close = data["Close"]
        for c, t in zip(codes, tickers):
            col = close[t] if hasattr(close, "columns") and t in close.columns else (
                close if not hasattr(close, "columns") else None)
            if col is None:
                continue
            col = col.dropna()
            if len(col) and float(col.iloc[-1]) > 0:
                out[c] = float(col.iloc[-1])
    except Exception as e:
        logger.warning(f"FX fetch failed for {codes}: {type(e).__name__}")
    return out


def usd_rates(codes) -> dict[str, float]:
    """{CCY: units of CCY per 1 USD} for every code that can be priced (USD = 1,
    CAD from get_usdcad_rate). Cached 1h, misses 5 min."""
    want = {str(c).upper() for c in codes if c}
    out: dict[str, float] = {}
    missing = []
    for c in sorted(want):
        if c == "USD":
            out[c] = 1.0
        elif c == "CAD":
            r = get_usdcad_rate()
            if r:
                out[c] = r
        else:
            cached = _fx_cache.get(f"USD{c}")
            if cached is None:
                missing.append(c)
            elif cached:
                out[c] = cached
    if missing:
        got = _download_fx(missing)
        for c in missing:
            if c in got:
                _last_good[c] = got[c]
            rate = got.get(c) or _last_good.get(c, 0.0)
            _fx_cache.set(f"USD{c}", rate, ttl=FX_TTL if c in got else FX_MISS_TTL)
            if rate:
                out[c] = rate
    return out


def fx_convert(amount: float | None, from_ccy: str | None, to_ccy: str | None) -> float | None:
    """Any-currency conversion through USD (cached rates). None = can't convert."""
    if amount is None:
        return None
    f, t = (from_ccy or "").upper(), (to_ccy or "").upper()
    if not f or not t:
        return None
    if f == t:
        return amount
    rates = usd_rates([f, t])
    if f not in rates or t not in rates:
        return None
    return amount / rates[f] * rates[t]


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
    # A failure serves the last good rate (retried in 5 min), so CAD totals
    # never silently drop USD holdings.
    fetched = rate is not None
    if fetched:
        _last_good["CAD"] = rate
    else:
        rate = _last_good.get("CAD")
    _fx_cache.set("USDCAD", rate or 0.0, ttl=3600 if fetched else 300)
    return rate


def fx_to_usd(symbol: str | None) -> Optional[float]:
    """Multiplier converting a native-currency amount for `symbol` into USD
    (None when the rate can't be fetched; callers must not mix currencies)."""
    ccy = native_currency(symbol)
    if ccy == "USD":
        return 1.0
    rate = usd_rates([ccy]).get(ccy)
    return (1.0 / rate) if rate else None


# ── Daily close history (portfolio risk: correlation / beta / vol) ────
#
# ~1y of daily closes per symbol, cached 6h (correlations over 120 trading
# days barely move intraday). A failed/empty symbol is cached as None for
# 30 min so one bad ticker doesn't trigger a Yahoo call on every scan.

_history_cache = TTLCache(max_size=20000, default_ttl=6 * 3600)   # every followed symbol × period
_hist_lock = threading.Lock()
_hist_inflight: dict[str, threading.Event] = {}
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
        from app.market.currency import price_factor
        k = price_factor(sym)   # pence/cents listings (LSE, JSE, TASE), like the quotes table
        if k != 1.0:
            s = s * k
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
    # One download per symbol at a time: a symbol another request is already
    # downloading is waited for (then read from the cache), not fetched again.
    mine, theirs = [], []
    with _hist_lock:
        for sym in missing:
            key = f"hist:{period}:{sym}"
            ev = _hist_inflight.get(key)
            if ev is None:
                _hist_inflight[key] = threading.Event()
                mine.append(sym)
            else:
                theirs.append((sym, ev))
    try:
        out.update(_download_closes(mine, period) if mine else {})
    finally:
        with _hist_lock:
            for sym in mine:
                ev = _hist_inflight.pop(f"hist:{period}:{sym}", None)
                if ev is not None:
                    ev.set()
    for sym, ev in theirs:
        ev.wait(timeout=30)
        entry = _history_cache.get(f"hist:{period}:{sym}")
        if entry is not None and entry is not False:
            out[sym] = entry
    return out


def _download_closes(missing: list[str], period: str) -> dict:
    """One batched yf.download; caches each symbol (or its miss). Never raises."""
    out: dict = {}
    try:
        import pandas as pd
        import yfinance as yf

        from app.services import usage_metrics
        usage_metrics.record("provider_calls.daily_history")
        data = yf.download(missing, period=period, interval="1d", progress=False,
                           threads=download_threads(len(missing)), auto_adjust=True)
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
