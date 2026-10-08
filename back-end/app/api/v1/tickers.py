"""Price history for charts (GET /tickers/{ticker}/chart). Free.

The chart is shared by everyone viewing the same symbol and period: cached
CHART_TTL_S seconds (short for intraday, long for daily/weekly), and one
Yahoo request even when many users open it at the same time."""

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from loguru import logger

from app.core.cache import TTLCache
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/tickers", tags=["Tickers"])

# yfinance period → interval mapping for optimal chart resolution
_PERIOD_CONFIG = {
    "1d": {"period": "1d", "interval": "5m"},      # 5-min candles for intraday
    "5d": {"period": "5d", "interval": "15m"},     # 15-min candles for 5 days
    "1mo": {"period": "1mo", "interval": "1h"},    # Hourly for 1 month
    "3mo": {"period": "3mo", "interval": "1d"},    # Daily for 3 months
    "6mo": {"period": "6mo", "interval": "1d"},    # Daily for 6 months
    "1y": {"period": "1y", "interval": "1d"},      # Daily for 1 year
    "5y": {"period": "5y", "interval": "1wk"},     # Weekly for 5 years
}

CHART_TTL_S = {"1d": 60, "5d": 5 * 60, "1mo": 15 * 60, "3mo": 3600, "6mo": 3600, "1y": 3600, "5y": 6 * 3600}
EMPTY_TTL_S = 10 * 60
ERROR_TTL_S = 30           # a failed Yahoo call (timeout, 429)      # "no data" is remembered too, so a bad symbol isn't re-asked every view
_charts = TTLCache(max_size=5000, default_ttl=3600)
_locks: dict[tuple[str, str], asyncio.Lock] = {}


def _px(v: float) -> float:
    """Cheap prices (crypto, penny stocks, yen pairs) keep 4 decimals."""
    return round(v, 4) if abs(v) < 10 else round(v, 2)


def clear_cache() -> None:
    _charts.clear()
    _locks.clear()


def chart_points(df) -> list[dict]:
    """OHLCV rows -> chart points. yfinance sometimes returns a bar with NaN
    prices (often today's unfinished bar): it is skipped, since NaN can't be
    sent as JSON (it made the whole chart answer 500). A missing volume is 0."""
    import math

    out = []
    for idx, row in df.iterrows():
        try:
            o, h, lo, c = (float(row[k]) for k in ("Open", "High", "Low", "Close"))
        except (TypeError, ValueError, KeyError):
            continue
        if not all(math.isfinite(v) for v in (o, h, lo, c)):
            continue
        try:
            vol = float(row["Volume"])
            vol = int(vol) if math.isfinite(vol) else 0
        except (TypeError, ValueError, KeyError):
            vol = 0
        out.append({"date": idx.isoformat(), "open": _px(o), "high": _px(h),
                    "low": _px(lo), "close": _px(c), "volume": vol})
    return out


@router.get("/{ticker}/chart")
async def get_ticker_chart(
    ticker: str = Path(..., pattern=r"^[A-Z0-9.\-]{1,10}$"),
    period: Literal["1d", "5d", "1mo", "3mo", "6mo", "1y", "5y"] = Query("3mo"),
    user: dict = Depends(get_current_user),
):
    """Get OHLCV price history for charting.

    Returns data points formatted for charts.
    Each point has: date, open, high, low, close, volume.

    Periods:
    - 1d: 5-min candles (intraday)
    - 5d: 15-min candles
    - 1mo: hourly candles
    - 3mo/6mo/1y: daily candles
    - 5y: weekly candles
    """
    ticker = ticker.upper()
    key = (ticker, period)
    body = _charts.get(f"{ticker}|{period}")
    if body is None:
        lock = _locks.setdefault(key, asyncio.Lock())
        async with lock:
            body = _charts.get(f"{ticker}|{period}")
            if body is None:
                body = await _load_chart(ticker, period)
        if not lock.locked():
            _locks.pop(key, None)   # bounded: the next miss makes a new lock
    if body.get("error"):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to fetch price data")
    if body.get("empty"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No price data for {ticker}")
    return body


async def _load_chart(ticker: str, period: str) -> dict:
    """Yahoo -> chart body, cached for everyone ({"error"} for ERROR_TTL_S on a failed fetch)."""
    config = _PERIOD_CONFIG[period]
    cache_key = f"{ticker}|{period}"

    def _fetch():
        import yfinance as yf
        t = yf.Ticker(ticker)
        df = t.history(period=config["period"], interval=config["interval"])
        return df

    try:
        df = await asyncio.to_thread(_fetch)
    except Exception as e:
        logger.error(f"Chart data fetch failed for {ticker}: {e}")
        # remembered briefly: the users waiting on this chart don't each retry Yahoo
        _charts.set(cache_key, {"error": True}, ttl=ERROR_TTL_S)
        return {"error": True}

    # Flatten MultiIndex if present
    import pandas as pd
    if not df.empty and isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    data_points = chart_points(df) if not df.empty else []
    if not data_points:
        _charts.set(cache_key, {"empty": True}, ttl=EMPTY_TTL_S)
        return {"empty": True}

    # Summary stats
    current = data_points[-1]["close"]
    first = data_points[0]["close"]
    high = max(p["high"] for p in data_points)
    low = min(p["low"] for p in data_points)
    change = current - first
    change_pct = (change / first * 100) if first else 0

    body = {
        "ticker": ticker,
        "period": period,
        "interval": config["interval"],
        "data_points": data_points,
        "count": len(data_points),
        "summary": {
            "current_price": _px(current),
            "period_high": _px(high),
            "period_low": _px(low),
            "change": _px(change),
            "change_pct": round(change_pct, 2),
        },
        "signal_markers": [],   # kept for older clients; always empty
    }
    _charts.set(cache_key, body, ttl=CHART_TTL_S[period])
    return body
