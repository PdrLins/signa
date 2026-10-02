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
  * The per-user part ("followed": holdings / watchlist, "position": the
    user's shares across accounts, "slots") is read from the DB on every
    request and never cached.

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


def _last_bar(history) -> dict:
    try:
        if history is None or not len(history):
            return {}
        row = history.iloc[-1]
        return {k: _num(row.get(k)) for k in ("High", "Low", "Volume")}
    except Exception:
        return {}


def _avg_volume(history, n: int = 63) -> float | None:
    try:
        v = history["Volume"].dropna().tail(n)
        return _num(v.mean()) if len(v) else None
    except Exception:
        return None


def build_statistics(history, info: dict | None, quote: dict, dividend_profile: dict | None) -> dict:
    """Key statistics, each nullable. Pure.

    day_low/day_high     today's session range (Yahoo info, else the last daily bar)
    low_52w/high_52w     same as quote
    market_cap           listing currency
    pe_ratio             trailing P/E; forward_pe: forward P/E
    dividend_yield       FRACTION (0.035 = 3.5%), from the dividend profile
    avg_volume           ~3-month average daily volume (shares); volume: today's
    beta                 5-year monthly beta (Yahoo)"""
    info = info or {}
    bar = _last_bar(history)

    def first(*keys):
        for k in keys:
            v = _num(info.get(k))
            if v is not None:
                return v
        return None

    pe, fpe = first("trailingPE"), first("forwardPE")
    return {
        "day_low": _r(first("regularMarketDayLow", "dayLow") or bar.get("Low"), 4),
        "day_high": _r(first("regularMarketDayHigh", "dayHigh") or bar.get("High"), 4),
        "low_52w": quote.get("low_52w"),
        "high_52w": quote.get("high_52w"),
        "market_cap": quote.get("market_cap"),
        "pe_ratio": _r(pe) if pe is not None and pe > 0 else None,
        "forward_pe": _r(fpe) if fpe is not None and fpe > 0 else None,
        "dividend_yield": _r((dividend_profile or {}).get("yield"), 5),
        "avg_volume": _r(first("averageVolume", "averageDailyVolume3Month") or _avg_volume(history), 0),
        "volume": _r(first("regularMarketVolume", "volume") or bar.get("Volume"), 0),
        "beta": _r(first("beta")),
    }


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
        "statistics": build_statistics(history, info, quote, profile),
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


def _wavg(pairs: list[tuple[float | None, float | None]]) -> float | None:
    """Share-weighted average of (shares, avg_cost), lots without a cost skipped."""
    known = [(sh, c) for sh, c in pairs if sh and c is not None]
    total = sum(sh for sh, _ in known)
    return sum(sh * c for sh, c in known) / total if total else None


def _pl(abs_: float | None, base: float | None) -> dict:
    return {"abs": _r(abs_), "pct": _r(abs_ / base * 100) if abs_ is not None and base else None}


def build_position(symbols: set[str], scope: dict) -> dict | None:
    """This user's position in the symbol (all accounts), or None when not held. Pure.

    `scope` is portfolio_context.load_scope (whole portfolio, with quotes
    and transactions). Native money is in the position `currency`; *_home
    in the user's home currency (USD/CAD only, else null)."""
    from app.services import portfolio_context as pc
    from app.services.portfolio_ledger import derive_positions

    home, usdcad = scope["home_currency"], scope.get("usdcad")
    rows = pc.value_positions(scope["holdings"], scope.get("quotes") or {}, home, usdcad)
    mine = [r for r in rows if r["symbol"] in symbols and (r.get("shares") or 0) > 0]
    if not mine:
        return None
    total_home = sum(r["value_home"] for r in rows if r.get("value_home") is not None)
    names = {str(a.get("id")): a.get("name") for a in scope.get("all_accounts") or scope.get("accounts") or []}

    def total(key: str) -> float | None:
        vals = [r.get(key) for r in mine]
        return sum(v for v in vals if v is not None) if any(v is not None for v in vals) else None

    shares = sum(r["shares"] for r in mine)
    avg_cost = _wavg([(r["shares"], r.get("avg_cost")) for r in mine])
    ccy = mine[0]["currency"]
    price = next((r["price"] for r in mine if r.get("price") is not None), None)
    prev = next((r["prev_close"] for r in mine if r.get("prev_close") is not None), None)
    value = shares * price if price is not None else None
    value_home = total("value_home")
    cost = shares * avg_cost if avg_cost is not None else None
    open_abs = value - cost if value is not None and cost is not None else None
    today_abs = shares * (price - prev) if price is not None and prev is not None else None

    txs = [t for t in scope.get("transactions") or [] if str(t.get("symbol") or "").upper() in symbols]
    dividends_received = realized = None
    if txs:
        led = [p for p in derive_positions(txs)["positions"] if p["symbol"] in symbols]
        dividends_received = sum(p["dividends_total"] for p in led)
        realized = sum(p["realized_pl"] for p in led)
    gain_abs = None
    if open_abs is not None:
        gain_abs = open_abs + (dividends_received or 0) + (realized or 0)

    def home_of(v):
        return _r(pc.to_home(v, ccy, home, usdcad))

    return {
        "shares": _r(shares, 6),
        "avg_cost": _r(avg_cost, 4),
        "currency": ccy,
        "price": _r(price, 4),
        "home_currency": home,
        "market_value": _r(value),
        "market_value_home": _r(value_home),
        "weight_pct": _r(value_home / total_home * 100) if value_home is not None and total_home else None,
        "today_pl": {**_pl(today_abs, shares * prev if prev else None), "abs_home": home_of(today_abs)},
        "open_pl": {**_pl(open_abs, cost), "abs_home": home_of(open_abs)},
        "dividends_received": _r(dividends_received),
        "realized_pl": _r(realized),
        "total_gain": {**_pl(gain_abs, cost), "abs_home": home_of(gain_abs)},
        "has_transactions": bool(txs),
        "price_source": mine[0].get("price_source"),
        "as_of": mine[0].get("as_of"),
        "per_account": [
            {"account_id": r.get("account_id"),
             "account_name": names.get(str(r.get("account_id"))) if r.get("account_id") else None,
             "shares": _r(r["shares"], 6), "avg_cost": _r(r.get("avg_cost"), 4),
             "value": _r(r.get("value")), "value_home": _r(r.get("value_home"))}
            for r in sorted(mine, key=lambda r: -(r.get("value") or 0))
        ],
    }


def position(user: dict, symbols: set[str]) -> dict | None:
    """build_position for this user (DB + shared quotes). Errors -> None."""
    from app.services import portfolio_context as pc
    try:
        scope = pc.load_scope(user, None, None, True, True)
    except Exception as e:
        logger.debug(f"stock_page: position unavailable: {e}")
        return None
    return build_position({s.upper() for s in symbols}, scope)


def slots(user: dict) -> dict | None:
    from app.services import slots as slot_service
    try:
        return slot_service.slot_summary(user)
    except Exception as e:
        logger.debug(f"stock_page: slots unavailable: {e}")
        return None


async def get_stock_page(raw_symbol: str, user: dict) -> dict:
    """Shared body + this user's part (never cached): followed, position, slots."""
    body = await get_shared_page(raw_symbol)
    sym = normalize(raw_symbol)
    symbols = {body["symbol"], sym}
    fol, pos, slot = await asyncio.gather(
        asyncio.to_thread(followed, user["user_id"], symbols),
        asyncio.to_thread(position, user, symbols),
        asyncio.to_thread(slots, user),
    )
    # pre-market / after-hours price (Premium, migration 021); per user, never cached in the body
    from app.core.access import can
    from app.services import quotes as quotes_service
    level = user.get("access_level") or "free"
    view = None
    if can(level, "feature.extended_hours"):
        view = await asyncio.to_thread(quotes_service.extended_for_symbol, body["symbol"], body.get("quote"))
    quote = {**(body.get("quote") or {}), **quotes_service.extended_payload(level, body["symbol"], view)}
    return {**body, "quote": quote, "followed": fol, "position": pos, "slots": slot}
