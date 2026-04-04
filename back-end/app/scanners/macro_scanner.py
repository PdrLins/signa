"""FRED API client for macro economic data."""

import asyncio
from typing import Optional

import httpx
import yfinance as yf
from loguru import logger

from app.core.config import settings

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

SERIES = {
    "fed_funds_rate": "FEDFUNDS",
    "treasury_10y": "GS10",
    "cpi_yoy": "CPIAUCSL",
    "unemployment_rate": "UNRATE",
}


async def _fetch_fred_series(series_id: str, client: httpx.AsyncClient) -> Optional[float]:
    """Fetch the latest value for a FRED series."""
    try:
        params = {
            "series_id": series_id,
            "api_key": settings.fred_api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 1,
        }
        resp = await client.get(FRED_BASE_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        observations = data.get("observations", [])
        if observations and observations[0].get("value") != ".":
            return float(observations[0]["value"])
    except Exception as e:
        logger.warning(f"FRED fetch failed for {series_id}: {e}")
    return None


async def _fetch_vix() -> Optional[float]:
    """Fetch current VIX level via yfinance."""
    def _fetch():
        vix = yf.Ticker("^VIX")
        hist = vix.history(period="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
        return None

    try:
        return await asyncio.to_thread(_fetch)
    except Exception as e:
        logger.warning(f"VIX fetch failed: {e}")
        return None


def classify_macro_environment(macro_data: dict) -> str:
    """Classify macro environment as favorable, neutral, or hostile."""
    hostile_signals = 0

    vix = macro_data.get("vix")
    fed_funds = macro_data.get("fed_funds_rate")
    unemployment = macro_data.get("unemployment_rate")
    treasury_10y = macro_data.get("treasury_10y")

    if vix is not None and vix > 30:
        hostile_signals += 1
    if fed_funds is not None and fed_funds > 5.0:
        hostile_signals += 1
    if unemployment is not None and unemployment > 6.0:
        hostile_signals += 1
    if treasury_10y is not None and fed_funds is not None and treasury_10y < fed_funds:
        hostile_signals += 1

    if hostile_signals >= 3:
        return "hostile"
    elif hostile_signals >= 1:
        return "neutral"
    return "favorable"


async def get_macro_snapshot() -> dict:
    """Fetch all macro data and return a snapshot dict.

    Called once per scan cycle — macro data doesn't change between tickers.
    """
    async with httpx.AsyncClient() as client:
        # Fetch all data in parallel (FRED + VIX)
        fed_funds, treasury, cpi, unemployment, vix = await asyncio.gather(
            _fetch_fred_series(SERIES["fed_funds_rate"], client),
            _fetch_fred_series(SERIES["treasury_10y"], client),
            _fetch_fred_series(SERIES["cpi_yoy"], client),
            _fetch_fred_series(SERIES["unemployment_rate"], client),
            _fetch_vix(),
        )

    macro_data = {
        "fed_funds_rate": fed_funds,
        "treasury_10y": treasury,
        "cpi_yoy": cpi,
        "unemployment_rate": unemployment,
        "vix": vix,
    }

    macro_data["environment"] = classify_macro_environment(macro_data)

    logger.info(
        f"Macro snapshot: VIX={vix}, FedFunds={fed_funds}, "
        f"10Y={treasury}, Environment={macro_data['environment']}"
    )

    return macro_data
