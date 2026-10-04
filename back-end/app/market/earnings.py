"""Earnings dates: the next report (stock page, Coming up, the
earnings_soon check) and the last surprise.

Data sources (verified against the installed yfinance 1.7):
  • `Ticker.calendar["Earnings Date"]` — list[date] from the
    quoteSummary `calendarEvents` module (JSON API). Primary source for
    the NEXT report date.
  • `Ticker.get_earnings_dates(limit=12)` — DataFrame indexed by
    tz-aware "Earnings Date" with columns "EPS Estimate",
    "Reported EPS", "Surprise(%)" (PERCENT). Scraped HTML; used for
    the last surprise and as a fallback for the next date.

Results are cached for 12h per ticker (dates don't change intraday),
so the extra requests are paid once per ticker per day.
"""

import asyncio
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from loguru import logger

from app.core.cache import TTLCache

_earnings_cache = TTLCache(max_size=2000, default_ttl=12 * 3600)

_ET = ZoneInfo("America/New_York")


def _empty() -> dict:
    return {
        "days_since_earnings": None,
        "earnings_surprise_pct": None,
        "drift_signal": "NONE",
        "drift_score": 0,
        "next_earnings_date": None,
        "days_to_earnings": None,
        "pre_earnings_flag": False,
    }


def _next_from_calendar(cal, today: date) -> date | None:
    """Earliest calendar 'Earnings Date' that is today or later."""
    if not isinstance(cal, dict):
        return None
    dates = cal.get("Earnings Date") or []
    if not isinstance(dates, (list, tuple)):
        dates = [dates]
    future = []
    for d in dates:
        if isinstance(d, datetime):
            d = d.date()
        if isinstance(d, date) and d >= today:
            future.append(d)
    return min(future) if future else None


def build_earnings_context(cal, earnings_df, today: date | None = None) -> dict:
    """Pure parser — builds the context dict from yfinance outputs.

    Args:
        cal: `Ticker.calendar` dict (or None).
        earnings_df: `Ticker.get_earnings_dates()` DataFrame (or None).
        today: date override for tests.
    """
    today = today or datetime.now(_ET).date()
    result = _empty()

    next_date = _next_from_calendar(cal, today)

    if earnings_df is not None and not getattr(earnings_df, "empty", True):
        df = earnings_df.sort_index()  # ascending, explicit
        idx_dates = [
            (ts.tz_convert(_ET) if getattr(ts, "tzinfo", None) else ts).date()
            for ts in pd.DatetimeIndex(df.index)
        ]
        df = df.assign(_d=idx_dates)
        # A report dated TODAY counts as past only once EPS is reported.
        todays = df[df["_d"] == today]
        reported_today = (
            not todays.empty and "Reported EPS" in todays.columns
            and bool(todays["Reported EPS"].notna().any())
        )
        if reported_today:
            past, future = df[df["_d"] <= today], df[df["_d"] > today]
        else:
            past, future = df[df["_d"] < today], df[df["_d"] >= today]

        if not past.empty:
            last = past.iloc[-1]
            result["days_since_earnings"] = (today - last["_d"]).days
            surprise = None
            if "Surprise(%)" in past.columns and pd.notna(last.get("Surprise(%)")):
                surprise = float(last["Surprise(%)"])
            elif {"Reported EPS", "EPS Estimate"} <= set(past.columns):
                actual, est = last.get("Reported EPS"), last.get("EPS Estimate")
                if pd.notna(actual) and pd.notna(est) and est:
                    surprise = (float(actual) - float(est)) / abs(float(est)) * 100
            if surprise is not None:
                result["earnings_surprise_pct"] = round(surprise, 2)

        if next_date is None and not future.empty:
            next_date = future.iloc[0]["_d"]

    # PEAD drift signal
    days = result["days_since_earnings"]
    surprise = result["earnings_surprise_pct"]
    if days is not None and surprise is not None and days <= 40:
        if surprise > 5:
            result["drift_signal"] = "POSITIVE_DRIFT"
            result["drift_score"] = min(15, int(surprise * 0.5))
        elif surprise > 2:
            result["drift_signal"] = "POSITIVE_DRIFT"
            result["drift_score"] = 5
        elif surprise < -2:
            result["drift_signal"] = "NEGATIVE_DRIFT"

    if next_date is not None:
        result["next_earnings_date"] = next_date.isoformat()
        result["days_to_earnings"] = (next_date - today).days
        result["pre_earnings_flag"] = result["days_to_earnings"] <= 7

    return result


async def get_earnings_context(ticker: str) -> dict:
    """Get earnings context for a ticker — next date, last surprise, drift.

    Returns dict with:
    - days_since_earnings: calendar days since last report (None if unknown)
    - earnings_surprise_pct: last EPS surprise in PERCENT
    - drift_signal: POSITIVE_DRIFT / NEGATIVE_DRIFT / NONE
    - drift_score: 0-15
    - next_earnings_date: ISO date string or None
    - days_to_earnings: calendar days until next report
    - pre_earnings_flag: True if next report within 7 calendar days
    """
    cached = _earnings_cache.get(ticker)
    if cached is not None:
        return cached

    def _fetch():
        t = yf.Ticker(ticker)
        cal = None
        edf = None
        try:
            cal = t.calendar
        except Exception as e:
            logger.debug(f"Earnings calendar unavailable for {ticker}: {e}")
        try:
            edf = t.get_earnings_dates(limit=12)
        except Exception as e:
            logger.debug(f"Earnings dates unavailable for {ticker}: {e}")
        return build_earnings_context(cal, edf)

    try:
        result = await asyncio.to_thread(_fetch)
    except Exception as e:
        logger.debug(f"Earnings context failed for {ticker}: {e}")
        return _empty()
    _earnings_cache.set(ticker, result)
    return result


def next_earnings_date_from_info(info: dict) -> str | None:
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


def _asset_type(h: dict) -> str:
    at = str(h.get("asset_type") or "").upper()
    if at in ("STOCK", "ETF", "CRYPTO", "OTHER"):
        return at
    sym = str(h.get("symbol") or "")
    if sym.endswith("-USD"):
        return "CRYPTO"
    from app.market.universe import get_asset_class
    return get_asset_class(sym)


def _exchange_code(symbol: str) -> str:
    if symbol.endswith("-USD"):
        return "CRYPTO"
    if symbol.endswith((".TO", ".V")):
        return "TSX"
    return "NYSE"


async def earnings_info(h: dict, today: date | None = None) -> dict | None:
    """{"date", "days", "trading_days"} for stocks ({"symbol", "asset_type"});
    None for other assets or on error."""
    if _asset_type(h) != "STOCK":
        return None
    from app.core.market_calendar import trading_days_until

    try:
        ctx = await get_earnings_context(h["symbol"])
    except Exception as e:
        logger.debug(f"earnings({h['symbol']}) failed: {e}")
        return None
    d = (ctx or {}).get("next_earnings_date")
    if not d:
        return {"date": None, "days": None, "trading_days": None}
    today = today or datetime.now(_ET).date()
    try:
        nd = date.fromisoformat(str(d)[:10])
    except ValueError:
        return {"date": None, "days": None, "trading_days": None}
    return {"date": nd.isoformat(), "days": (nd - today).days,
            "trading_days": trading_days_until(_exchange_code(str(h["symbol"])), nd, today)}
