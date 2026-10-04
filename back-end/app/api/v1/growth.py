"""Where users come from and whether they stay (migration 029, app/services/growth.py).

  POST /api/v1/attribution          area.profile (any signed-in user)
       {"utm_source"?, "utm_medium"?, "utm_campaign"?, "utm_content"?, "utm_term"?,
        "heard_from"? (GET /auth/signup-config), "asa_token"? (Apple Search Ads)}
       -> {"saved": [field, ...]}   only fields still empty are saved (first touch wins);
       bad values are dropped, never an error. The iOS app sends asa_token once after
       sign-up (AAAttribution.attributionToken(), iOS 14.3+).
  GET  /api/v1/admin/growth?from=YYYY-MM-DD&to=YYYY-MM-DD&group=channel   area.admin (owner)
       group: channel | campaign | heard_from | country | platform | week
       -> {"from", "to", "group", "rows": [{"key", "signups", "activated", "activated_3",
           "week2", "week2_eligible", "premium", "activated_pct", "activated_3_pct",
           "week2_pct", "premium_pct"}], "totals": {...}, "definitions": {...}}
       Default range: the last 30 days. 422 invalid_group | invalid_range.
503 migration_required {"migration": "029_growth.sql"} before the migration.
"""

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Body, Depends, Query

from app.core.access import require_feature
from app.core.api_errors import run_db_for
from app.core.dependencies import get_current_user
from app.services import growth as svc

router = APIRouter(tags=["Growth"])


@router.post("/attribution", dependencies=[Depends(require_feature("area.profile"))])
async def attribution(body: dict = Body(...), user: dict = Depends(get_current_user)):
    return await run_db_for(svc.MIGRATION, svc.add_attribution, user["user_id"], body)


@router.get("/admin/growth", dependencies=[Depends(require_feature("area.admin"))])
async def admin_growth(
    start: Optional[date] = Query(None, alias="from"),
    end: Optional[date] = Query(None, alias="to"),
    group: str = Query("channel"),
    user: dict = Depends(get_current_user),
):
    from app.services.dividends import today_et
    end = end or today_et()
    start = start or end - timedelta(days=29)
    return await run_db_for(svc.MIGRATION, svc.funnel_body, start, end, group)
