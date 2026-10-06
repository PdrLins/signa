"""Fixed income entered by hand (migration 032): Tesouro Direto, CDB, LCI/LCA,
LC, debentures, CRI/CRA. No AI. Valued every day from the indexer:

  cdi / selic  principal x prod(1 + daily_rate x rate%) over the business days
               from the start date (CDI/Selic from Banco Central, app/market/br_rates.py).
               rate = % of the index (110 = 110% of CDI).
  pre          principal x (1 + rate%)^(business days / 252)
  ipca         principal x prod(1 + monthly IPCA) x (1 + rate%)^(business days / 252)
               (published months only; the current month isn't known yet)

Accrual stops at the maturity date. Business days are the days with a CDI
value (B3 calendar); without the series, weekdays. Without the needed rates
(Banco Central down), the value is the principal and "estimated": true.

Income tax estimate (Brazil, regressive table on the gain): 22.5% up to 180
days, 20% up to 360, 17.5% up to 720, then 15%; none for tax_exempt (LCI,
LCA, CRI, CRA for individuals). IOF (first 30 days) is not included.
Values are in the asset's currency (BRL); totals add home-currency values.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.core.api_errors import api_error

MIGRATION = "032_auto_dividends_fixed_income.sql"
KINDS = ("tesouro_selic", "tesouro_prefixado", "tesouro_ipca", "cdb", "lci", "lca", "lc", "debenture",
         "cri", "cra", "other")
INDEXERS = ("cdi", "selic", "pre", "ipca")
EXEMPT_BY_DEFAULT = {"lci", "lca", "cri", "cra"}
DEFAULT_INDEXER = {"tesouro_selic": "selic", "tesouro_prefixado": "pre", "tesouro_ipca": "ipca"}
RATE_RANGE = {"cdi": (1, 300), "selic": (1, 300), "pre": (0, 100), "ipca": (0, 50)}
NAME_MAX, NOTE_MAX = 80, 200
COLUMNS = ("id, account_id, name, kind, indexer, rate, principal, currency, start_date, maturity_date, "
           "tax_exempt, note, created_at, updated_at")


def _f(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def _d(v: Any) -> date | None:
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _422(code: str, message: str, field: str, **extra) -> Exception:
    return api_error(code, message, 422, field=field, **extra)


# ============================================================
# Valuation (pure)
# ============================================================

def tax_rate(days: int) -> float:
    if days <= 180:
        return 0.225
    if days <= 360:
        return 0.20
    if days <= 720:
        return 0.175
    return 0.15


def _business_days(start: date, end: date, calendar: dict[date, float] | None) -> list[date]:
    """Days d with start <= d < end that accrue (a CDI value exists), else weekdays."""
    if calendar:
        return sorted(d for d in calendar if start <= d < end)
    out, d = [], start
    while d < end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def value(asset: dict, today: date, rates: dict[str, dict[date, float]]) -> dict:
    """{"value", "gain", "gain_pct", "net_value", "tax_rate", "days", "estimated", "matured"}. Pure.
    rates: {"CDI": {date: % a day}, "SELIC": {...}, "IPCA": {first-of-month: % a month}}."""
    principal = _f(asset.get("principal")) or 0.0
    start = _d(asset.get("start_date")) or today
    maturity = _d(asset.get("maturity_date"))
    end = min(today, maturity) if maturity else today
    indexer, rate = asset.get("indexer"), _f(asset.get("rate")) or 0.0
    cal = rates.get("CDI") or {}
    estimated = False
    factor = 1.0
    if end > start:
        if indexer in ("cdi", "selic"):
            series = rates.get(indexer.upper()) or {}
            days = [d for d in series if start <= d < end]
            if not days:
                estimated = True
            for d in days:
                factor *= 1 + series[d] / 100 * rate / 100
        else:
            bd = len(_business_days(start, end, cal))
            if not cal:
                estimated = True
            factor = (1 + rate / 100) ** (bd / 252)
            if indexer == "ipca":
                ipca = rates.get("IPCA") or {}
                months = [m for m in ipca if date(start.year, start.month, 1) <= m < date(end.year, end.month, 1)]
                if not ipca:
                    estimated = True
                for m in months:
                    factor *= 1 + ipca[m] / 100
    gross = principal * factor
    gain = gross - principal
    held = (end - start).days
    tr = 0.0 if asset.get("tax_exempt") else tax_rate(held)
    net = gross - max(0.0, gain) * tr
    return {"value": round(gross, 2), "gain": round(gain, 2),
            "gain_pct": round(gain / principal * 100, 2) if principal else None,
            "net_value": round(net, 2), "tax_rate": tr, "days": held,
            "estimated": estimated, "matured": bool(maturity and today >= maturity)}


def needed_rates(assets: list[dict]) -> dict[str, date]:
    """{"CDI": since, ...} to value these assets. Pure."""
    need: dict[str, date] = {}
    for a in assets:
        start = _d(a.get("start_date"))
        if not start:
            continue
        names = {"cdi": ["CDI"], "selic": ["SELIC", "CDI"], "pre": ["CDI"], "ipca": ["IPCA", "CDI"]}
        for n in names.get(a.get("indexer"), []):
            need[n] = min(need.get(n, start), start)
    return need


def load_rates(assets: list[dict]) -> dict[str, dict[date, float]]:
    """Blocking: the Banco Central series these assets need (cached)."""
    from app.market import br_rates
    return {name: br_rates.series(name, since) for name, since in needed_rates(assets).items()}


# ============================================================
# Validation
# ============================================================

def validate(body: dict, partial: bool = False, current: dict | None = None) -> dict:
    out: dict = {}
    cur = current or {}
    if "name" in body or not partial:
        name = str(body.get("name") or "").strip()
        if not name or len(name) > NAME_MAX:
            raise _422("invalid_name", f"Give it a name (up to {NAME_MAX} characters).", "name")
        out["name"] = name
    if "kind" in body or not partial:
        kind = str(body.get("kind") or "").lower()
        if kind not in KINDS:
            raise _422("invalid_kind", f"kind must be one of {', '.join(KINDS)}.", "kind")
        out["kind"] = kind
    kind = out.get("kind", cur.get("kind"))
    if "indexer" in body or not partial:
        ix = str(body.get("indexer") or DEFAULT_INDEXER.get(kind, "")).lower()
        if ix not in INDEXERS:
            raise _422("invalid_indexer", f"indexer must be one of {', '.join(INDEXERS)}.", "indexer")
        out["indexer"] = ix
    ix = out.get("indexer", cur.get("indexer"))
    if "rate" in body or not partial or ("indexer" in out and partial):
        r = _f(body.get("rate", cur.get("rate")))
        lo, hi = RATE_RANGE.get(ix, (0, 300))
        if r is None or not (lo <= r <= hi):
            what = "% of the index (e.g. 110)" if ix in ("cdi", "selic") else "% a year"
            raise _422("invalid_rate", f"rate must be {what}, between {lo} and {hi}.", "rate", min=lo, max=hi)
        out["rate"] = r
    if "principal" in body or not partial:
        p = _f(body.get("principal"))
        if p is None or p <= 0:
            raise _422("invalid_principal", "principal must be the amount invested (positive).", "principal")
        out["principal"] = round(p, 2)
    from app.services.dividends import today_et
    today = today_et() + timedelta(days=1)   # New York's today, +1 day so "today" works in every time zone
    if "start_date" in body or not partial:
        s = _d(body.get("start_date"))
        if not s or s > today:
            raise _422("invalid_start_date", "start_date must be a date (YYYY-MM-DD), not in the future.",
                       "start_date")
        out["start_date"] = s.isoformat()
    if "maturity_date" in body:
        m = _d(body.get("maturity_date")) if body.get("maturity_date") else None
        s = _d(out.get("start_date", cur.get("start_date")))
        if body.get("maturity_date") and (not m or (s and m <= s)):
            raise _422("invalid_maturity_date", "maturity_date must be after start_date.", "maturity_date")
        out["maturity_date"] = m.isoformat() if m else None
    if "tax_exempt" in body and body["tax_exempt"] is not None:
        if not isinstance(body["tax_exempt"], bool):
            raise _422("invalid_tax_exempt", "tax_exempt must be true or false.", "tax_exempt")
        out["tax_exempt"] = body["tax_exempt"]
    elif not partial:
        out["tax_exempt"] = kind in EXEMPT_BY_DEFAULT
    if body.get("currency") is not None or not partial:
        c = str(body.get("currency") or "BRL").upper()
        if len(c) != 3 or not c.isalpha():
            raise _422("invalid_currency", "currency must be a 3-letter code.", "currency")
        out["currency"] = c
    if "note" in body:
        n = (str(body["note"]).strip() if body["note"] is not None else "") or None
        if n and len(n) > NOTE_MAX:
            raise _422("invalid_note", f"note must be at most {NOTE_MAX} characters.", "note")
        out["note"] = n
    if "account_id" in body:
        out["account_id"] = str(body["account_id"]) if body["account_id"] else None
    return out


# ============================================================
# Service (blocking; routes run these with run_db_for)
# ============================================================

def _db():
    from app.db.supabase import get_client
    return get_client()


def rows_for(user_id: str) -> list[dict]:
    from app.db.queries import _select_all_pages
    return _select_all_pages(lambda: _db().table("fixed_income").select(COLUMNS).eq("user_id", user_id)
                             .order("start_date").order("id"))


def _check_account(user_id: str, account_id: str | None) -> None:
    if not account_id:
        return
    from app.db import queries
    if not any(str(a["id"]) == account_id for a in queries.get_accounts(user_id)):
        raise _422("invalid_account", "That account isn't yours.", "account_id")


def public(row: dict, today: date, rates: dict, home: str, usdcad: float | None) -> dict:
    from app.services import portfolio_context as pc
    v = value(row, today, rates)
    return {**{k: row.get(k) for k in COLUMNS.replace(" ", "").split(",")},
            "principal": _f(row.get("principal")), "rate": _f(row.get("rate")),
            **v, "value_home": pc.to_home(v["value"], row.get("currency") or "BRL", home, usdcad)}


def list_body(user: dict, today: date | None = None) -> dict:
    from app.services import portfolio_context as pc
    scope = pc.load_scope(user, None, None, False, False)
    home, usdcad = scope["home_currency"], scope.get("usdcad")
    today = today or datetime.now(timezone.utc).date()
    rows = rows_for(user["user_id"])
    rates = load_rates(rows)
    items = [public(r, today, rates, home, usdcad) for r in rows]
    total = sum(i["value_home"] or 0 for i in items)
    return {"items": items, "count": len(items), "home_currency": home,
            "total_home": round(total, 2),
            "invested_home": round(sum(pc.to_home(i["principal"], i.get("currency") or "BRL", home, usdcad) or 0
                                       for i in items), 2),
            "estimated": any(i["estimated"] for i in items)}


def create(user: dict, body: dict) -> dict:
    data = validate(body)
    _check_account(user["user_id"], data.get("account_id"))
    count = len(rows_for(user["user_id"]))
    if count >= MAX_PER_USER:
        raise _422("fixed_income_limit", f"Up to {MAX_PER_USER} fixed-income assets.", "name", limit=MAX_PER_USER)
    row = _db().table("fixed_income").insert({**data, "user_id": user["user_id"]}).execute().data[0]
    return _one(user, row)


def update(user: dict, asset_id: str, body: dict) -> dict:
    cur = (_db().table("fixed_income").select(COLUMNS).eq("id", asset_id).eq("user_id", user["user_id"])
           .limit(1).execute().data or [None])[0]
    if not cur:
        raise api_error("not_found", "Fixed-income asset not found.", 404)
    data = validate(body, partial=True, current=cur)
    if not data:
        raise api_error("nothing_to_update", "Send at least one field to change.", 422)
    if "account_id" in data:
        _check_account(user["user_id"], data["account_id"])
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    row = (_db().table("fixed_income").update(data).eq("id", asset_id).eq("user_id", user["user_id"])
           .execute().data or [None])[0]
    if not row:
        raise api_error("not_found", "Fixed-income asset not found.", 404)
    return _one(user, row)


def delete(user: dict, asset_id: str) -> dict:
    rows = _db().table("fixed_income").delete().eq("id", asset_id).eq("user_id", user["user_id"]).execute().data
    if not rows:
        raise api_error("not_found", "Fixed-income asset not found.", 404)
    return {"deleted": True, "id": asset_id}


def _one(user: dict, row: dict) -> dict:
    from app.services import portfolio_context as pc
    scope = pc.load_scope(user, None, None, False, False)
    rates = load_rates([row])
    return public(row, datetime.now(timezone.utc).date(), rates, scope["home_currency"], scope.get("usdcad"))


MAX_PER_USER = 200


def scope_value(rows: list[dict], home: str, usdcad: float | None, today: date | None = None) -> dict:
    """{"value", "invested", "gain", "count", "estimated", "items": [{id, name, kind, account_id,
    value_home}]} of loaded rows, in the home currency. Blocking only for the rates (cached)."""
    from app.services import portfolio_context as pc
    if not rows:
        return {"value": 0.0, "invested": 0.0, "gain": 0.0, "count": 0, "estimated": False, "items": []}
    today = today or datetime.now(timezone.utc).date()
    rates = load_rates(rows)
    items, total, invested, est = [], 0.0, 0.0, False
    for r in rows:
        v = value(r, today, rates)
        ccy = r.get("currency") or "BRL"
        vh = pc.to_home(v["value"], ccy, home, usdcad)
        ih = pc.to_home(_f(r.get("principal")), ccy, home, usdcad)
        est = est or v["estimated"] or vh is None
        total += vh or 0.0
        invested += ih or 0.0
        items.append({"id": r.get("id"), "name": r.get("name"), "kind": r.get("kind"),
                      "account_id": r.get("account_id"), "value_home": round(vh, 2) if vh is not None else None})
    return {"value": round(total, 2), "invested": round(invested, 2), "gain": round(total - invested, 2),
            "count": len(rows), "estimated": est, "items": items}


def scope_total(user_id: str, home: str, usdcad: float | None, account_ids: list | None = None) -> dict:
    """{"value_home", "invested_home", "count", "estimated"} for the portfolio
    summary and snapshots. Never raises (before migration 032: zeros)."""
    from app.services import portfolio_context as pc
    try:
        rows = rows_for(user_id)
    except Exception:
        return {"value_home": 0.0, "invested_home": 0.0, "count": 0, "estimated": False}
    if account_ids is not None:
        rows = [r for r in rows if str(r.get("account_id")) in {str(a) for a in account_ids}]
    if not rows:
        return {"value_home": 0.0, "invested_home": 0.0, "count": 0, "estimated": False}
    today = datetime.now(timezone.utc).date()
    rates = load_rates(rows)
    vals = [(value(r, today, rates), r) for r in rows]
    total = sum(pc.to_home(v["value"], r.get("currency") or "BRL", home, usdcad) or 0 for v, r in vals)
    invested = sum(pc.to_home(_f(r.get("principal")), r.get("currency") or "BRL", home, usdcad) or 0 for _, r in vals)
    return {"value_home": round(total, 2), "invested_home": round(invested, 2), "count": len(rows),
            "estimated": any(v["estimated"] for v, _ in vals)}
