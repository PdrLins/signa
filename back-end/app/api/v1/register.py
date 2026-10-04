"""Invite-only sign-up and invite-code lookup (migration 019). Both PUBLIC
(app/middleware/auth.py) and rate-limited (app/middleware/rate_limit.py).

  POST /api/v1/auth/register            AUTH tier, every attempt counts
       {"username", "password", "referral_code",
        "client": "web" | "ios" (default "web"), "device_name": str | null,
        "country"?: "BR", "home_currency"?: "BRL", "language"?: "pt", "locale"?: "pt-BR"}
       (first profile settings; the currency defaults to the country's)
       201 — the same payload as a password-only POST /auth/login:
         {"message": "Account created", "session_token": null, "code_via": null,
          "access_token", "token_type": "bearer", "expires_in", "last_login": null,
          "refresh_token" (ios + 017), "session_id" (017), "session_expires_at" (017)}
       422 invalid_username | weak_password | invalid_referral, 409 username_taken,
       503 migration_required (019_referrals.sql)
  GET  /api/v1/auth/referral/{code}     lookup tier (20 / 15 min per IP)
       {"valid": bool} — case-insensitive, no personal data.
       503 migration_required (019_referrals.sql)
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Path, Request, status
from pydantic import Field

from app.core.api_errors import run_db_for, run_db_write
from app.core.utils import get_client_ip
from app.models.auth import DeviceInfo, LoginResponse
from app.services import profile_service, referrals, registration

router = APIRouter(prefix="/auth", tags=["Authentication"])


class RegisterRequest(DeviceInfo):
    # Loose limits here: the service answers invalid_username / weak_password.
    username: str = Field(..., max_length=100)
    password: str = Field(..., max_length=256)
    referral_code: Optional[str] = Field(None, max_length=32)
    # First settings (optional; the phone's region / language). Invalid values are ignored.
    country: Optional[str] = Field(None, max_length=8)        # ISO alpha-2, e.g. "BR"
    home_currency: Optional[str] = Field(None, max_length=8)  # ISO 4217; default: the country's
    language: Optional[str] = Field(None, max_length=8)       # "en" | "pt"
    locale: Optional[str] = Field(None, max_length=20)        # e.g. "pt-BR" (fills what's missing)


@router.post("/register", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
async def register(request: Request, body: RegisterRequest):
    """Create a free account with an invite code and sign it in. (Public)"""
    result = await run_db_write(
        referrals.MIGRATION, registration.register,
        body.username, body.password, body.referral_code or "",
        get_client_ip(request), request.headers.get("User-Agent", ""),
        body.client, body.device_name,
        profile_service.signup_settings(body.country, body.home_currency, body.language, body.locale),
    )
    return LoginResponse(**result)


@router.get("/referral/{code}")
async def referral_code_valid(code: str = Path(..., min_length=1, max_length=32)):
    """Is this invite code valid? {"valid": bool} (Public)"""
    return {"valid": await run_db_for(referrals.MIGRATION, referrals.is_valid_code, code)}
