"""Authentication routes — login, OTP verification, logout, refresh."""

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.core.access import FEATURE_CATALOG, allowed_features, get_feature_levels
from app.core.config import settings
from app.core.dependencies import get_current_user
from app.core.utils import get_client_ip
from app.models.auth import (
    LoginRequest,
    LoginResponse,
    MessageResponse,
    OTPVerifyRequest,
    RefreshRequest,
    SessionView,
    TokenResponse,
)
from app.core.api_errors import api_error, is_missing_schema, migration_required
from app.services import auth_service, sessions

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=LoginResponse)
async def login(request: Request, body: LoginRequest):
    """Step 1: Validate credentials and send OTP to Telegram. (Public)"""
    result = await auth_service.login(
        username=body.username,
        password=body.password,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
        client=body.client,
        device_name=body.device_name,
    )
    return LoginResponse(**result)


@router.post("/verify-otp", response_model=TokenResponse)
async def verify_otp(request: Request, body: OTPVerifyRequest):
    """Step 2: Verify OTP and receive JWT access token. (Public)"""
    result = await auth_service.verify_otp_code(
        session_token=body.session_token,
        otp_code=body.otp_code,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
        client=body.client,
        device_name=body.device_name,
    )
    return TokenResponse(**result)


@router.post("/logout", response_model=MessageResponse)
async def logout(request: Request, user: dict = Depends(get_current_user)):
    """Invalidate the current JWT token. (Protected)"""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.split(" ", 1)[1] if " " in auth_header else ""

    await asyncio.to_thread(
        auth_service.logout,
        token=token,
        user_id=user["user_id"],
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
    )
    return MessageResponse(message="Successfully logged out")


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(request: Request):
    """Rotate the JWT access token. (Public — validated here, not by middleware)

    Accepts a token that expired less than JWT_REFRESH_GRACE_HOURS ago. The
    presented token is revoked (single use), revoked tokens are rejected, and
    the total session is capped at JWT_MAX_SESSION_HOURS since OTP login.
    """
    from app.core.security import decode_token_allow_expired

    auth_header = request.headers.get("Authorization", "")
    token = auth_header.split(" ", 1)[1].strip() if auth_header.startswith("Bearer ") else ""

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No token provided")

    payload = decode_token_allow_expired(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token too old for refresh")

    try:
        result = await asyncio.to_thread(
            auth_service.refresh_token,
            payload=payload,
            ip_address=get_client_ip(request),
            user_agent=request.headers.get("User-Agent", ""),
        )
    except auth_service.TokenRefreshError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=e.detail,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenResponse(**result)


@router.post("/token/refresh", response_model=TokenResponse)
async def refresh_with_session(request: Request, body: RefreshRequest):
    """iOS: trade a refresh token for a new access token and a NEW refresh
    token (the old one stops working). (Public — the refresh token is the credential)

    Body {"refresh_token"}. 200 TokenResponse with refresh_token, session_id,
    session_expires_at. 401 {"detail": {"code": "invalid_refresh" |
    "session_revoked" | "session_expired" | "reuse_detected", "message"}}:
    sign in again. reuse_detected means an old refresh token was presented:
    the session is ended everywhere. 503 migration_required before 017.
    Lost response: re-presenting the token just rotated, within
    settings.session_refresh_grace_seconds (30 s) and before the new one is
    used, returns 200 with the SAME new refresh_token (and a fresh access
    token) once per rotation; later or older tokens -> reuse_detected.
    """
    import asyncio

    try:
        result = await asyncio.to_thread(
            auth_service.refresh_session, body.refresh_token,
            get_client_ip(request), request.headers.get("User-Agent", ""),
        )
    except sessions.SessionError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail={"code": e.code, "message": e.message},
                            headers={"WWW-Authenticate": "Bearer"})
    except Exception as e:
        if is_missing_schema(e):
            raise migration_required(sessions.MIGRATION)
        raise
    return TokenResponse(**result)


async def _sessions_call(fn, *args):
    from app.core.api_errors import run_db_for
    return await run_db_for(sessions.MIGRATION, fn, *args)


@router.get("/sessions", response_model=list[SessionView])
async def list_sessions(user: dict = Depends(get_current_user)):
    """Where the user is signed in: active sessions, most recent first;
    `current` marks the device making this request."""
    return await _sessions_call(sessions.list_for_user, user["user_id"], user.get("sid"))


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(session_id: UUID, request: Request, user: dict = Depends(get_current_user)):
    """Sign out one device (any of the user's own sessions, including this
    one). 404 session_not_found when it isn't the user's or is already ended."""
    done = await _sessions_call(sessions.revoke, str(session_id), user["user_id"], "user")
    if not done:
        raise api_error("session_not_found", "That device is not signed in.", status.HTTP_404_NOT_FOUND)
    from app.db.queries import insert_audit_log
    from app.models.audit import AuditEvent
    await asyncio.to_thread(insert_audit_log, event_type=AuditEvent.SESSION_REVOKED, success=True,
                            user_id=user["user_id"], ip_address=get_client_ip(request),
                            user_agent=request.headers.get("User-Agent", ""),
                            metadata={"session_id": str(session_id), "reason": "user"})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sessions/revoke-others")
async def revoke_other_sessions(request: Request, user: dict = Depends(get_current_user)):
    """Sign out every other device; this one stays signed in. {"revoked": n}"""
    n = await _sessions_call(sessions.revoke_others, user["user_id"], user.get("sid"))
    from app.db.queries import insert_audit_log
    from app.models.audit import AuditEvent
    await asyncio.to_thread(insert_audit_log, event_type=AuditEvent.SESSION_REVOKED, success=True,
                            user_id=user["user_id"], ip_address=get_client_ip(request),
                            user_agent=request.headers.get("User-Agent", ""),
                            metadata={"reason": "others", "count": n})
    return {"revoked": n}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    """Who am I and what can I use? The single source of access for every
    client (web, iOS): the level, every allowed area/action key, the full
    catalog (key -> min level, so a client can show "premium" badges on
    locked items) and followed-stock slots."""
    from app.services import referrals, slots

    level = user.get("access_level") or "free"
    levels = get_feature_levels()
    account_id, slot_info = await asyncio.gather(
        asyncio.to_thread(referrals.account_id_for, user["user_id"]),
        asyncio.to_thread(slots.slot_summary, user))
    return {
        "user_id": user["user_id"],
        "username": user.get("username"),
        # visible account ID = invite code (migration 019; null before it)
        "account_id": account_id,
        "access_level": level,
        # Dev tools ("View as"): the real level and whether the switch may be
        # shown (owner + DEV_TOOLS_ENABLED). Clients ignore these otherwise.
        "real_access_level": user.get("real_access_level") or level,
        "dev_tools": bool(settings.dev_tools_enabled
                          and (user.get("real_access_level") or level) == "owner"),
        "features": allowed_features(level),
        "catalog": [
            {"key": k, "min_level": levels[k], "description": FEATURE_CATALOG.get(k, ("", ""))[1]}
            for k in sorted(levels)
        ],
        "slots": slot_info,
    }
