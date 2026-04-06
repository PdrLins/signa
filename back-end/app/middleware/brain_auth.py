"""Brain Editor authentication — second layer of protection.

Validates the X-Brain-Token header issued after Telegram OTP challenge.
This is ON TOP of the existing JWT auth — both are required.
"""

from fastapi import Depends, HTTPException, Request, status

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.db.supabase import get_client

import jwt as pyjwt
from jwt.exceptions import PyJWTError


def _decode_brain_token(token: str) -> dict | None:
    """Decode and validate a brain token."""
    try:
        payload = pyjwt.decode(
            token,
            settings.brain_token_secret,
            algorithms=[settings.jwt_algorithm],
        )
        if payload.get("type") != "brain_editor":
            return None
        return payload
    except PyJWTError:
        return None


async def require_brain_token(
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict:
    """Dependency that requires both JWT auth AND a valid brain token.

    Use this on all brain content endpoints (not highlights/challenge).
    """
    brain_token = request.headers.get("X-Brain-Token")

    if not brain_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Brain Editor access required. Request a code first.",
        )

    payload = _decode_brain_token(brain_token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or expired brain token. Please re-verify.",
        )

    # Verify user matches
    if payload.get("sub") != user.get("user_id"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Brain token user mismatch.",
        )

    # JTI is required — reject tokens without one
    jti = payload.get("jti")
    if not jti:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid brain token (missing session ID). Please re-verify.",
        )

    # Verify JTI exists in brain_sessions
    client = get_client()
    result = (
        client.table("brain_sessions")
        .select("id")
        .eq("brain_token_jti", jti)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Brain session not found. Please re-verify.",
        )

    return {**user, "brain_jti": jti}
