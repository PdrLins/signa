"""Daily portfolio snapshots (migration 013, table portfolio_snapshots). No AI.

After the close (scheduler, weekdays 16:30 ET) every user with holdings or
accounts gets one row per account plus one whole-portfolio row
(account_id NULL), all in the user's home currency:

  market_value  sum(shares x price) of priced holdings (quotes table,
                falling back to the monitor's last price)
  cash          accounts.cash_balance
  cost_basis    sum(shares x avg_cost) where avg_cost is known
  unconverted   amounts that could not be converted: only USD<->CAD is
                converted today (TODO: other currencies need an FX source),
                everything else is left out of the sums and listed here.

Idempotent: re-running a date replaces that user's rows for the date.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from zoneinfo import ZoneInfo

from loguru import logger

from app.core.market_calendar import is_market_open
from app.services.holdings_service import holding_currency

_ET = ZoneInfo("America/New_York")


def _f(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def convert(amount: float | None, from_ccy: str | None, to_ccy: str, usdcad: float | None) -> float | None:
    """USD/CAD only (usdcad = CAD per 1 USD). None = can't convert."""
    if amount is None:
        return None
    f, t = (from_ccy or "").upper(), (to_ccy or "").upper()
    if f == t:
        return amount
    if usdcad and {f, t} == {"USD", "CAD"}:
        return amount * usdcad if f == "USD" else amount / usdcad
    # TODO: other currencies (EUR, GBP, BRL ...) need an FX source.
    return None


def _bucket() -> dict:
    return {"market_value": 0.0, "cash": 0.0, "cost_basis": 0.0, "unconverted": []}


def compute_snapshot_rows(holdings: list[dict], accounts: list[dict], quotes: dict[str, dict],
                          home_currency: str, usdcad: float | None) -> list[dict]:
    """One user's rows (without user_id / snapshot_date). Pure."""
    home = (home_currency or "CAD").upper()
    total = _bucket()
    per: dict[str, dict] = {str(a["id"]): _bucket() for a in accounts}

    def targets(account_id) -> list[dict]:
        b = per.get(str(account_id)) if account_id else None
        return [total, b] if b is not None else [total]

    for h in holdings:
        shares = _f(h.get("shares"))
        if not shares or shares <= 0:
            continue
        sym = str(h.get("symbol") or "").upper()
        q = quotes.get(sym) or {}
        price = _f(q.get("price")) or _f((h.get("holding_status") or {}).get("price"))
        if not price:
            continue
        ccy = (q.get("currency") or holding_currency(h)).upper()
        mv = shares * price
        cost = _f(h.get("avg_cost"))
        mv_home = convert(mv, ccy, home, usdcad)
        for b in targets(h.get("account_id")):
            if mv_home is None:
                b["unconverted"].append({"symbol": sym, "currency": ccy, "market_value": round(mv, 2)})
                continue
            b["market_value"] += mv_home
            if cost:
                b["cost_basis"] += convert(shares * cost, ccy, home, usdcad) or 0.0

    for a in accounts:
        cash = _f(a.get("cash_balance")) or 0.0
        if not cash:
            continue
        cash_home = convert(cash, a.get("currency") or home, home, usdcad)
        for b in targets(a.get("id")):
            if cash_home is None:
                b["unconverted"].append({"account_id": str(a["id"]), "currency": a.get("currency"),
                                         "cash": round(cash, 2)})
            else:
                b["cash"] += cash_home

    def row(account_id, b: dict) -> dict:
        return {"account_id": account_id, "market_value": round(b["market_value"], 2),
                "cash": round(b["cash"], 2), "cost_basis": round(b["cost_basis"], 2),
                "currency": home, "unconverted": b["unconverted"] or None}

    return [row(None, total)] + [row(aid, b) for aid, b in per.items()]


def run_snapshots(on_date: date | None = None) -> dict:
    """Scheduler entry (sync — run in a thread). Skips days both TSX and NYSE are closed."""
    from app.db import queries
    from app.services.price_cache import get_usdcad_rate
    from app.services.quotes import get_quotes

    d = on_date or datetime.now(_ET).date()
    if not (is_market_open("NYSE", d) or is_market_open("TSX", d)):
        return {"status": "market_closed", "date": d.isoformat()}
    try:
        holdings = queries.get_all_holdings()
        accounts = queries.get_all_accounts()
    except Exception as e:
        logger.warning(f"snapshots: portfolio tables unavailable (apply migration 013?): {e}")
        return {"status": "unavailable"}
    by_user_h: dict[str, list[dict]] = {}
    by_user_a: dict[str, list[dict]] = {}
    for h in holdings:
        by_user_h.setdefault(str(h.get("user_id")), []).append(h)
    for a in accounts:
        by_user_a.setdefault(str(a.get("user_id")), []).append(a)
    users = sorted(set(by_user_h) | set(by_user_a))
    if not users:
        return {"status": "ok", "users": 0, "rows": 0}
    try:
        currencies = queries.get_user_home_currencies(users)
    except Exception as e:
        logger.warning(f"snapshots: home currencies unavailable, using CAD: {e}")
        currencies = {}
    quotes = get_quotes({str(h.get("symbol") or "").upper() for h in holdings if h.get("symbol")})
    usdcad = get_usdcad_rate()
    written = failed = 0
    for uid in users:
        rows = compute_snapshot_rows(by_user_h.get(uid, []), by_user_a.get(uid, []), quotes,
                                     currencies.get(uid, "CAD"), usdcad)
        try:
            written += queries.replace_portfolio_snapshots(uid, d.isoformat(), rows)
        except Exception as e:
            failed += 1
            logger.warning(f"snapshots: user {uid} failed: {e}")
    logger.info(f"Portfolio snapshots {d}: {len(users)} users, {written} rows, {failed} failed")
    return {"status": "ok", "date": d.isoformat(), "users": len(users), "rows": written, "failed": failed}
