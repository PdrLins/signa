"""Coming up: one merged, date-sorted feed of events for the user's held and
watched symbols (GET /api/v1/events/upcoming). No AI.

Symbols
  * held     = the holdings in the scope (portfolio_context.load_scope). A
               stock held in several accounts gives ONE item per event, with
               the total shares/cash and an `accounts` split
               [{account_id, shares, cash}] (clients show one row, a detail
               can list accounts).
  * watched  = the user's watchlist, only for the whole-portfolio scope (a
               watchlist belongs to no account). Watched-only symbols get
               events with owned=false and NO cash (null).

Sources (each a pure builder + a replaceable fetcher; a failing source is
reported in `sources` and never breaks the feed):
  ex_dividend       dividend profiles (services/dividends, shared ~12h cache)
                    via dividend_calendar.profile_events: ex-dates in the
                    window. cash = total shares x amount per share (native
                    currency) + cash_home (USD/CAD only, else null).
  dividend_payment  the same events placed on their pay date (pay dates are
                    often projected: estimated=true).
  earnings          stocks only: holdings_monitor.earnings_info (next report)
                    + the average ABSOLUTE move over the last 8 reports:
                    for each past report date d, close of the last session
                    before d -> close of the first session after d (a
                    2-session window that covers before-open and after-close
                    reports). Report dates: yfinance get_earnings_dates(12);
                    closes: price_cache.fetch_daily_closes(period="5y").
                    Cached per symbol 24h.
  analyst           HELD symbols only: yfinance upgrades_downgrades rows of
                    the last RECENT_DAYS (7) days, cached per symbol per day:
                    firm, action, from -> to grade, price target (current /
                    prior) when the provider has it.
  check_changed     the five Signa checks (check_status_daily, migration 014):
                    latest stored day vs the day before, one item per symbol
                    with `changes` [{key, from, to}], if the latest day is in
                    the last 7 days. Table missing -> sources.check_changed =
                    "unavailable", no items.
  economy           economic_calendar (manually maintained BoC / Fed rate
                    decisions, US / CA CPI releases).

Dates: forward-looking items are dated today..today+days. analyst and
check_changed look BACK (today-7..today): they are in the same list with
their real (past) date and recent=true, so the list starts with what just
happened, then what is coming. Order: date, then type (economy,
ex_dividend, dividend_payment, earnings, analyst, check_changed), then symbol.
"""

from __future__ import annotations

import asyncio
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

from loguru import logger

from app.core.cache import TTLCache
from app.services import economic_calendar, portfolio_context as pc

TYPE_ORDER = ("economy", "ex_dividend", "dividend_payment", "earnings", "analyst", "check_changed")
MIN_DAYS, MAX_DAYS, DEFAULT_DAYS = 1, 90, 30
RECENT_DAYS = 7
EARNINGS_REPORTS = 8
CONCURRENCY = 4
FETCH_TIMEOUT_S = 25.0

_moves_cache = TTLCache(max_size=1000, default_ttl=24 * 3600)
_analyst_cache = TTLCache(max_size=1000, default_ttl=24 * 3600)


def clear_cache() -> None:
    _moves_cache.clear()
    _analyst_cache.clear()


def _f(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _d(v: Any) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if hasattr(v, "date") and callable(v.date):
        try:
            return v.date()
        except Exception:
            return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _item(type_: str, day: date | str, symbol: str | None, title: str, detail: str, **extra) -> dict:
    base = {"type": type_, "date": day.isoformat() if isinstance(day, date) else str(day)[:10],
            "symbol": symbol, "title": title, "detail": detail, "cash": None, "cash_home": None,
            "currency": None, "estimated": False, "owned": False, "recent": False}
    base.update(extra)
    return base


def sort_items(items: list[dict]) -> list[dict]:
    rank = {t: i for i, t in enumerate(TYPE_ORDER)}
    return sorted(items, key=lambda it: (it["date"], rank.get(it["type"], 99), it.get("symbol") or ""))


# ============================================================
# Positions (pure)
# ============================================================

def positions_by_symbol(holdings: list[dict]) -> dict[str, dict]:
    """{SYMBOL: {"shares", "currency", "name", "asset_type", "accounts": [{account_id, shares}]}}."""
    from app.services.holdings_service import holding_currency

    out: dict[str, dict] = {}
    for h in holdings or []:
        sym = str(h.get("symbol") or "").upper()
        if not sym:
            continue
        p = out.setdefault(sym, {"symbol": sym, "shares": None, "currency": holding_currency(h),
                                 "name": h.get("name"), "asset_type": h.get("asset_type"), "accounts": []})
        sh = _f(h.get("shares"))
        if sh and sh > 0:
            p["shares"] = (p["shares"] or 0.0) + sh
        p["accounts"].append({"account_id": h.get("account_id"), "shares": sh if sh and sh > 0 else None})
    return out


# ============================================================
# Builders (pure)
# ============================================================

def dividend_items(profile: dict | None, pos: dict, owned: bool, today: date, end: date,
                   home: str, usdcad: float | None) -> list[dict]:
    from app.services.dividend_calendar import profile_events

    if not profile or not profile.get("pays_dividend"):
        return []
    sym = pos["symbol"]
    ccy = str(profile.get("currency") or pos.get("currency") or "USD").upper()
    shares = pos.get("shares") if owned else None
    out: list[dict] = []
    for ev in profile_events(profile, today):
        amt = _f(ev.get("amount_per_share"))
        cash = shares * amt if shares and amt is not None else None
        cash_home = pc.to_home(cash, ccy, home, usdcad)
        accounts = [{"account_id": a["account_id"], "shares": a["shares"],
                     "cash": pc.r2(a["shares"] * amt) if a["shares"] and amt is not None else None}
                    for a in pos.get("accounts") or []] if owned else []
        common = {"name": pos.get("name"), "amount_per_share": amt, "shares": shares, "currency": ccy,
                  "cash": pc.r2(cash), "cash_home": pc.r2(cash_home), "owned": owned,
                  "ex_date": ev["ex_date"], "pay_date": ev.get("pay_date"), "special": bool(ev.get("special")),
                  "frequency": profile.get("frequency"), "accounts": accounts}
        amt_txt = f"{amt:.4g} {ccy} per share" if amt is not None else "amount not known yet"
        ex = _d(ev.get("ex_date"))
        if ex is not None and today <= ex <= end and not ev.get("ex_passed"):
            out.append(_item("ex_dividend", ex, sym, f"{sym} ex-dividend",
                             f"Own it before this date to receive {amt_txt}.",
                             estimated=bool(ev.get("estimated")), **common))
        pay = _d(ev.get("pay_date"))
        if pay is not None and today <= pay <= end:
            out.append(_item("dividend_payment", pay, sym, f"{sym} dividend payment",
                             f"Payment of {amt_txt}.",
                             estimated=bool(ev.get("estimated")) or bool(ev.get("pay_date_estimated")), **common))
    return out


def avg_earnings_move(closes, report_dates: list[date], today: date, n: int = EARNINGS_REPORTS) -> dict | None:
    """Average absolute close-to-close move across the last n past reports
    (see the module docstring). None when no report could be measured. Pure."""
    import pandas as pd

    if closes is None or len(closes) < 2:
        return None
    s = closes.dropna()
    s = s[s > 0]
    idx = pd.DatetimeIndex(s.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    days = [ts.date() for ts in idx]
    vals = [float(v) for v in s.values]
    past = sorted({d for d in report_dates if d and d < today})[-n:]
    moves = []
    for d in past:
        before = [i for i, x in enumerate(days) if x < d]
        after = [i for i, x in enumerate(days) if x > d]
        if not before or not after:
            continue
        b, a = vals[before[-1]], vals[after[0]]
        moves.append({"date": d.isoformat(), "move_pct": round((a / b - 1) * 100, 2)})
    if not moves:
        return None
    avg = sum(abs(m["move_pct"]) for m in moves) / len(moves)
    return {"avg_abs_move_pct": round(avg, 2), "reports": len(moves), "moves": moves}


def earnings_item(sym: str, e: dict | None, move: dict | None, pos: dict, owned: bool,
                  today: date, end: date, home: str, usdcad: float | None) -> dict | None:
    d = _d((e or {}).get("date"))
    if d is None or not (today <= d <= end):
        return None
    avg = (move or {}).get("avg_abs_move_pct")
    detail = f"{sym} reports earnings."
    if avg is not None:
        detail += f" It moved {avg:.1f}% on average (up or down) after its last {move['reports']} reports."
    shares = pos.get("shares") if owned else None
    value = None
    if shares and avg is not None and pos.get("price") is not None:
        value = pc.r2(pc.to_home(shares * pos["price"] * avg / 100, pos.get("currency"), home, usdcad))
    return _item("earnings", d, sym, f"{sym} earnings", detail, name=pos.get("name"), owned=owned,
                 days=(e or {}).get("days"), trading_days=(e or {}).get("trading_days"),
                 avg_abs_move_pct=avg, reports_measured=(move or {}).get("reports"),
                 past_moves=(move or {}).get("moves") or [], typical_move_home=value)


def analyst_items(sym: str, rows: list[dict], pos: dict, today: date, recent_days: int = RECENT_DAYS) -> list[dict]:
    start = today - timedelta(days=recent_days)
    out = []
    for r in rows or []:
        d = _d(r.get("date"))
        if d is None or not (start <= d <= today):
            continue
        firm = r.get("firm") or "An analyst"
        frm, to = r.get("from_grade") or None, r.get("to_grade") or None
        action = str(r.get("action") or "").lower() or None
        cur_t, prior_t = _f(r.get("current_target")), _f(r.get("prior_target"))
        grade = f"{frm} → {to}" if frm and to and frm != to else (to or frm or "")
        detail = f"{firm}: {grade}".strip().rstrip(":")
        if cur_t:
            detail += f", target {cur_t:g}" + (f" (was {prior_t:g})" if prior_t and prior_t != cur_t else "")
        out.append(_item("analyst", d, sym, f"{sym} analyst {action or 'rating'}", detail + ".",
                         name=pos.get("name"), owned=True, recent=True, firm=r.get("firm"), action=action,
                         from_grade=frm, to_grade=to, price_target=cur_t, prior_price_target=prior_t))
    return out


CHECK_TITLES = {"uptrend": "trend", "not_overheated": "heat", "liquidity": "liquidity",
                "earnings_soon": "earnings timing", "dividend_health": "dividend health"}


def check_items(changes: dict[str, dict], names: dict[str, dict], owned: set[str], today: date,
                recent_days: int = RECENT_DAYS) -> list[dict]:
    out = []
    for sym, ch in (changes or {}).items():
        d = _d(ch.get("date"))
        if sym not in names or d is None or not (today - timedelta(days=recent_days) <= d <= today):
            continue
        parts = [f"{CHECK_TITLES.get(c['key'], c['key'])}: {c['from']} → {c['to']}" for c in ch["changes"]]
        out.append(_item("check_changed", d, sym, f"{sym}: a Signa check changed", "; ".join(parts) + ".",
                         name=names[sym].get("name"), owned=sym in owned, recent=True,
                         changes=ch["changes"], previous_date=ch.get("prev_date")))
    return out


def economy_items(today: date, end: date) -> list[dict]:
    return [_item("economy", e["date"], None, e["title"], e["detail"], code=e["code"], country=e["country"],
                  estimated=bool(e["provisional"]), owned=False)
            for e in economic_calendar.events_between(today, end)]


# ============================================================
# Fetchers (blocking; tests replace them)
# ============================================================

def fetch_earnings_dates(symbol: str) -> list[date]:
    """Past and upcoming report dates (yfinance get_earnings_dates, 12 rows)."""
    import yfinance as yf

    df = yf.Ticker(symbol).get_earnings_dates(limit=12)
    if df is None or getattr(df, "empty", True):
        return []
    return sorted({d for d in (_d(ts) for ts in df.index) if d})


def fetch_upgrades(symbol: str) -> list[dict]:
    """yfinance upgrades_downgrades -> [{date, firm, to_grade, from_grade, action,
    current_target, prior_target}] (newest first as returned)."""
    import yfinance as yf

    df = yf.Ticker(symbol).upgrades_downgrades
    if df is None or getattr(df, "empty", True):
        return []
    out = []
    for ts, row in df.head(40).iterrows():
        g = row.get
        out.append({"date": (_d(ts) or date.min).isoformat(), "firm": g("Firm"), "to_grade": g("ToGrade"),
                    "from_grade": g("FromGrade"), "action": g("Action"),
                    "current_target": _f(g("currentPriceTarget")), "prior_target": _f(g("priorPriceTarget"))})
    return out


def fetch_closes(symbols: list[str]) -> dict:
    from app.services.price_cache import fetch_daily_closes
    return fetch_daily_closes(symbols, period="5y")


async def fetch_earnings(item: dict, today: date) -> dict | None:
    from app.services.holdings_monitor import earnings_info
    return await earnings_info(item, today)


async def fetch_profiles(symbols: list[str]) -> dict[str, dict | None]:
    from app.services.dividend_calendar import fetch_profiles as fp
    return await fp(symbols)


async def _earnings_move(sym: str, today: date) -> dict | None:
    key = f"{sym}|{today.isoformat()}"
    hit = _moves_cache.get(key)
    if hit is not None:
        return hit or None
    from app.services import usage_metrics
    usage_metrics.record("provider_calls.earnings_moves")
    dates = await asyncio.to_thread(fetch_earnings_dates, sym)
    closes = (await asyncio.to_thread(fetch_closes, [sym])).get(sym)
    move = avg_earnings_move(closes, dates, today)
    _moves_cache.set(key, move or {})
    return move


async def _analyst(sym: str, today: date) -> list[dict]:
    key = f"{sym}|{today.isoformat()}"
    hit = _analyst_cache.get(key)
    if hit is not None:
        return hit
    from app.services import usage_metrics
    usage_metrics.record("provider_calls.analyst")
    rows = await asyncio.to_thread(fetch_upgrades, sym)
    _analyst_cache.set(key, rows)
    return rows


# ============================================================
# Assembly
# ============================================================

def validate_days(days: Any) -> int:
    from app.core.api_errors import api_error
    try:
        n = int(days)
    except (TypeError, ValueError):
        n = -1
    if not (MIN_DAYS <= n <= MAX_DAYS):
        raise api_error("invalid_days", f"days must be between {MIN_DAYS} and {MAX_DAYS}.", 422,
                        field="days", min=MIN_DAYS, max=MAX_DAYS)
    return n


async def build_upcoming(scope: dict, watchlist: list[dict] | None, days: int, today: date | None = None) -> dict:
    """The /events/upcoming response for a loaded scope. Never raises for a
    failing source (see `sources`)."""
    from app.core.api_errors import is_missing_schema
    from app.db import queries
    from app.services import dividends, usage_metrics

    usage_metrics.record("requests.events_upcoming")
    today = today or dividends.today_et()
    end = today + timedelta(days=days)
    home, usdcad = scope["home_currency"], scope.get("usdcad")
    held = positions_by_symbol(scope["holdings"])
    positions = pc.value_positions(scope["holdings"], scope.get("quotes") or {}, home, usdcad)
    for p in positions:
        if p["symbol"] in held and p.get("price") is not None:
            held[p["symbol"]]["price"] = p["price"]
            held[p["symbol"]]["currency"] = p["currency"]
    watched: dict[str, dict] = {}
    if scope.get("account_ids") is None:
        for w in watchlist or []:
            sym = str(w.get("symbol") or "").upper()
            if sym and sym not in held:
                watched[sym] = {"symbol": sym, "shares": None, "currency": None, "name": w.get("name"),
                                "asset_type": w.get("asset_type"), "accounts": []}
    every = {**held, **watched}
    sources: dict[str, str] = {}
    items: list[dict] = []
    sem = asyncio.Semaphore(CONCURRENCY)

    async def guarded(coro):
        async with sem:
            return await asyncio.wait_for(coro, FETCH_TIMEOUT_S)

    # dividends
    try:
        profiles = await fetch_profiles(list(every))
        failed = [s for s in every if profiles.get(s) is None]
        for sym, pos in every.items():
            items += dividend_items(profiles.get(sym), pos, sym in held, today, end, home, usdcad)
        sources["dividends"] = "ok" if not failed else ("failed" if len(failed) == len(every) else "partial")
    except Exception as e:
        logger.warning(f"events: dividends failed: {e!r}")
        sources["dividends"] = "failed"

    # earnings (+ average move, only for reports inside the window)
    async def one_earnings(sym: str, pos: dict):
        e = await guarded(fetch_earnings({"symbol": sym, "asset_type": pos.get("asset_type")}, today))
        if not e or not e.get("date") or not (today <= (_d(e["date"]) or date.min) <= end):
            return None
        try:
            move = await guarded(_earnings_move(sym, today))
        except Exception as ex:
            logger.debug(f"events: earnings move {sym} failed: {ex!r}")
            move = None
        return earnings_item(sym, e, move, pos, sym in held, today, end, home, usdcad)

    res = await asyncio.gather(*(one_earnings(s, p) for s, p in every.items()), return_exceptions=True)
    errs = sum(1 for r in res if isinstance(r, BaseException))
    items += [r for r in res if isinstance(r, dict)]
    sources["earnings"] = "ok" if not errs else ("failed" if errs == len(res) else "partial")

    # analyst (held only)
    res = await asyncio.gather(*(guarded(_analyst(s, today)) for s in held), return_exceptions=True)
    errs = 0
    for sym, rows in zip(held, res):
        if isinstance(rows, BaseException):
            errs += 1
            continue
        items += analyst_items(sym, rows, held[sym], today)
    sources["analyst"] = "ok" if not errs else ("failed" if errs == len(res) else "partial")

    # check_changed
    from app.services.check_status import latest_changes
    try:
        since = (today - timedelta(days=RECENT_DAYS + 7)).isoformat()
        rows = await asyncio.to_thread(queries.get_check_status_rows, sorted(every), since) if every else []
        items += check_items(latest_changes(rows), every, set(held), today)
        sources["check_changed"] = "ok"
    except Exception as e:
        sources["check_changed"] = "unavailable" if is_missing_schema(e) else "failed"
        logger.debug(f"events: check statuses unavailable: {e}")

    items += economy_items(today, end)
    sources["economy"] = "ok"

    meta = pc.price_meta(positions)
    items = sort_items(items)
    return {
        "as_of": meta["as_of"],
        "delayed_minutes": meta["delayed_minutes"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "today": today.isoformat(),
        "window": {"start": today.isoformat(), "end": end.isoformat(), "days": days},
        "recent_from": (today - timedelta(days=RECENT_DAYS)).isoformat(),
        "home_currency": home,
        "usdcad": usdcad,
        "symbols": {"held": sorted(held), "watched": sorted(watched)},
        "items": items,
        "count": len(items),
        "sources": sources,
        "economy_calendar": {"last_reviewed": economic_calendar.LAST_REVIEWED.isoformat(),
                             "covered_until": economic_calendar.COVERED_UNTIL.isoformat(),
                             "maintained": "manually"},
    }
