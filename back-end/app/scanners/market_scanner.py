"""Market data fetching via yfinance — prices, volume, and fundamentals."""

import asyncio
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from loguru import logger

from app.core.cache import TTLCache

# Disable yfinance's internal SQLite caching entirely.
# It corrupts under concurrent async access. We use our own TTLCache instead.
import os as _os
_os.environ["YF_CACHE"] = "0"
try:
    yf.set_tz_cache_location(_os.devnull)
except Exception:
    pass

# Per-ticker bulk-screening cache. The 1y-derived features bulk_screening returns
# doesn't materially change minute-to-minute, so we cache across scans and
# only re-fetch on misses. First scan of the day pays full price; later
# scans skip most of the ~100s yfinance screening cost.
#
# TTL is dynamic — see `_bulk_screen_ttl()`. Shorter during market hours
# (prices move fast, stale data risks acting on a gap) and longer outside
# hours (nothing moves). The audit explicitly flagged this stale-data risk.
_bulk_screening_cache = TTLCache(max_size=2000, default_ttl=1800)  # fallback only


def _bulk_screen_ttl() -> int:
    """TTL for bulk-screening cache entries, tuned to the session clock.

    During the US regular session (9:30-16:00 ET, weekdays) prices move
    fast enough that a stale cache from 30 min ago could feed a scan data
    that's materially wrong. Keep it to 15 min.

    Outside the regular session (overnight, weekends, holidays) prices
    don't move and we can safely reuse results for hours — we cap at 1 hr
    anyway because the trading day rolls and the bulk_screening window
    shifts when a new session closes.
    """
    now_et = datetime.now(ZoneInfo("America/New_York"))
    if now_et.weekday() >= 5:  # weekend
        return 3600
    minutes = now_et.hour * 60 + now_et.minute
    # 9:30am = 570, 4:00pm = 960
    if 570 <= minutes < 960:
        return 900  # 15 min during session
    return 3600  # 1 hr outside session

# Concurrency cap for parallel batch downloads. yfinance + DNS + macOS thread
# pool starts to fall over above ~3 simultaneous in-flight downloads — this
# is the same DNS-exhaustion ceiling that motivated batch_size=20/threads=False
# in the first place. Keep this conservative.
_BULK_BATCH_CONCURRENCY = 3


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
        result = t.history(period=period)
        # yfinance sometimes returns None instead of an empty DataFrame
        if result is None:
            return pd.DataFrame()
        return result

    try:
        df = await asyncio.to_thread(_fetch)
        if df is None or df.empty:
            logger.warning(f"No price data for {ticker}")
            return pd.DataFrame()
        return df
    except Exception as e:
        logger.error(f"Failed to fetch price history for {ticker}: {e}")
        return pd.DataFrame()


def _normalize_pct(value) -> float | None:
    """Normalize percentage values from yfinance.

    yfinance is inconsistent -- dividend_yield and payout_ratio
    sometimes come as decimals (0.0199 = 1.99%) and sometimes
    as whole numbers (1.99 = 1.99%). We normalize to decimal form
    so 0.04 means 4%.
    """
    if value is None:
        return None
    try:
        v = float(value)
        # If value > 1, it's likely a percentage (e.g., 1.99 = 1.99%)
        # Convert to decimal form (0.0199)
        if v > 1:
            return v / 100
        return v
    except (ValueError, TypeError):
        return None


def _fraction(value) -> float | None:
    """Coerce a yfinance value that is ALREADY a fraction (payoutRatio,
    shortPercentOfFloat, trailingAnnualDividendYield, ETF `yield`).

    Unlike `_normalize_pct` this never divides by 100 based on magnitude:
    a payout ratio of 1.5 (150%) is real and must stay 1.5.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _dividend_yield_fraction(info: dict) -> float | None:
    """Dividend yield as a FRACTION (0.04 = 4%), robust to yfinance units.

    Why not `_normalize_pct(info["dividendYield"])`: since early 2025
    Yahoo reports `dividendYield` in PERCENT (AAPL 0.44 means 0.44%).
    The magnitude heuristic ("> 1 means percent") misread every sub-1%
    yield as a fraction — 0.44 became 44%, which `_cap_dividend_yield`
    then discarded as garbage, so low-yield names showed NO dividend.

    Resolution order (first that is present wins):
      1. dividendRate / price   — both unambiguous (USD per share / USD)
      2. dividendYield / 100    — percent units in yfinance >= 0.2.54
      3. trailingAnnualDividendYield — fraction
      4. yield                  — fraction (ETFs)
    """
    rate = info.get("dividendRate")
    price = (
        info.get("regularMarketPrice") or info.get("currentPrice")
        or info.get("previousClose")
    )
    try:
        if rate is not None and price and float(price) > 0:
            return float(rate) / float(price)
    except (TypeError, ValueError):
        pass
    dy = info.get("dividendYield")
    if dy is not None:
        try:
            return float(dy) / 100.0
        except (TypeError, ValueError):
            pass
    for key in ("trailingAnnualDividendYield", "yield"):
        v = _fraction(info.get(key))
        if v is not None:
            return v
    return None


def _next_earnings_date_from_info(info: dict) -> str | None:
    """Next earnings date (ISO) from the real yfinance `.info` keys.

    `.info` has no "earningsDate" key (that lives in Ticker.calendar, a
    different quoteSummary module), so the old parser always produced
    None. The v7 quote payload merged into `.info` carries
    `earningsTimestampStart` / `earningsTimestamp` / `earningsTimestampEnd`
    (epoch seconds). Pick the earliest one that is today or later.
    """
    today = date.today()
    candidates = []
    for key in ("earningsTimestampStart", "earningsTimestamp", "earningsTimestampEnd"):
        ts = info.get(key)
        if not ts:
            continue
        try:
            d = datetime.fromtimestamp(float(ts), tz=ZoneInfo("America/New_York")).date()
        except (ValueError, TypeError, OSError, OverflowError):
            continue
        if d >= today:
            candidates.append(d)
    return min(candidates).isoformat() if candidates else None


def _cap_dividend_yield(value: float | None) -> float | None:
    """Cap dividend yield at 15% to filter yfinance garbage data.

    No legitimate, sustainable dividend yield exceeds ~15% (even REITs
    and BDCs rarely go above 12%). yfinance regularly returns nonsense
    values for ADRs and international stocks — PBR-A showed 744%,
    AGI.TO showed 24%. These inflate the "Dividend Reliability" score
    component and mislead the brain into thinking a stock has strong
    income characteristics when it doesn't.

    Values above 15% are capped to None (treated as no dividend data)
    rather than capped to 15%, because a garbage value tells us the
    data source is unreliable — better to score as "unknown" than to
    assume the cap is the real yield.
    """
    if value is None:
        return None
    if value > 0.15:  # 15% in decimal form
        return None
    return value


def _compute_period_changes(hist: pd.DataFrame) -> dict:
    """Compute 1W, 1M, 3M, YTD price changes from a 1-year history DataFrame."""
    if hist.empty or len(hist) < 2:
        return {}

    current = float(hist["Close"].iloc[-1])
    result = {}

    def _pct(days_ago_approx: int, key: str):
        idx = max(0, len(hist) - days_ago_approx)
        if idx < len(hist):
            old = float(hist["Close"].iloc[idx])
            if old > 0:
                result[key] = round(((current - old) / old) * 100, 2)

    _pct(5, "week_change_pct")    # ~5 trading days
    _pct(21, "month_change_pct")  # ~21 trading days
    _pct(63, "three_month_change_pct")  # ~63 trading days

    # YTD: find first trading day of this year
    try:
        this_year = date.today().year
        ytd_data = hist[hist.index.year == this_year]
        if not ytd_data.empty:
            ytd_start = float(ytd_data["Close"].iloc[0])
            if ytd_start > 0:
                result["ytd_change_pct"] = round(((current - ytd_start) / ytd_start) * 100, 2)
    except Exception:
        pass

    return result


async def _get_spy_benchmark() -> dict:
    """Get SPY period changes for benchmark comparison. Cached for 5 min."""
    from app.core.cache import price_cache
    cache_key = "benchmark:SPY"
    cached = price_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        t = yf.Ticker("SPY")
        hist = t.history(period="1y")
        return _compute_period_changes(hist)

    try:
        result = await asyncio.to_thread(_fetch)
        price_cache.set(cache_key, result, ttl=300)
        return result
    except Exception as e:
        logger.debug(f"SPY benchmark fetch failed: {e}")
        return {}


async def get_fundamentals(ticker: str) -> dict:
    """Fetch fundamental data for a ticker via yfinance .info. Cached for 5 min.

    Returns dict with P/E, dividend yield, EPS, debt/equity, etc.
    """
    from app.core.cache import price_cache
    cache_key = f"fund:{ticker}"
    cached = price_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        def _fetch():
            t = yf.Ticker(ticker)
            try:
                info = t.info or {}
            except Exception:
                info = {}
            return info

        info = await asyncio.to_thread(_fetch)

        # Next earnings date from the real .info keys (see helper).
        earnings_date = _next_earnings_date_from_info(info)

        result = {
            "company_name": info.get("longName") or info.get("shortName"),
            "description": info.get("longBusinessSummary"),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "eps": info.get("trailingEps"),
            "eps_growth": info.get("earningsGrowth"),
            "dividend_yield": _cap_dividend_yield(_dividend_yield_fraction(info)),
            "payout_ratio": _fraction(info.get("payoutRatio")),
            "debt_to_equity": info.get("debtToEquity"),
            "market_cap": info.get("marketCap"),
            "sector": info.get("sector"),
            "quote_type": info.get("quoteType"),
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
            "short_percent_of_float": _fraction(info.get("shortPercentOfFloat")),
        }
        # Richer equity data (estimate revisions, relative-strength
        # benchmarks, short-interest trend, insider buying). Cached ~12h
        # per ticker inside enrichment; never fails the fundamentals call.
        try:
            from app.scanners.enrichment import get_enrichment
            result.update(await get_enrichment(ticker, info))
        except Exception as e:
            logger.debug(f"Enrichment skipped for {ticker}: {e}")
        price_cache.set(cache_key, result, ttl=300)
        return result
    except Exception as e:
        logger.error(f"Failed to fetch fundamentals for {ticker}: {e}")
        return {}


async def get_period_changes(ticker: str) -> dict:
    """Get multi-period price changes + SPY benchmark for a single ticker.

    Only called from the ticker detail page, NOT during scans.
    Cached for 5 minutes.
    """
    from app.core.cache import price_cache
    cache_key = f"periods:{ticker}"
    cached = price_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        t = yf.Ticker(ticker)
        hist = t.history(period="1y")
        return _compute_period_changes(hist)

    try:
        changes = await asyncio.to_thread(_fetch)
        spy_changes = await _get_spy_benchmark()
        result = {**changes, "spy": spy_changes}
        price_cache.set(cache_key, result, ttl=300)
        return result
    except Exception as e:
        logger.debug(f"Period changes fetch failed for {ticker}: {e}")
        return {}


def _screening_features(df: pd.DataFrame) -> dict:
    """Cheap per-ticker features for the pre-filter, from ~1y daily bars.

    Besides price/volume/day_change (kept for display and back-compat),
    computes the TREND-QUALITY inputs the pre-filter now ranks on:
      vs_sma50 / vs_sma200   — % distance of price from the SMAs
      sma50_above_sma200     — long-term uptrend structure
      ret_3m_ex_1w           — ~3-month return EXCLUDING the last week
                               (classic momentum skips the most recent
                               period to avoid short-term reversal)
      rsi14                  — to avoid overbought / broken names
    """
    close = df["Close"].astype(float)
    volume = df["Volume"].astype(float).fillna(0)
    last_close = float(close.iloc[-1])
    prev_close = float(close.iloc[-2])
    day_change = (last_close - prev_close) / prev_close if prev_close else 0.0
    # 20-session average volume (prior bars) — robust to a partial today.
    vol_window = volume.iloc[-21:-1] if len(volume) >= 21 else volume
    feats: dict = {
        "price": last_close,
        "volume": float(volume.iloc[-1]),
        "avg_volume": float(vol_window.mean()),
        "day_change": float(day_change),
    }
    n = len(close)
    if n >= 50:
        sma50 = float(close.iloc[-50:].mean())
        if sma50 > 0:
            feats["vs_sma50"] = (last_close - sma50) / sma50
    if n >= 200:
        sma200 = float(close.iloc[-200:].mean())
        if sma200 > 0:
            feats["vs_sma200"] = (last_close - sma200) / sma200
        if n >= 50 and sma200 > 0:
            feats["sma50_above_sma200"] = float(close.iloc[-50:].mean()) > sma200
    if n >= 69:
        start, end = float(close.iloc[-69]), float(close.iloc[-6])
        if start > 0:
            feats["ret_3m_ex_1w"] = (end - start) / start
    if n >= 15:
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
        g, l = float(gain.iloc[-1]), float(loss.iloc[-1])
        feats["rsi14"] = 100.0 if l == 0 else 100 - 100 / (1 + g / l)
    return feats


def _parse_bulk_batch(batch: list[str], data) -> dict[str, dict]:
    """Parse a single yf.download() result frame into a per-ticker dict."""
    out: dict[str, dict] = {}
    for ticker in batch:
        try:
            if len(batch) == 1:
                df = data
            else:
                df = data[ticker] if ticker in data.columns.get_level_values(0) else pd.DataFrame()

            # Multi-ticker downloads align on a union index; crypto rows
            # (7 days/week) leave NaN weekend rows on equities. Drop them.
            if not df.empty:
                df = df.dropna(subset=["Close"])
            if df.empty or len(df) < 2:
                continue

            out[ticker] = _screening_features(df)
        except Exception:
            continue
    return out


def _download_one_batch(batch: list[str]) -> dict[str, dict]:
    """Synchronously download + parse one batch of tickers. Runs in a thread."""
    try:
        data = yf.download(
            " ".join(batch), period="1y", group_by="ticker",
            progress=False, threads=False,
        )
        return _parse_bulk_batch(batch, data)
    except Exception as e:
        logger.warning(f"Batch download failed for batch of {len(batch)}: {e}")
        return {}


async def get_bulk_screening(tickers: list[str]) -> dict[str, dict]:
    """Fetch quick screening data for many tickers (volume, price change).

    Used for pre-filtering the universe down to candidates.

    Performance shape:
      • Per-ticker TTL cache (30 min) — back-to-back scans within the
        cache window skip the network entirely for warm tickers. The first
        scan of the day pays full price; subsequent scans only pay for
        cache misses.
      • Parallel batched downloads — uncached tickers are split into
        batches of 20 and `_BULK_BATCH_CONCURRENCY` (3) batches run
        concurrently via `asyncio.gather`. `threads=False` is kept inside
        each `yf.download` call (DNS thread pool exhaustion is real),
        but we get safe outer-level parallelism by stacking 3 sub-batches.

    Returns:
        Dict mapping ticker -> { volume, avg_volume, day_change, price }
    """
    results: dict[str, dict] = {}
    misses: list[str] = []

    # 1. Cache lookup
    for ticker in tickers:
        cached = _bulk_screening_cache.get(ticker)
        if cached is not None:
            results[ticker] = cached
        else:
            misses.append(ticker)

    if not misses:
        logger.info(f"Bulk screening: {len(results)} tickers from cache, 0 fetched")
        return results

    # 2. Fetch misses in parallel batches
    batch_size = 20  # safe per-batch ceiling for yfinance with threads=False
    batches = [misses[i:i + batch_size] for i in range(0, len(misses), batch_size)]
    sem = asyncio.Semaphore(_BULK_BATCH_CONCURRENCY)

    async def _guarded_download(batch: list[str]) -> dict[str, dict]:
        async with sem:
            return await asyncio.to_thread(_download_one_batch, batch)

    try:
        batch_results = await asyncio.gather(
            *[_guarded_download(b) for b in batches], return_exceptions=True,
        )
    except Exception as e:
        logger.error(f"Bulk screening gather failed: {e}")
        return results

    # 3. Merge + cache. TTL is market-hours-aware — shorter during the
    # regular session so a fast-moving open can't feed stale prices to
    # the next scan. See `_bulk_screen_ttl()`.
    ttl = _bulk_screen_ttl()
    fetched_count = 0
    for br in batch_results:
        if isinstance(br, Exception):
            logger.warning(f"Bulk screening batch raised: {br}")
            continue
        for ticker, row in br.items():
            results[ticker] = row
            _bulk_screening_cache.set(ticker, row, ttl=ttl)
            fetched_count += 1

    logger.info(
        f"Bulk screening: {len(results) - fetched_count} cached, "
        f"{fetched_count} fetched, {len(misses) - fetched_count} missing"
    )
    return results


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
