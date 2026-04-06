"""Pydantic models for authentication."""

from typing import Optional
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=128)


class LoginResponse(BaseModel):
    message: str = "OTP sent to your Telegram"
    session_token: str
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
