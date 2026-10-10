"""Monthly recap: how the portfolio did last month (no AI).

  value        start (last close before the month) -> end (last close of the
               month) from the daily history (snapshots, else estimated from
               current shares x closes, like /portfolio/history); change abs/pct
               includes deposits/withdrawals (it's "how much the value moved")
  dividends    dividend transactions dated in the month (home currency) when
               the user records transactions; null otherwise
  movers       best and worst held symbols by price return over the month
  next month   expected dividends dated in the following month (calendar)

  return_pct   the month's return without deposits/withdrawals (`period_return`):
               with transactions, Modified Dietz like /portfolio/performance (dividends
               added back on the trades basis); without, the price return of the
               holdings (today's shares x closes). null without a start value or when
               closes cover under half the holdings' value.
  benchmark    the user's Performance benchmark (compare_index) over the same dates

Recap = {"month": "2026-09", "currency", "start_value" | null, "end_value" | null,
         "change": {"abs" | null, "pct" | null},
         "return_pct": float | null, "benchmark": str | null, "benchmark_symbol": str | null,
         "benchmark_return_pct": float | null,
         "dividends_received": float | null, "dividend_payments": int,
         "best": [{"symbol", "return_pct"}], "worst": [{"symbol", "return_pct"}],   # up to 3 each
         "next_month": {"month": "2026-10", "expected": float | null, "payments": int},
         "estimated": bool}
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from app.core.cache import TTLCache
from app.services import portfolio_context as pc
from app.services import portfolio_performance as perf

MOVERS = 3
EN_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
             "October", "November", "December"]
PT_MONTHS = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro",
             "Outubro", "Novembro", "Dezembro"]


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def month_bounds(month: str | None, today: date) -> tuple[date, date]:
    """(first day, last day) of `month` (YYYY-MM); default = the previous month. 422 on bad input."""
    from app.core.api_errors import api_error

    if month is None:
        last = today.replace(day=1) - timedelta(days=1)
        return last.replace(day=1), last
    try:
        y, m = (int(x) for x in month.split("-"))
        first = date(y, m, 1)
    except (ValueError, TypeError):
        raise api_error("invalid_month", "month must be YYYY-MM.", 422)
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    if first > today:
        raise api_error("invalid_month", "That month hasn't started yet.", 422)
    return first, nxt - timedelta(days=1)


def value_at(points: list[tuple[date, float]], d: date) -> float | None:
    """Last value on or before d. Pure."""
    best = None
    for pd_, v in points:
        if pd_ <= d:
            best = v
        else:
            break
    return best


def symbol_returns(closes: dict, first: date, last: date) -> list[tuple[str, float]]:
    out = []
    for sym, s in (closes or {}).items():
        if s is None or not len(s):
            continue
        idx = [i.date() if hasattr(i, "date") else i for i in s.index]
        before = [v for d, v in zip(idx, s.values) if d < first]
        within = [v for d, v in zip(idx, s.values) if first <= d <= last]
        a, b = (_f(before[-1]) if before else None), (_f(within[-1]) if within else None)
        if a and b:
            out.append((sym, round((b / a - 1) * 100, 2)))
    return sorted(out, key=lambda x: -x[1])


MIN_PRICE_COVERAGE = 0.5


def period_return(scope: dict, live: dict, points: list, closes: dict, first: date, last: date) -> float | None:
    """Return (PERCENT) from the close before `first` to `last`, without the
    effect of money added or taken out (see the module docstring). Pure."""
    home, usdcad = scope["home_currency"], scope.get("usdcad")
    txs = scope.get("transactions") or []
    base = first - timedelta(days=1)
    if txs:
        start, end = value_at(points, base), value_at(points, last)
        if not start or start <= 0 or end is None:
            return None
        fl = perf.external_flows(txs, base, last, home, usdcad)
        extra = fl["dividends"] if fl["basis"] == "trades" else 0.0
        r = perf.modified_dietz(start, end, fl["flows"], base, last, extra)["return_pct"]
        return round(r, 2) if r is not None else None
    a = b = covered = total = 0.0
    for p in live["merged"]:
        fx = perf._fx(p["currency"], home, usdcad) if p.get("currency") else None
        if not (p.get("shares") and fx):
            continue
        total += p.get("value_home") or 0.0
        pts = perf._closes_points(closes.get(p["symbol"]), base, last)
        if len(pts) < 2:
            continue
        a += p["shares"] * pts[0][1] * fx
        b += p["shares"] * pts[-1][1] * fx
        covered += p.get("value_home") or 0.0
    if a <= 0 or (total and covered < MIN_PRICE_COVERAGE * total):
        return None
    return round((b / a - 1) * 100, 2)


def benchmark_return(closes: dict, symbol: str | None, first: date, last: date) -> float | None:
    if not symbol:
        return None
    pts = perf._closes_points(closes.get(symbol), first - timedelta(days=1), last)
    return round((pts[-1][1] / pts[0][1] - 1) * 100, 2) if len(pts) >= 2 and pts[0][1] else None


def benchmark_name(symbol: str | None) -> str | None:
    if not symbol:
        return None
    from app.services.profile_service import COMPARE_INDEXES
    return COMPARE_INDEXES.get(symbol)


def range_for(first: date, today: date) -> str:
    """The shortest history range whose start is before `first`."""
    span = (today - first).days
    return "3M" if span <= 85 else "1Y" if span <= 360 else "5Y" if span <= 5 * 365 - 5 else "ALL"


def dividends_in(transactions: list[dict], first: date, last: date, home: str, usdcad: float | None
                 ) -> tuple[float | None, int]:
    total, n, _bad = _dividends_in(transactions, first, last, home, usdcad)
    return total, n


def _dividends_in(transactions: list[dict], first: date, last: date, home: str, usdcad: float | None
                  ) -> tuple[float | None, int, int]:
    """(total in home currency or None without transactions, payments, unconverted). Pure."""
    total, n, bad, any_tx = 0.0, 0, 0, bool(transactions)
    for t in transactions or []:
        if t.get("type") != "dividend":
            continue
        d = perf._d(t.get("trade_date"))
        if not d or not (first <= d <= last):
            continue
        amt = pc.to_home(_f(t.get("amount")), str(t.get("currency") or home), home, usdcad)
        n += 1
        if amt is None:
            bad += 1
        else:
            total += amt
    return (round(total, 2) if any_tx else None), n, bad


def build(scope: dict, first: date, last: date, today: date, next_events: list[dict]) -> dict:
    home, usdcad = scope["home_currency"], scope.get("usdcad")
    live = perf._live(scope)
    bench = scope.get("compare_index")
    daily = perf._daily(scope, live, range_for(first, today), today, [bench] if bench else [])
    points = sorted(daily["points"])
    start = value_at(points, first - timedelta(days=1))
    end = value_at(points, last)
    txs = scope.get("transactions") or []
    net_deposits = None
    if txs and start is not None and end is not None:
        # money added or taken out during the month is not a gain or a loss
        fl = perf.external_flows(txs, first - timedelta(days=1), last, home, usdcad)
        extra = fl["dividends"] if fl["basis"] == "trades" else 0.0
        md = perf.modified_dietz(start, end, fl["flows"], first - timedelta(days=1), last, extra)
        change_abs = round(md["gain"], 2)
        change_pct = round(md["return_pct"], 2) if md["return_pct"] is not None else None
        net_deposits = round(md["net_flows"], 2)
    else:
        change_abs = round(end - start, 2) if start is not None and end is not None else None
        change_pct = round((end / start - 1) * 100, 2) if start and end is not None else None
    held = {p["symbol"] for p in live["merged"]}
    rets = [r for r in symbol_returns(daily["closes"], first, last) if r[0] in held]
    received, payments, unconverted = _dividends_in(txs, first, last, home, usdcad)
    nm_first = last + timedelta(days=1)
    nm_last = date(nm_first.year + (nm_first.month == 12), nm_first.month % 12 + 1, 1) - timedelta(days=1)
    nxt = [e for e in next_events if e.get("owned") and nm_first.isoformat() <= str(e.get("date")) <= nm_last.isoformat()]
    expected = 0.0
    for e in nxt:
        amt = pc.to_home(_f(e.get("expected_cash")), str(e.get("currency") or home), home, usdcad)
        if amt is None and _f(e.get("expected_cash")):
            unconverted += 1
        expected += amt or 0.0
    return {
        "month": first.strftime("%Y-%m"), "currency": home,
        "start_value": round(start, 2) if start is not None else None,
        "end_value": round(end, 2) if end is not None else None,
        "change": {"abs": change_abs, "pct": change_pct},
        # the month's return without deposits/withdrawals (safe to share as a percentage)
        "return_pct": period_return(scope, live, points, daily["closes"], first, last),
        "benchmark": benchmark_name(bench), "benchmark_symbol": bench,
        "benchmark_return_pct": benchmark_return(daily["closes"], bench, first, last),
        # money added (or withdrawn, negative) during the month, from transactions; not counted
        # as a gain. null without transactions (then the change is simply end - start).
        "net_deposits": net_deposits,
        "unconverted": unconverted,   # amounts left out because a currency couldn't be converted
        "dividends_received": received, "dividend_payments": payments,
        "best": [{"symbol": s, "return_pct": r} for s, r in rets[:MOVERS] if r > 0],
        "worst": [{"symbol": s, "return_pct": r} for s, r in reversed(rets[-MOVERS:]) if r < 0],
        "next_month": {"month": nm_first.strftime("%Y-%m"), "expected": round(expected, 2) if nxt else None,
                       "payments": len(nxt)},
        "estimated": daily["reason"] is not None,
    }


# ============================================================
# Year in review (GET /portfolio/recap/year)
# ============================================================

YEAR_TTL_S = 300
_year_cache = TTLCache(max_size=2000, default_ttl=YEAR_TTL_S)


def year_bounds(year: int | None, today: date) -> tuple[date, date]:
    """(Jan 1, Dec 31 or today) of `year`; default = this year. 422 invalid_year."""
    from app.core.api_errors import api_error

    y = today.year if year is None else year
    if y > today.year or y < 1990:
        raise api_error("invalid_year", "year must be this year or an earlier one.", 422)
    return date(y, 1, 1), min(date(y, 12, 31), today)


def _first_acquired(scope: dict) -> dict[str, date]:
    """symbol -> first time it was acquired: the earliest buy transaction, else
    (no buys recorded) the holding's created date. Pure."""
    out: dict[str, date] = {}
    for t in scope.get("transactions") or []:
        d = perf._d(t.get("trade_date"))
        sym = str(t.get("symbol") or "").upper()
        if t.get("type") == "buy" and sym and d and (sym not in out or d < out[sym]):
            out[sym] = d
    for h in scope.get("holdings") or []:
        sym = str(h.get("symbol") or "").upper()
        d = perf._d(str(h.get("created_at") or "")[:10])
        if sym and d and sym not in out:
            out[sym] = d
    return out


def _avg_buy_price(transactions: list[dict], symbol: str, first: date, last: date) -> float | None:
    qty = cost = 0.0
    for t in transactions or []:
        d = perf._d(t.get("trade_date"))
        if t.get("type") != "buy" or str(t.get("symbol") or "").upper() != symbol or not d or not first <= d <= last:
            continue
        q, px = abs(_f(t.get("quantity")) or 0.0), _f(t.get("price"))
        if q and px:
            qty, cost = qty + q, cost + q * px
    return cost / qty if qty else None


def year_symbol_returns(scope: dict, closes: dict, held: set[str], first: date, last: date) -> list[tuple[str, float]]:
    """Price return of each held symbol over the year, or since its first buy
    when it was bought during the year (from the average buy price). Pure."""
    acquired = _first_acquired(scope)
    txs = scope.get("transactions") or []
    out = []
    for sym in held:
        pts = perf._closes_points(closes.get(sym), first - timedelta(days=1), last)
        if not pts:
            continue
        end = pts[-1][1]
        start = pts[0][1] if len(pts) >= 2 else None
        got = acquired.get(sym)
        if got and first <= got <= last:
            start = _avg_buy_price(txs, sym, first, last) or start
        if start and end:
            out.append((sym, round((end / start - 1) * 100, 2)))
    return sorted(out, key=lambda x: -x[1])


def _net_deposits(transactions: list[dict], first: date, last: date, home: str, usdcad: float | None) -> float | None:
    """Deposits - withdrawals in [first, last], home currency; None when the user
    records no deposits or withdrawals at all. Pure."""
    rows = [t for t in transactions or [] if t.get("type") in ("deposit", "withdrawal")]
    if not rows:
        return None
    net = 0.0
    for t in rows:
        d = perf._d(t.get("trade_date"))
        if not d or not first <= d <= last:
            continue
        amt = pc.to_home(abs(_f(t.get("amount")) or 0.0), str(t.get("currency") or home), home, usdcad)
        if amt is not None:
            net += amt if t["type"] == "deposit" else -amt
    return round(net, 2)


def build_year(scope: dict, first: date, last: date, today: date) -> dict:
    """Year in review. Pure apart from the shared daily series / closes."""
    home, usdcad = scope["home_currency"], scope.get("usdcad")
    live = perf._live(scope)
    bench = scope.get("compare_index")
    daily = perf._daily(scope, live, range_for(first, today), today, [bench] if bench else [])
    points, closes = sorted(daily["points"]), daily["closes"]
    start, end = value_at(points, first - timedelta(days=1)), value_at(points, last)
    txs = scope.get("transactions") or []
    months = []
    m = first
    while m <= last:
        m_last = min(date(m.year + (m.month == 12), m.month % 12 + 1, 1) - timedelta(days=1), last)
        r = period_return(scope, live, points, closes, m, m_last)
        if r is not None:
            months.append({"month": m.strftime("%Y-%m"), "return_pct": r})
        m = m_last + timedelta(days=1)
    held = {p["symbol"] for p in live["merged"]}
    rets = year_symbol_returns(scope, closes, held, first, last)
    received, payments, _bad = _dividends_in(txs, first, last, home, usdcad)
    acquired = _first_acquired(scope)
    return {
        "year": first.year, "currency": home,
        "start": first.isoformat(), "end": last.isoformat(),
        "return_pct": period_return(scope, live, points, closes, first, last),
        "benchmark": benchmark_name(bench), "benchmark_symbol": bench,
        "benchmark_return_pct": benchmark_return(closes, bench, first, last),
        "start_value": round(start, 2) if start is not None else None,
        "end_value": round(end, 2) if end is not None else None,
        "net_deposits": _net_deposits(txs, first, last, home, usdcad),
        "dividends_received": received, "dividend_payments": payments,
        "best_month": max(months, key=lambda x: x["return_pct"]) if months else None,
        "worst_month": min(months, key=lambda x: x["return_pct"]) if months else None,
        "months": months,
        "best": [{"symbol": s, "return_pct": r} for s, r in rets[:MOVERS] if r > 0],
        "worst": [{"symbol": s, "return_pct": r} for s, r in reversed(rets[-MOVERS:]) if r < 0],
        "holdings_count": len(held),
        "new_holdings": sum(1 for d in acquired.values() if first <= d <= last),
        "estimated": daily["reason"] is not None,
    }


def year_cached(scope: dict, first: date, last: date, today: date) -> dict:
    """build_year cached YEAR_TTL_S per user, scope and year (a user's write
    starts a new entry: app/core/user_cache.py generation)."""
    from app.core import user_cache

    uid = scope.get("user_id")
    acc = scope.get("account_ids")
    key = "|".join(map(str, (uid, ",".join(sorted(map(str, acc))) if acc is not None else "*", first.year,
                             user_cache.generation(uid) if uid else 0, today.isoformat())))
    hit = _year_cache.get(key)
    if hit is not None:
        return hit
    body = build_year(scope, first, last, today)
    if uid:
        _year_cache.set(key, body)
    return body


def push_text(recap: dict, money, lang: str = "en") -> str:
    """One-line push: "September: +3.2% (+C$1,240.00) · C$45.00 in dividends"
    / "Setembro: +3,2% (+R$ 1.240,00) · R$ 45,00 em dividendos". Pure."""
    y, m = (int(x) for x in recap["month"].split("-"))
    pt = lang == "pt"
    month = (PT_MONTHS if pt else EN_MONTHS)[m - 1]
    parts = [f"{month}:"]
    ch = recap["change"]
    if ch["pct"] is not None:
        sign = "+" if ch["pct"] >= 0 else "-"
        p = f"{abs(ch['pct']):.1f}".replace(".", "," if pt else ".")
        parts.append(f"{sign}{p}% ({'+' if ch['abs'] >= 0 else '-'}{money(abs(ch['abs']), recap['currency'], lang)})")
    if recap.get("dividends_received"):
        word = "em dividendos" if pt else "in dividends"
        parts.append(f"· {money(recap['dividends_received'], recap['currency'], lang)} {word}")
    if len(parts) > 1:
        return " ".join(parts)
    return f"Resumo de {month.lower()} pronto." if pt else f"{month} recap is ready."


def ready_text(recap: dict, lang: str = "en") -> str:
    """No amounts (privacy.hide_amounts): "September recap is ready". Pure."""
    m = int(recap["month"].split("-")[1])
    month = (PT_MONTHS if lang == "pt" else EN_MONTHS)[m - 1]
    return f"Seu resumo de {month.lower()} está pronto." if lang == "pt" else f"Your {month} recap is ready."


NEXT_EVENTS_TIMEOUT_S = 6.0


async def next_month_events(scope: dict) -> list[dict]:
    """Owned dividend events of the next ~2 months (calendar); [] on timeout."""
    import asyncio

    from loguru import logger

    from app.services import dividend_calendar

    if not scope["holdings"]:
        return []
    try:
        cal = await asyncio.wait_for(
            dividend_calendar.get_calendar(scope["holdings"], None, 2, scope.get("usdcad"), home=scope["home_currency"]), NEXT_EVENTS_TIMEOUT_S)
        return cal.get("events") or []
    except Exception as e:
        logger.debug(f"recap: dividend events unavailable ({e!r})")
        return []


async def run_monthly_push(today: date | None = None) -> dict:
    """1st of the month: push last month's recap to every user with the app. Never raises."""
    import asyncio

    from loguru import logger

    from app.core.access import get_user_access
    from app.services import notification_prefs, portfolio_context, push
    from app.services.telegram_notify import money, user_language

    today = today or perf.today_et()
    first, last = month_bounds(None, today)
    try:
        devices = await asyncio.to_thread(push.active_devices)
    except Exception as e:
        logger.warning(f"recap: devices unavailable ({type(e).__name__})")
        return {"status": "failed"}
    users = sorted({str(d["user_id"]) for d in devices})
    from app.core.executors import in_job_pool
    from app.services.telegram_notify import DELIVERY_CONCURRENCY
    sem = asyncio.Semaphore(DELIVERY_CONCURRENCY)

    month_key = f"push:recap:{first.strftime('%Y-%m')}"

    async def one(uid: str) -> int:
        async with sem:
            try:
                from app.db import queries
                if await in_job_pool(queries.get_delivered_keys, uid, [month_key]):
                    return 0   # already sent (a catch-up or a restart never sends it twice)
                user = {"user_id": uid, "access_level": (await in_job_pool(get_user_access, uid))["level"]}
                scope = await in_job_pool(portfolio_context.load_scope, user, None, None, True)
                if not scope["holdings"]:
                    return 0
                r = await in_job_pool(build, scope, first, last, today, await next_month_events(scope))
                lang = await in_job_pool(user_language, uid)
                prefs = (await in_job_pool(notification_prefs.get_prefs, uid))["prefs"]
                text = (ready_text(r, lang) if notification_prefs.hide_amounts(prefs)
                        else push_text(r, money, lang))
                if not await push.notify_user(uid, "Signa", text, {"kind": "monthly_recap", "month": r["month"]}):
                    return 0
                await in_job_pool(queries.insert_deliveries, uid, [("monthly_recap", month_key)])
                return 1
            except Exception as e:
                logger.warning(f"recap: {uid} failed: {type(e).__name__}: {e}")
                return 0
    sent = sum(await asyncio.gather(*(one(u) for u in users)))
    return {"status": "ok", "users": len(users), "sent": sent, "month": first.strftime("%Y-%m")}
