"""Shared quotes (migration 013, table `quotes`) — one row per symbol for all users.

  refresh_quotes(symbols)  ONE batched yfinance download for all the symbols
                           (chunks of QUOTE_BATCH, not one call per symbol),
                           upserted into `quotes`. Returns {symbol: quote}.
  get_quotes(symbols)      reads the table; symbols missing from it are
                           fetched live (and stored). Never raises: a symbol
                           nobody can price is simply absent.
  refresh_followed_quotes()  scheduler: the distinct symbols in every user's
                           holdings and watchlists. Nothing per user.

Quote shape: {symbol, price, prev_close, change_pct, currency, day_high,
day_low, as_of (ISO), updated_at (ISO)}. The price is the last daily bar's
close (during the session yfinance's current daily bar = the live price).
No AI.
"""

from __future__ import annotations

import math
from datetime import datetime, time, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

from loguru import logger

from app.core.market_calendar import is_market_open
from app.services.price_cache import native_currency

QUOTE_BATCH = 500
_ET = ZoneInfo("America/New_York")
SESSION_OPEN_ET, SESSION_CLOSE_ET = time(9, 30), time(16, 0)


def _f(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _clean(symbols: Iterable[str]) -> list[str]:
    from app.core.utils import validate_ticker
    out = []
    for s in symbols or []:
        s = str(s or "").strip().upper()
        if s and len(s) <= 24 and validate_ticker(s):
            out.append(s)
    return list(dict.fromkeys(out))


def _download(symbols: list[str]):
    import yfinance as yf
    return yf.download(symbols, period="5d", interval="1d", progress=False, threads=False,
                       auto_adjust=False, group_by="column")


def _series(data, field: str, sym: str, multi: bool):
    try:
        col = data[field]
        if multi:
            if sym not in col.columns:
                return None
            col = col[sym]
        elif hasattr(col, "columns"):   # single ticker with MultiIndex columns (newer yfinance)
            col = col.iloc[:, 0]
        col = col.dropna()
        return col if len(col) else None
    except Exception:
        return None


def parse_download(data, symbols: list[str], now_iso: str | None = None) -> dict[str, dict]:
    """yf.download frame -> {symbol: quote row}. Pure (tested with a fake frame)."""
    import pandas as pd

    out: dict[str, dict] = {}
    if data is None or getattr(data, "empty", True):
        return out
    multi = isinstance(data.columns, pd.MultiIndex) and len(symbols) > 1
    now_iso = now_iso or datetime.now(timezone.utc).isoformat()
    for sym in symbols:
        close = _series(data, "Close", sym, multi)
        if close is None:
            continue
        price = _f(close.iloc[-1])
        if price is None or price <= 0:
            continue
        prev = _f(close.iloc[-2]) if len(close) >= 2 else None
        hi, lo = _series(data, "High", sym, multi), _series(data, "Low", sym, multi)
        ts = close.index[-1]
        try:
            as_of = pd.Timestamp(ts).tz_localize("UTC").isoformat() if pd.Timestamp(ts).tzinfo is None \
                else pd.Timestamp(ts).isoformat()
        except Exception:
            as_of = now_iso
        out[sym] = {
            "symbol": sym,
            "price": round(price, 6),
            "prev_close": round(prev, 6) if prev else None,
            "change_pct": round((price / prev - 1) * 100, 4) if prev else None,
            "currency": native_currency(sym),
            "day_high": round(_f(hi.iloc[-1]), 6) if hi is not None and _f(hi.iloc[-1]) else None,
            "day_low": round(_f(lo.iloc[-1]), 6) if lo is not None and _f(lo.iloc[-1]) else None,
            "as_of": as_of,
            "updated_at": now_iso,
        }
    return out


def fetch_quotes(symbols: list[str]) -> dict[str, dict]:
    """Live quotes, one yfinance call per QUOTE_BATCH symbols. Never raises."""
    out: dict[str, dict] = {}
    for i in range(0, len(symbols), QUOTE_BATCH):
        chunk = symbols[i:i + QUOTE_BATCH]
        try:
            out.update(parse_download(_download(chunk), chunk))
        except Exception as e:
            logger.warning(f"quotes: batch download failed for {len(chunk)} symbols: {e}")
    return out


def refresh_quotes(symbols: Iterable[str]) -> dict[str, dict]:
    """Fetch (batched) and upsert into `quotes`. Returns what was fetched."""
    from app.db import queries

    syms = _clean(symbols)
    if not syms:
        return {}
    quotes = fetch_quotes(syms)
    if quotes:
        try:
            queries.upsert_quotes(list(quotes.values()))
        except Exception as e:
            logger.warning(f"quotes: could not store {len(quotes)} quotes (apply migration 013?): {e}")
    return quotes


def get_quotes(symbols: Iterable[str]) -> dict[str, dict]:
    """Stored quotes; symbols missing from the table are fetched live."""
    from app.db import queries

    syms = _clean(symbols)
    if not syms:
        return {}
    out: dict[str, dict] = {}
    try:
        for r in queries.get_quote_rows(syms):
            if r.get("symbol") and _f(r.get("price")):
                out[str(r["symbol"]).upper()] = {**r, **{k: _f(r.get(k)) for k in
                                                         ("price", "prev_close", "change_pct", "day_high", "day_low")}}
    except Exception as e:
        logger.debug(f"quotes table unavailable, fetching live: {e}")
    missing = [s for s in syms if s not in out]
    if missing:
        out.update(refresh_quotes(missing))
    return out


def in_market_session(now: datetime | None = None) -> bool:
    """True during the 09:30-16:00 ET regular session on a day NYSE or TSX trades."""
    now = (now or datetime.now(_ET)).astimezone(_ET)
    if not (is_market_open("NYSE", now.date()) or is_market_open("TSX", now.date())):
        return False
    return SESSION_OPEN_ET <= now.time() <= SESSION_CLOSE_ET


def refresh_followed_quotes(force: bool = False, now: datetime | None = None) -> dict:
    """Scheduler entry: refresh every followed symbol (skips outside the session unless force)."""
    from app.db import queries

    if not force and not in_market_session(now):
        return {"status": "closed"}
    try:
        symbols = sorted(queries.get_all_followed_symbols())
    except Exception as e:
        logger.warning(f"quotes: followed symbols unavailable: {e}")
        return {"status": "unavailable"}
    if not symbols:
        return {"status": "ok", "symbols": 0, "quotes": 0}
    quotes = refresh_quotes(symbols)
    return {"status": "ok", "symbols": len(symbols), "quotes": len(quotes)}
