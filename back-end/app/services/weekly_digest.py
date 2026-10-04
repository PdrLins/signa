"""Weekly push digest: "your week" every Sunday 10:00 New York (11:00 in
Brasília, 7:00 in Vancouver). No AI.

  "Your week: +1.2% (+C$540.00) · C$32.00 in dividends · next week: 3 dividends (C$85.00)"
  "Sua semana: +1,2% (+R$ 540,00) · R$ 32,00 em dividendos · próxima semana: 3 dividendos (R$ 85,00)"

  * change: last 7 days of the portfolio value (snapshots, else estimated from
    daily closes). With transactions, money added or withdrawn isn't a gain
    (modified Dietz, as in the monthly recap).
  * dividends received: the ledger's dividend transactions of the week.
  * next week: owned dividend payments expected in the next 7 days.

Who gets it: every user with the app (push device), Free and Premium, unless
notification_prefs.weekly_digest is off. Accounts waiting for deletion and
empty portfolios are skipped. privacy.hide_amounts -> "Your weekly summary is
ready". Deduped per ISO week ("push:weekly:2026-W41"), so a restart or a
catch-up never sends it twice.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.services import portfolio_context as pc
from app.services import portfolio_performance as perf

DAYS = 7
TEXT = {
    "en": {"head": "Your week:", "div": "in dividends", "next": "next week:", "payment": "dividend",
           "payments": "dividends", "ready": "Your weekly summary is ready.", "quiet": "A quiet week."},
    "pt": {"head": "Sua semana:", "div": "em dividendos", "next": "próxima semana:", "payment": "dividendo",
           "payments": "dividendos", "ready": "Seu resumo da semana está pronto.", "quiet": "Uma semana tranquila."},
}


def week_key(today: date) -> str:
    y, w, _ = today.isocalendar()
    return f"push:weekly:{y}-W{w:02d}"


def build(scope: dict, today: date, upcoming: list[dict]) -> dict:
    """{"change": {"abs", "pct"}, "dividends_received", "next_week": {"payments", "expected"}}. Blocking (closes)."""
    from app.services.recap import _dividends_in, value_at

    home, usdcad = scope["home_currency"], scope.get("usdcad")
    live = perf._live(scope)
    first = today - timedelta(days=DAYS)
    daily = perf._daily(scope, live, "1M", today)
    points = sorted(daily["points"])
    start, end = value_at(points, first), value_at(points, today)
    txs = scope.get("transactions") or []
    change_abs = change_pct = None
    if start is not None and end is not None:
        if txs:
            fl = perf.external_flows(txs, first, today, home, usdcad)
            extra = fl["dividends"] if fl["basis"] == "trades" else 0.0
            md = perf.modified_dietz(start, end, fl["flows"], first, today, extra)
            change_abs, change_pct = md["gain"], md["return_pct"]
        else:
            change_abs = end - start
            change_pct = (end / start - 1) * 100 if start else None
    received, _n, _bad = _dividends_in(txs, first + timedelta(days=1), today, home, usdcad)
    nxt = [e for e in upcoming if e.get("owned")
           and today.isoformat() < str(e.get("date")) <= (today + timedelta(days=DAYS)).isoformat()]
    expected = 0.0
    for e in nxt:
        expected += pc.to_home(pc._f(e.get("expected_cash")), str(e.get("currency") or home), home, usdcad) or 0.0
    return {"currency": home,
            "change": {"abs": round(change_abs, 2) if change_abs is not None else None,
                       "pct": round(change_pct, 2) if change_pct is not None else None},
            "dividends_received": received or None,
            "next_week": {"payments": len(nxt), "expected": round(expected, 2) if nxt else None}}


def push_text(d: dict, money, lang: str = "en", hide_amounts: bool = False) -> str:
    """One line for the push. Pure."""
    t = TEXT["pt" if lang == "pt" else "en"]
    if hide_amounts:
        return t["ready"]
    pt = lang == "pt"
    ccy = d["currency"]
    parts = []
    ch = d["change"]
    if ch["pct"] is not None and ch["abs"] is not None:
        sign = "+" if ch["pct"] >= 0 else "-"
        p = f"{abs(ch['pct']):.1f}".replace(".", "," if pt else ".")
        parts.append(f"{t['head']} {sign}{p}% ({'+' if ch['abs'] >= 0 else '-'}{money(abs(ch['abs']), ccy, lang)})")
    if d.get("dividends_received"):
        parts.append(f"{money(d['dividends_received'], ccy, lang)} {t['div']}")
    nw = d["next_week"]
    if nw["payments"]:
        word = t["payment"] if nw["payments"] == 1 else t["payments"]
        amount = f" ({money(nw['expected'], ccy, lang)})" if nw.get("expected") else ""
        parts.append(f"{t['next']} {nw['payments']} {word}{amount}")
    if not parts:
        return t["quiet"]
    if not parts[0].startswith(t["head"]):
        parts[0] = f"{t['head']} {parts[0]}"
    return " · ".join(parts)


async def run(today: date | None = None) -> dict:
    """Sunday job: one push per user with the app. Never raises."""
    import asyncio

    from loguru import logger

    from app.core.access import get_user_access
    from app.core.executors import in_job_pool
    from app.db import queries
    from app.services import notification_prefs, push
    from app.services.recap import next_month_events
    from app.services.telegram_notify import DELIVERY_CONCURRENCY, money, user_language

    today = today or perf.today_et()
    key = week_key(today)
    try:
        devices = await in_job_pool(push.active_devices)
        pending = await in_job_pool(queries.pending_deletion_ids)
    except Exception as e:
        logger.warning(f"weekly digest: devices unavailable ({type(e).__name__})")
        return {"status": "failed"}
    users = sorted({str(d["user_id"]) for d in devices} - pending)
    sem = asyncio.Semaphore(DELIVERY_CONCURRENCY)

    async def one(uid: str) -> int:
        async with sem:
            try:
                prefs = (await in_job_pool(notification_prefs.get_prefs, uid))["prefs"]
                if not (prefs.get("weekly_digest") or {}).get("enabled", True):
                    return 0
                if await in_job_pool(queries.get_delivered_keys, uid, [key]):
                    return 0
                user = {"user_id": uid, "access_level": (await in_job_pool(get_user_access, uid))["level"]}
                scope = await in_job_pool(pc.load_scope, user, None, None, True)
                if not scope["holdings"]:
                    return 0
                d = await in_job_pool(build, scope, today, await next_month_events(scope))
                lang = await in_job_pool(user_language, uid)
                text = push_text(d, money, lang, notification_prefs.hide_amounts(prefs))
                if not await push.notify_user(uid, "Signa", text, {"kind": "weekly_digest"}):
                    return 0
                await in_job_pool(queries.insert_deliveries, uid, [("weekly_digest", key)])
                return 1
            except Exception as e:
                logger.warning(f"weekly digest: one user failed ({type(e).__name__})")
                return 0
    sent = sum(await asyncio.gather(*(one(u) for u in users)))
    return {"status": "ok", "users": len(users), "sent": sent, "week": key}
