"""Data loader for backtest — OHLCV, fundamentals, and macro data."""

import json
import random
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pandas as pd
import yfinance as yf
from loguru import logger

# Fetch 300 calendar days before start_date for indicator warmup
# (SMA 200 needs ~200 trading days ≈ ~280 calendar days)
WARMUP_CALENDAR_DAYS = 300

FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"


class DataLoader:
    def __init__(self, config: dict):
        self.config = config
        self.cache_dir = Path(config["cache_dir"])
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.start_date = config["start_date"]
        self.end_date = config["end_date"]
        self.use_cache = config.get("use_cache", True)

        # Compute warmup start date for yfinance fetch
        start_dt = datetime.strptime(self.start_date, "%Y-%m-%d")
        self._fetch_start = (start_dt - timedelta(days=WARMUP_CALENDAR_DAYS)).strftime("%Y-%m-%d")

    def load_all(self) -> dict[str, pd.DataFrame]:
        """Load OHLCV data for all tickers in config.

        Returns dict mapping ticker -> DataFrame.
        """
        all_tickers = (
            self.config["tickers"].get("US", [])
            + self.config["tickers"].get("TSX", [])
            + self.config["tickers"].get("CRYPTO", [])
        )
        results: dict[str, pd.DataFrame] = {}
        failed: list[str] = []

        for ticker in all_tickers:
            df = self.load_ticker(ticker)
            if df is not None and not df.empty:
                results[ticker] = df
            else:
                failed.append(ticker)

        loaded = len(results)
        total = len(all_tickers)
        if failed:
            logger.warning(
                f"Loaded {loaded}/{total} tickers successfully "
                f"({len(failed)} failed: {', '.join(failed)})"
            )
        else:
            logger.info(f"Loaded {loaded}/{total} tickers successfully")

        return results

    def load_ticker(self, ticker: str) -> pd.DataFrame | None:
        """Load OHLCV data for a single ticker.

        Fetches extra history before start_date for indicator warmup.
        Uses parquet cache if available and use_cache=True.
        """
        cache_path = self.cache_dir / f"{ticker.replace('.', '_')}.parquet"

        if self.use_cache and cache_path.exists():
            try:
                df = pd.read_parquet(cache_path)
                df.index = pd.to_datetime(df.index)
                logger.info(f"Loading {ticker}... cached ({len(df)} rows)")
                return df
            except Exception as e:
                logger.warning(f"Cache read failed for {ticker}, refetching: {e}")

        try:
            time.sleep(random.uniform(0.1, 0.3))
            df = yf.download(
                ticker,
                start=self._fetch_start,
                end=self.end_date,
                progress=False,
            )
            if df.empty:
                logger.error(f"Loading {ticker}... no data returned")
                return None

            # Flatten MultiIndex columns if present (yfinance 0.2.50+)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df.index = pd.to_datetime(df.index)
            df.to_parquet(cache_path)
            logger.info(f"Loading {ticker}... fetched ({len(df)} rows)")
            return df

        except Exception as e:
            logger.error(f"Loading {ticker}... FAILED: {e}")
            return None

    def load_fundamentals(self, ticker: str) -> dict:
        """Load fundamental data for a ticker.

        Uses JSON cache if available, otherwise pulls from yfinance.
        """
        fund_dir = self.cache_dir / "fundamentals"
        fund_dir.mkdir(parents=True, exist_ok=True)
        cache_path = fund_dir / f"{ticker.replace('.', '_')}.json"

        if self.use_cache and cache_path.exists():
            try:
                with open(cache_path) as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Fundamentals cache read failed for {ticker}: {e}")

        try:
            time.sleep(random.uniform(0.1, 0.3))
            info = yf.Ticker(ticker).info

            fundamentals = {
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
                "beta": info.get("beta"),
                "52w_high": info.get("fiftyTwoWeekHigh"),
                "52w_low": info.get("fiftyTwoWeekLow"),
                "short_ratio": info.get("shortRatio"),
                "book_value": info.get("bookValue"),
                "revenue_growth": info.get("revenueGrowth"),
                "profitMargins": info.get("profitMargins"),
            }

            # Strip None values for cleaner JSON
            fundamentals = {k: v for k, v in fundamentals.items() if v is not None}

            with open(cache_path, "w") as f:
                json.dump(fundamentals, f, indent=2)

            logger.debug(f"Fundamentals for {ticker}: {len(fundamentals)} fields")
            return fundamentals

        except Exception as e:
            logger.error(f"Fundamentals fetch failed for {ticker}: {e}")
            return {}

    def load_macro(self) -> dict[str, pd.DataFrame]:
        """Load macro economic data from FRED via direct API calls.

        Series:
        - DFF: Fed Funds Rate
        - CPIAUCSL: CPI inflation
        - VIXCLS: VIX volatility index

        Returns dict of { series_name: DataFrame }.
        """
        cache_path = self.cache_dir / "macro.parquet"

        if self.use_cache and cache_path.exists():
            try:
                combined = pd.read_parquet(cache_path)
                combined.index = pd.to_datetime(combined.index)
                result = {col: combined[[col]].dropna() for col in combined.columns}
                logger.info("Macro data loaded from cache")
                return result
            except Exception as e:
                logger.warning(f"Macro cache read failed, refetching: {e}")

        fred_key = self.config.get("fred_api_key", "")
        if not fred_key:
            # Try loading from .env
            try:
                from dotenv import dotenv_values
                env = dotenv_values(".env")
                fred_key = env.get("FRED_API_KEY", "")
            except Exception:
                pass

        if not fred_key:
            logger.warning("No FRED_API_KEY — skipping macro data")
            return {}

        series_ids = {
            "fed_funds_rate": "DFF",
            "cpi": "CPIAUCSL",
            "vix": "VIXCLS",
        }

        frames: dict[str, pd.DataFrame] = {}

        for name, series_id in series_ids.items():
            df = self._fetch_fred_series(series_id, name, fred_key)
            if df is not None:
                frames[name] = df

        # Cache combined DataFrame
        if frames:
            try:
                combined = pd.concat(frames.values(), axis=1)
                combined.to_parquet(cache_path)
            except Exception as e:
                logger.warning(f"Macro cache write failed: {e}")

        if frames:
            logger.info(f"Macro data loaded: {', '.join(frames.keys())}")
        else:
            logger.warning("No macro data loaded")

        return frames

    def _fetch_fred_series(
        self, series_id: str, name: str, api_key: str,
    ) -> pd.DataFrame | None:
        """Fetch a single FRED series via the REST API."""
        try:
            resp = httpx.get(
                FRED_API_URL,
                params={
                    "series_id": series_id,
                    "api_key": api_key,
                    "file_type": "json",
                    "observation_start": self._fetch_start,
                    "observation_end": self.end_date,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            observations = data.get("observations", [])
            if not observations:
                logger.warning(f"FRED {name} ({series_id}): no observations")
                return None

            rows = []
            for obs in observations:
                val = obs.get("value")
                if val and val != ".":
                    rows.append({
                        "date": obs["date"],
                        name: float(val),
                    })

            if not rows:
                return None

            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
            logger.debug(f"FRED {name} ({series_id}): {len(df)} rows")
            return df

        except Exception as e:
            logger.warning(f"FRED fetch failed for {name} ({series_id}): {e}")
            return None

    def get_trading_days(self) -> list[str]:
        """Return all trading days between start and end date.

        Uses AAPL price data as the reference calendar.
        Only returns days within the configured date range (not warmup).
        """
        aapl = self.load_ticker("AAPL")
        if aapl is None or aapl.empty:
            logger.error("Cannot determine trading days — AAPL data unavailable")
            return []

        start_ts = pd.Timestamp(self.start_date)
        end_ts = pd.Timestamp(self.end_date)
        mask = (aapl.index >= start_ts) & (aapl.index <= end_ts)
        days = [d.strftime("%Y-%m-%d") for d in aapl.index[mask]]
        if not days:
            logger.error("No trading days found in date range")
            return []
        logger.info(f"Trading days: {len(days)} ({days[0]} → {days[-1]})")
        return days
