"""Forward dividend income forecast + its daily snapshot (migration 014). No AI.

  compute_forecast(holdings, profiles, home, usdcad)   pure
  diff_forecasts(base, now, home)                      pure: "why your income changed"
  run_income_snapshots(on_date)                        scheduler entry (18:00 ET weekdays)

Forecast = for every symbol the user holds (all accounts summed):
shares x the forward annual rate per share (profile["annual_rate"]: Yahoo
dividendRate, else trailing), in the listing currency and converted to the
user's home currency (USD/CAD only; anything else is listed under
`unconverted` and left out of total_home). Non-payers are omitted.

Snapshot row (income_forecast_snapshots): {total_home, currency, usdcad,
per_symbol: {SYM: {shares, annual_rate, currency, annual_native, annual_home}}}.

Diff (base = the stored snapshot, now = today's forecast). Every
component is valued at the BASE FX rate, and FX is the rest, so the
components add up exactly to the change:
  fx              Σ now annual_native x (rate now − rate then)
  raises / cuts   shares_now x (rate_now − rate_then) per symbol held both times
  new_shares      (shares_now − shares_then) x rate_then when shares grew,
                  and whole new symbols (their current income)
  removed_shares  the same when shares fell, and whole removed symbols
"""

from __future__ import annotations

import asyncio
import math
from datetime import date

from loguru import logger

from app.services.holdings_service import holding_currency
from app.services.portfolio_snapshots import convert


def _f(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _r(v, nd=2):
    return round(v, nd) if v is not None and math.isfinite(v) else None


def compute_forecast(holdings: list[dict], profiles: dict[str, dict | None], home: str,
                     usdcad: float | None) -> dict:
    home = (home or "CAD").upper()
    shares: dict[str, float] = {}
    ccys: dict[str, str] = {}
    for h in holdings or []:
        sym = str(h.get("symbol") or "").upper()
        s = _f(h.get("shares"))
        if not sym or not s or s <= 0:
            continue
        shares[sym] = shares.get(sym, 0.0) + s
        ccys.setdefault(sym, holding_currency(h))
    per: dict[str, dict] = {}
    total = 0.0
    unconverted = []
    for sym, s in sorted(shares.items()):
        prof = profiles.get(sym) or {}
        rate = _f(prof.get("annual_rate")) if prof.get("pays_dividend") else None
        if not rate or rate <= 0:
            continue
        ccy = str(prof.get("currency") or ccys[sym]).upper()
        native = s * rate
        home_amt = convert(native, ccy, home, usdcad)
        per[sym] = {"shares": round(s, 8), "annual_rate": round(rate, 6), "currency": ccy,
                    "annual_native": round(native, 4), "annual_home": _r(home_amt, 4)}
        if home_amt is None:
            unconverted.append(sym)
        else:
            total += home_amt
    return {"total_home": round(total, 2), "currency": home, "usdcad": usdcad, "per_symbol": per,
            "unconverted": unconverted}


def diff_forecasts(base: dict, now: dict, home: str) -> dict:
    """{"before_total", "now_total", "change", "components": {...}, "items": [...]}. Pure."""
    home = (home or "CAD").upper()
    fx0, fx1 = _f(base.get("usdcad")), _f(now.get("usdcad"))
    fx0 = fx0 or fx1
    b, n = base.get("per_symbol") or {}, now.get("per_symbol") or {}
    comp = {"fx": 0.0, "raises": 0.0, "cuts": 0.0, "new_shares": 0.0, "removed_shares": 0.0}
    items: list[dict] = []

    def at0(amount, ccy):
        return convert(amount, ccy, home, fx0) or 0.0

    def add(kind: str, key: str, sym: str, amount: float, **detail):
        if abs(amount) < 0.005:
            return
        comp[key] += amount
        items.append({"symbol": sym, "kind": kind, "amount": round(amount, 2), **detail})

    before = sum(at0(_f(v.get("annual_native")) or 0.0, v.get("currency")) for v in b.values())
    for sym in sorted(set(b) | set(n)):
        p0, p1 = b.get(sym), n.get(sym)
        if p0 and not p1:
            add("removed_position", "removed_shares", sym, -at0(_f(p0.get("annual_native")) or 0.0, p0.get("currency")),
                shares_before=p0.get("shares"))
            continue
        ccy = p1.get("currency")
        if p1 and not p0:
            add("new_position", "new_shares", sym, at0(_f(p1.get("annual_native")) or 0.0, ccy),
                shares=p1.get("shares"))
            continue
        s0, s1 = _f(p0.get("shares")) or 0.0, _f(p1.get("shares")) or 0.0
        r0, r1 = _f(p0.get("annual_rate")) or 0.0, _f(p1.get("annual_rate")) or 0.0
        ds = at0((s1 - s0) * r0, ccy)
        add("more_shares" if ds > 0 else "fewer_shares", "new_shares" if ds > 0 else "removed_shares", sym, ds,
            shares_before=s0, shares=s1)
        dr = at0(s1 * (r1 - r0), ccy)
        add("raise" if dr > 0 else "cut", "raises" if dr > 0 else "cuts", sym, dr,
            rate_before=r0, rate=r1, change_pct=_r((r1 / r0 - 1) * 100) if r0 else None)
    now_total = 0.0
    for sym, p1 in n.items():
        native = _f(p1.get("annual_native")) or 0.0
        v1 = convert(native, p1.get("currency"), home, fx1)
        if v1 is None:
            continue
        now_total += v1
        comp["fx"] += v1 - at0(native, p1.get("currency"))
    items.sort(key=lambda i: -abs(i["amount"]))
    return {"before_total": round(before, 2), "now_total": round(now_total, 2),
            "change": round(now_total - before, 2),
            "components": {k: round(v, 2) for k, v in comp.items()},
            "usdcad_before": fx0, "usdcad_now": fx1, "items": items[:20]}


async def run_income_snapshots(on_date: date | None = None, fetch=None) -> dict:
    """Scheduler entry: one forecast per user with holdings. Idempotent per day."""
    from app.core.api_errors import is_missing_schema
    from app.db import queries
    from app.services import dividend_calendar, dividends
    from app.services.price_cache import get_usdcad_rate

    d = on_date or dividends.today_et()
    try:
        holdings = await asyncio.to_thread(queries.get_all_holdings)
    except Exception as e:
        logger.warning(f"income snapshots: holdings unavailable: {e}")
        return {"status": "unavailable"}
    by_user: dict[str, list[dict]] = {}
    for h in holdings:
        by_user.setdefault(str(h.get("user_id")), []).append(h)
    if not by_user:
        return {"status": "ok", "users": 0, "rows": 0}
    try:
        currencies = await asyncio.to_thread(queries.get_user_home_currencies, sorted(by_user))
    except Exception as e:
        logger.warning(f"income snapshots: home currencies unavailable, using CAD: {e}")
        currencies = {}
    symbols = sorted({str(h.get("symbol") or "").upper() for h in holdings if h.get("symbol")})
    profiles = await dividend_calendar.fetch_profiles(symbols, fetch)
    try:
        usdcad = await asyncio.to_thread(get_usdcad_rate)
    except Exception:
        usdcad = None
    written = failed = 0
    for uid, rows in by_user.items():
        fc = compute_forecast(rows, profiles, currencies.get(uid, "CAD"), usdcad)
        row = {k: fc[k] for k in ("total_home", "currency", "usdcad", "per_symbol")}
        try:
            written += await asyncio.to_thread(queries.upsert_income_snapshot, uid, d.isoformat(), row)
        except Exception as e:
            if is_missing_schema(e):
                logger.warning(f"income snapshots: table missing (apply migration 014): {e}")
                return {"status": "unavailable"}
            failed += 1
            logger.warning(f"income snapshots: user {uid} failed: {e}")
    return {"status": "ok", "date": d.isoformat(), "users": len(by_user), "rows": written, "failed": failed}
