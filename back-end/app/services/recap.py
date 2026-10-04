"""Monthly recap: how the portfolio did last month (no AI).

  value        start (last close before the month) -> end (last close of the
               month) from the daily history (snapshots, else estimated from
               current shares x closes, like /portfolio/history); change abs/pct
               includes deposits/withdrawals (it's "how much the value moved")
  dividends    dividend transactions dated in the month (home currency) when
               the user records transactions; null otherwise
  movers       best and worst held symbols by price return over the month
  next month   expected dividends dated in the following month (calendar)

Recap = {"month": "2026-09", "currency", "start_value" | null, "end_value" | null,
         "change": {"abs" | null, "pct" | null},
         "dividends_received": float | null, "dividend_payments": int,
         "best": [{"symbol", "return_pct"}], "worst": [{"symbol", "return_pct"}],   # up to 3 each
         "next_month": {"month": "2026-10", "expected": float | null, "payments": int},
         "estimated": bool}
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

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


def dividends_in(transactions: list[dict], first: date, last: date, home: str, usdcad: float | None
                 ) -> tuple[float | None, int]:
    total, n, any_tx = 0.0, 0, bool(transactions)
    for t in transactions or []:
        if t.get("type") != "dividend":
            continue
        d = perf._d(t.get("trade_date"))
        if not d or not (first <= d <= last):
            continue
        amt = pc.to_home(_f(t.get("amount")), str(t.get("currency") or home), home, usdcad)
        if amt is not None:
            total += amt
            n += 1
    return (round(total, 2) if any_tx else None), n


def build(scope: dict, first: date, last: date, today: date, next_events: list[dict]) -> dict:
    home, usdcad = scope["home_currency"], scope.get("usdcad")
    live = perf._live(scope)
    span = (today - first).days
    rng = "3M" if span <= 85 else "1Y" if span <= 360 else "5Y"
    daily = perf._daily(scope, live, rng, today)
    points = sorted(daily["points"])
    start = value_at(points, first - timedelta(days=1))
    end = value_at(points, last)
    change_abs = round(end - start, 2) if start is not None and end is not None else None
    change_pct = round((end / start - 1) * 100, 2) if start and end is not None else None
    held = {p["symbol"] for p in live["merged"]}
    rets = [r for r in symbol_returns(daily["closes"], first, last) if r[0] in held]
    received, payments = dividends_in(scope.get("transactions") or [], first, last, home, usdcad)
    nm_first = last + timedelta(days=1)
    nm_last = date(nm_first.year + (nm_first.month == 12), nm_first.month % 12 + 1, 1) - timedelta(days=1)
    nxt = [e for e in next_events if e.get("owned") and nm_first.isoformat() <= str(e.get("date")) <= nm_last.isoformat()]
    expected = 0.0
    for e in nxt:
        amt = pc.to_home(_f(e.get("expected_cash")), str(e.get("currency") or home), home, usdcad)
        expected += amt or 0.0
    return {
        "month": first.strftime("%Y-%m"), "currency": home,
        "start_value": round(start, 2) if start is not None else None,
        "end_value": round(end, 2) if end is not None else None,
        "change": {"abs": change_abs, "pct": change_pct},
        "dividends_received": received, "dividend_payments": payments,
        "best": [{"symbol": s, "return_pct": r} for s, r in rets[:MOVERS] if r > 0],
        "worst": [{"symbol": s, "return_pct": r} for s, r in reversed(rets[-MOVERS:]) if r < 0],
        "next_month": {"month": nm_first.strftime("%Y-%m"), "expected": round(expected, 2) if nxt else None,
                       "payments": len(nxt)},
        "estimated": daily["reason"] is not None,
    }


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
    from app.services import portfolio_context, push
    from app.services.telegram_notify import money, user_language

    today = today or perf.today_et()
    first, last = month_bounds(None, today)
    try:
        devices = await asyncio.to_thread(push.active_devices)
    except Exception as e:
        logger.warning(f"recap: devices unavailable ({type(e).__name__})")
        return {"status": "failed"}
    users = sorted({str(d["user_id"]) for d in devices})
    sent = 0
    for uid in users:
        try:
            user = {"user_id": uid, "access_level": get_user_access(uid)["level"]}
            scope = await asyncio.to_thread(portfolio_context.load_scope, user, None, None, True)
            if not scope["holdings"]:
                continue
            r = await asyncio.to_thread(build, scope, first, last, today, await next_month_events(scope))
            lang = await asyncio.to_thread(user_language, uid)
            sent += 1 if await push.notify_user(uid, "Signa", push_text(r, money, lang),
                                                {"kind": "monthly_recap", "month": r["month"]}) else 0
        except Exception as e:
            logger.warning(f"recap: {uid} failed: {type(e).__name__}: {e}")
    return {"status": "ok", "users": len(users), "sent": sent, "month": first.strftime("%Y-%m")}
