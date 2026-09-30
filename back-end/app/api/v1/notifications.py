"""Notification preferences (migration 013). Delivery comes in a later phase.

  GET /api/v1/notifications/prefs   feature area.profile
  PUT /api/v1/notifications/prefs   feature area.profile — partial merge

Response:
  {"prefs": {
      "exdiv_reminder":  {"enabled": true},
      "dividend_paid":   {"enabled": true},
      "dividend_change": {"enabled": true},
      "check_changed":   {"enabled": true},
      "earnings":        {"enabled": true},
      "big_move":        {"enabled": true, "threshold_pct": 5.0},
      "analyst_ratings": {"enabled": false},
      "economy":         {"enabled": true}},
   "is_default": bool,          # true = nothing saved yet
   "updated_at": iso | null}

PUT body: any subset, e.g. {"big_move": {"threshold_pct": 8}, "economy": {"enabled": false}}.
Errors: 400 nothing_to_update; 422 invalid_prefs (unknown key/field, bad
value, threshold outside 1-50); 503 migration_required.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from app.core.access import require_feature
from app.core.api_errors import run_db
from app.core.dependencies import get_current_user
from app.services import notification_prefs

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("/prefs", dependencies=[Depends(require_feature("area.profile"))])
async def get_prefs(user: dict = Depends(get_current_user)):
    return await run_db(notification_prefs.get_prefs, user["user_id"])


@router.put("/prefs", dependencies=[Depends(require_feature("area.profile"))])
async def update_prefs(body: dict = Body(...), user: dict = Depends(get_current_user)):
    return await run_db(notification_prefs.update_prefs, user["user_id"], body)
