"""Authentication routes — login, OTP verification, logout, refresh."""

from fastapi import APIRouter, Depends, Request

from app.core.dependencies import get_current_user
from app.core.utils import get_client_ip
from app.models.auth import (
    LoginRequest,
    LoginResponse,
    MessageResponse,
    OTPVerifyRequest,
    TokenResponse,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=LoginResponse)
async def login(request: Request, body: LoginRequest):
    """Step 1: Validate credentials and send OTP to Telegram. (Public)"""
    result = await auth_service.login(
        username=body.username,
        password=body.password,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
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
    )
    return TokenResponse(**result)


@router.post("/logout", response_model=MessageResponse)
async def logout(request: Request, user: dict = Depends(get_current_user)):
    """Invalidate the current JWT token. (Protected)"""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.split(" ", 1)[1] if " " in auth_header else ""

    auth_service.logout(
        token=token,
        user_id=user["user_id"],
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
    )
    return MessageResponse(message="Successfully logged out")


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(request: Request):
    """Refresh the JWT access token. Accepts expired tokens within a grace window.

    Grace period: 4 hours. Long enough for a normal work session, short
    enough that leaving overnight logs you out. Was 24h previously, which
    meant the silent refresh always succeeded and the user was never
    kicked out — defeating the purpose of token expiry.
    """
    from app.core.security import decode_token_allow_expired

    auth_header = request.headers.get("Authorization", "")
    token = auth_header.split(" ", 1)[1] if " " in auth_header else ""

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No token provided")

    payload = decode_token_allow_expired(token, max_age_hours=4)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token too old for refresh")

    user_id = payload.get("sub")
    username = payload.get("username")
    if not user_id or not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    result = auth_service.refresh_token(
        token=token,
        user_id=user_id,
        username=username,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
    )
    return TokenResponse(**result)
