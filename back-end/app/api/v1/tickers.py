"""Ticker detail + price history API — for charts and ticker pages."""

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from loguru import logger

from app.core.dependencies import get_current_user
from app.scanners import market_scanner
from app.scanners.universe import get_exchange

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


@router.get("/{ticker}")
async def get_ticker_detail(
    ticker: str = Path(..., pattern=r"^[A-Z0-9.\-]{1,10}$"),
    user: dict = Depends(get_current_user),
):
    """Get full detail for a ticker — current price, fundamentals, latest signal.

    This is the data for the ticker detail page in the frontend.
    """
    ticker = ticker.upper()

    # Fetch price + fundamentals in parallel
    price_task = market_scanner.get_current_price(ticker)
    fundamentals_task = market_scanner.get_fundamentals(ticker)
    current_price, fundamentals = await asyncio.gather(price_task, fundamentals_task)

    if current_price is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Ticker {ticker} not found")

    exchange = get_exchange(ticker)
    asset_type = "CRYPTO" if exchange == "CRYPTO" else "EQUITY"

    # Get latest signal for this ticker (if any)
    from app.db import queries
    signals = queries.get_signals_by_ticker(ticker, limit=1)
    latest_signal = signals[0] if signals else None

    # Get open position (if any)
    positions = queries.get_open_positions()
    open_position = next((p for p in positions if p.get("symbol") == ticker), None)

    return {
        "ticker": ticker,
        "company_name": fundamentals.get("company_name") if fundamentals else None,
        "exchange": exchange,
        "asset_type": asset_type,
        "current_price": current_price,
        "fundamentals": fundamentals,
        "latest_signal": latest_signal,
        "open_position": open_position,
    }


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

    # Build chart data points
    data_points = []
    for idx, row in df.iterrows():
        data_points.append({
            "date": idx.isoformat(),
            "open": round(float(row["Open"]), 2),
            "high": round(float(row["High"]), 2),
            "low": round(float(row["Low"]), 2),
            "close": round(float(row["Close"]), 2),
            "volume": int(row["Volume"]),
        })

    # Summary stats
    current = data_points[-1]["close"] if data_points else 0
    first = data_points[0]["close"] if data_points else 0
    high = max(p["high"] for p in data_points) if data_points else 0
    low = min(p["low"] for p in data_points) if data_points else 0
    change = current - first
    change_pct = (change / first * 100) if first else 0

    # Get signal overlay points (BUY/SELL signals in this period)
    from app.db import queries
    all_signals = queries.get_signals_by_ticker(ticker, limit=100)
    signal_markers = []
    if data_points:
        chart_start = data_points[0]["date"]
        for s in all_signals:
            created = s.get("created_at", "")
            if created >= chart_start and s.get("action") in ("BUY", "SELL", "AVOID"):
                signal_markers.append({
                    "date": created,
                    "action": s["action"],
                    "score": s.get("score"),
                    "price": s.get("price_at_signal"),
                })

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
        "signal_markers": signal_markers,
    }


@router.get("/{ticker}/signals")
async def get_ticker_signals(
    ticker: str = Path(..., pattern=r"^[A-Z0-9.\-]{1,10}$"),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """Get signal history for a ticker."""
    from app.services import signal_service
    signals = signal_service.get_signals_by_ticker(ticker.upper(), limit=limit)
    return {"signals": signals, "count": len(signals)}
