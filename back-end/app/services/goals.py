"""Investing goals (migration 026): a target portfolio value or a monthly
dividend income, in the user's home currency. Free: FREE_GOALS goal;
Premium (feature.unlimited_goals): unlimited. Progress is computed on read.

  portfolio_value   current = market value + cash (= /portfolio/summary total)
  monthly_income    current = forward annual dividend income / 12 (shares x each
                    payer's annual rate; = the income forecast)

Goal = {"id", "kind", "target", "currency", "title" | null, "target_date" | null,
        "monthly_contribution" | null, "expected_return_pct" | null,     # migration 034
        "created_at", "updated_at",
        "progress": {"current": float | null, "pct": 0..100 | null, "remaining": float | null,
                     "reached": bool, "estimated": bool,
                     "yield_pct": float | null, "avg_monthly_deposit": float | null}}
`estimated` is true when some holdings couldn't be valued or converted.
monthly_contribution (>= 0) and expected_return_pct (-20..30, yearly growth: portfolio
growth for portfolio_value, dividend growth for monthly_income) are what the user plans;
the app projects the date. Left out of the goal before migration 034.
yield_pct = forward annual dividend income / holdings' market value x 100 (the
dividends summary's yield, from the income forecast the monthly_income goal uses).
avg_monthly_deposit = net deposits (deposits - withdrawals) a month over the last 12
months, home currency; null with under 2 months of transactions or no deposits.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from app.core.access import can
from app.core.api_errors import api_error
from app.db.supabase import get_client

MIGRATION = "026_goals.sql"
FEATURE = "feature.unlimited_goals"
FREE_GOALS = 1
KINDS = ("portfolio_value", "monthly_income")
TITLE_MAX = 60
COLUMNS = "id, kind, target, currency, title, target_date, created_at, updated_at"
PROJECTION_COLUMNS = ", monthly_contribution, expected_return_pct"   # migration 034
PROJECTION_FIELDS = ("monthly_contribution", "expected_return_pct")
RETURN_RANGE = (-20.0, 30.0)
MAX_CONTRIBUTION = 1e9


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def limit_for(level: str) -> int | None:
    return None if can(level, FEATURE) else FREE_GOALS


def clean(body: dict, partial: bool = False) -> dict:
    """Validated fields (422 on bad input). Pure."""
    out: dict = {}
    if not partial or "kind" in body:
        if body.get("kind") not in KINDS:
            raise api_error("invalid_kind", f"kind must be one of {', '.join(KINDS)}.", 422)
        out["kind"] = body["kind"]
    if not partial or "target" in body:
        t = _num(body.get("target"))
        if t is None or t <= 0 or t > 1e12:
            raise api_error("invalid_target", "target must be a positive amount.", 422)
        out["target"] = round(t, 2)
    if "title" in body:
        title = body["title"]
        if title is not None and (not isinstance(title, str) or len(title.strip()) > TITLE_MAX):
            raise api_error("invalid_title", f"title must be text up to {TITLE_MAX} characters.", 422)
        out["title"] = (title.strip() or None) if isinstance(title, str) else None
    if "target_date" in body:
        d = body["target_date"]
        if d is not None:
            try:
                d = date.fromisoformat(str(d)).isoformat()
            except ValueError:
                raise api_error("invalid_target_date", "target_date must be YYYY-MM-DD.", 422)
        out["target_date"] = d
    if "monthly_contribution" in body:
        v = body["monthly_contribution"]
        n = _num(v)
        if v is not None and (n is None or isinstance(v, bool) or n < 0 or n > MAX_CONTRIBUTION):
            raise api_error("invalid_input", "monthly_contribution must be an amount of 0 or more.", 422,
                            field="monthly_contribution")
        out["monthly_contribution"] = round(n, 2) if v is not None else None
    if "expected_return_pct" in body:
        v = body["expected_return_pct"]
        n = _num(v)
        lo, hi = RETURN_RANGE
        if v is not None and (n is None or isinstance(v, bool) or not lo <= n <= hi):
            raise api_error("invalid_input", f"expected_return_pct must be between {lo:g} and {hi:g}.", 422,
                            field="expected_return_pct")
        out["expected_return_pct"] = round(n, 2) if v is not None else None
    if partial and not out:
        raise api_error("nothing_to_update", "Send kind, target, title, target_date, monthly_contribution "
                        "or expected_return_pct.", 400)
    return out


def progress(goal: dict, current: float | None, estimated: bool, inputs: dict | None = None) -> dict:
    """Pure. inputs = {"yield_pct", "avg_monthly_deposit"} (projection inputs, both kinds)."""
    target = _num(goal.get("target")) or 0
    extra = {"yield_pct": (inputs or {}).get("yield_pct"),
             "avg_monthly_deposit": (inputs or {}).get("avg_monthly_deposit")}
    if current is None or target <= 0:
        return {"current": None, "pct": None, "remaining": None, "reached": False, "estimated": estimated,
                **extra}
    return {"current": round(current, 2), "pct": round(min(100.0, max(0.0, current / target * 100)), 1),
            "remaining": round(max(0.0, target - current), 2), "reached": current >= target,
            "estimated": estimated, **extra}


def avg_monthly_deposit(transactions: list[dict], home: str, usdcad: float | None, today: date) -> float | None:
    """Net deposits (deposits - withdrawals) a month over the last 12 months, in
    `home`. Shorter history: over the months since the first transaction. None
    with under 2 months of transactions, or no deposit/withdrawal. Pure."""
    from app.services.portfolio_context import to_home
    dates = [d for d in (_date(t.get("trade_date")) for t in transactions or []) if d]
    if not dates:
        return None
    first = min(dates)
    if (today - first).days < 60:
        return None
    start = today - timedelta(days=365)
    net, seen = 0.0, False
    for t in transactions:
        typ = str(t.get("type") or "")
        d = _date(t.get("trade_date"))
        if typ not in ("deposit", "withdrawal") or d is None or not (start < d <= today):
            continue
        amt = to_home(abs(_num(t.get("amount")) or 0.0), str(t.get("currency") or home).upper(), home, usdcad)
        if amt is None:
            continue
        net += amt if typ == "deposit" else -amt
        seen = True
    if not seen:
        return None
    months = 12.0 if first <= start else min(12.0, max(2.0, (today - first).days / 30.44))
    return round(net / months, 2)


def _date(v: Any) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


# ---------------------------------------------------------------- storage (blocking)

def list_goals(user_id: str) -> list[dict]:
    from app.db.queries import _with_optional
    return _with_optional("goals_034", COLUMNS, PROJECTION_COLUMNS, lambda cols: (
        get_client().table("goals").select(cols).eq("user_id", user_id).order("created_at").execute().data or []))


def _write(run, row: dict):
    """run(row); before migration 034 retry without the projection fields."""
    from app.db.queries import _missing_optional, _missing_schema
    try:
        return run(row)
    except Exception as e:
        if not (_missing_schema(e) and any(k in row for k in PROJECTION_FIELDS)):
            raise
        _missing_optional.add("goals_034")
        rest = {k: v for k, v in row.items() if k not in PROJECTION_FIELDS}
        if not rest:   # only projection fields were sent
            raise api_error("migration_required", "Apply migration 034_goal_projections.sql first.", 503,
                            migration="034_goal_projections.sql")
        return run(rest)


def create(user: dict, body: dict, home: str) -> dict:
    row = clean(body)
    limit = limit_for(user.get("access_level") or "free")
    count = len(list_goals(user["user_id"])) if limit is not None else 0
    if limit is not None and count >= limit:
        raise _limit_error(limit, count, f"Your plan allows {limit} goal. Upgrade to set more.")
    res = _write(lambda r: get_client().table("goals").insert(
        {**r, "user_id": user["user_id"], "currency": home}).execute(), row)
    return (res.data or [{}])[0]


def _limit_error(limit: int, count: int, message: str):
    return api_error("goal_limit", message, 403, limit=limit, count=count,
                     upgrade={"feature": FEATURE, "plan": "premium"})


def check_can_edit(user: dict) -> None:
    """Above the plan's limit (Premium -> Free with several goals), goals are kept
    and can be deleted, but none can be edited: 403 goal_limit."""
    limit = limit_for(user.get("access_level") or "free")
    if limit is None:
        return
    count = len(list_goals(user["user_id"]))
    if count > limit:
        raise _limit_error(limit, count, f"Your plan allows {limit} goal. Delete goals to edit, or upgrade.")


def update(user_id: str, goal_id: str, body: dict) -> dict:
    data = clean(body, partial=True)
    res = _write(lambda r: get_client().table("goals").update(r).eq("id", goal_id).eq("user_id", user_id)
                 .execute(), data)
    if not res.data:
        raise api_error("goal_not_found", "Goal not found.", 404)
    return res.data[0]


def delete(user_id: str, goal_id: str) -> dict:
    res = get_client().table("goals").delete().eq("id", goal_id).eq("user_id", user_id).execute()
    if not res.data:
        raise api_error("goal_not_found", "Goal not found.", 404)
    return {"deleted": True, "id": goal_id}
