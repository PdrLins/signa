"""Notification preferences (migration 013) and the user's Telegram chat
(migration 016, delivery: app/services/telegram_notify.py).

  GET /api/v1/notifications/prefs   feature area.profile
  PUT /api/v1/notifications/prefs   feature area.profile — partial merge

  GET    /api/v1/notifications/telegram       area.profile
         {"available": bool (feature.telegram_alerts), "linked": bool,
          "username": "@name" | "First" | null, "linked_at": iso | null,
          "bot_username": str | null, "pending": {"expires_at": iso} | null}
  POST   /api/v1/notifications/telegram/link  feature.telegram_alerts (premium)
         {"code": str, "url": "https://t.me/<bot>?start=<code>", "expires_at": iso}
         one-time, 10 minutes; a new code invalidates older unused ones.
         503 telegram_not_configured (no bot token / username).
  POST   /api/v1/notifications/telegram/test  feature.telegram_alerts
         {"sent": true} · 409 not_linked · 502 telegram_send_failed
  DELETE /api/v1/notifications/telegram       area.profile (works after a downgrade)
         {"unlinked": true}
  All four: 503 migration_required (016_telegram_notifications.sql).

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
from app.core.api_errors import run_db, run_db_for
from app.core.dependencies import get_current_user
from app.services import notification_prefs, telegram_notify

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("/prefs", dependencies=[Depends(require_feature("area.profile"))])
async def get_prefs(user: dict = Depends(get_current_user)):
    return await run_db(notification_prefs.get_prefs, user["user_id"])


@router.put("/prefs", dependencies=[Depends(require_feature("area.profile"))])
async def update_prefs(body: dict = Body(...), user: dict = Depends(get_current_user)):
    return await run_db(notification_prefs.update_prefs, user["user_id"], body)


# ---------------------------------------------------------------- Telegram (migration 016)

@router.get("/telegram", dependencies=[Depends(require_feature("area.profile"))])
async def telegram_status(user: dict = Depends(get_current_user)):
    bot = await telegram_notify.bot_username()
    return await run_db_for(telegram_notify.MIGRATION, telegram_notify.status_payload, user, bot)


@router.post("/telegram/link", dependencies=[Depends(require_feature(telegram_notify.FEATURE))])
async def telegram_link(user: dict = Depends(get_current_user)):
    bot = await telegram_notify.bot_username()
    return await run_db_for(telegram_notify.MIGRATION, telegram_notify.create_link, user, bot)


@router.post("/telegram/test", dependencies=[Depends(require_feature(telegram_notify.FEATURE))])
async def telegram_test(user: dict = Depends(get_current_user)):
    return await telegram_notify.send_test(user)


@router.delete("/telegram", dependencies=[Depends(require_feature("area.profile"))])
async def telegram_unlink(user: dict = Depends(get_current_user)):
    return await run_db_for(telegram_notify.MIGRATION, telegram_notify.unlink, user)
