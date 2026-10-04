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
    # a username or, for email accounts (migration 018), the email address
    username: str = Field(..., min_length=1, max_length=254)
    password: str = Field(..., min_length=1, max_length=128)
    # an account waiting for deletion (migration 030) answers 403
    # account_pending_deletion; sign in again with this set to keep it
    restore_account: bool = False


class LoginResponse(BaseModel):
    """OTP flow: session_token is set and the client calls /verify-otp.
    Password-only flow (LOGIN_OTP_ENABLED=false): access_token is set instead."""
    message: str = "OTP sent to your Telegram"
    session_token: Optional[str] = None
    # where the code went: "telegram" | "email" (null when no code is needed)
    code_via: Optional[str] = None
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


class SignupRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=128)
    language: Literal["en", "pt"] = "en"


class CodeSentResponse(BaseModel):
    """A code was (or, to avoid revealing accounts, may have been) emailed:
    send it back with this session_token."""
    session_token: str
    message: str


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)


class ResetPasswordRequest(BaseModel):
    session_token: str = Field(..., min_length=1, max_length=128)
    otp_code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")
    new_password: str = Field(..., min_length=1, max_length=128)


class EmailChangeRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=128)


class EmailConfirmRequest(BaseModel):
    session_token: str = Field(..., min_length=1, max_length=128)
    otp_code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class DeleteAccountRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=128)
