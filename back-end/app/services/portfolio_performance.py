"""Home and performance math for the tracker (GET /portfolio/summary,
/portfolio/history, /portfolio/performance). No AI.

Everything is in the user's home currency (USD/CAD converted with the
current CAD=X rate; other currencies are left out and listed). Prices are
free, delayed data (see portfolio_context).

SUMMARY (`summary_body`, pure)
  market_value   sum of shares x price of the priced, convertible holdings
  cash           sum of the scope's accounts.cash_balance
  total          market_value + cash
  day_change     sum of shares x (price - prev_close); pct vs the previous value
  total_gain     unrealized (value - cost, holdings with an avg_cost) and, when
                 the scope has transactions, + realized P/L + dividends from the
                 ledger (portfolio_ledger.derive_positions). pct = abs / cost basis.
                 Without transactions: unrealized only, dividends_included=false.

HISTORY (`history_body`)
  1D     intraday bars of the held symbols (5-minute for plans with
         feature.intraday_chart, else 15-minute), one batched download
         shared per symbol (`get_intraday_bars`, cached INTRADAY_TTL seconds).
         value(t) = cash + sum shares x last bar price <= t (previous close
         before a symbol's first bar). Return is from the first bar of the
         session (/summary's day_change is vs the previous close).
  1W 1M YTD 1Y ALL
         portfolio_snapshots (the daily 16:30 ET job) where they exist;
         before the first snapshot (or with none) the series is ESTIMATED:
         today's shares x daily closes (dividend-adjusted, price_cache) x
         TODAY's USD/CAD rate + today's cash. Dates before a held symbol's
         first close are cut (reason history_shorter). The last point is
         always the live total (same as /summary).
         estimated_reason: no_snapshots | partial_snapshots | no_intraday |
         no_history | null
  compare (opt-in, one of profile_service.COMPARE_INDEXES) -> a second series
         of the benchmark's price, scaled to the portfolio's first value (the
         benchmark is not converted: its own currency, price return).
  ALL starts at the first transaction or first snapshot (else 5 years back).

PERFORMANCE (`performance_body`)
  method "transactions" (the scope has transactions): modified Dietz
      R = (V1 - V0 - F + D') / (V0 + sum w_i F_i),  w_i = (E - d_i) / (E - S)
      External flows F: deposits (+) and withdrawals (-) when the scope has
      any; otherwise buys (+ amount + fee) and sells (- amount + fee) are the
      flows (the money that went into / came out of the positions) and the
      dividends received D' are added back (they left the positions).
      With deposits the dividends are assumed to sit in the account cash
      (D' = 0). ALL: V0 = 0 from the day before the first transaction.
      Holdings not bought through recorded transactions inflate the return:
      the ledger should be complete for this method.
  method "estimate" (no transactions): (V1 - V0) / V0 from the history
      series (today's shares over the whole range; no dividends).
  dividends_received: dividend transactions dated in (S, E], home currency.
  drivers: per holding (merged across accounts), assuming today's shares
      were held the whole range: weight at start (share of the holdings'
      start value, cash excluded) x the holding's price return, in points.
      Top 5 positive and top 5 negative. With compare: the benchmark's
      return, the difference (points) and the drivers vs the benchmark
      ((holding return - benchmark return) x start weight).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger

from app.core.executors import download_threads

from app.core.api_errors import api_error
from app.core.cache import SingleFlight, TTLCache
from app.services import portfolio_context as pc
from app.services.price_cache import native_currency

ET = ZoneInfo("America/New_York")
RANGES: tuple[str, ...] = ("1D", "1W", "1M", "3M", "YTD", "1Y", "5Y", "ALL")
# Ranges beyond one year need feature.full_history (premium).
LONG_RANGES: frozenset[str] = frozenset({"5Y", "ALL"})
INTRADAY_TTL = 180
INTRADAY_MISS_TTL = 120
ALL_FALLBACK_YEARS = 5
TOP_DRIVERS = 5

_intraday_cache = TTLCache(max_size=20000, default_ttl=INTRADAY_TTL)
_intraday_flight = SingleFlight()


def _f(v: Any) -> float | None:
    return pc._f(v)


def today_et() -> date:
    return datetime.now(ET).date()


def _d(v: Any) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def validate_range(rng: str) -> str:
    r = str(rng or "").upper()
    if r not in RANGES:
        raise api_error("invalid_range", f"range must be one of {', '.join(RANGES)}.",
                        422, field="range")
    return r


def validate_compare(compare: str | None) -> str | None:
    if compare is None or str(compare).strip() == "":
        return None
    from app.services.profile_service import COMPARE_INDEXES
    c = str(compare).strip().upper()
    if c not in COMPARE_INDEXES:
        raise api_error("invalid_compare", f"compare must be one of {', '.join(COMPARE_INDEXES)}.",
                        422, field="compare")
    return c


def range_start(rng: str, today: date) -> date | None:
    """Base date of a range (the value at the last close on/before it is the
    starting value). None for ALL (decided from the data)."""
    import pandas as pd

    if rng == "1D":
        return today - timedelta(days=1)
    if rng == "1W":
        return today - timedelta(days=7)
    if rng == "1M":
        return (pd.Timestamp(today) - pd.DateOffset(months=1)).date()
    if rng == "3M":
        return (pd.Timestamp(today) - pd.DateOffset(months=3)).date()
    if rng == "YTD":
        return date(today.year, 1, 1) - timedelta(days=1)
    if rng == "1Y":
        return (pd.Timestamp(today) - pd.DateOffset(years=1)).date()
    if rng == "5Y":
        return (pd.Timestamp(today) - pd.DateOffset(years=5)).date()
    return None


def closes_period(start: date, today: date) -> str:
    days = (today - start).days
    if days <= 360:
        return "1y"
    if days <= 2 * 366:   # 1Y (365/366 days) needs the close before its start: 2y, not 5y
        return "2y"
    if days <= 5 * 366:
        return "5y"
    return "max"


# ============================================================
# Scope money (pure)
# ============================================================

def scope_cash(accounts: list[dict], home: str, usdcad: float | None) -> tuple[float, list[dict]]:
    total, unconverted = 0.0, []
    for a in accounts or []:
        c = _f(a.get("cash_balance")) or 0.0
        if not c:
            continue
        v = pc.to_home(c, a.get("currency") or home, home, usdcad)
        if v is None:
            unconverted.append({"account_id": a.get("id"), "currency": a.get("currency"), "cash": round(c, 2)})
        else:
            total += v
    return total, unconverted


def _tx_currency(tx: dict, home: str) -> str:
    c = str(tx.get("currency") or "").upper()
    if c:
        return c
    return native_currency(tx.get("symbol")) if tx.get("symbol") else home


def ledger_totals(transactions: list[dict], home: str, usdcad: float | None) -> dict:
    """{"realized", "dividends", "unconverted"} in home currency from the ledger. Pure."""
    from app.services.portfolio_ledger import derive_positions

    led = derive_positions(transactions)
    realized = dividends = 0.0
    unconverted = []
    for p in led["positions"]:
        ccy = p.get("currency") or native_currency(p["symbol"])
        r = pc.to_home(p["realized_pl"], ccy, home, usdcad)
        d = pc.to_home(p["dividends_total"], ccy, home, usdcad)
        if r is None or d is None:
            unconverted.append({"symbol": p["symbol"], "currency": ccy})
            continue
        realized += r
        dividends += d
    return {"realized": realized, "dividends": dividends, "unconverted": unconverted}


def summary_body(scope: dict) -> dict:
    """GET /portfolio/summary body from a loaded scope. Pure."""
    home, usdcad = scope["home_currency"], scope["usdcad"]
    positions = pc.value_positions(scope["holdings"], scope["quotes"], home, usdcad)
    merged = pc.merge_positions_by_symbol(positions)
    mv = sum(p["value_home"] for p in positions if p["value_home"] is not None)
    cash, cash_unconv = scope_cash(scope["accounts"], home, usdcad)
    # today's move only from live quotes: a "last_close" fallback (monitor's
    # holding_status) carries YESTERDAY's prev_close -> yesterday's move
    today = [p for p in positions if p["day_change_home"] is not None and p.get("price_source") == "quote"]
    day_abs = sum(p["day_change_home"] for p in today)
    day_base = sum(p["prev_value_home"] for p in today)
    cost = sum(p["cost_home"] for p in positions if p["gain_home"] is not None)
    unreal = sum(p["gain_home"] for p in positions if p["gain_home"] is not None)
    txs = scope.get("transactions") or []
    realized = dividends = None
    led_unconv: list[dict] = []
    if txs:
        lt = ledger_totals(txs, home, usdcad)
        realized, dividends, led_unconv = lt["realized"], lt["dividends"], lt["unconverted"]
    gain = unreal + (realized or 0.0) + (dividends or 0.0)
    meta = pc.price_meta(positions)
    missing_cost = sorted({p["symbol"] for p in positions if p["shares"] and p["value"] is not None
                           and p["cost_home"] is None and p["converted"]})
    unpriced = sorted({p["symbol"] for p in positions if p["shares"] and p["price"] is None})
    missing_shares = sorted({p["symbol"] for p in positions if not p["shares"]})
    unconverted = [{"symbol": p["symbol"], "currency": p["currency"], "value": pc.r2(p["value"])}
                   for p in positions if not p["converted"]] + cash_unconv + led_unconv
    estimated = bool(meta["estimated_prices"] or unpriced or unconverted or missing_cost)
    ext = extended_change(positions, scope.get("quotes") or {}, scope.get("quotes_ext") or {}, home, usdcad, mv)
    from app.services import fixed_income as fixed_mod
    fixed = fixed_mod.scope_value(scope.get("fixed_income") or [], home, usdcad)
    from app.core.access import can
    from app.services import quotes as quotes_service
    phase = quotes_service.market_phase()
    ext_locked = (not can(scope.get("level") or "free", "feature.extended_hours") and phase in ("pre", "post")
                  and any(quotes_service.is_us_equity(p["symbol"]) and p["shares"] for p in positions))
    return {
        "currency": home,
        "market_value": pc.r2(mv),
        "cash": pc.r2(cash),
        "total": pc.r2(mv + cash + fixed["value"]),
        # fixed income entered by hand (migration 032), included in total
        "fixed_income": {"value": fixed["value"], "invested": fixed["invested"], "gain": fixed["gain"],
                         "count": fixed["count"], "estimated": fixed["estimated"]},
        "day_change": {"abs": pc.r2(day_abs) if day_base else None,
                       "pct": pc.r2(day_abs / day_base * 100) if day_base else None},
        "total_gain": {
            "abs": pc.r2(gain) if (cost or txs) else None,
            "pct": pc.r2(gain / cost * 100) if cost else None,
            "unrealized": pc.r2(unreal) if cost else None,
            "realized": pc.r2(realized),
            "dividends": pc.r2(dividends),
            "dividends_included": bool(txs),
        },
        "cost_basis": pc.r2(cost) if cost else None,
        "holdings_count": len(merged),
        "as_of": meta["as_of"],
        "delayed_minutes": meta["delayed_minutes"],
        "estimated": estimated,
        "estimated_flags": {
            "prices_from_last_close": meta["estimated_prices"],
            "unpriced": unpriced,
            "missing_cost": missing_cost,
            "missing_shares": missing_shares,
            "unconverted": unconverted,
        },
        "usdcad": usdcad,
        # US market phase: "pre" | "regular" | "post" | "closed" (ET, NYSE calendar)
        "market_phase": phase,
        # Premium: change since the regular-session price from pre-market /
        # after-hours trades (null when none) — {"session", "abs", "pct", "as_of", "symbols"}
        "extended": ext,
        # Free: true while held US stocks trade pre/after hours (show the Premium hint)
        "extended_locked": ext_locked,
    }


def extended_change(positions: list[dict], quotes: dict, ext_rows: dict, home: str,
                    usdcad: float | None, market_value: float) -> dict | None:
    """Value change from pre/after-hours prices vs the regular price, in home
    currency. Only positions with a current extended price count. Pure apart
    from the clock (quotes.extended_view)."""
    from app.services import quotes as quotes_service

    total = 0.0
    n = 0
    session = as_of = None
    for p in positions:
        if not p.get("shares") or p.get("price") is None:
            continue
        v = quotes_service.extended_view(quotes.get(p["symbol"]), ext_rows.get(p["symbol"]))
        if not v:
            continue
        fx = pc.to_home(1.0, p["currency"], home, usdcad)
        if fx is None:
            continue
        total += p["shares"] * (v["price"] - p["price"]) * fx
        n += 1
        session = session or v["session"]
        as_of = max(as_of, v["as_of"]) if as_of else v["as_of"]
    if not n:
        return None
    return {"session": session, "abs": pc.r2(total),
            "pct": pc.r2(total / market_value * 100) if market_value else None,
            "as_of": as_of, "symbols": n}


# ============================================================
# Intraday bars (shared per symbol, cached)
# ============================================================

def parse_intraday(data, symbols: list[str]) -> dict[str, list[tuple[datetime, float]]]:
    """yf.download intraday frame -> {symbol: [(UTC datetime, close)]}. Pure."""
    import pandas as pd

    out: dict[str, list[tuple[datetime, float]]] = {}
    if data is None or getattr(data, "empty", True):
        return out
    multi = isinstance(data.columns, pd.MultiIndex) and len(symbols) > 1
    for sym in symbols:
        try:
            col = data["Close"]
            if multi:
                if sym not in col.columns:
                    continue
                col = col[sym]
            elif hasattr(col, "columns"):
                col = col.iloc[:, 0]
            col = col.dropna()
        except Exception:
            continue
        from app.market.currency import price_factor
        k = price_factor(sym)   # pence/cents listings, like the quotes table
        pts = []
        for ts, v in col.items():
            x = _f(v)
            if x is None or x <= 0:
                continue
            t = pd.Timestamp(ts)
            t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
            pts.append((t.to_pydatetime(), x * k))
        if pts:
            out[sym] = pts
    return out


def _download_intraday(symbols: list[str], interval: str, prepost: bool = False) -> dict[str, list[tuple[datetime, float]]]:
    """One batched intraday download of the latest trading day; prepost=True
    adds pre-market and after-hours bars (Premium, feature.extended_hours).
    Blocking. Tests replace this function."""
    import yfinance as yf

    data = yf.download(symbols, period="1d", interval=interval, prepost=prepost, progress=False,
                       threads=download_threads(len(symbols)), auto_adjust=False, group_by="column")
    return parse_intraday(data, symbols)


def get_intraday_bars(symbols: list[str], interval: str, prepost: bool = False) -> dict[str, list[tuple[datetime, float]]]:
    """{symbol: bars} shared across users, cached INTRADAY_TTL. Never raises."""
    from app.services import usage_metrics

    out: dict[str, list] = {}
    missing = []
    tag = f"{interval}{':x' if prepost else ''}"
    for s in dict.fromkeys(x for x in symbols if x):
        hit = _intraday_cache.get(f"{tag}:{s}")
        if hit is None:
            missing.append(s)
        elif hit is not False:
            out[s] = hit
    if not missing:
        return out
    # At the open every user's 1D chart asks for the same symbols: one download each.
    mine_keys, their_keys = _intraday_flight.claim([f"{tag}:{s}" for s in missing])
    mine = [k[len(tag) + 1:] for k in mine_keys]
    try:
        if mine:
            usage_metrics.record("provider_calls.intraday")
            try:
                got = (_download_intraday(mine, interval, True) if prepost else _download_intraday(mine, interval)) or {}
            except Exception as e:
                logger.warning(f"intraday bars failed for {len(mine)} symbols: {e}")
                got = {}
            for s in mine:
                if got.get(s):
                    _intraday_cache.set(f"{tag}:{s}", got[s])
                    out[s] = got[s]
                else:
                    _intraday_cache.set(f"{tag}:{s}", False, ttl=INTRADAY_MISS_TTL)
    finally:
        _intraday_flight.release(mine_keys)
    if their_keys:
        _intraday_flight.wait(their_keys)
        for k in their_keys:
            hit = _intraday_cache.get(k)
            if hit:
                out[k[len(tag) + 1:]] = hit
    return out


def clear_cache() -> None:
    _intraday_cache.clear()
    _daily_cache.clear()


# ============================================================
# Series builders (pure)
# ============================================================

def _fx(ccy: str, home: str, usdcad: float | None) -> float | None:
    return pc.to_home(1.0, ccy, home, usdcad)


def intraday_series(positions: list[dict], bars: dict[str, list], home: str, usdcad: float | None,
                    cash: float) -> list[tuple[datetime, float]]:
    """value(t) = cash + sum shares x (last bar <= t, else prev_close, else first bar). Pure.
    One pass per position over its bars (they and the stamps are sorted)."""
    held = []
    for p in positions:
        fx = _fx(p["currency"], home, usdcad) if p.get("shares") and p.get("price") else None
        if fx:
            held.append((p, fx))
    stamps = sorted({t for p, _ in held for t, _ in bars.get(p["symbol"], [])})
    totals = [cash] * len(stamps)
    for p, fx in held:
        b = bars.get(p["symbol"]) or []
        px = p.get("prev_close") or (b[0][1] if b else p["price"])   # before its first bar
        k = p["shares"] * fx
        i = 0
        for j, t in enumerate(stamps):
            while i < len(b) and b[i][0] <= t:
                px = b[i][1]
                i += 1
            totals[j] += k * px
    return list(zip(stamps, totals))


def estimate_series(positions: list[dict], closes: dict, base: date, today: date, home: str,
                    usdcad: float | None, cash: float) -> tuple[list[tuple[date, float]], bool]:
    """(points [(date, value)], truncated) from today's shares x daily closes.
    The first point is the last close on/before `base`. Holdings without
    closes count at their current value. Pure."""
    import pandas as pd

    held = [p for p in positions if p.get("shares") and p.get("price") and _fx(p["currency"], home, usdcad)]
    with_hist = [p for p in held if closes.get(p["symbol"]) is not None and len(closes[p["symbol"]])]
    hist_ids = {id(p) for p in with_hist}
    const = cash + sum(p["shares"] * p["price"] * _fx(p["currency"], home, usdcad)
                       for p in held if id(p) not in hist_ids)
    if not with_hist:
        return [], False
    df = pd.concat({p["symbol"]: closes[p["symbol"]] for p in with_hist}, axis=1).sort_index().ffill()
    df.index = pd.DatetimeIndex(df.index).normalize()
    df = df[~df.index.duplicated(keep="last")]
    df = df[df.index <= pd.Timestamp(today)]
    before = df[df.index <= pd.Timestamp(base)]
    start_ts = before.index[-1] if len(before) else df.index[0]
    df = df[df.index >= start_ts]
    complete = df.dropna()
    truncated = len(complete) < len(df) or (len(before) == 0)
    # value = const + closes · (shares × fx), one vector operation for every day
    weights: dict[str, float] = {}
    for p in with_hist:
        weights[p["symbol"]] = weights.get(p["symbol"], 0.0) + p["shares"] * _fx(p["currency"], home, usdcad)
    w = pd.Series(weights)
    values = complete[list(w.index)].astype(float).mul(w).sum(axis=1) + const
    points = [(ts.date(), float(v)) for ts, v in values.items()]
    return points, truncated


def snapshot_series(rows: list[dict]) -> dict[date, float]:
    """{date: market_value + cash} summed per date (per-account rows add up). Pure."""
    out: dict[date, float] = {}
    for r in rows or []:
        d = _d(r.get("snapshot_date"))
        if d is None:
            continue
        v = (_f(r.get("market_value")) or 0.0) + (_f(r.get("cash")) or 0.0)
        out[d] = out.get(d, 0.0) + v
    return out


def combine_daily(estimate: list[tuple[date, float]], snaps: dict[date, float], base: date,
                  today: date, live_total: float | None) -> tuple[list[tuple[date, float]], str | None]:
    """Snapshots where present, the estimate before the first one, the live
    total as today's point. Returns (points, estimated_reason). Pure."""
    snaps = {d: v for d, v in snaps.items() if d <= today}
    base_snaps = [d for d in snaps if d <= base]
    if base_snaps:   # a snapshot covers the range's base: start there
        first = max(base_snaps)
        snaps = {d: v for d, v in snaps.items() if d >= first}
    else:
        snaps = {d: v for d, v in snaps.items() if d > base}
    if snaps and base_snaps:
        pts, reason = sorted(snaps.items()), None
    elif snaps:
        first = min(snaps)
        pts = [(d, v) for d, v in estimate if d < first] + sorted(snaps.items())
        reason = "partial_snapshots"
    else:
        pts = list(estimate)
        reason = "no_snapshots" if pts else "no_history"
    if live_total is not None:
        pts = [(d, v) for d, v in pts if d < today] + [(today, live_total)]
    return pts, reason


def scale_benchmark(points: list[tuple[Any, float]], bench: list[tuple[Any, float]]) -> list[tuple[Any, float]]:
    """Benchmark price at each portfolio time (last bench price <= t, else its
    first), scaled so the first point equals the portfolio's first value. Pure."""
    if not points or not bench:
        return []
    bench = sorted(bench, key=lambda x: x[0])
    vals = []
    j, last = 0, None
    for t, _ in points:
        while j < len(bench) and bench[j][0] <= t:
            last = bench[j][1]
            j += 1
        vals.append((t, last if last is not None else bench[0][1]))
    b0 = vals[0][1]
    if not b0:
        return []
    start = points[0][1]
    return [(t, start * v / b0) for t, v in vals]


def range_return(points: list[tuple[Any, float]]) -> float | None:
    if len(points) < 2 or not points[0][1]:
        return None
    return (points[-1][1] / points[0][1] - 1) * 100


def _series_out(points: list[tuple[Any, float]]) -> list[dict]:
    return [{"t": t.isoformat(), "value": round(v, 2)} for t, v in points]


MAX_DAILY_POINTS = 400   # a phone chart can't show more; 5Y/ALL go weekly past this


def thin_weekly(points: list[tuple[Any, float]], max_points: int = MAX_DAILY_POINTS) -> list[tuple[Any, float]]:
    """Long daily series -> the last point of each ISO week, keeping the
    first and last points exact (range return unchanged). Pure (tested)."""
    if len(points) <= max_points:
        return points
    out: list[tuple[Any, float]] = [points[0]]
    for i in range(1, len(points) - 1):
        if points[i][0].isocalendar()[:2] != points[i + 1][0].isocalendar()[:2]:
            out.append(points[i])
    out.append(points[-1])
    return out


def _closes_points(series, base: date, today: date) -> list[tuple[date, float]]:
    import pandas as pd

    if series is None or not len(series):
        return []
    s = series.dropna()
    s.index = pd.DatetimeIndex(s.index).normalize()
    s = s[s.index <= pd.Timestamp(today)]
    before = s[s.index <= pd.Timestamp(base)]
    start = before.index[-1] if len(before) else (s.index[0] if len(s) else None)
    if start is None:
        return []
    s = s[s.index >= start]
    return [(ts.date(), float(v)) for ts, v in s.items()]


# ============================================================
# Performance math (pure)
# ============================================================

def external_flows(transactions: list[dict], start: date, end: date, home: str,
                   usdcad: float | None) -> dict:
    """{"basis": "deposits"|"trades"|None, "flows": [(date, amount_home)],
    "dividends": float, "unconverted": int} for transactions dated in (start, end]. Pure."""
    txs = transactions or []
    has_deposits = any(str(t.get("type")) in ("deposit", "withdrawal") for t in txs)
    basis = ("deposits" if has_deposits else "trades") if txs else None
    flows, dividends, unconv = [], 0.0, 0
    for t in txs:
        d = _d(t.get("trade_date"))
        if d is None or not (start < d <= end):
            continue
        typ = str(t.get("type") or "")
        amt = abs(_f(t.get("amount")) or ((_f(t.get("quantity")) or 0) * (_f(t.get("price")) or 0)))
        fee = abs(_f(t.get("fee")) or 0.0)
        ccy = _tx_currency(t, home)
        signed = None
        if typ == "dividend":
            v = pc.to_home(amt, ccy, home, usdcad)
            if v is None:
                unconv += 1
            else:
                dividends += v
            continue
        if basis == "deposits":
            if typ == "deposit":
                signed = amt
            elif typ == "withdrawal":
                signed = -amt
        else:
            if typ == "buy":
                signed = amt + fee
            elif typ == "sell":
                signed = -(amt - fee)
        if signed is None:
            continue
        v = pc.to_home(signed, ccy, home, usdcad)
        if v is None:
            unconv += 1
            continue
        flows.append((d, v))
    return {"basis": basis, "flows": flows, "dividends": dividends, "unconverted": unconv}


def modified_dietz(v0: float, v1: float, flows: list[tuple[date, float]], start: date, end: date,
                   extra_gain: float = 0.0) -> dict:
    """{"return_pct", "gain", "net_flows", "weighted_flows"}. Pure.
    R = (V1 - V0 - F + extra) / (V0 + sum w_i F_i), w_i = (E - d_i) / (E - S)."""
    span = max(1, (end - start).days)
    net = sum(a for _, a in flows)
    weighted = sum(a * max(0.0, min(1.0, (end - d).days / span)) for d, a in flows)
    gain = v1 - v0 - net + extra_gain
    denom = v0 + weighted
    return {"return_pct": (gain / denom * 100) if denom > 0 else None, "gain": gain,
            "net_flows": net, "weighted_flows": weighted}


def compute_drivers(items: list[dict], bench_return: float | None = None) -> dict:
    """items: [{symbol, start_value, return}] (return as a fraction). Returns
    {"positive", "negative", "vs_benchmark": {...} | None}; contribution in
    points = start weight x return x 100. Pure."""
    total = sum(i["start_value"] for i in items if i.get("start_value"))
    rows = []
    for i in items:
        if not i.get("start_value") or total <= 0 or i.get("return") is None:
            continue
        w = i["start_value"] / total
        row = {"symbol": i["symbol"], "weight_pct": round(w * 100, 2), "return_pct": round(i["return"] * 100, 2),
               "contribution_pts": round(w * i["return"] * 100, 4)}
        if bench_return is not None:
            row["vs_benchmark_pts"] = round(w * (i["return"] - bench_return) * 100, 4)
        rows.append(row)

    def split(key: str) -> dict:
        pos = sorted((r for r in rows if r[key] > 0), key=lambda r: -r[key])[:TOP_DRIVERS]
        neg = sorted((r for r in rows if r[key] < 0), key=lambda r: r[key])[:TOP_DRIVERS]
        return {"positive": pos, "negative": neg}

    out = split("contribution_pts")
    out["vs_benchmark"] = split("vs_benchmark_pts") if bench_return is not None else None
    return out


# ============================================================
# Orchestration (sync — run with run_db)
# ============================================================

def _live(scope: dict) -> dict:
    home, usdcad = scope["home_currency"], scope["usdcad"]
    positions = pc.value_positions(scope["holdings"], scope["quotes"], home, usdcad)
    merged = pc.merge_positions_by_symbol(positions)
    cash, _ = scope_cash(scope["accounts"], home, usdcad)
    mv = sum(p["value_home"] for p in positions if p["value_home"] is not None)
    prev = sum((p["prev_value_home"] if p["prev_value_home"] is not None else (p["value_home"] or 0.0))
               for p in positions if p["value_home"] is not None)
    return {"positions": positions, "merged": merged, "cash": cash, "total": mv + cash,
            "prev_total": prev + cash, "meta": pc.price_meta(positions)}


def _all_base(scope: dict, snaps: dict[date, float], today: date) -> date:
    cands = [d for d in snaps] + [_d(t.get("trade_date")) for t in scope.get("transactions") or []]
    cands = [d for d in cands if d]
    if cands:
        return min(cands) - timedelta(days=1)
    return today - timedelta(days=365 * ALL_FALLBACK_YEARS)


def _snapshot_rows(scope: dict, since: str | None) -> list[dict]:
    from app.db import queries

    ids = scope.get("account_ids")
    if ids is not None and not ids:
        return []
    return queries.get_portfolio_snapshot_rows(scope["user_id"], since, ids)


DAILY_TTL_S = 30   # history + performance open together: the second reuses the first's series
_daily_cache = TTLCache(max_size=5000, default_ttl=DAILY_TTL_S)


def _daily(scope: dict, live: dict, rng: str, today: date, extra_symbols: list[str] = ()) -> dict:
    """Daily series for 1W..ALL + the closes used (for drivers / benchmark).
    Cached DAILY_TTL_S per user, scope and range; a write by the user (new
    generation in app/core/user_cache.py) starts a new entry."""
    from app.core import user_cache

    uid = scope.get("user_id")
    key = None
    if uid:
        acc = scope.get("account_ids")
        key = "|".join([str(uid), ",".join(sorted(map(str, acc))) if acc is not None else "*", rng,
                        ",".join(sorted(extra_symbols)), str(user_cache.generation(uid)), today.isoformat()])
        hit = _daily_cache.get(key)
        if hit is not None:
            return hit
    out = _daily_build(scope, live, rng, today, extra_symbols)
    if key:
        _daily_cache.set(key, out)
    return out


def _daily_build(scope: dict, live: dict, rng: str, today: date, extra_symbols: list[str] = ()) -> dict:
    from app.services import price_cache

    home, usdcad = scope["home_currency"], scope["usdcad"]
    base = range_start(rng, today)
    if rng == "ALL":
        snaps = snapshot_series(_snapshot_rows(scope, None))
        base = _all_base(scope, snaps, today)
    else:
        snaps = snapshot_series(_snapshot_rows(scope, (base - timedelta(days=7)).isoformat()))
    syms = [p["symbol"] for p in live["merged"] if p.get("shares") and p.get("price")]
    closes = price_cache.fetch_daily_closes(list(dict.fromkeys(syms + list(extra_symbols))),
                                            period=closes_period(base, today)) if (syms or extra_symbols) else {}
    est, truncated = estimate_series(live["merged"], closes, base, today, home, usdcad, live["cash"])
    points, reason = combine_daily(est, snaps, base, today, live["total"] if live["merged"] or live["cash"] else None)
    return {"points": points, "reason": reason, "base": base, "closes": closes,
            "truncated": bool(truncated and reason in ("no_snapshots", "partial_snapshots")),
            "snapshots": len(snaps), "estimated_points": len(est)}


def history_body(scope: dict, rng: str, interval: str, compare: str | None, today: date | None = None) -> dict:
    today = today or today_et()
    live = _live(scope)
    home = scope["home_currency"]
    bench_name = None
    if compare:
        from app.services.profile_service import COMPARE_INDEXES
        bench_name = COMPARE_INDEXES.get(compare)
    bench_pts: list = []
    sources = {"snapshots": 0, "estimated": 0, "history_truncated": False}
    if rng == "1D":
        syms = [p["symbol"] for p in live["merged"] if p.get("shares") and p.get("price")]
        from app.core.access import can
        prepost = can(scope.get("level") or "free", "feature.extended_hours")
        bars = get_intraday_bars(syms + ([compare] if compare else []), interval, prepost) if (syms or compare) else {}
        points = intraday_series(live["merged"], bars, home, scope["usdcad"], live["cash"])
        reason = None
        if not points:
            if live["merged"] or live["cash"]:
                now = datetime.now(timezone.utc)
                open_t = datetime.combine(today, time(9, 30), tzinfo=ET).astimezone(timezone.utc)
                points = [(open_t, live["prev_total"]), (max(now, open_t), live["total"])]
            reason = "no_intraday"
        if compare:
            bench_pts = list(bars.get(compare) or [])
        start = end = today
    else:
        daily = _daily(scope, live, rng, today, [compare] if compare else [])
        points, reason = daily["points"], daily["reason"]
        sources = {"snapshots": daily["snapshots"], "estimated": daily["estimated_points"],
                   "history_truncated": daily["truncated"]}
        if compare:
            bench_pts = _closes_points(daily["closes"].get(compare), daily["base"], today)
        start = points[0][0] if points else daily["base"]
        end = today
    bench_series = scale_benchmark(points, bench_pts) if compare else []
    if rng in LONG_RANGES:
        points, bench_series = thin_weekly(points), thin_weekly(bench_series)
    return {
        "range": rng,
        "interval": interval if rng == "1D" else "1d",
        "currency": home,
        "start": start.isoformat() if isinstance(start, date) else None,
        "end": end.isoformat(),
        "series": _series_out(points),
        "range_return_pct": pc.r2(range_return(points)),
        "estimated": reason is not None,
        "estimated_reason": reason,
        "sources": sources,
        "compare": None if not compare else {
            "symbol": compare, "name": bench_name,
            "series": _series_out(bench_series),
            "range_return_pct": pc.r2(range_return(bench_series)),
            "available": bool(bench_series),
        },
        "as_of": live["meta"]["as_of"],
        "delayed_minutes": live["meta"]["delayed_minutes"],
        # 1D only: the regular session's bounds, so clients can show the
        # pre-market / after-hours part (Premium bars) differently
        "session": _session_bounds(today) if rng == "1D" else None,
    }


def _session_bounds(day: date) -> dict:
    return {"open": datetime.combine(day, time(9, 30), tzinfo=ET).astimezone(timezone.utc).isoformat(),
            "close": datetime.combine(day, time(16, 0), tzinfo=ET).astimezone(timezone.utc).isoformat()}


def _start_price(series, base: date):
    pts = _closes_points(series, base, date.max)
    return pts[0][1] if pts else None


def in_range_trades_value(txs: list[dict], start: date, end: date, closes: dict, base: date,
                          home: str, usdcad: float | None) -> float:
    """Value at the range's start price of the shares bought (minus sold) inside
    (start, end], in the home currency. Pure. A symbol without a start close
    uses the trade's own price."""
    total = 0.0
    for t in txs or []:
        typ = str(t.get("type") or "")
        d = _d(t.get("trade_date"))
        sym = str(t.get("symbol") or "").upper()
        if typ not in ("buy", "sell") or not sym or d is None or not (start < d <= end):
            continue
        qty = abs(_f(t.get("quantity")) or 0.0)
        px = _start_price(closes.get(sym), base) or _f(t.get("price"))
        fx = _fx(_tx_currency(t, home), home, usdcad)
        if not qty or not px or not fx:
            continue
        total += (qty if typ == "buy" else -qty) * px * fx
    return total


def performance_body(scope: dict, rng: str, compare: str | None, today: date | None = None) -> dict:
    from app.services import price_cache

    today = today or today_et()
    home, usdcad = scope["home_currency"], scope["usdcad"]
    live = _live(scope)
    txs = scope.get("transactions") or []
    v1 = live["total"]
    estimated_reason = None

    # starting value + per-symbol start prices
    if rng == "1D":
        start = today - timedelta(days=1)
        v0 = live["prev_total"]
        start_prices = {p["symbol"]: p.get("prev_close") for p in live["merged"]}
        closes = {}
        bench_ret = None
        if compare:   # today's move from the shared quote (live), like the portfolio's
            from app.services.quotes import get_quotes
            q = get_quotes([compare]).get(compare) or {}
            if q.get("change_pct") is not None:
                bench_ret = float(q["change_pct"]) / 100
            else:
                closes = price_cache.fetch_daily_closes([compare], period="1y")
                if closes.get(compare) is not None and len(closes[compare]) >= 2:
                    s = closes[compare].dropna()
                    bench_ret = float(s.iloc[-1]) / float(s.iloc[-2]) - 1
    else:
        daily = _daily(scope, live, rng, today, [compare] if compare else [])
        start = daily["base"] if not daily["points"] else min(daily["base"], daily["points"][0][0])
        v0 = daily["points"][0][1] if daily["points"] else None
        estimated_reason = daily["reason"]
        closes = daily["closes"]
        start_prices = {p["symbol"]: _start_price(closes.get(p["symbol"]), daily["base"]) for p in live["merged"]}
        bench_ret = None
        if compare:
            bp = _closes_points(closes.get(compare), daily["base"], today)
            if len(bp) >= 2 and bp[0][1]:
                bench_ret = bp[-1][1] / bp[0][1] - 1

    fl = external_flows(txs, start, today, home, usdcad) if txs else None
    if txs and rng not in ("1D", "ALL") and estimated_reason in ("no_snapshots", "partial_snapshots") \
            and v0 is not None:
        # The estimated start value uses TODAY's shares; the buys/sells inside the
        # range are also counted as flows. Take them out of the start value.
        v0 = v0 - in_range_trades_value(txs, start, today, closes, daily["base"], home, usdcad)
    if txs:
        method = "transactions"
        if rng == "ALL":
            v0 = 0.0
            first_tx = min(d for d in (_d(t.get("trade_date")) for t in txs) if d)
            start = first_tx - timedelta(days=1)
            fl = external_flows(txs, start, today, home, usdcad)
            if fl["basis"] == "trades":
                v1 = v1 - live["cash"]   # cash isn't a flow on this basis: it isn't a gain either
        extra = fl["dividends"] if fl["basis"] == "trades" else 0.0
        md = modified_dietz(v0 or 0.0, v1, fl["flows"], start, today, extra)
        ret, gain, net = md["return_pct"], md["gain"], md["net_flows"]
    else:
        method = "estimate"
        ret = (v1 / v0 - 1) * 100 if v0 else None
        gain = v1 - v0 if v0 is not None else None
        net = 0.0

    items = []
    for p in live["merged"]:
        sp = start_prices.get(p["symbol"])
        fx = _fx(p["currency"], home, usdcad) if p.get("currency") else None
        if not (p.get("shares") and p.get("price") and sp and fx):
            continue
        items.append({"symbol": p["symbol"], "start_value": p["shares"] * sp * fx, "return": p["price"] / sp - 1})
    drivers = compute_drivers(items, bench_ret)
    vs = drivers.pop("vs_benchmark")
    bench_name = None
    if compare:
        from app.services.profile_service import COMPARE_INDEXES
        bench_name = COMPARE_INDEXES.get(compare)
    return {
        "range": rng,
        "start": start.isoformat(),
        "end": today.isoformat(),
        "currency": home,
        "method": method,
        "flows_basis": fl["basis"] if fl else None,
        "return_pct": pc.r2(ret),
        "gain": pc.r2(gain),
        "start_value": pc.r2(v0),
        "end_value": pc.r2(v1),
        "net_flows": pc.r2(net),
        "dividends_received": pc.r2(fl["dividends"]) if fl else None,
        "drivers": drivers,
        "compare": None if not compare else {
            "symbol": compare, "name": bench_name,
            "return_pct": pc.r2(bench_ret * 100) if bench_ret is not None else None,
            "difference_pts": pc.r2(ret - bench_ret * 100) if ret is not None and bench_ret is not None else None,
            "drivers": vs,
        },
        "estimated": method == "estimate" or estimated_reason is not None,
        "estimated_reason": estimated_reason if method == "estimate" or estimated_reason else None,
        "as_of": live["meta"]["as_of"],
        "delayed_minutes": live["meta"]["delayed_minutes"],
    }
