"""Pydantic models for authentication."""

from typing import Optional
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=128)


class LoginResponse(BaseModel):
    """OTP flow: session_token is set and the client calls /verify-otp.
    Password-only flow (LOGIN_OTP_ENABLED=false): access_token is set instead."""
    message: str = "OTP sent to your Telegram"
    session_token: Optional[str] = None
    access_token: Optional[str] = None
    token_type: Optional[str] = None
    expires_in: Optional[int] = None
    last_login: Optional[str] = None


class OTPVerifyRequest(BaseModel):
    session_token: str = Field(..., min_length=1, max_length=128)
    otp_code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 3600
    last_login: Optional[str] = None


class MessageResponse(BaseModel):
    message: str
