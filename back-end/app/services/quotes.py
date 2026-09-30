"""Shared quotes (migration 013, table `quotes`) — one row per symbol for all users.

  refresh_quotes(symbols)  ONE batched yfinance download for all the symbols
                           (chunks of QUOTE_BATCH, not one call per symbol),
                           upserted into `quotes`. Returns {symbol: quote}.
  get_quotes(symbols)      reads the table; symbols missing from it are
                           fetched live (and stored). Never raises: a symbol
                           nobody can price is simply absent.
  refresh_followed_quotes()  scheduler, every minute in the session: the
                           symbols in the holdings / watchlists of users seen
                           in the last settings.quotes_active_user_days days,
                           each refreshed only when DUE for its best follower's
                           level (cost control, `due_symbols`):
                             any premium/owner follower -> every
                               settings.quotes_refresh_seconds_premium (60s)
                             free followers only -> every
                               settings.quotes_refresh_seconds_free (900s)
                           force=True (16:05 ET, after the close) refreshes
                           every active-followed symbol once. Nothing per user.
                           Symbols of active price alerts count as followed;
                           after storing, price_alerts.evaluate_refreshed fires
                           the alerts whose target was crossed (migration 015).

Quote shape: {symbol, price, prev_close, change_pct, currency, day_high,
day_low, as_of (ISO), as_of_source, updated_at (ISO)}. The price is the last
daily bar's close (during the session yfinance's current daily bar = the
live price, delayed ~15 minutes: DELAYED_MINUTES).

as_of is the real time of the price (`resolve_as_of`), never a bare date:
  * "bar"    the bar carries a time of day (intraday data): that time
  * "close"  a finished daily bar: that day's session close (16:00 ET;
             crypto: the end of the UTC day)
  * "fetch"  today's still-open daily bar: the time it was fetched (the
             price is at most DELAYED_MINUTES older than that)
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
DELAYED_MINUTES = 15   # free Yahoo data: clients label prices "delayed 15 min"
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


def resolve_as_of(bar_ts, symbol: str, now: datetime | None = None) -> tuple[str, str]:
    """(ISO time of the price, source) for the last daily bar. Pure.

    yfinance labels a daily bar with its date at midnight, which is not the
    time of the price. See the module docstring for the three sources."""
    import pandas as pd

    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    ts = pd.Timestamp(bar_ts)
    crypto = symbol.upper().endswith("-USD")
    tz = timezone.utc if crypto else _ET
    local = ts.tz_localize(tz) if ts.tzinfo is None else ts.tz_convert(tz)
    if (local.hour, local.minute, local.second) != (0, 0, 0):
        return local.to_pydatetime().astimezone(timezone.utc).isoformat(), "bar"
    day = local.date()
    if crypto:
        close_dt = datetime.combine(day, time(23, 59, 59), tzinfo=timezone.utc)
    else:
        close_dt = datetime.combine(day, SESSION_CLOSE_ET, tzinfo=_ET).astimezone(timezone.utc)
    if now >= close_dt:
        return close_dt.isoformat(), "close"
    return now.isoformat(), "fetch"


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
        try:
            as_of, as_of_source = resolve_as_of(close.index[-1], sym, datetime.fromisoformat(now_iso))
        except Exception:
            as_of, as_of_source = now_iso, "fetch"
        out[sym] = {
            "symbol": sym,
            "price": round(price, 6),
            "prev_close": round(prev, 6) if prev else None,
            "change_pct": round((price / prev - 1) * 100, 4) if prev else None,
            "currency": native_currency(sym),
            "day_high": round(_f(hi.iloc[-1]), 6) if hi is not None and _f(hi.iloc[-1]) else None,
            "day_low": round(_f(lo.iloc[-1]), 6) if lo is not None and _f(lo.iloc[-1]) else None,
            "as_of": as_of,
            "as_of_source": as_of_source,
            "updated_at": now_iso,
        }
    return out


def fetch_quotes(symbols: list[str]) -> dict[str, dict]:
    """Live quotes, one yfinance call per QUOTE_BATCH symbols. Never raises."""
    from app.services import usage_metrics

    out: dict[str, dict] = {}
    for i in range(0, len(symbols), QUOTE_BATCH):
        chunk = symbols[i:i + QUOTE_BATCH]
        usage_metrics.record("provider_calls.quotes")
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


# symbol -> epoch seconds of the last refresh attempt by the job (process
# memory: after a restart every followed symbol is due once).
_last_refresh: dict[str, float] = {}
DUE_SLACK_S = 5   # the job runs every 60s; a 60s interval must not slip to 120s


def _ts(v) -> datetime | None:
    if not v:
        return None
    try:
        d = v if isinstance(v, datetime) else datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def follower_levels(follow_rows: list[dict], users: list[dict], now: datetime, active_days: int) -> dict[str, str]:
    """symbol -> best level ("premium" covers owner too, else "free") among
    followers seen in the last `active_days` days (users.last_seen_at, else
    last_login). Symbols with no active follower are left out. Pure."""
    from datetime import timedelta

    from app.core.access import LEVEL_RANK, normalize_level

    cutoff = now - timedelta(days=active_days)
    active: dict[str, str] = {}
    for u in users or []:
        seen = _ts(u.get("last_seen_at")) or _ts(u.get("last_login"))
        if seen is not None and seen >= cutoff:
            # before migration 011 there is no access_level: the single user is the owner
            active[str(u.get("id"))] = normalize_level(u.get("access_level")) if "access_level" in u else "owner"
    out: dict[str, str] = {}
    for r in follow_rows or []:
        lvl = active.get(str(r.get("user_id")))
        sym = str(r.get("symbol") or "").strip().upper()
        if lvl is None or not sym:
            continue
        tier = "premium" if LEVEL_RANK[lvl] >= LEVEL_RANK["premium"] else "free"
        if out.get(sym) != "premium":
            out[sym] = tier
    return out


def due_symbols(levels: dict[str, str], last_refresh: dict[str, float], now_ts: float,
                free_s: int, premium_s: int) -> list[str]:
    """Symbols whose refresh interval (by tier) has elapsed. Pure."""
    out = []
    for sym, tier in sorted(levels.items()):
        interval = premium_s if tier == "premium" else free_s
        last = last_refresh.get(sym)
        if last is None or now_ts - last >= interval - DUE_SLACK_S:
            out.append(sym)
    return out


def refresh_followed_quotes(force: bool = False, now: datetime | None = None) -> dict:
    """Scheduler entry (see the module docstring). Skips outside the session unless force."""
    from app.core.config import settings
    from app.db import queries
    from app.services import usage_metrics

    now = (now or datetime.now(timezone.utc))
    now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    if not force and not in_market_session(now):
        return {"status": "closed"}
    from app.services import price_alerts
    try:
        # active price alerts need fresh quotes too (at their owner's tier)
        follows = queries.get_follow_rows() + price_alerts.alert_follow_rows()
        levels = follower_levels(follows, queries.get_users_activity(), now,
                                 settings.quotes_active_user_days)
    except Exception as e:
        logger.warning(f"quotes: followed symbols unavailable: {e}")
        return {"status": "unavailable"}
    if not levels:
        return {"status": "ok", "followed": 0, "symbols": 0, "quotes": 0}
    now_ts = now.timestamp()
    symbols = sorted(levels) if force else due_symbols(
        levels, _last_refresh, now_ts, settings.quotes_refresh_seconds_free, settings.quotes_refresh_seconds_premium)
    if not symbols:
        return {"status": "ok", "followed": len(levels), "symbols": 0, "quotes": 0}
    for sym in symbols:   # an attempt counts: an unpriceable symbol must not be retried every minute
        _last_refresh[sym] = now_ts
    quotes = refresh_quotes(symbols)
    usage_metrics.record("symbols_refreshed", len(quotes))
    out = {"status": "ok", "followed": len(levels), "symbols": len(symbols), "quotes": len(quotes)}
    fired = price_alerts.evaluate_refreshed(quotes, now)   # price alerts (015); never raises
    if fired:
        out["alerts_triggered"] = fired
    return out
