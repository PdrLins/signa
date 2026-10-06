"""Profile — who the user is and how the tracker shows his money (migration 013).

  GET /api/v1/profile     feature area.profile
  PUT /api/v1/profile     feature area.profile — partial update: only the
                          fields sent change; null clears a nullable field.

Response (GET and PUT):
  {
    "user_id", "username",
    "display_name": str | null,
    "email": str | null,                 # read-only (users.email when present)
    "country": "CA" | "US" | ... | null, # ISO 3166-1 alpha-2
    "home_currency": "CAD",
    "language": "en" | "pt",
    "dividend_tax_view": "before" | "after",   # EFFECTIVE value
    "dividend_tax_view_stored": "before" | "after",
    "tax_view_available": bool,          # premium AND country in CA/US
    "compare_index": "XEQT.TO" | ... | null,   # opt-in benchmark
    "holdings_native_currency": bool,
    "access_level": "free" | "premium" | "owner",
    "slots": {"used", "limit", "remaining"}
  }

PUT body (all optional): display_name, country, home_currency, language,
dividend_tax_view, compare_index, holdings_native_currency.

Errors ({"detail": {"code", "message", "field"?}}):
  422 invalid_display_name | invalid_country | invalid_currency |
      invalid_language | invalid_compare_index | invalid_tax_view |
      invalid_value | tax_view_unavailable (after-tax outside CA/US)
  403 upgrade_required (after-tax view without feature.tax_view)
  503 migration_required (013 not applied)
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.core.access import require_feature
from app.core.api_errors import run_db
from app.core.dependencies import get_current_user
from app.services import profile_service

router = APIRouter(prefix="/profile", tags=["Profile"])


class ProfileUpdate(BaseModel):
    """Types are checked by the service so every error has a code."""
    model_config = ConfigDict(extra="forbid")

    display_name: Optional[Any] = None
    country: Optional[Any] = None
    home_currency: Optional[Any] = None
    language: Optional[Any] = None
    dividend_tax_view: Optional[Any] = None
    compare_index: Optional[Any] = None
    holdings_native_currency: Optional[Any] = None
    auto_dividends: Optional[Any] = None   # migration 032 (the service answers 422 invalid_value if not a bool)


@router.get("", dependencies=[Depends(require_feature("area.profile"))])
async def get_profile(user: dict = Depends(get_current_user)):
    return await run_db(profile_service.get_profile, user)


@router.put("", dependencies=[Depends(require_feature("area.profile"))])
async def update_profile(body: ProfileUpdate, user: dict = Depends(get_current_user)):
    patch = {k: getattr(body, k) for k in body.model_fields_set}
    return await run_db(profile_service.update_profile, user, patch)


@router.get("/options", dependencies=[Depends(require_feature("area.profile"))])
async def profile_options(user: dict = Depends(get_current_user)):
    """Choices for the profile form: {"countries", "currencies", "convertible_currencies",
    "languages", "compare_indexes": [{"symbol", "name"}], "tax_view_countries"}."""
    return {
        "countries": sorted(profile_service.COUNTRIES),
        "currencies": sorted(profile_service.CURRENCIES),
        "convertible_currencies": sorted(profile_service.CONVERTIBLE_CURRENCIES),
        "languages": list(profile_service.LANGUAGES),
        "compare_indexes": [{"symbol": s, "name": n} for s, n in profile_service.COMPARE_INDEXES.items()],
        "tax_view_countries": sorted(profile_service.TAX_VIEW_COUNTRIES),
    }
