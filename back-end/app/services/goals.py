"""Investing goals (migration 026): a target portfolio value or a monthly
dividend income, in the user's home currency. Free: FREE_GOALS goal;
Premium (feature.unlimited_goals): unlimited. Progress is computed on read.

  portfolio_value   current = market value + cash (= /portfolio/summary total)
  monthly_income    current = forward annual dividend income / 12 (shares x each
                    payer's annual rate; = the income forecast)

Goal = {"id", "kind", "target", "currency", "title" | null, "target_date" | null,
        "created_at", "updated_at",
        "progress": {"current": float | null, "pct": 0..100 | null, "remaining": float | null,
                     "reached": bool, "estimated": bool}}
`estimated` is true when some holdings couldn't be valued or converted.
"""

from __future__ import annotations

import math
from datetime import date
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
    if partial and not out:
        raise api_error("nothing_to_update", "Send kind, target, title or target_date.", 400)
    return out


def progress(goal: dict, current: float | None, estimated: bool) -> dict:
    """Pure."""
    target = _num(goal.get("target")) or 0
    if current is None or target <= 0:
        return {"current": None, "pct": None, "remaining": None, "reached": False, "estimated": estimated}
    return {"current": round(current, 2), "pct": round(min(100.0, max(0.0, current / target * 100)), 1),
            "remaining": round(max(0.0, target - current), 2), "reached": current >= target, "estimated": estimated}


# ---------------------------------------------------------------- storage (blocking)

def list_goals(user_id: str) -> list[dict]:
    return (get_client().table("goals").select(COLUMNS).eq("user_id", user_id)
            .order("created_at").execute().data or [])


def create(user: dict, body: dict, home: str) -> dict:
    row = clean(body)
    limit = limit_for(user.get("access_level") or "free")
    if limit is not None and len(list_goals(user["user_id"])) >= limit:
        raise api_error("goal_limit", f"Your plan allows {limit} goal. Upgrade to set more.", 403,
                        limit=limit, upgrade={"feature": FEATURE, "plan": "premium"})
    res = get_client().table("goals").insert({**row, "user_id": user["user_id"], "currency": home}).execute()
    return (res.data or [{}])[0]


def update(user_id: str, goal_id: str, body: dict) -> dict:
    data = clean(body, partial=True)
    res = get_client().table("goals").update(data).eq("id", goal_id).eq("user_id", user_id).execute()
    if not res.data:
        raise api_error("goal_not_found", "Goal not found.", 404)
    return res.data[0]


def delete(user_id: str, goal_id: str) -> dict:
    res = get_client().table("goals").delete().eq("id", goal_id).eq("user_id", user_id).execute()
    if not res.data:
        raise api_error("goal_not_found", "Goal not found.", 404)
    return {"deleted": True, "id": goal_id}
