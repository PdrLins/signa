"""Pydantic models for authentication."""

from typing import Literal, Optional
from pydantic import BaseModel, Field

Client = Literal["web", "ios"]


class DeviceInfo(BaseModel):
    """Which app is signing in (migration 017 sessions). The iOS app sends
    client="ios" and the device's name ("Pedro's iPhone"); the web sends
    nothing (defaults to "web", named from its User-Agent)."""
    client: Client = "web"
    device_name: Optional[str] = Field(None, max_length=80)


class LoginRequest(DeviceInfo):
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
    refresh_token: Optional[str] = None
    session_id: Optional[str] = None
    session_expires_at: Optional[str] = None


class OTPVerifyRequest(DeviceInfo):
    session_token: str = Field(..., min_length=1, max_length=128)
    otp_code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class TokenResponse(BaseModel):
    """refresh_token is set for client="ios" only (keep it in the Keychain);
    session_id / session_expires_at once migration 017 is applied."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 3600
    last_login: Optional[str] = None
    refresh_token: Optional[str] = None
    session_id: Optional[str] = None
    session_expires_at: Optional[str] = None


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=20, max_length=200)


class SessionView(BaseModel):
    id: str
    client: Optional[str] = None
    device_name: Optional[str] = None
    created_at: Optional[str] = None
    last_used_at: Optional[str] = None
    expires_at: Optional[str] = None
    current: bool = False


class MessageResponse(BaseModel):
    message: str
