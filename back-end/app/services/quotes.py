"""Shared quotes (migration 013, table `quotes`) — one row per symbol for all users.

  refresh_quotes(symbols)  ONE batched yfinance download for all the symbols
                           (chunks of QUOTE_BATCH, not one call per symbol),
                           upserted into `quotes`. Returns {symbol: quote}.
  get_stored_quotes(syms)  reads the table only (no live fetch).
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
from app.market import sessions
from app.market.currency import price_factor
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
        k = price_factor(sym)   # pence/cents listings (LSE, JSE, TASE) -> main currency
        price = _f(close.iloc[-1])
        if price is None or price <= 0:
            continue
        price *= k
        prev = _f(close.iloc[-2]) if len(close) >= 2 else None
        prev = prev * k if prev else prev
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
            "day_high": round(_f(hi.iloc[-1]) * k, 6) if hi is not None and _f(hi.iloc[-1]) else None,
            "day_low": round(_f(lo.iloc[-1]) * k, 6) if lo is not None and _f(lo.iloc[-1]) else None,
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


def get_stored_quotes(symbols: Iterable[str]) -> dict[str, dict]:
    """Stored quotes only (no live fetch for missing symbols). Never raises."""
    from app.db import queries

    syms = _clean(symbols)
    out: dict[str, dict] = {}
    if not syms:
        return out
    try:
        for r in queries.get_quote_rows(syms):
            if r.get("symbol") and _f(r.get("price")):
                out[str(r["symbol"]).upper()] = {**r, **{k: _f(r.get(k)) for k in
                                                         ("price", "prev_close", "change_pct", "day_high", "day_low")}}
    except Exception as e:
        logger.debug(f"quotes table unavailable: {e}")
    return out


def get_quotes(symbols: Iterable[str]) -> dict[str, dict]:
    """Stored quotes; symbols missing from the table are fetched live."""
    syms = _clean(symbols)
    if not syms:
        return {}
    out = get_stored_quotes(syms)
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


FOLLOW_TTL_S = 300
_follow_cache: dict = {}


def _followed_levels(now: datetime) -> dict[str, str]:
    """follower_levels over holdings + watchlists + active price alerts, cached
    FOLLOW_TTL_S (the job runs every minute; a new follow is priced on first
    view via get_quotes anyway). clear_follow_cache() after bulk changes."""
    from app.core.config import settings
    from app.db import queries
    from app.services import price_alerts

    hit = _follow_cache.get("levels")
    if hit and now.timestamp() - hit[0] < FOLLOW_TTL_S:
        return dict(hit[1])
    follows = queries.get_follow_rows() + price_alerts.alert_follow_rows()
    levels = follower_levels(follows, queries.get_users_activity(), now, settings.quotes_active_user_days)
    _follow_cache["levels"] = (now.timestamp(), levels)
    return dict(levels)


def clear_follow_cache() -> None:
    _follow_cache.clear()


def refresh_followed_quotes(force: bool = False, now: datetime | None = None) -> dict:
    """Scheduler entry (see the module docstring). Skips outside the session unless force."""
    from app.core.config import settings
    from app.services import usage_metrics

    now = (now or datetime.now(timezone.utc))
    now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    from app.services import price_alerts
    try:
        levels = _followed_levels(now)
    except Exception as e:
        logger.warning(f"quotes: followed symbols unavailable: {e}")
        return {"status": "unavailable"}
    if not force:
        # Each symbol while ITS exchange trades (and 10 min after its close, for
        # the closing price): B3, LSE, Tokyo ... not only New York/Toronto hours.
        # Crypto: here during the US session, else in refresh_offhours.
        us_open = in_market_session(now)
        levels = {s: t for s, t in levels.items()
                  if (us_open if is_crypto(s) else sessions.is_trading(s, now))}
        if not levels:
            return {"status": "closed"}
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


# ============================================================
# Outside the regular session (migration 021)
# ============================================================
#   crypto (-USD)  trades 24/7: refreshed at the follower's plan rate
#                  (free 15 min, premium 1 min) whenever the session job
#                  isn't running — nights, weekends, holidays.
#   US stocks      pre-market 4:00-9:30 and after-hours 16:00-20:00 ET on
#                  trading days: refreshed every quotes_refresh_seconds_extended
#                  for symbols followed by an active Premium/owner user
#                  (feature.extended_hours). Stored in quotes.ext_* — the
#                  regular price is untouched. Canadian listings (.TO) have
#                  no extended trading worth showing and are skipped.

PRE_OPEN_ET, POST_CLOSE_ET = time(4, 0), time(20, 0)
_last_offhours: dict[str, float] = {}


def is_crypto(symbol: str) -> bool:
    return symbol.upper().endswith("-USD")


def is_us_equity(symbol: str) -> bool:
    """US listing (no exchange suffix), not crypto / index / FX. Pure."""
    s = symbol.upper()
    return bool(s) and "." not in s and not s.endswith("-USD") and not s.startswith("^") and "=" not in s


def market_phase(now: datetime | None = None) -> str:
    """'pre' | 'regular' | 'post' | 'closed' for US stocks (ET, NYSE calendar). Pure."""
    now = (now or datetime.now(_ET)).astimezone(_ET)
    if not is_market_open("NYSE", now.date()):
        return "closed"
    t = now.time()
    if PRE_OPEN_ET <= t < SESSION_OPEN_ET:
        return "pre"
    if SESSION_OPEN_ET <= t < SESSION_CLOSE_ET:
        return "regular"
    if SESSION_CLOSE_ET <= t < POST_CLOSE_ET:
        return "post"
    return "closed"


def session_of(ts: datetime) -> str | None:
    """'pre' / 'post' for a bar time outside the regular session, else None. Pure."""
    t = ts.astimezone(_ET).time()
    if PRE_OPEN_ET <= t < SESSION_OPEN_ET:
        return "pre"
    if SESSION_CLOSE_ET <= t < POST_CLOSE_ET:
        return "post"
    return None


def parse_extended(data, symbols: list[str]) -> dict[str, dict]:
    """Intraday frame downloaded with prepost=True -> {symbol: {ext_price,
    ext_session, ext_as_of}} from the LAST bar, only when that bar is outside
    the regular session. Pure (tested with a fake frame)."""
    import pandas as pd

    out: dict[str, dict] = {}
    if data is None or getattr(data, "empty", True):
        return out
    multi = isinstance(data.columns, pd.MultiIndex) and len(symbols) > 1
    for sym in symbols:
        close = _series(data, "Close", sym, multi)
        if close is None:
            continue
        price = _f(close.iloc[-1])
        if price is None or price <= 0:
            continue
        ts = pd.Timestamp(close.index[-1])
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        sess = session_of(ts.to_pydatetime())
        if sess:
            out[sym] = {"ext_price": round(price, 6), "ext_session": sess,
                        "ext_as_of": ts.to_pydatetime().isoformat()}
    return out


def fetch_extended(symbols: list[str]) -> dict[str, dict]:
    """One batched 5-minute download with pre/after-hours bars. Never raises."""
    from app.services import usage_metrics

    if not symbols:
        return {}
    usage_metrics.record("provider_calls.extended")
    try:
        import yfinance as yf
        data = yf.download(symbols, period="2d", interval="5m", prepost=True, progress=False,
                           threads=False, auto_adjust=False, group_by="column")
        return parse_extended(data, symbols)
    except Exception as e:
        logger.warning(f"quotes: extended-hours download failed for {len(symbols)} symbols: {e}")
        return {}


def store_extended(found: dict[str, dict], regular: dict[str, dict]) -> int:
    """Write ext_* (+ change vs the regular price) on existing quotes rows."""
    from app.db import queries

    n = 0
    for sym, ext in found.items():
        base = _f((regular.get(sym) or {}).get("price"))
        row = {**ext, "ext_change_pct": round((ext["ext_price"] / base - 1) * 100, 4) if base else None}
        try:
            queries.update_quote_extended(sym, row)
            n += 1
        except Exception as e:
            logger.debug(f"quotes: extended price not stored for {sym} (migration 021?): {e}")
            break
    return n


def extended_view(quote: dict | None, ext: dict | None, now: datetime | None = None) -> dict | None:
    """What clients show: {"session", "price", "change_pct", "as_of"}, or None
    when there is nothing newer than the regular price, or the regular session
    is on. Pure."""
    if not ext or _f(ext.get("ext_price")) is None or not ext.get("ext_as_of"):
        return None
    now = now or datetime.now(timezone.utc)
    if market_phase(now) == "regular":
        return None
    ext_t = _ts(ext.get("ext_as_of"))
    reg_t = _ts((quote or {}).get("as_of"))
    if ext_t is None or (reg_t is not None and ext_t <= reg_t):
        return None
    if (now - ext_t).total_seconds() > 20 * 3600:   # yesterday's after-hours: stale
        return None
    return {"session": ext.get("ext_session"), "price": _f(ext.get("ext_price")),
            "change_pct": _f(ext.get("ext_change_pct")), "as_of": ext_t.isoformat()}


def get_extended(symbols) -> dict[str, dict]:
    """Stored ext_* rows by symbol ({} before migration 021). Never raises."""
    from app.db import queries

    syms = _clean(symbols)
    if not syms:
        return {}
    try:
        return {str(r["symbol"]).upper(): r for r in queries.get_quote_extended_rows(syms)}
    except Exception as e:
        logger.debug(f"quotes: extended columns unavailable (migration 021?): {e}")
        return {}


def refresh_offhours(now: datetime | None = None) -> dict:
    """Scheduler entry, every minute, any day: crypto 24/7 and US extended
    hours (see the section comment). Does nothing during the regular session
    (refresh_followed_quotes covers everything then)."""
    from app.core.config import settings
    from app.db import queries
    from app.services import price_alerts, usage_metrics

    now = (now or datetime.now(timezone.utc))
    now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    phase = market_phase(now)
    if in_market_session(now):
        return {"status": "session"}
    try:
        follows = queries.get_follow_rows() + price_alerts.alert_follow_rows()
        levels = follower_levels(follows, queries.get_users_activity(), now, settings.quotes_active_user_days)
    except Exception as e:
        logger.warning(f"quotes: followed symbols unavailable: {e}")
        return {"status": "unavailable"}
    now_ts = now.timestamp()
    out: dict = {"status": "ok", "phase": phase}

    crypto = {s: t for s, t in levels.items() if is_crypto(s)}
    due = due_symbols(crypto, _last_offhours, now_ts, settings.quotes_refresh_seconds_free,
                      settings.quotes_refresh_seconds_premium)
    if due:
        for s in due:
            _last_offhours[s] = now_ts
        got = refresh_quotes(due)
        usage_metrics.record("symbols_refreshed", len(got))
        out["crypto"] = len(got)
        fired = price_alerts.evaluate_refreshed(got, now)
        if fired:
            out["alerts_triggered"] = fired

    if phase in ("pre", "post"):
        us = {f"x:{s}": "premium" for s, t in levels.items() if t == "premium" and is_us_equity(s)}
        due_x = due_symbols(us, _last_offhours, now_ts, settings.quotes_refresh_seconds_extended,
                            settings.quotes_refresh_seconds_extended)
        if due_x:
            for k in due_x:
                _last_offhours[k] = now_ts
            syms = [k[2:] for k in due_x]
            found = fetch_extended(syms)
            out["extended"] = store_extended(found, get_quotes(list(found))) if found else 0
    return out


_ext_cache: dict[str, tuple[float, dict]] = {}
EXT_CACHE_S = 120


def extended_for_symbol(symbol: str, quote: dict | None, now: datetime | None = None) -> dict | None:
    """Stock page: the stored after-hours price, else (US stock, pre/post
    phase) a one-symbol download cached EXT_CACHE_S for everyone viewing it.
    Never raises."""
    import time as _time

    sym = symbol.upper()
    now = now or datetime.now(timezone.utc)
    v = extended_view(quote, get_extended([sym]).get(sym), now)
    if v is not None or not is_us_equity(sym) or market_phase(now) not in ("pre", "post"):
        return v
    hit = _ext_cache.get(sym)
    if hit and _time.time() - hit[0] < EXT_CACHE_S:
        found = hit[1]
    else:
        found = fetch_extended([sym]).get(sym) or {}
        _ext_cache[sym] = (_time.time(), found)
    if not found:
        return None
    base = _f((quote or {}).get("price"))
    row = {**found, "ext_change_pct": round((found["ext_price"] / base - 1) * 100, 4) if base else None}
    return extended_view(quote, row, now)


def extended_payload(level: str, symbol: str, view: dict | None, now: datetime | None = None) -> dict:
    """{"extended": view | None, "extended_locked": bool} for a client: Free
    users get extended_locked=true while a US stock trades pre/after hours,
    so the app can show the Premium hint. Pure apart from the clock."""
    from app.core.access import can

    if can(level, "feature.extended_hours"):
        return {"extended": view, "extended_locked": False}
    locked = is_us_equity(symbol) and market_phase(now) in ("pre", "post")
    return {"extended": None, "extended_locked": locked}
