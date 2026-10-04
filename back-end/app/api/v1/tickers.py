"""Price history for charts (GET /tickers/{ticker}/chart). Free."""

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from loguru import logger

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
        out.append({"date": idx.isoformat(), "open": round(o, 2), "high": round(h, 2),
                    "low": round(lo, 2), "close": round(c, 2), "volume": vol})
    return out


@router.get("/{ticker}/chart")
async def get_ticker_chart(
    ticker: str = Path(..., pattern=r"^[A-Z0-9.\-]{1,10}$"),
    period: Literal["1d", "5d", "1mo", "3mo", "6mo", "1y", "5y"] = Query("3mo"),
    user: dict = Depends(get_current_user),
):
    """Get OHLCV price history for charting.

    Returns data points formatted for frontend chart libraries.
    Each point has: date, open, high, low, close, volume.

    Periods:
    - 1d: 5-min candles (intraday)
    - 5d: 15-min candles
    - 1mo: hourly candles
    - 3mo/6mo/1y: daily candles
    - 5y: weekly candles
    """
    ticker = ticker.upper()
    config = _PERIOD_CONFIG[period]

    def _fetch():
        import yfinance as yf
        t = yf.Ticker(ticker)
        df = t.history(period=config["period"], interval=config["interval"])
        return df

    try:
        df = await asyncio.to_thread(_fetch)
    except Exception as e:
        logger.error(f"Chart data fetch failed for {ticker}: {e}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to fetch price data")

    if df.empty:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No price data for {ticker}")

    # Flatten MultiIndex if present
    import pandas as pd
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    data_points = chart_points(df)
    if not data_points:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No price data for {ticker}")

    # Summary stats
    current = data_points[-1]["close"] if data_points else 0
    first = data_points[0]["close"] if data_points else 0
    high = max(p["high"] for p in data_points) if data_points else 0
    low = min(p["low"] for p in data_points) if data_points else 0
    change = current - first
    change_pct = (change / first * 100) if first else 0

    return {
        "ticker": ticker,
        "period": period,
        "interval": config["interval"],
        "data_points": data_points,
        "count": len(data_points),
        "summary": {
            "current_price": round(current, 2),
            "period_high": round(high, 2),
            "period_low": round(low, 2),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
        },
        "signal_markers": [],   # kept for older clients; always empty
    }
