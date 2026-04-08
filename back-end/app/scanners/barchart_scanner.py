"""Barchart options flow scraper for sentiment enrichment.

Scrapes barchart.com/stocks/quotes/{TICKER}/overview to extract:
- Put/Call Volume Ratio
- IV Percentile
- Today's options volume vs 30-day average

Free data source — no API key required.
"""

import asyncio
import re
from typing import Optional

import httpx
from loguru import logger

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Rate limiter: max 3 concurrent requests to avoid being blocked
_semaphore = asyncio.Semaphore(3)
_MIN_DELAY = 0.5  # seconds between requests


def _clean_ticker(ticker: str) -> str:
    """Convert internal ticker format to Barchart format.

    SHOP.TO → SHOP (TSX tickers won't have options data on Barchart)
    BTC-USD → skip (crypto has no options)
    AAPL → AAPL
    """
    if ticker.endswith("-USD"):
        return ""  # crypto — no options
    if ".TO" in ticker:
        return ""  # TSX — Barchart uses US-only options data
    return ticker


def _parse_number(text: str) -> Optional[float]:
    """Parse a number from text, handling commas and percentages."""
    if not text:
        return None
    text = text.strip().replace(",", "").replace("%", "")
    try:
        return float(text)
    except (ValueError, TypeError):
        return None


async def get_options_flow(ticker: str) -> Optional[dict]:
    """Scrape Barchart overview page for options flow data.

    Returns:
        Dict with put_call_ratio, iv_percentile, options_volume,
        options_volume_avg_30d, volume_vs_avg, and a derived signal.
        None if ticker is unsupported or scrape fails.
    """
    clean = _clean_ticker(ticker)
    if not clean:
        return None

    async with _semaphore:
        await asyncio.sleep(_MIN_DELAY)
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"https://www.barchart.com/stocks/quotes/{clean}/overview",
                    headers=_HEADERS,
                    timeout=15,
                    follow_redirects=True,
                )
                resp.raise_for_status()
                html = resp.text

            result = _parse_options_data(html, ticker)
            if result:
                logger.debug(
                    f"Barchart [{ticker}] → P/C={result['put_call_ratio']}, "
                    f"IV%={result['iv_percentile']}, "
                    f"vol_vs_avg={result['volume_vs_avg']}"
                )
            return result

        except httpx.TimeoutException:
            logger.warning(f"Barchart: timeout for {ticker}")
        except httpx.HTTPStatusError as e:
            logger.warning(f"Barchart: HTTP {e.response.status_code} for {ticker}")
        except Exception as e:
            logger.warning(f"Barchart: unexpected error for {ticker}: {e}")
        return None


def _parse_options_data(html: str, ticker: str) -> Optional[dict]:
    """Extract options flow metrics from Barchart HTML.

    Looks for Put/Call Volume Ratio, IV Percentile, and options volume data
    in the overview page HTML.
    """
    if not html or len(html) < 500:
        return None

    put_call_ratio = _extract_put_call_ratio(html)
    iv_percentile = _extract_iv_percentile(html)
    options_volume = _extract_options_volume(html)
    options_volume_avg = _extract_options_volume_avg(html)

    # Need at least one meaningful data point
    if put_call_ratio is None and iv_percentile is None and options_volume is None:
        logger.debug(f"Barchart: no options data found for {ticker}")
        return None

    # Compute volume vs average ratio
    volume_vs_avg = None
    if options_volume is not None and options_volume_avg is not None and options_volume_avg > 0:
        volume_vs_avg = round(options_volume / options_volume_avg, 2)

    # Derive a directional signal from the options data
    signal = _derive_options_signal(put_call_ratio, iv_percentile, volume_vs_avg)

    return {
        "put_call_ratio": put_call_ratio,
        "iv_percentile": iv_percentile,
        "options_volume": options_volume,
        "options_volume_avg_30d": options_volume_avg,
        "volume_vs_avg": volume_vs_avg,
        "signal": signal["direction"],
        "signal_strength": signal["strength"],
        "agreement_note": signal["note"],
    }


def _extract_put_call_ratio(html: str) -> Optional[float]:
    """Extract Put/Call Volume Ratio from Barchart page."""
    patterns = [
        r'Put/Call\s*(?:Volume\s*)?Ratio[^<]*?<[^>]*>([0-9.,]+)',
        r'putCallVolRatio["\s:]+([0-9.,]+)',
        r'Put/Call[^0-9]*?([0-9]+\.[0-9]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            val = _parse_number(match.group(1))
            if val is not None and 0 < val < 10:
                return round(val, 2)
    return None


def _extract_iv_percentile(html: str) -> Optional[float]:
    """Extract IV Percentile from Barchart page."""
    patterns = [
        r'IV\s*Percentile[^<]*?<[^>]*>([0-9.,]+)%?',
        r'ivPercentile["\s:]+([0-9.,]+)',
        r'Implied\s*Volatility\s*Percentile[^0-9]*?([0-9.]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            val = _parse_number(match.group(1))
            if val is not None and 0 <= val <= 100:
                return round(val, 1)
    return None


def _extract_options_volume(html: str) -> Optional[float]:
    """Extract today's options volume from Barchart page."""
    patterns = [
        r'Options\s*Volume[^<]*?<[^>]*>([0-9.,]+)',
        r'optionsVolume["\s:]+([0-9.,]+)',
        r'Total\s*(?:Options\s*)?Volume[^0-9]*?([0-9,]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            val = _parse_number(match.group(1))
            if val is not None and val > 0:
                return val
    return None


def _extract_options_volume_avg(html: str) -> Optional[float]:
    """Extract 30-day average options volume from Barchart page."""
    patterns = [
        r'(?:30[- ]?(?:Day|d)\s*)?(?:Avg|Average)\s*(?:Options\s*)?Volume[^<]*?<[^>]*>([0-9.,]+)',
        r'avgOptionsVolume["\s:]+([0-9.,]+)',
        r'Average\s*Volume[^0-9]*?([0-9,]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            val = _parse_number(match.group(1))
            if val is not None and val > 0:
                return val
    return None


def _derive_options_signal(
    put_call_ratio: Optional[float],
    iv_percentile: Optional[float],
    volume_vs_avg: Optional[float],
) -> dict:
    """Derive a directional signal from options flow data.

    Returns dict with direction (bullish/bearish/neutral),
    strength (0-100), and a human-readable note.
    """
    signals = []
    notes = []

    if put_call_ratio is not None:
        if put_call_ratio < 0.7:
            signals.append(("bullish", 30))
            notes.append(f"Low P/C ratio ({put_call_ratio}) = call-heavy flow")
        elif put_call_ratio > 1.2:
            signals.append(("bearish", 30))
            notes.append(f"High P/C ratio ({put_call_ratio}) = put-heavy flow")
        else:
            signals.append(("neutral", 10))

    if iv_percentile is not None:
        if iv_percentile > 80:
            signals.append(("bearish", 20))
            notes.append(f"High IV percentile ({iv_percentile}%) = elevated fear")
        elif iv_percentile < 20:
            signals.append(("bullish", 20))
            notes.append(f"Low IV percentile ({iv_percentile}%) = complacency")
        else:
            signals.append(("neutral", 5))

    if volume_vs_avg is not None:
        if volume_vs_avg > 1.5:
            notes.append(f"Options volume {volume_vs_avg}x above 30d avg = unusual activity")
            signals.append(("notable", 15))
        elif volume_vs_avg < 0.5:
            signals.append(("neutral", 5))

    if not signals:
        return {"direction": "neutral", "strength": 0, "note": "No options data"}

    # Tally bullish vs bearish
    bullish_score = sum(s for d, s in signals if d == "bullish")
    bearish_score = sum(s for d, s in signals if d == "bearish")

    strength = abs(bullish_score - bearish_score)
    if bullish_score > bearish_score:
        direction = "bullish"
    elif bearish_score > bullish_score:
        direction = "bearish"
    else:
        direction = "neutral"

    note = "; ".join(notes) if notes else "Options flow neutral"
    return {"direction": direction, "strength": min(100, strength), "note": note}
