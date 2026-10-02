"""Portfolio allocation: mix by class, holdings map, warnings, targets, deposit plan.

No AI. Classes, warning thresholds, target and plan rules: see the docstring
of app/services/allocation.py. All amounts are in the user's home currency
(USD/CAD converted; other currencies are left out and listed in `unpriced`).
Prices are free, delayed data: `as_of` (oldest quote time) + `delayed_minutes`.

  GET /api/v1/portfolio/allocation?account_id=&person_id=        area.insights
  {
    "home_currency": "CAD", "as_of": ISO | null, "delayed_minutes": 15,
    "estimated_prices": ["SYM", ...],           # priced from the monitor's last close
    "scope": {"account_id": uuid | null, "person_id": uuid | null},
    "total_home", "invested_home", "cash_home",   # cash = accounts' cash_balance
    "mix": [{"class": "stocks"|"broad_etfs"|"option_income_etfs"|"cash_like"|"crypto"|"other",
             "value_home", "pct", "members": [{"symbol", "value_home", "pct"}
                                              | {"symbol": null, "kind": "account_cash", ...}]}],
    "tiles": [{"symbol", "name", "class", "value_home", "weight_pct", "day_change_pct",
               "total_gain_pct"}],               # largest first (holdings map)
    "warnings": [{"code": "top3_concentration"|"single_holding"|"cash_like_high"|
                  "option_income_high", "params": {...}}],
    "unpriced": ["SYM", ...],
    "targets": {class: pct} | null
  }

  GET /api/v1/portfolio/allocation/targets                        area.insights
  -> {"targets": {class: pct} | null, "classes": [...]}
  PUT /api/v1/portfolio/allocation/targets                        area.insights
  body {"targets": {class: pct} | null}  (null clears; sum must be 100)
  -> {"targets": {...every class...} | null, "classes": [...]}
  (Gated by area.insights like the reads: targets are the user's own
  preference, available on every plan.)

  GET /api/v1/portfolio/allocation/plan?amount=&account_id=&person_id=   area.insights
  {
    "home_currency", "as_of", "delayed_minutes", "targets": {...},
    "amount", "allocated", "unallocated",
    "items": [{"class", "amount", "gap_home", "current_pct", "target_pct", "after_pct",
               "buy": {"symbol": str | null, "source": "largest_holding"|"default"|null,
                       "code": "no_default" | null}}]
  }

Errors ({"detail": {"code", "message", ...}}):
  404 account_not_found | person_not_found · 409 no_targets (plan before any target is set) ·
  422 invalid_scope | invalid_targets | targets_sum {sum} | invalid_amount ·
  403 upgrade_required · 503 migration_required | storage_unavailable
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, status

from app.core.access import require_feature
from app.core.api_errors import api_error, run_db
from app.core.dependencies import get_current_user
from app.services import allocation as alloc
from app.services import portfolio_context as pc

router = APIRouter(prefix="/portfolio/allocation", tags=["Portfolio"])


def _s(v: Optional[UUID]) -> str | None:
    return str(v) if v else None


def _allocation(user: dict, account_id: str | None, person_id: str | None) -> tuple[dict, dict, dict]:
    ctx = pc.load_scope(user, account_id, person_id, with_transactions=False)
    home = ctx["home_currency"]
    positions = pc.value_positions(ctx["holdings"], ctx["quotes"], home, ctx["usdcad"])
    merged = pc.merge_positions_by_symbol(positions)
    cash = 0.0
    for a in ctx["accounts"]:
        c = pc.to_home(pc._f(a.get("cash_balance")) or 0.0, a.get("currency") or home, home, ctx["usdcad"])
        cash += c or 0.0
    body = alloc.build_allocation(merged, cash)
    meta = pc.price_meta(positions)
    return ctx, body, meta


def get_allocation(user: dict, account_id: str | None, person_id: str | None) -> dict:
    from app.db import queries
    ctx, body, meta = _allocation(user, account_id, person_id)
    return {"home_currency": ctx["home_currency"], **meta,
            "scope": {"account_id": account_id, "person_id": person_id}, **body,
            "targets": queries.get_allocation_targets(user["user_id"])}


def get_targets(user_id: str) -> dict:
    from app.db import queries
    return {"targets": queries.get_allocation_targets(user_id), "classes": list(alloc.CLASSES)}


def put_targets(user_id: str, raw: Any) -> dict:
    from app.db import queries
    clean = alloc.validate_targets(raw)
    queries.set_allocation_targets(user_id, clean)
    return {"targets": clean, "classes": list(alloc.CLASSES)}


def get_plan(user: dict, raw_amount: Any, account_id: str | None, person_id: str | None) -> dict:
    from app.db import queries
    amount = pc._f(raw_amount)
    if amount is None or not (0 < amount <= alloc.MAX_PLAN_AMOUNT):
        raise api_error("invalid_amount", "Amount must be greater than 0 (up to 1,000,000,000).",
                        status.HTTP_422_UNPROCESSABLE_ENTITY, field="amount")
    targets = queries.get_allocation_targets(user["user_id"])
    if not targets:
        raise api_error("no_targets", "Set your target mix first (PUT /portfolio/allocation/targets).",
                        status.HTTP_409_CONFLICT)
    ctx, body, meta = _allocation(user, account_id, person_id)
    plan = alloc.build_plan(body, targets, amount, ctx["home_currency"])
    return {"home_currency": ctx["home_currency"], "as_of": meta["as_of"],
            "delayed_minutes": meta["delayed_minutes"], "targets": targets, **plan}


@router.get("", dependencies=[Depends(require_feature("area.insights"))])
async def allocation(account_id: Optional[UUID] = Query(None), person_id: Optional[UUID] = Query(None),
                     user: dict = Depends(get_current_user)):
    return await run_db(get_allocation, user, _s(account_id), _s(person_id))


@router.get("/targets", dependencies=[Depends(require_feature("area.insights")), Depends(require_feature("feature.allocation_plan"))])
async def read_targets(user: dict = Depends(get_current_user)):
    return await run_db(get_targets, user["user_id"])


@router.put("/targets", dependencies=[Depends(require_feature("area.insights")), Depends(require_feature("feature.allocation_plan"))])
async def write_targets(body: dict = Body(...), user: dict = Depends(get_current_user)):
    if "targets" not in body:
        raise api_error("invalid_targets", "Body must be {\"targets\": {class: pct} | null}.",
                        status.HTTP_422_UNPROCESSABLE_ENTITY)
    return await run_db(put_targets, user["user_id"], body["targets"])


@router.get("/plan", dependencies=[Depends(require_feature("area.insights")), Depends(require_feature("feature.allocation_plan"))])
async def plan(amount: Optional[str] = Query(None), account_id: Optional[UUID] = Query(None),
               person_id: Optional[UUID] = Query(None), user: dict = Depends(get_current_user)):
    return await run_db(get_plan, user, amount, _s(account_id), _s(person_id))
