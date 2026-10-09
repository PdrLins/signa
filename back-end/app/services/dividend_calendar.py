"""Dividend calendar for a user's own holdings (free area, no AI).

Built only from shared market data: services/dividends.get_dividend_profile
(yfinance, cached ~12h per symbol and shared across users), so a request
costs nothing per user. Nothing here calls app/ai or anything @ai_guarded.

  build_calendar(holdings, watchlist, today, months, usdcad, profiles)   pure
  get_calendar(holdings, watchlist, months, usdcad)                      async

Events
  * Upcoming cycles come from profile["upcoming"] (ex-dates in the next
    ~365 days; estimated=true when projected from the payment history,
    false for the announced next ex-date).
  * A recent ex-date (already passed) whose payment is still to come is
    included too (ex_passed=true, amount known, pay date = ex + the
    symbol's usual ex->pay offset, pay_date_estimated=true). These carry
    the real "special" flag from the payment history.
  * Each event is placed on its pay date, falling back to the ex-date
    (the "date" field). The window is calendar months: from today to the
    end of the month (months - 1) after the current one (the month
    buckets / chart). income_next_12m is rolling instead: today..today+365,
    so a quarterly payer always shows its 4 payments.

Money
  * expected_cash = shares x amount_per_share (null when shares unknown or
    the stock is on the watchlist only). Totals are per currency plus a CAD
    total (USD x CAD=X, holdings_service.to_cad conventions); a currency
    with no CAD rule (e.g. GBP) stays in the per-currency split only and
    sets fx_missing.
  * annual_income = shares x the forward annual rate (Yahoo dividendRate,
    else trailing) — the "yearly income" of the holdings as they stand.
  * forward_yield_pct = annual income (CAD) / market value (CAD) of the
    owned holdings that have both shares and a price (payers and
    non-payers alike).

A symbol whose profile fails is listed under "unknown" and never breaks
the response; crypto and non-payers are listed under "non_payers".

Response (GET /api/v1/dividends/calendar):
{
  "as_of": "2026-09-29",                       # today (US/Eastern)
  "window": {"start": "2026-09-29", "end": "2027-08-31", "months": 12},
  "usdcad": 1.39 | null,
  "include_watchlist": false,
  "summary": {
    "income_window":  Money,                   # owned events in the window
    "income_next_12m": Money,                  # owned events dated today..today+365 (rolling)
    "annual_income":  Money,                   # forward annual rate x shares
    "next_payment":   Event | null,            # first owned event on/after today by date
    "next_ex_date":   Event | null,            # first owned event with ex_date >= today
    "payers": 3, "non_payers": 1, "unknown": 0, "holdings": 4,
    "missing_shares": 1,
    "forward_yield_pct": 2.41 | null,
    "market_value_cad": 12345.67 | null        # denominator of the yield
  },
  "months": [                                  # every month of the window, empty ones too
    {"month": "2026-10", "total": Money, "events": [Event, ...]}
  ],
  "events": [Event, ...],                      # all window events, sorted by date then symbol
  "positions": [Position, ...],                # one per symbol (owned first)
  "non_payers": [{"symbol", "name", "reason": "crypto"|"no_dividend"|"suspended", "owned"}],
  "unknown":    [{"symbol", "name", "owned"}],
  "missing_shares": [{"symbol", "name"}]       # owned payers/unknown without shares
}
Money = {"by_currency": {"USD": 12.3, "CAD": 45.6}, "total_cad": 62.7 | null, "fx_missing": false,
         "total_home": 62.7 | null, "home_fx_missing": false}        # *_home: the user's home currency
(Also: top-level "home_currency"; events "expected_cash_home"; positions "annual_income_home";
 summary "market_value_home", "forward_yield_pct_home". The *_cad fields stay for older clients.)
Event = {
  "symbol", "name", "date",                    # date = pay_date or ex_date (ISO)
  "ex_date", "pay_date" | null, "pay_date_estimated": bool,
  "amount_per_share": float | null, "currency": "USD",
  "estimated": bool,                           # ex-date/amount projected, not announced
  "special": bool, "ex_passed": bool,
  "frequency": "quarterly" | ... | null,
  "shares": float | null, "expected_cash": float | null, "expected_cash_cad": float | null,
  "account": "TFSA" | ... | null, "owned": bool
}
Position = {
  "symbol", "name", "owned", "account", "shares", "currency", "price",
  "status": "payer" | "non_payer" | "unknown", "reason": str | null,
  "frequency", "annual_rate", "yield_pct", "annual_income", "annual_income_cad",
  "next_ex_date", "next_pay_date"
}
"""

from __future__ import annotations

import asyncio
import math
from datetime import date, timedelta
from typing import Awaitable, Callable, Iterable

from loguru import logger

from app.services import dividends
from app.services.holdings_service import convert, holding_currency, holding_price, to_cad

MAX_MONTHS = 12
CONCURRENCY = 4
PROFILE_TIMEOUT_S = 25.0
MAX_WATCHLIST = 100
NEXT_12M_DAYS = 365


# ============================================================
# Small helpers
# ============================================================

def _num(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _r(v: float | None, nd: int = 2) -> float | None:
    return round(v, nd) if v is not None and math.isfinite(v) else None


def _d(v) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def add_months(d: date, n: int) -> date:
    """First day of the month n months after d's month."""
    idx = d.year * 12 + (d.month - 1) + n
    return date(idx // 12, idx % 12 + 1, 1)


def window_for(today: date, months: int) -> tuple[date, date]:
    """[today, last day of the (months-1)th month after today's month]."""
    months = max(1, min(MAX_MONTHS, int(months)))
    return today, add_months(today, months) - timedelta(days=1)


def month_keys(start: date, end: date) -> list[str]:
    out, cur = [], date(start.year, start.month, 1)
    while cur <= end:
        out.append(f"{cur.year:04d}-{cur.month:02d}")
        cur = add_months(cur, 1)
    return out


class _Money:
    def __init__(self, usdcad: float | None, home: str = "CAD"):
        self.usdcad = usdcad
        self.home = home
        self.by_ccy: dict[str, float] = {}
        self.cad = 0.0
        self.home_total = 0.0
        self.any = False
        self.fx_missing = False
        self.home_missing = False

    def add(self, amount: float | None, currency: str) -> None:
        if amount is None:
            return
        self.by_ccy[currency] = self.by_ccy.get(currency, 0.0) + amount
        self.any = True
        c = to_cad(amount, currency, self.usdcad)
        if c is None:
            self.fx_missing = True
        else:
            self.cad += c
        h = convert(amount, currency, self.home, self.usdcad)
        if h is None:
            self.home_missing = True
        else:
            self.home_total += h

    def out(self) -> dict:
        return {
            "by_currency": {k: _r(v) for k, v in sorted(self.by_ccy.items())},
            "total_cad": _r(self.cad) if self.any else None,
            "fx_missing": self.fx_missing,
            "total_home": _r(self.home_total) if self.any else None,
            "home_fx_missing": self.home_missing,
        }


# ============================================================
# Pure: events
# ============================================================

def _pay_offset(profile: dict) -> int | None:
    """The symbol's usual ex -> pay gap in days, from its schedule."""
    for u in profile.get("upcoming") or []:
        ex, pay = _d(u.get("ex_date")), _d(u.get("pay_date"))
        if ex and pay and 0 <= (pay - ex).days <= dividends.max_pay_offset(profile.get("symbol")):   # B3 pays months later
            return (pay - ex).days
    return None


def profile_events(profile: dict, today: date) -> list[dict]:
    """Raw events (no position data) from one profile: recent ex-dates still
    awaiting payment + the upcoming schedule. Pure."""
    out: list[dict] = []
    if not profile or not profile.get("pays_dividend"):
        return out
    offset = _pay_offset(profile)
    upcoming_ex = {str(u.get("ex_date")) for u in profile.get("upcoming") or []}
    if offset is not None:
        for p in profile.get("last_payments") or []:
            ex = _d(p.get("ex_date"))
            if ex is None or ex >= today or p.get("ex_date") in upcoming_ex:
                continue
            pay = ex + timedelta(days=offset)
            if pay < today:
                continue
            out.append({"ex_date": ex.isoformat(), "pay_date": pay.isoformat(), "pay_date_estimated": True,
                        "amount_per_share": _num(p.get("amount")), "estimated": False,
                        "special": bool(p.get("special")), "ex_passed": True})
    for u in profile.get("upcoming") or []:
        ex = _d(u.get("ex_date"))
        if ex is None:
            continue
        pay = _d(u.get("pay_date"))
        out.append({"ex_date": ex.isoformat(), "pay_date": pay.isoformat() if pay else None,
                    "pay_date_estimated": bool(u.get("pay_estimated", True)) if pay else True,
                    "amount_per_share": _num(u.get("amount")), "estimated": bool(u.get("estimated", True)),
                    "special": False, "ex_passed": ex < today})
    return out


def _event_date(ev: dict) -> str:
    return ev.get("pay_date") or ev["ex_date"]


def _position(item: dict, owned: bool) -> dict:
    shares = _num(item.get("shares")) if owned else None
    return {
        "symbol": str(item.get("symbol") or "").upper(),
        "name": item.get("name"),
        "owned": owned,
        "account": item.get("account") if owned else None,
        "shares": shares if shares and shares > 0 else None,
        "currency": holding_currency(item),
        "price": holding_price(item) if owned else None,
    }


def build_calendar(holdings: list[dict], watchlist: Iterable[dict] | None, profiles: dict[str, dict | None],
                   today: date, months: int = 12, usdcad: float | None = None, home: str = "CAD") -> dict:
    """The whole calendar response from holdings + profiles. Pure.

    `profiles` maps symbol -> dividend profile, or None when it failed."""
    months = max(1, min(MAX_MONTHS, int(months or 12)))
    start, end = window_for(today, months)
    end12 = today + timedelta(days=NEXT_12M_DAYS)

    positions: list[dict] = []
    seen: set[str] = set()
    for h in holdings or []:
        p = _position(h, True)
        if p["symbol"] and p["symbol"] not in seen:
            seen.add(p["symbol"])
            positions.append(p)
    wl_on = watchlist is not None
    for w in watchlist or []:
        p = _position(w, False)
        if p["symbol"] and p["symbol"] not in seen:
            seen.add(p["symbol"])
            positions.append(p)

    events: list[dict] = []
    home = (home or "CAD").upper()
    income_window, income_12m, annual = _Money(usdcad, home), _Money(usdcad, home), _Money(usdcad, home)
    month_money = {k: _Money(usdcad, home) for k in month_keys(start, end)}
    month_events: dict[str, list[dict]] = {k: [] for k in month_money}
    non_payers, unknown, missing_shares, pos_out = [], [], [], []
    payers = non_pay = unk = 0
    mv_cad = 0.0
    mv_any = False
    annual_cad_for_yield = 0.0
    mv_home = annual_home_for_yield = 0.0
    mv_home_any = False

    for pos in positions:
        sym, owned, shares = pos["symbol"], pos["owned"], pos["shares"]
        prof = profiles.get(sym)
        reason = None
        if prof is None or (not prof.get("pays_dividend") and prof.get("reason") == "unavailable"):
            status = "unknown"
        elif prof.get("pays_dividend"):
            status = "payer"
        else:
            status, reason = "non_payer", prof.get("reason") or "no_dividend"
        ccy = str((prof or {}).get("currency") or pos["currency"]).upper()

        annual_rate = _num((prof or {}).get("annual_rate")) if status == "payer" else None
        annual_income = shares * annual_rate if owned and shares and annual_rate else None
        annual_income_cad = to_cad(annual_income, ccy, usdcad)
        annual_income_home = convert(annual_income, ccy, home, usdcad)
        y = _num((prof or {}).get("yield")) if status == "payer" else None

        if owned:
            if status == "payer":
                payers += 1
            elif status == "non_payer":
                non_pay += 1
            else:
                unk += 1
            if status != "non_payer" and not shares:
                missing_shares.append({"symbol": sym, "name": pos["name"]})
            annual.add(annual_income, ccy)
            price = pos["price"]
            if shares and price:
                v = to_cad(shares * price, pos["currency"], usdcad)
                if v is not None:
                    mv_cad += v
                    mv_any = True
                    if annual_income_cad:
                        annual_cad_for_yield += annual_income_cad
                vh = convert(shares * price, pos["currency"], home, usdcad)
                if vh is not None:
                    mv_home += vh
                    mv_home_any = True
                    if annual_income_home:
                        annual_home_for_yield += annual_income_home
        if status == "non_payer":
            non_payers.append({"symbol": sym, "name": pos["name"], "reason": reason, "owned": owned})
        elif status == "unknown":
            unknown.append({"symbol": sym, "name": pos["name"], "owned": owned})

        pos_out.append({
            **pos, "status": status, "reason": reason,
            "frequency": (prof or {}).get("frequency") if status == "payer" else None,
            "annual_rate": _r(annual_rate, 6), "yield_pct": _r(y * 100) if y is not None else None,
            "annual_income": _r(annual_income), "annual_income_cad": _r(annual_income_cad),
            "annual_income_home": _r(annual_income_home),
            "next_ex_date": (prof or {}).get("next_ex_date") if status == "payer" else None,
            "next_pay_date": (prof or {}).get("next_pay_date") if status == "payer" else None,
        })
        if status != "payer":
            continue

        for raw in profile_events(prof, today):
            key = _d(_event_date(raw))
            if key is None or key < start or key > end12:
                continue
            amt = raw["amount_per_share"]
            cash = shares * amt if owned and shares and amt is not None else None
            cash_cad = to_cad(cash, ccy, usdcad)
            cash_home = convert(cash, ccy, home, usdcad)
            ev = {
                "symbol": sym, "name": pos["name"], "date": key.isoformat(), **raw,
                "currency": ccy, "frequency": prof.get("frequency"),
                "shares": shares if owned else None,
                "expected_cash": _r(cash), "expected_cash_cad": _r(cash_cad),
                "expected_cash_home": _r(cash_home),
                "account": pos["account"], "owned": owned,
            }
            if owned:
                income_12m.add(cash, ccy)
            if key > end:
                continue
            events.append(ev)
            if owned:
                income_window.add(cash, ccy)
            mk = key.strftime("%Y-%m")
            if mk in month_money:
                month_events[mk].append(ev)
                if owned:
                    month_money[mk].add(cash, ccy)

    order = lambda e: (e["date"], e["ex_date"], not e["owned"], e["symbol"])  # noqa: E731
    events.sort(key=order)
    for lst in month_events.values():
        lst.sort(key=order)
    owned_events = [e for e in events if e["owned"]]
    next_payment = next((e for e in owned_events if e["date"] >= today.isoformat()), None)
    next_ex = min((e for e in owned_events if e["ex_date"] >= today.isoformat()),
                  key=lambda e: (e["ex_date"], e["symbol"]), default=None)
    pos_out.sort(key=lambda p: (not p["owned"], p["status"] != "payer", p["symbol"]))

    return {
        "as_of": today.isoformat(),
        "window": {"start": start.isoformat(), "end": end.isoformat(), "months": months},
        "usdcad": usdcad,
        "home_currency": home,
        "include_watchlist": wl_on,
        "summary": {
            "income_window": income_window.out(),
            "income_next_12m": income_12m.out(),
            "annual_income": annual.out(),
            "next_payment": next_payment,
            "next_ex_date": next_ex,
            "payers": payers, "non_payers": non_pay, "unknown": unk,
            "holdings": sum(1 for p in positions if p["owned"]),
            "missing_shares": len(missing_shares),
            "forward_yield_pct": _r(annual_cad_for_yield / mv_cad * 100) if mv_any and mv_cad > 0 else None,
            "market_value_cad": _r(mv_cad) if mv_any else None,
            "market_value_home": _r(mv_home) if mv_home_any else None,
            "forward_yield_pct_home": (_r(annual_home_for_yield / mv_home * 100)
                                       if mv_home_any and mv_home > 0 else None),
        },
        "months": [{"month": k, "total": month_money[k].out(), "events": month_events[k]} for k in month_money],
        "events": events,
        "positions": pos_out,
        "non_payers": non_payers,
        "unknown": unknown,
        "missing_shares": missing_shares,
    }


# ============================================================
# Async: fetch profiles (shared cache) + build
# ============================================================

ProfileFn = Callable[[str], Awaitable[dict]]


async def fetch_profiles(symbols: Iterable[str], fetch: ProfileFn | None = None,
                         concurrency: int = CONCURRENCY, timeout: float = PROFILE_TIMEOUT_S) -> dict[str, dict | None]:
    """symbol -> profile (None when it failed or timed out). Never raises."""
    fetch = fetch or dividends.get_dividend_profile
    sem = asyncio.Semaphore(concurrency)

    async def one(sym: str):
        async with sem:
            try:
                return sym, await asyncio.wait_for(fetch(sym), timeout)
            except Exception as e:  # includes TimeoutError
                logger.warning(f"dividend calendar: profile({sym}) failed: {e!r}")
                return sym, None

    uniq = list(dict.fromkeys(s for s in symbols if s))
    results = await asyncio.gather(*(one(s) for s in uniq))
    return dict(results)


async def get_calendar(holdings: list[dict], watchlist: list[dict] | None = None, months: int = 12,
                       usdcad: float | None = None, today: date | None = None,
                       fetch: ProfileFn | None = None, home: str = "CAD") -> dict:
    """Fetch the shared dividend profiles and build the calendar. Holdings are
    merged by symbol here (a stock in two accounts is one position with both
    lots' shares), so every caller gets full amounts."""
    from app.services.holdings_service import merge_by_symbol
    holdings = merge_by_symbol(holdings or [])
    wl = list(watchlist or [])[:MAX_WATCHLIST] if watchlist is not None else None
    symbols = [str(h.get("symbol") or "").upper() for h in holdings or []]
    symbols += [str(w.get("symbol") or "").upper() for w in wl or []]
    profiles = await fetch_profiles(symbols, fetch)
    return build_calendar(holdings, wl, profiles, today or dividends.today_et(), months, usdcad, home)


# ============================================================
# Per-holding dividend fields (GET /holdings items)
# ============================================================

def holding_dividend(profile: dict | None, held_since: date | None, today: date) -> dict | None:
    """{"yield_pct": forward yield in PERCENT (the stock page's), "next_pay_date"}
    or None when the symbol pays nothing known. next_pay_date = the earliest
    payment on/after today; a payment whose ex-date passed counts only when the
    holding existed before that ex-date. Pure."""
    if not profile or not profile.get("pays_dividend"):
        return None
    y = _num(profile.get("yield"))
    nxt = None
    for ev in profile_events(profile, today):
        pay, ex = _d(ev.get("pay_date")), _d(ev.get("ex_date"))
        if pay is None or pay < today:
            continue
        if ev.get("ex_passed") and held_since and ex and held_since >= ex:
            continue   # bought on/after the ex-date: this payment isn't theirs
        nxt = pay if nxt is None or pay < nxt else nxt
    if y is None and nxt is None:
        return None
    return {"yield_pct": round(y * 100, 2) if y is not None else None,
            "next_pay_date": nxt.isoformat() if nxt else None}
