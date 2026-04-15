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
    "yield_curve_10y2y": "T10Y2Y",        # 10Y-2Y spread (pre-computed by FRED)
    "credit_spread_bbb": "BAMLC0A4CBBB",  # ICE BofA BBB Corporate OAS (~1 day lag)
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


async def _fetch_fear_greed() -> Optional[dict]:
    """Fetch CNN Fear & Greed Index (free, no API key needed).

    Returns dict with 'score' (0-100) and 'label' (Extreme Fear/Fear/Neutral/Greed/Extreme Greed).
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                logger.warning("Fear & Greed: unexpected response format (not a dict)")
                return None
            fg = data.get("fear_and_greed") or data.get("data", {}).get("fear_and_greed", {})
            if not isinstance(fg, dict):
                logger.warning(f"Fear & Greed: missing fear_and_greed key, got keys: {list(data.keys())[:5]}")
                return None
            score = fg.get("score")
            rating = fg.get("rating")
            if score is None:
                logger.warning("Fear & Greed: score field is None")
                return None
            score_val = float(score)
            if not (0 <= score_val <= 100):
                logger.warning(f"Fear & Greed: score {score_val} out of range")
                return None
            return {"score": round(score_val, 1), "label": rating or "Unknown"}
    except httpx.TimeoutException:
        logger.warning("Fear & Greed: request timed out")
    except httpx.HTTPStatusError as e:
        logger.warning(f"Fear & Greed: HTTP {e.response.status_code}")
    except (ValueError, TypeError) as e:
        logger.warning(f"Fear & Greed: parse error: {e}")
    except Exception as e:
        logger.warning(f"Fear & Greed: unexpected error: {e}")
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


async def _fetch_vix_30d_high() -> Optional[float]:
    """Fetch the highest VIX close in the last 30 calendar days.

    Used by regime detection to determine if a recent crisis occurred
    (VIX > 30 within the window). Fetched ONCE per scan alongside the
    other macro data in get_macro_snapshot()'s asyncio.gather — NOT
    inside regime.py where it would block the event loop.
    """
    def _fetch():
        vix = yf.Ticker("^VIX")
        hist = vix.history(period="1mo")
        if hist.empty:
            return None
        return float(hist["Close"].max())

    try:
        return await asyncio.to_thread(_fetch)
    except Exception as e:
        logger.debug(f"VIX 30d high fetch failed: {e}")
        return None


async def _fetch_vix_term_structure() -> Optional[dict]:
    """Fetch VIX spot vs VIX 3-month futures to detect contango/backwardation.

    Backwardation (spot > futures) = market stress easing = bullish signal.
    Contango (spot < futures) = normal/complacent = neutral.
    """
    def _fetch():
        import yfinance as yf
        vix_spot = yf.Ticker("^VIX")
        vix_3m = yf.Ticker("^VIX3M")
        spot_hist = vix_spot.history(period="1d")
        futures_hist = vix_3m.history(period="1d")
        if spot_hist.empty or futures_hist.empty:
            return None
        spot = float(spot_hist["Close"].iloc[-1])
        futures = float(futures_hist["Close"].iloc[-1])
        ratio = spot / futures if futures > 0 else 1.0
        structure = "backwardation" if ratio > 1.0 else "contango"
        return {"spot": round(spot, 2), "futures_3m": round(futures, 2), "ratio": round(ratio, 3), "structure": structure}

    try:
        return await asyncio.to_thread(_fetch)
    except Exception as e:
        logger.warning(f"VIX term structure fetch failed: {e}")
        return None


async def _fetch_intermarket_signals() -> dict:
    """Fetch key intermarket indicators for cross-asset context.

    - 10Y-2Y Treasury spread (yield curve)
    - DXY (dollar index proxy via UUP)
    - Gold, Oil, Copper/Gold ratio
    """
    def _fetch():
        import yfinance as yf
        signals = {}
        try:
            # Gold and Oil for sector rotation
            gold = yf.Ticker("GC=F")
            oil = yf.Ticker("CL=F")
            gold_hist = gold.history(period="5d")
            oil_hist = oil.history(period="5d")
            if not gold_hist.empty:
                signals["gold_price"] = round(float(gold_hist["Close"].iloc[-1]), 2)
                if len(gold_hist) >= 2:
                    signals["gold_change_pct"] = round(((float(gold_hist["Close"].iloc[-1]) - float(gold_hist["Close"].iloc[0])) / float(gold_hist["Close"].iloc[0])) * 100, 2)
            if not oil_hist.empty:
                signals["oil_price"] = round(float(oil_hist["Close"].iloc[-1]), 2)
                if len(oil_hist) >= 2:
                    signals["oil_change_pct"] = round(((float(oil_hist["Close"].iloc[-1]) - float(oil_hist["Close"].iloc[0])) / float(oil_hist["Close"].iloc[0])) * 100, 2)
            # Copper/Gold ratio (economic health indicator)
            copper = yf.Ticker("HG=F")
            copper_hist = copper.history(period="1d")
            if not copper_hist.empty and not gold_hist.empty:
                copper_price = float(copper_hist["Close"].iloc[-1])
                gold_price = float(gold_hist["Close"].iloc[-1])
                if gold_price > 0:
                    signals["copper_gold_ratio"] = round(copper_price / gold_price * 1000, 2)
        except Exception as e:
            logger.debug(f"Intermarket fetch partial failure: {e}")
        return signals

    try:
        return await asyncio.to_thread(_fetch)
    except Exception as e:
        logger.warning(f"Intermarket signals fetch failed: {e}")
        return {}


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

    # VIX backwardation = stress (spot > futures)
    vix_term = macro_data.get("vix_term_structure")
    if vix_term and isinstance(vix_term, dict) and vix_term.get("ratio", 1.0) > 1.15:
        hostile_signals += 1

    # Yield curve inversion = recession warning (10Y-2Y spread negative)
    yield_curve = macro_data.get("yield_curve_10y2y")
    if yield_curve is not None and yield_curve < 0:
        hostile_signals += 1

    # Credit stress = corporate default risk elevated (BBB OAS > 3.0%)
    credit_spread = macro_data.get("credit_spread_bbb")
    if credit_spread is not None and credit_spread > 3.0:
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
        # Fetch all data in parallel (FRED + VIX + Fear & Greed)
        (
            fed_funds, treasury, cpi, unemployment,
            yield_curve, credit_spread,
            vix, fear_greed, vix_term, intermarket, vix_30d_high,
        ) = await asyncio.gather(
            _fetch_fred_series(SERIES["fed_funds_rate"], client),
            _fetch_fred_series(SERIES["treasury_10y"], client),
            _fetch_fred_series(SERIES["cpi_yoy"], client),
            _fetch_fred_series(SERIES["unemployment_rate"], client),
            _fetch_fred_series(SERIES["yield_curve_10y2y"], client),
            _fetch_fred_series(SERIES["credit_spread_bbb"], client),
            _fetch_vix(),
            _fetch_fear_greed(),
            _fetch_vix_term_structure(),
            _fetch_intermarket_signals(),
            _fetch_vix_30d_high(),
        )

    macro_data = {
        "fed_funds_rate": fed_funds,
        "treasury_10y": treasury,
        "cpi_yoy": cpi,
        "unemployment_rate": unemployment,
        "yield_curve_10y2y": yield_curve,
        "credit_spread_bbb": credit_spread,
        "vix": vix,
        "fear_greed": fear_greed,
        "vix_term_structure": vix_term,
        "intermarket": intermarket,
        "vix_30d_high": vix_30d_high,
    }

    macro_data["environment"] = classify_macro_environment(macro_data)

    logger.info(
        f"Macro snapshot: VIX={vix}, FedFunds={fed_funds}, "
        f"10Y={treasury}, YieldCurve={yield_curve}, CreditSpread={credit_spread}, "
        f"F&G={fear_greed}, VIX_term={vix_term}, "
        f"Intermarket={intermarket}, Environment={macro_data['environment']}"
    )

    return macro_data
