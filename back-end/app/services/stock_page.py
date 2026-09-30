"""Free stock page: price, dividends, events and rule-based "Signa checks".

The heart of the free tier (GET /api/v1/stocks/{symbol}, app/api/v1/stocks.py).
It must cost nothing per user:

  * NO AI. Nothing here calls Grok / Claude / Codex, nothing decorated with
    @ai_guarded, nothing from app/ai/provider.py. The only thing used from
    app/ai/ is `signal_engine.technical_filter`, a pure function.
  * Shared market data only (yfinance), cached per symbol and shared by
    every user: the page body for 15 minutes (PAGE_TTL), the dividend
    profile ~12h (services/dividends.py), earnings dates ~12h
    (signals/earnings.py).
  * The per-user part ("followed": holdings / watchlist) is read from the
    DB on every request and never cached.

Blocking yfinance calls run in a thread (`_fetch_market`, replaced by the
tests). Data errors degrade to partial data with nulls; only an unknown
symbol is an error (StockPageError not_found -> 404).

Signa checks (`build_checks`, pure). They describe the stock; they are not
buy/sell advice (a backtest showed they don't beat SPY on their own). The
thresholds are the brain's technical filter settings (app/core/config.py):

  uptrend          price > SMA200 and SMA50 > SMA200
                   both -> pass, one -> warn, neither -> fail,
                   < 200 daily bars -> na
  not_overheated   RSI(14) <= tech_filter_max_rsi (75) and price
                   <= tech_filter_max_ext_sma50_pct (15%) above SMA50
                   both -> pass, otherwise warn; no data -> na
  liquidity        20-session average dollar volume >= tech_filter_min_dollar_volume
                   ($10M, native currency) or tech_filter_min_dollar_volume_crypto
                   ($50M) -> pass, below -> warn, no volume -> na
  earnings_soon    stocks: next report within earnings_blackout_trading_days (3)
                   trading days -> warn; later -> pass (with the date);
                   no date / ETF / crypto -> na
  dividend_health  hold-mode dividend rules (dividends.long_term_dividend_assessment):
                   good -> pass, fair -> warn, poor -> fail, non-payer / ETF /
                   crypto -> na
"""

from __future__ import annotations

import asyncio
import math
from datetime import date, datetime, timezone
from typing import Any

from loguru import logger

from app.ai.signal_engine import technical_filter
from app.core.cache import TTLCache
from app.core.config import settings
from app.core.market_calendar import trading_days_until
from app.scanners import indicators
from app.scanners.universe import get_asset_class
from app.services import dividends

PAGE_TTL = 15 * 60          # shared page body (quote + checks), per symbol
PARTIAL_TTL = 2 * 60        # a page built from partial data is retried sooner
MISSING_TTL = 10 * 60       # "no such symbol" is remembered this long
HISTORY_PERIOD = "1y"       # >= 200 daily bars for SMA200

CHECK_KEYS = ("uptrend", "not_overheated", "liquidity", "earnings_soon", "dividend_health")

# Yahoo `info["exchange"]` codes -> Signa exchange codes.
_EXCHANGE_CODES = {
    "NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ", "NAS": "NASDAQ",
    "NYQ": "NYSE", "PCX": "NYSE", "ASE": "NYSE", "BTS": "NYSE",
    "TOR": "TSX", "VAN": "TSXV", "CCC": "CRYPTO",
}

_page_cache = TTLCache(max_size=500, default_ttl=PAGE_TTL)
_resolve_cache = TTLCache(max_size=1000, default_ttl=24 * 3600)   # input -> resolved symbol
_missing_cache = TTLCache(max_size=1000, default_ttl=MISSING_TTL)
_locks: dict[str, asyncio.Lock] = {}


class StockPageError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _num(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _r(v: Any, nd: int = 2) -> float | None:
    f = _num(v)
    return round(f, nd) if f is not None else None


def _today_et() -> date:
    return dividends.today_et()


def clear_cache() -> None:
    _page_cache.clear()
    _resolve_cache.clear()
    _missing_cache.clear()
    _locks.clear()


# ============================================================
# Fetch (blocking; tests replace _fetch_market)
# ============================================================

def _fetch_market(symbol: str) -> dict:
    """{"history": daily OHLCV DataFrame (1y) or None, "info": dict}.

    `info` is only fetched when there is price history (an unknown
    candidate costs one call, not two). Never raises."""
    import yfinance as yf

    out: dict = {"history": None, "info": {}}
    t = yf.Ticker(symbol)
    try:
        df = t.history(period=HISTORY_PERIOD)
        out["history"] = df if df is not None and not df.empty else None
    except Exception as e:
        logger.debug(f"stock_page: history({symbol}) failed: {e}")
    if out["history"] is None:
        return out
    try:
        out["info"] = t.info or {}
    except Exception as e:
        logger.debug(f"stock_page: info({symbol}) failed: {e}")
    return out


# ============================================================
# Pure pieces
# ============================================================

def asset_type_for(symbol: str, info: dict | None) -> str:
    """STOCK | ETF | CRYPTO (Yahoo quoteType first, then Signa's universe)."""
    from app.services.long_term_check import asset_type_for as lt_asset_type

    at = lt_asset_type(symbol, info or {})
    return at if at in ("STOCK", "ETF", "CRYPTO") else get_asset_class(symbol)


def exchange_for(symbol: str, info: dict | None) -> str:
    code = _EXCHANGE_CODES.get(str((info or {}).get("exchange") or "").upper())
    if code:
        return code
    from app.services.stock_check import exchange_for as sc_exchange_for
    return sc_exchange_for(symbol)


def build_quote(history, info: dict | None) -> dict:
    """{price, change_pct, high_52w, low_52w, market_cap, as_of}; nulls when unknown."""
    info = info or {}
    closes = None
    try:
        if history is not None and "Close" in history:
            closes = history["Close"].dropna()
    except Exception:
        closes = None
    price = prev = None
    as_of = None
    live, live_prev = _num(info.get("regularMarketPrice")), _num(info.get("regularMarketPreviousClose"))
    if live and live_prev:
        price, prev = live, live_prev
        ts = _num(info.get("regularMarketTime"))
        if ts:
            try:
                as_of = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            except (OverflowError, OSError, ValueError):
                as_of = None
    elif closes is not None and len(closes):
        price = _num(closes.iloc[-1])
        prev = _num(closes.iloc[-2]) if len(closes) >= 2 else None
    if as_of is None and closes is not None and len(closes):
        try:
            as_of = closes.index[-1].isoformat()
        except Exception:
            as_of = None
    hi, lo = _num(info.get("fiftyTwoWeekHigh")), _num(info.get("fiftyTwoWeekLow"))
    if (hi is None or lo is None) and history is not None:
        try:
            hi = hi if hi is not None else _num(history["High"].max())
            lo = lo if lo is not None else _num(history["Low"].min())
        except Exception:
            pass
    change_pct = round((price / prev - 1) * 100, 2) if price and prev else None
    return {"price": _r(price, 4), "change_pct": change_pct, "high_52w": _r(hi, 4), "low_52w": _r(lo, 4),
            "market_cap": _num(info.get("marketCap")), "as_of": as_of}


def _dollar_volume(tech: dict, crypto: bool) -> float | None:
    """Same source as technical_filter's liquidity rule."""
    if crypto:  # Yahoo crypto volume is already USD
        return _num(tech.get("volume_avg_20")) or _num(tech.get("volume_avg"))
    dv = _num(tech.get("dollar_volume_avg_20"))
    if dv is None:
        price = _num(tech.get("last_close")) or _num(tech.get("current_price"))
        shares = _num(tech.get("volume_avg_20")) or _num(tech.get("volume_avg"))
        dv = shares * price if shares is not None and price else None
    return dv


def _check(key: str, status: str, value: Any, detail_code: str, params: dict | None = None) -> dict:
    return {"key": key, "status": status, "value": value, "detail_code": detail_code, "params": params or {}}


def build_checks(tech: dict | None, asset_type: str, earnings: dict | None, dividend_item: dict | None,
                 currency: str | None = None) -> list[dict]:
    """The five Signa checks (see the module docstring). Pure."""
    tech = tech or {}
    crypto = asset_type == "CRYPTO"
    _, reasons = technical_filter(tech, {}, asset_type)
    price = _num(tech.get("last_close")) or _num(tech.get("current_price"))
    sma50, sma200, rsi = _num(tech.get("sma_50")), _num(tech.get("sma_200")), _num(tech.get("rsi"))
    checks: list[dict] = []

    # uptrend
    trend_params = {"price": _r(price), "sma50": _r(sma50), "sma200": _r(sma200)}
    if "insufficient_history" in reasons:
        checks.append(_check("uptrend", "na", None, "insufficient_history", trend_params))
    else:
        below200, cross = "below_sma200" in reasons, "sma50_below_sma200" in reasons
        vs200 = _r((price / sma200 - 1) * 100) if price and sma200 else None
        if not below200 and not cross:
            checks.append(_check("uptrend", "pass", vs200, "uptrend", trend_params))
        elif below200 and cross:
            checks.append(_check("uptrend", "fail", vs200, "downtrend", trend_params))
        else:
            checks.append(_check("uptrend", "warn", vs200, "below_sma200" if below200 else "sma50_below_sma200",
                                 trend_params))

    # not_overheated
    ext = _r((price / sma50 - 1) * 100) if price and sma50 else None
    heat_params = {"rsi": _r(rsi, 1), "max_rsi": settings.tech_filter_max_rsi, "ext_pct": ext,
                   "max_ext_pct": settings.tech_filter_max_ext_sma50_pct}
    hot_rsi, hot_ext = "rsi_overbought" in reasons, "overextended_vs_sma50" in reasons
    if rsi is None and ext is None:
        checks.append(_check("not_overheated", "na", None, "no_data", heat_params))
    elif hot_rsi and hot_ext:
        checks.append(_check("not_overheated", "warn", _r(rsi, 1), "rsi_and_extended", heat_params))
    elif hot_rsi:
        checks.append(_check("not_overheated", "warn", _r(rsi, 1), "rsi_overbought", heat_params))
    elif hot_ext:
        checks.append(_check("not_overheated", "warn", _r(rsi, 1), "overextended_vs_sma50", heat_params))
    else:
        checks.append(_check("not_overheated", "pass", _r(rsi, 1), "calm", heat_params))

    # liquidity
    floor = settings.tech_filter_min_dollar_volume_crypto if crypto else settings.tech_filter_min_dollar_volume
    dv = _dollar_volume(tech, crypto)
    liq_params = {"dollar_volume": _r(dv, 0), "min": floor, "currency": "USD" if crypto else currency}
    if "no_liquidity_data" in reasons or dv is None:
        checks.append(_check("liquidity", "na", None, "no_data", liq_params))
    elif "low_liquidity" in reasons:
        checks.append(_check("liquidity", "warn", _r(dv, 0), "low_liquidity", liq_params))
    else:
        checks.append(_check("liquidity", "pass", _r(dv, 0), "liquid", liq_params))

    # earnings_soon
    limit = settings.earnings_blackout_trading_days
    e = earnings or {}
    e_params = {"date": e.get("date"), "trading_days": e.get("trading_days"), "days": e.get("days"),
                "limit": limit}
    if asset_type != "STOCK":
        checks.append(_check("earnings_soon", "na", None, "not_applicable", e_params))
    elif not e.get("date"):
        checks.append(_check("earnings_soon", "na", None, "no_date", e_params))
    else:
        td = e.get("trading_days")
        soon = td is not None and 0 <= int(td) <= limit
        checks.append(_check("earnings_soon", "warn" if soon else "pass", e.get("date"),
                             "earnings_soon" if soon else "earnings_later", e_params))

    # dividend_health
    item = dividend_item or {}
    rating = item.get("rating") or "n/a"
    status = {"good": "pass", "fair": "warn", "poor": "fail"}.get(rating, "na")
    checks.append(_check("dividend_health", status, rating, item.get("code") or "unavailable",
                         {**(item.get("params") or {}), "rating": rating}))
    return checks


def build_events(earnings: dict | None, profile: dict | None) -> dict:
    p = profile or {}
    ex = {"date": p.get("next_ex_date"), "estimated": bool(p.get("next_estimated")),
          "amount": p.get("next_amount")} if p.get("next_ex_date") else None
    pay = {"date": p.get("next_pay_date"), "estimated": bool(p.get("next_pay_estimated"))} \
        if p.get("next_pay_date") else None
    return {"earnings": earnings if earnings and earnings.get("date") else None,
            "ex_dividend": ex, "dividend_payment": pay}


async def _earnings(symbol: str, asset_type: str, exchange: str, info: dict) -> dict | None:
    """Next earnings {"date", "days", "trading_days"} for stocks (shared, cached
    in signals/earnings.py); falls back to the date in Yahoo's info."""
    if asset_type != "STOCK":
        return None
    from app.services.holdings_monitor import earnings_info

    try:
        e = await earnings_info({"symbol": symbol, "asset_type": "STOCK"})
    except Exception as ex:
        logger.debug(f"stock_page: earnings({symbol}) failed: {ex}")
        e = None
    if e and e.get("date"):
        return e
    from app.scanners.market_scanner import _next_earnings_date_from_info
    iso = _next_earnings_date_from_info(info or {})
    if not iso:
        return {"date": None, "days": None, "trading_days": None}
    nd, today = date.fromisoformat(iso), _today_et()
    return {"date": iso, "days": (nd - today).days, "trading_days": trading_days_until(exchange, nd, today)}


# ============================================================
# Resolve + build (shared, cached)
# ============================================================

def normalize(raw: str) -> str:
    """Uppercase / trim; StockPageError(invalid_symbol) on a bad format."""
    from app.services.stock_check import StockCheckError, normalize_input
    try:
        return normalize_input(raw)
    except StockCheckError:
        raise StockPageError("invalid_symbol", "Enter a ticker symbol like AAPL, XEQT.TO or BTC-USD.", 400)


async def _resolve(sym: str) -> tuple[str, dict]:
    """(resolved symbol, raw market data). Tries SYM, SYM.TO, SYM-USD (universe
    members first, stock_check.candidate_symbols); 404 when none trades."""
    from app.services.stock_check import candidate_symbols

    known = _resolve_cache.get(sym)
    cands = [known] if known else candidate_symbols(sym)
    for cand in cands:
        if _missing_cache.get(cand):
            continue
        raw = await asyncio.to_thread(_fetch_market, cand)
        if raw.get("history") is not None:
            _resolve_cache.set(sym, cand)
            return cand, raw
        _missing_cache.set(cand, True)
    raise StockPageError("not_found", f"No recent price data for {sym}.", 404)


async def _build(symbol: str, raw: dict) -> tuple[dict, bool]:
    """(shared page body, complete?)."""
    info = raw.get("info") or {}
    history = raw.get("history")
    asset_type = asset_type_for(symbol, info)
    exchange = exchange_for(symbol, info)
    from app.services.long_term_check import currency_of
    currency = currency_of(symbol, info)
    quote = build_quote(history, info)

    try:
        tech = indicators.compute_indicators(history, exchange=exchange) if history is not None else {}
    except Exception as e:
        logger.warning(f"stock_page: indicators({symbol}) failed: {e}")
        tech = {}

    got = await asyncio.gather(
        dividends.get_dividend_profile(symbol, info=info or None, price=quote["price"]),
        _earnings(symbol, asset_type, exchange, info),
        return_exceptions=True,
    )
    profile = got[0] if isinstance(got[0], dict) else dividends.empty_profile(symbol, "unavailable")
    earnings = got[1] if isinstance(got[1], dict) else None
    try:
        div = dividends.long_term_dividend_assessment(profile, asset_type, info.get("sector"), info.get("industry"))
    except Exception as e:
        logger.warning(f"stock_page: dividend rules({symbol}) failed: {e}")
        div = {"item": {"key": "dividend", "code": "unavailable", "rating": "n/a", "reason": "", "params": {}},
               "rules": [], "cap": False}

    body = {
        "symbol": symbol,
        "name": info.get("longName") or info.get("shortName"),
        "exchange": exchange,
        "exchange_name": info.get("fullExchangeName"),
        "currency": currency,
        "asset_type": asset_type.lower(),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "quote": quote,
        "dividend": {
            "profile": profile,
            "rating": div["item"]["rating"],
            "rating_code": div["item"]["code"],
            "rules": div["rules"],
        },
        "events": build_events(earnings, profile),
        "checks": build_checks(tech, asset_type, earnings, div["item"], currency),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    complete = bool(info) and bool(tech) and not isinstance(got[0], BaseException) \
        and profile.get("reason") != "unavailable"
    return body, complete


async def get_shared_page(raw_symbol: str) -> dict:
    """Shared (per-symbol, cross-user) part of the page. Raises StockPageError."""
    sym = normalize(raw_symbol)
    resolved = _resolve_cache.get(sym) or sym
    cached = _page_cache.get(resolved)
    if cached is not None:
        return cached
    lock = _locks.setdefault(sym, asyncio.Lock())
    async with lock:
        resolved = _resolve_cache.get(sym) or sym
        cached = _page_cache.get(resolved)
        if cached is not None:
            return cached
        symbol, raw = await _resolve(sym)
        body, complete = await _build(symbol, raw)
        _page_cache.set(symbol, body, ttl=PAGE_TTL if complete else PARTIAL_TTL)
        if len(_locks) > 1000:
            _locks.clear()
        return body


# ============================================================
# Per-user part (never cached)
# ============================================================

def followed(user_id: str, symbols: set[str]) -> dict:
    """{"in_holdings", "in_watchlist"} for this user. DB errors -> False."""
    from app.db.supabase import get_client

    out = {"in_holdings": False, "in_watchlist": False}
    try:
        db = get_client()
    except Exception:
        return out
    for table, key in (("holdings", "in_holdings"), ("watchlist", "in_watchlist")):
        try:
            rows = (db.table(table).select("symbol").eq("user_id", user_id)
                    .in_("symbol", sorted(symbols)).limit(1).execute().data or [])
            out[key] = bool(rows)
        except Exception as e:
            logger.debug(f"stock_page: followed({table}) failed: {e}")
    return out


async def get_stock_page(raw_symbol: str, user_id: str) -> dict:
    body = await get_shared_page(raw_symbol)
    sym = normalize(raw_symbol)
    fol = await asyncio.to_thread(followed, user_id, {body["symbol"], sym})
    return {**body, "followed": fol}
