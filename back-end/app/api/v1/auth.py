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
async def refresh_token(request: Request, user: dict = Depends(get_current_user)):
    """Refresh the JWT access token. (Protected)"""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.split(" ", 1)[1] if " " in auth_header else ""

    result = auth_service.refresh_token(
        token=token,
        user_id=user["user_id"],
        username=user["username"],
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
    )
    return TokenResponse(**result)
