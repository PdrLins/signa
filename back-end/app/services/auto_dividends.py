"""Dividends logged automatically (migration 032). No AI.

Most people only enter holdings, so their "received" income history (the
dividend summary for a past year, the monthly recap, the weekly digest) stays
empty. Every evening this job records each dividend a holding paid as a
`dividend` transaction with source "auto" ("estimated"):

  amount   shares held before the ex-date x the amount per share (gross,
           before withholding tax), in the listing's currency
  date     the pay date: the ex-date + the stock's usual ex -> pay gap
           (dividend_calendar._pay_offset), or DEFAULT_PAY_GAP_DAYS
  shares   from the user's buy/sell transactions when there are any for that
           stock and account, else the holding's shares (only when the
           holding existed before the ex-date: nothing is back-filled)

It never duplicates a real record: a manual or imported dividend for the same
stock within DEDUPE_DAYS of the pay date wins, and an estimate that a real
record later matches is removed. The user can edit an estimate (it becomes a
normal "manual" transaction) or delete it (it's remembered in
auto_dividend_dismissed and never re-created). user_settings.auto_dividends =
false stops new estimates. Payments older than LOOKBACK_DAYS are never added.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from loguru import logger

MIGRATION = "032_auto_dividends_fixed_income.sql"
SOURCE = "auto"
LOOKBACK_DAYS = 45
DEDUPE_DAYS = 15
DEFAULT_PAY_GAP_DAYS = 21
NOTE = "Estimated by Signa from the dividend history (before tax). Edit or delete it if it differs."
NOTE_PT = "Estimado pelo Signa a partir do histórico de dividendos (antes do imposto). Edite ou apague se for diferente."
NOTES = {NOTE, NOTE_PT}


def note_for(lang: str | None) -> str:
    return NOTE_PT if lang == "pt" else NOTE


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def _d(v: Any) -> date | None:
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None


def auto_ref(account_id: Any, symbol: str, ex_date: date) -> str:
    return f"auto:{account_id or '-'}:{symbol.upper()}:{ex_date.isoformat()}"


def shares_before(ex_date: date, holding: dict, trades: list[dict]) -> float:
    """Shares held at the close before the ex-date. Pure."""
    if trades:
        n = 0.0
        for t in sorted(trades, key=lambda t: str(t.get("trade_date"))):
            d = _d(t.get("trade_date"))
            if d is None or d >= ex_date:
                continue
            q = abs(_f(t.get("quantity")) or 0.0)
            if t.get("type") == "buy":
                n += q
            elif t.get("type") == "sell":
                n = max(0.0, n - q)
            elif t.get("type") == "split" and q > 0:
                n *= q
        return n
    created = _d(holding.get("created_at"))
    if created is None or created >= ex_date:   # added after the ex-date: no back-fill
        return 0.0
    return _f(holding.get("shares")) or 0.0


def plan(holdings: list[dict], transactions: list[dict], profiles: dict[str, dict | None], today: date,
         dismissed: set[str], lang: str = "en") -> tuple[list[dict], list[str]]:
    """(rows to insert, ids of estimates to remove because a real record now
    matches). Pure."""
    from app.services.dividend_calendar import _pay_offset
    from app.services.holdings_service import holding_currency

    autos = {t.get("auto_ref"): t for t in transactions if t.get("source") == SOURCE and t.get("auto_ref")}
    known_refs = {t.get("auto_ref") for t in transactions if t.get("auto_ref")}
    real = [t for t in transactions if t.get("type") == "dividend" and t.get("source") != SOURCE]
    trades: dict[tuple, list[dict]] = defaultdict(list)
    for t in transactions:
        if t.get("type") in ("buy", "sell", "split") and t.get("symbol"):
            trades[(str(t.get("account_id") or ""), str(t["symbol"]).upper())].append(t)

    def real_near(symbol: str, account: str, d: date) -> bool:
        for t in real:
            td = _d(t.get("trade_date"))
            if (str(t.get("symbol") or "").upper() == symbol and td and abs((td - d).days) <= DEDUPE_DAYS
                    and (not t.get("account_id") or not account or str(t.get("account_id")) == account)):
                return True
        return False

    remove = [str(t["id"]) for ref, t in autos.items()
              if t.get("id") and real_near(str(t.get("symbol") or "").upper(), str(t.get("account_id") or ""),
                                           _d(t.get("trade_date")) or today)]
    rows: list[dict] = []
    for h in holdings:
        sym = str(h.get("symbol") or "").upper()
        prof = profiles.get(sym) or {}
        if not sym or not prof.get("pays_dividend", True):
            continue
        account = str(h.get("account_id") or "")
        gap = _pay_offset(prof) or DEFAULT_PAY_GAP_DAYS
        for p in prof.get("last_payments") or []:
            ex, per_share = _d(p.get("ex_date")), _f(p.get("amount"))
            if not ex or not per_share or per_share <= 0:
                continue
            pay = ex + timedelta(days=gap)
            if not (today - timedelta(days=LOOKBACK_DAYS) <= pay <= today):
                continue
            ref = auto_ref(h.get("account_id"), sym, ex)
            if ref in known_refs or ref in dismissed or real_near(sym, account, pay):
                continue
            shares = shares_before(ex, h, trades.get((account, sym), []))
            if shares <= 0:
                continue
            rows.append({
                "account_id": h.get("account_id"), "symbol": sym, "type": "dividend",
                "trade_date": pay.isoformat(), "quantity": round(shares, 8), "price": round(per_share, 6),
                "amount": round(shares * per_share, 2),
                "currency": str(prof.get("currency") or holding_currency(h)).upper(),
                "fee": 0, "note": note_for(lang), "source": SOURCE, "auto_ref": ref, "import_batch_id": None,
            })
            known_refs.add(ref)
    return rows, remove


async def run(today: date | None = None) -> dict:
    """Evening job. Never raises per user."""
    from app.core.api_errors import is_missing_schema
    from app.core.executors import in_job_pool
    from app.db import queries
    from app.services import dividends
    from app.services.dividend_calendar import fetch_profiles

    today = today or dividends.today_et()
    try:
        holdings = await in_job_pool(queries.get_all_holdings)
        off = await in_job_pool(queries.auto_dividends_off_users)
        pending = await in_job_pool(queries.pending_deletion_ids)
    except Exception as e:
        if is_missing_schema(e):
            return {"status": "migration_required"}
        logger.warning(f"auto dividends: holdings unavailable ({type(e).__name__})")
        return {"status": "failed"}
    by_user: dict[str, list[dict]] = defaultdict(list)
    for h in holdings:
        uid = str(h.get("user_id"))
        if uid not in off and uid not in pending and (_f(h.get("shares")) or 0) > 0:
            by_user[uid].append(h)
    symbols = sorted({str(h.get("symbol") or "").upper() for hs in by_user.values() for h in hs if h.get("symbol")})
    profiles = await fetch_profiles(symbols) if symbols else {}
    added = removed = failed = 0
    for uid, hs in by_user.items():
        try:
            txs = await in_job_pool(queries.get_all_transactions, uid)
            dismissed = await in_job_pool(queries.get_dismissed_auto_refs, uid)
            from app.services.telegram_notify import user_language
            lang = await in_job_pool(user_language, uid)
            rows, remove = plan(hs, txs, profiles, today, dismissed, lang)
            if rows:
                await in_job_pool(queries.insert_transactions, uid, rows)
                added += len(rows)
            for tx_id in remove:
                await in_job_pool(queries.delete_transaction, tx_id, uid)
                removed += 1
            if rows or remove:
                from app.core import user_cache
                user_cache.invalidate(uid)
        except Exception as e:
            failed += 1
            logger.warning(f"auto dividends: one user failed ({type(e).__name__})")
    return {"status": "ok", "users": len(by_user), "added": added, "removed": removed, "failed": failed}
