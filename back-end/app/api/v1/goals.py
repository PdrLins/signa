"""Investing goals (migration 026). No AI.

  GET    /api/v1/goals          area.home  {"items": [Goal], "count", "limit": 1 | null, "currency"}
  POST   /api/v1/goals          area.home  {"kind": "portfolio_value" | "monthly_income", "target": 500000,
                                            "title"?: str (<= 60), "target_date"?: "YYYY-MM-DD",
                                            "monthly_contribution"?: >= 0 | null,
                                            "expected_return_pct"?: -20..30 | null} -> 201 Goal
  PATCH  /api/v1/goals/{id}     area.home  any of kind, target, title, target_date, monthly_contribution,
                                            expected_return_pct -> Goal
  DELETE /api/v1/goals/{id}     area.home  -> {"deleted": true, "id"}

Goal: see app/services/goals.py. Targets are in the user's home currency
(stored with the goal). Free: 1 goal; Premium: unlimited (feature.unlimited_goals).
Over the limit (Premium -> Free with several goals): GET lists them all (count > limit),
DELETE works, PATCH answers 403 goal_limit until the user is back within the limit.
Errors: 403 goal_limit {"limit", "count", "upgrade": {"feature", "plan"}} · 404 goal_not_found ·
422 invalid_kind | invalid_target | invalid_title | invalid_target_date | invalid_input
(monthly_contribution / expected_return_pct, with "field") · 400 nothing_to_update ·
503 migration_required {"migration": "026_goals.sql" | "034_goal_projections.sql" (only
projection fields sent before 034)}.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, Body, Depends, status
from loguru import logger

from app.core.access import require_feature
from app.core.api_errors import run_db, run_db_for, run_db_write
from app.core.dependencies import get_current_user
from app.services import goals as svc
from app.services import portfolio_context
from app.services import portfolio_performance as perf

router = APIRouter(prefix="/goals", tags=["Goals"])

INCOME_TIMEOUT_S = 6.0


async def _currents(user: dict) -> tuple[str, dict[str, tuple[float | None, bool]], dict]:
    """(home currency, {kind: (current, estimated)}, projection inputs
    {"yield_pct", "avg_monthly_deposit"}). One scope load for every goal."""
    scope = await run_db(portfolio_context.load_scope, user, None, None, True)
    home, usdcad = scope["home_currency"], scope.get("usdcad")
    s = await asyncio.to_thread(perf.summary_body, scope)
    out: dict[str, tuple[float | None, bool]] = {"portfolio_value": (s.get("total"), bool(s.get("estimated")))}
    from app.services import dividend_calendar
    from app.services.income_forecast import compute_forecast
    held = sorted({str(h.get("symbol") or "").upper() for h in scope["holdings"] if h.get("symbol")})
    annual = None
    try:
        profiles = await asyncio.wait_for(dividend_calendar.fetch_profiles(held), INCOME_TIMEOUT_S)
        fc = await asyncio.to_thread(compute_forecast, scope["holdings"], profiles, home, usdcad)
        annual = fc["total_home"]
        out["monthly_income"] = (annual / 12, bool(fc.get("unconverted")))
    except Exception as e:
        logger.debug(f"goals: income unavailable ({e!r})")
        out["monthly_income"] = (None, True)
    mv = s.get("market_value") or 0
    inputs = {"yield_pct": round(annual / mv * 100, 2) if annual is not None and mv > 0 else None,
              "avg_monthly_deposit": svc.avg_monthly_deposit(scope.get("transactions") or [], home, usdcad,
                                                             perf.today_et())}
    return home, out, inputs


@router.get("", dependencies=[Depends(require_feature("area.home"))])
async def list_goals(user: dict = Depends(get_current_user)):
    rows = await run_db_for(svc.MIGRATION, svc.list_goals, user["user_id"])
    home, cur, inputs = await _currents(user) if rows else (None, {}, {})
    items = [{**r, "progress": svc.progress(r, *cur.get(r["kind"], (None, True)), inputs)} for r in rows]
    if home is None:
        scope_home = await run_db(portfolio_context.load_scope, user, None, None, False, False)
        home = scope_home["home_currency"]
    return {"items": items, "count": len(items), "limit": svc.limit_for(user.get("access_level") or "free"),
            "currency": home}


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_feature("area.home"))])
async def create_goal(body: dict = Body(...), user: dict = Depends(get_current_user)):
    scope = await run_db(portfolio_context.load_scope, user, None, None, False, False)
    row = await run_db_write(svc.MIGRATION, svc.create, user, body, scope["home_currency"])
    _home, cur, inputs = await _currents(user)
    return {**row, "progress": svc.progress(row, *cur[row["kind"]], inputs)}


@router.patch("/{goal_id}", dependencies=[Depends(require_feature("area.home"))])
async def update_goal(goal_id: UUID, body: dict = Body(...), user: dict = Depends(get_current_user)):
    await run_db_for(svc.MIGRATION, svc.check_can_edit, user)
    row = await run_db_for(svc.MIGRATION, svc.update, user["user_id"], str(goal_id), body)
    _home, cur, inputs = await _currents(user)
    return {**row, "progress": svc.progress(row, *cur[row["kind"]], inputs)}


@router.delete("/{goal_id}", dependencies=[Depends(require_feature("area.home"))])
async def delete_goal(goal_id: UUID, user: dict = Depends(get_current_user)):
    return await run_db_for(svc.MIGRATION, svc.delete, user["user_id"], str(goal_id))
