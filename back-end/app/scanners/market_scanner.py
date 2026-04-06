"""Market data fetching via yfinance — prices, volume, and fundamentals."""

import asyncio
from datetime import date
from typing import Optional

import pandas as pd
import yfinance as yf
from loguru import logger


async def get_price_history(ticker: str, period: str = "3mo") -> pd.DataFrame:
    """Fetch OHLCV price history for a ticker.

    Args:
        ticker: Stock symbol (e.g., 'AAPL' or 'SHOP.TO').
        period: yfinance period string ('1mo', '3mo', '6mo', '1y').

    Returns:
        DataFrame with Open, High, Low, Close, Volume columns.
    """
    def _fetch():
        t = yf.Ticker(ticker)
        return t.history(period=period)

    try:
        df = await asyncio.to_thread(_fetch)
        if df.empty:
            logger.warning(f"No price data for {ticker}")
        return df
    except Exception as e:
        logger.error(f"Failed to fetch price history for {ticker}: {e}")
        return pd.DataFrame()


async def get_fundamentals(ticker: str) -> dict:
    """Fetch fundamental data for a ticker via yfinance .info. Cached for 5 min.

    Returns dict with P/E, dividend yield, EPS, debt/equity, etc.
    """
    from app.core.cache import price_cache
    cache_key = f"fund:{ticker}"
    cached = price_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        t = yf.Ticker(ticker)
        return t.info

    try:
        info = await asyncio.to_thread(_fetch)

        # Parse earnings date
        earnings_date = None
        if "earningsDate" in info and info["earningsDate"]:
            try:
                ed = info["earningsDate"]
                if isinstance(ed, list) and len(ed) > 0:
                    earnings_date = date.fromtimestamp(ed[0]).isoformat()
                elif isinstance(ed, (int, float)):
                    earnings_date = date.fromtimestamp(ed).isoformat()
            except (ValueError, TypeError, OSError, OverflowError):
                pass

        result = {
            "company_name": info.get("longName") or info.get("shortName"),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "eps": info.get("trailingEps"),
            "eps_growth": info.get("earningsGrowth"),
            "dividend_yield": info.get("dividendYield"),
            "payout_ratio": info.get("payoutRatio"),
            "debt_to_equity": info.get("debtToEquity"),
            "market_cap": info.get("marketCap"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "earnings_date": earnings_date,
            "beta": info.get("beta"),
            "profit_margin": info.get("profitMargins"),
            "revenue_growth": info.get("revenueGrowth"),
            "52w_high": info.get("fiftyTwoWeekHigh"),
            "52w_low": info.get("fiftyTwoWeekLow"),
            # Market session prices
            "regular_market_price": info.get("regularMarketPrice"),
            "regular_market_change": info.get("regularMarketChange"),
            "regular_market_change_pct": info.get("regularMarketChangePercent"),
            "regular_market_time": info.get("regularMarketTime"),
            "post_market_price": info.get("postMarketPrice"),
            "post_market_change": info.get("postMarketChange"),
            "post_market_change_pct": info.get("postMarketChangePercent"),
            "pre_market_price": info.get("preMarketPrice"),
            "pre_market_change": info.get("preMarketChange"),
            "pre_market_change_pct": info.get("preMarketChangePercent"),
        }
        price_cache.set(cache_key, result, ttl=300)
        return result
    except Exception as e:
        logger.error(f"Failed to fetch fundamentals for {ticker}: {e}")
        return {}


async def get_bulk_screening(tickers: list[str]) -> dict[str, dict]:
    """Fetch quick screening data for many tickers (volume, price change).

    Used for pre-filtering the universe down to candidates.

    Returns:
        Dict mapping ticker -> { volume, avg_volume, day_change, price }
    """
    def _fetch():
        results = {}
        batch_size = 50
        for i in range(0, len(tickers), batch_size):
            batch = tickers[i:i + batch_size]
            symbols = " ".join(batch)
            try:
                data = yf.download(
                    symbols, period="5d", group_by="ticker",
                    progress=False, threads=True,
                )
                for ticker in batch:
                    try:
                        if len(batch) == 1:
                            df = data
                        else:
                            df = data[ticker] if ticker in data.columns.get_level_values(0) else pd.DataFrame()

                        if df.empty or len(df) < 2:
                            continue

                        last_close = df["Close"].iloc[-1]
                        prev_close = df["Close"].iloc[-2]
                        day_change = (last_close - prev_close) / prev_close if prev_close else 0
                        avg_volume = df["Volume"].mean()
                        last_volume = df["Volume"].iloc[-1]

                        results[ticker] = {
                            "price": float(last_close),
                            "volume": float(last_volume),
                            "avg_volume": float(avg_volume),
                            "day_change": float(day_change),
                        }
                    except Exception:
                        continue
            except Exception as e:
                logger.warning(f"Batch download failed for batch starting at {i}: {e}")
                continue
        return results

    try:
        return await asyncio.to_thread(_fetch)
    except Exception as e:
        logger.error(f"Bulk screening failed: {e}")
        return {}


async def get_current_price(ticker: str) -> Optional[float]:
    """Get the current/last price for a ticker. Cached for 60s."""
    from app.core.cache import price_cache
    cache_key = f"price:{ticker}"
    cached = price_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        t = yf.Ticker(ticker)
        hist = t.history(period="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
        return None

    try:
        price = await asyncio.to_thread(_fetch)
        if price is not None:
            price_cache.set(cache_key, price, ttl=60)
        return price
    except Exception as e:
        logger.error(f"Failed to get price for {ticker}: {e}")
        return None
