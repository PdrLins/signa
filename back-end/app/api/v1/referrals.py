"""Invite friends (migration 019).

  GET /api/v1/referrals   feature area.profile
      {"code": "K7M2QX9A",                 # the user's account ID = invite code
       "share_url": str | null,            # <WEB_APP_URL>/signup?code=<code>; null without WEB_APP_URL
       "per_friend": 5, "max_bonus": 25,
       "bonus_slots": int,                 # min(5 x rewarded, 25)
       "invited": int, "rewarded": int, "pending": int,
       "unlimited": bool}                  # premium / owner: slots already unlimited
      A referral is "rewarded" when the friend follows their first stock.
      503 migration_required (019_referrals.sql).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.access import require_feature
from app.core.api_errors import run_db_for
from app.core.dependencies import get_current_user
from app.services import referrals

router = APIRouter(prefix="/referrals", tags=["Referrals"])


@router.get("", dependencies=[Depends(require_feature("area.profile"))])
async def referral_summary(user: dict = Depends(get_current_user)):
    return await run_db_for(referrals.MIGRATION, referrals.summary, user)
