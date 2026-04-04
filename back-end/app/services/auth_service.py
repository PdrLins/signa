"""Authentication service — login, OTP, token management."""

from datetime import datetime, timedelta, timezone

from loguru import logger

from app.core.config import settings
from app.core.exceptions import (
    AuthenticationError,
    OTPExpiredError,
    OTPInvalidError,
)
from app.core.security import (
    create_access_token,
    create_session_token,
    decode_token,
    generate_otp,
    hash_otp,
    verify_otp,
    verify_password,
)
from app.db import queries
from app.models.audit import AuditEvent
from app.notifications.telegram_bot import send_otp_message


async def login(
    username: str,
    password: str,
    ip_address: str,
    user_agent: str,
) -> dict:
    """Step 1: Validate credentials and send OTP via Telegram."""
    user = queries.get_user_by_username(username)

    if user is None or not verify_password(password, user["password_hash"]):
        queries.insert_audit_log(
            event_type=AuditEvent.LOGIN_ATTEMPT,
            success=False,
            user_id=user["id"] if user else None,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"username": username},
        )
        raise AuthenticationError("Invalid username or password")

    queries.insert_audit_log(
        event_type=AuditEvent.LOGIN_ATTEMPT,
        success=True,
        user_id=user["id"],
        ip_address=ip_address,
        user_agent=user_agent,
    )

    # Generate OTP and session token
    otp_code = generate_otp()
    session_token = create_session_token()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.otp_expire_seconds)

    # Store OTP (hashed with session_token as salt)
    queries.insert_otp(
        user_id=user["id"],
        session_token=session_token,
        code_hash=hash_otp(otp_code, salt=session_token),
        expires_at=expires_at,
    )

    await send_otp_message(user["telegram_chat_id"], otp_code)

    queries.insert_audit_log(
        event_type=AuditEvent.OTP_SENT,
        success=True,
        user_id=user["id"],
        ip_address=ip_address,
        user_agent=user_agent,
    )

    logger.info(f"OTP sent to user {username}")

    return {
        "message": "OTP sent to your Telegram",
        "session_token": session_token,
    }


async def verify_otp_code(
    session_token: str,
    otp_code: str,
    ip_address: str,
    user_agent: str,
) -> dict:
    """Step 2: Verify OTP and issue JWT."""
    otp_record = queries.get_otp_by_session_token(session_token)

    if otp_record is None:
        raise AuthenticationError("Invalid or expired session token")

    user_id = otp_record["user_id"]

    # Check expiration
    expires_at = datetime.fromisoformat(otp_record["expires_at"])
    if datetime.now(timezone.utc) > expires_at:
        queries.invalidate_otp(otp_record["id"])
        queries.insert_audit_log(
            event_type=AuditEvent.OTP_EXPIRED,
            success=False,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        raise OTPExpiredError("OTP has expired. Please login again.")

    # Check attempt limit
    attempts = otp_record.get("attempts", 0)
    if attempts >= settings.max_otp_attempts_per_session:
        queries.invalidate_otp(otp_record["id"])
        queries.insert_audit_log(
            event_type=AuditEvent.OTP_FAILED,
            success=False,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"reason": "max_attempts_exceeded"},
        )
        raise AuthenticationError("Too many OTP attempts. Please login again.")

    # Verify OTP (constant-time comparison, salted with session_token)
    if not verify_otp(otp_code, otp_record["code_hash"], salt=session_token):
        queries.increment_otp_attempts(otp_record["id"])
        remaining = settings.max_otp_attempts_per_session - attempts - 1
        queries.insert_audit_log(
            event_type=AuditEvent.OTP_FAILED,
            success=False,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"attempts": attempts + 1, "remaining": remaining},
        )
        raise OTPInvalidError(
            detail="Invalid OTP code",
            attempts_remaining=max(0, remaining),
        )

    # OTP valid — mark used
    queries.mark_otp_used(otp_record["id"])

    # Get user info (excludes password_hash)
    user = queries.get_user_by_id(user_id)
    if not user:
        raise AuthenticationError("User not found")

    # Issue JWT
    access_token = create_access_token(
        user_id=user["id"],
        username=user["username"],
    )

    queries.update_user_last_login(user["id"])

    queries.insert_audit_log(
        event_type=AuditEvent.OTP_VERIFIED,
        success=True,
        user_id=user["id"],
        ip_address=ip_address,
        user_agent=user_agent,
    )
    queries.insert_audit_log(
        event_type=AuditEvent.TOKEN_ISSUED,
        success=True,
        user_id=user["id"],
        ip_address=ip_address,
        user_agent=user_agent,
    )

    logger.info(f"JWT issued for user {user['username']}")

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.jwt_access_token_expire_minutes * 60,
    }


def logout(token: str, user_id: str, ip_address: str, user_agent: str) -> None:
    """Invalidate a JWT by adding it to the blacklist."""
    payload = decode_token(token)
    if payload:
        jti = payload.get("jti")
        exp = payload.get("exp")
        if jti:
            expires_at = datetime.fromtimestamp(exp, tz=timezone.utc) if exp else datetime.now(timezone.utc)
            queries.blacklist_token(jti, user_id, expires_at)
            queries.insert_audit_log(
                event_type=AuditEvent.TOKEN_REVOKED,
                success=True,
                user_id=user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )


def refresh_token(token: str, user_id: str, username: str, ip_address: str, user_agent: str) -> dict:
    """Issue a new JWT and blacklist the old one."""
    payload = decode_token(token)
    if payload:
        jti = payload.get("jti")
        exp = payload.get("exp")
        if jti:
            expires_at = datetime.fromtimestamp(exp, tz=timezone.utc) if exp else datetime.now(timezone.utc)
            queries.blacklist_token(jti, user_id, expires_at)

    new_token = create_access_token(user_id=user_id, username=username)

    queries.insert_audit_log(
        event_type=AuditEvent.TOKEN_REFRESHED,
        success=True,
        user_id=user_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return {
        "access_token": new_token,
        "token_type": "bearer",
        "expires_in": settings.jwt_access_token_expire_minutes * 60,
    }
