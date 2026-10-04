"""Trading sessions per exchange (holidays, local hours, early closes) from
the maintained `exchange_calendars` library.

Exchange labels (TSX, B3, LSE, XETRA ... as in app/market/currency.py and
symbol_search) map to ISO MIC calendars (XTSE, BVMF, XLON, XETR ...). US
listings and anything unknown use XNYS; crypto trades 24/7 (no calendar).

  calendar_for(label)          -> exchange_calendars calendar or None (crypto / unmodelled)
  is_session_day(label, d)     -> True when the exchange trades on date d
  is_open(label, now)          -> True while the regular session is open
  close_of(label, d)           -> the session's close (UTC) on d, or None
  just_closed(label, now, min) -> True within `min` minutes after today's close
  label_for_symbol(symbol)     -> the exchange label used above for a Yahoo symbol

Calendars load lazily (~0.1 s each) and are kept for the process.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

import pandas as pd
from loguru import logger

MIC: dict[str, str] = {
    "NYSE": "XNYS", "NASDAQ": "XNYS", "NYSE American": "XNYS", "NYSE Arca": "XNYS", "Cboe": "XNYS", "US": "XNYS",
    "OTC": "XNYS",
    "TSX": "XTSE", "TSXV": "XTSE", "NEO": "XTSE", "CSE": "XTSE",
    "B3": "BVMF", "BMV": "XMEX", "BYMA": "XBUE", "Santiago": "XSGO",
    "LSE": "XLON", "LSE IOB": "XLON", "XETRA": "XETR", "Frankfurt": "XFRA", "Berlin": "XFRA", "Munich": "XFRA",
    "Stuttgart": "XFRA", "Düsseldorf": "XFRA", "Hamburg": "XFRA",
    "Euronext Paris": "XPAR", "Euronext Amsterdam": "XAMS", "Euronext Brussels": "XBRU", "Euronext Lisbon": "XLIS",
    "Euronext Dublin": "XDUB", "Borsa Italiana": "XMIL", "BME": "XMAD", "Vienna": "XWBO", "Helsinki": "XHEL",
    "SIX": "XSWX", "Stockholm": "XSTO", "Oslo": "XOSL", "Copenhagen": "XCSE", "Warsaw": "XWAR",
    "Prague": "XPRA", "Budapest": "XBUD", "Borsa Istanbul": "XIST",
    "Tokyo": "XTKS", "HKEX": "XHKG", "Shanghai": "XSHG", "Shenzhen": "XSHG", "KOSPI": "XKRX", "KOSDAQ": "XKRX",
    "TWSE": "XTAI", "TPEx": "XTAI", "SGX": "XSES", "NSE": "XBOM", "BSE": "XBOM", "IDX": "XIDX",
    "Bursa Malaysia": "XKLS", "SET": "XBKK", "ASX": "XASX", "NZX": "XNZE", "JSE": "XJSE", "TASE": "XTAE",
    "Tadawul": "XSAU",
}


@lru_cache(maxsize=64)
def _calendar(mic: str):
    try:
        import exchange_calendars as xcals
        return xcals.get_calendar(mic)
    except Exception as e:
        logger.warning(f"sessions: calendar {mic} unavailable: {type(e).__name__}")
        return None


def calendar_for(label: str | None):
    if not label or label == "CRYPTO":
        return None
    return _calendar(MIC.get(label, "XNYS"))


def label_for_symbol(symbol: str | None) -> str:
    from app.market.currency import exchange_for_suffix, is_crypto

    s = (symbol or "").upper()
    if is_crypto(s):
        return "CRYPTO"
    return exchange_for_suffix(s) or "US"


def _in_range(cal, d: date) -> bool:
    ts = pd.Timestamp(d)
    return cal.first_session <= ts <= cal.last_session


def is_session_day(label: str | None, d: date) -> bool:
    if label == "CRYPTO":
        return True
    cal = calendar_for(label)
    if cal is None or not _in_range(cal, d):
        return d.weekday() < 5
    return bool(cal.is_session(pd.Timestamp(d)))


def close_of(label: str | None, d: date) -> datetime | None:
    cal = calendar_for(label)
    if cal is None or not _in_range(cal, d) or not cal.is_session(pd.Timestamp(d)):
        return None
    return cal.session_close(pd.Timestamp(d)).to_pydatetime()


def is_open(label: str | None, now: datetime | None = None) -> bool:
    if label == "CRYPTO":
        return True
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cal = calendar_for(label)
    if cal is None:
        return False
    try:
        return bool(cal.is_open_on_minute(pd.Timestamp(now).floor("min")))
    except Exception:   # outside the calendar's range
        return False


def _local_date(label: str | None, now: datetime) -> date:
    cal = calendar_for(label)
    tz = getattr(cal, "tz", None) if cal is not None else None
    return now.astimezone(tz).date() if tz is not None else now.date()


def just_closed(label: str | None, now: datetime | None = None, minutes: int = 10) -> bool:
    """True from the session close until `minutes` after it (to catch the closing price)."""
    if label == "CRYPTO":
        return False
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    close = close_of(label, _local_date(label, now))
    return close is not None and close <= now <= close + timedelta(minutes=minutes)


def is_trading(symbol: str, now: datetime | None = None, after_close_minutes: int = 10) -> bool:
    """The symbol's exchange is open now, or closed less than `after_close_minutes` ago."""
    label = label_for_symbol(symbol)
    return is_open(label, now) or just_closed(label, now, after_close_minutes)
