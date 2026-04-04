"""JWT token management and password hashing."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from loguru import logger
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a password with bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(
    user_id: str,
    username: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT access token."""
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.jwt_access_token_expire_minutes)

    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "username": username,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(uuid4()),
    }

    token = _jwt_encode(payload)
    return token


def create_session_token() -> str:
    """Create a short-lived session token for OTP verification."""
    return secrets.token_urlsafe(32)


def decode_token(token: str) -> dict | None:
    """Decode and validate a JWT token.

    Returns token payload dict, or None if invalid/expired.
    """
    try:
        payload = _jwt_decode(token)
        return payload
    except Exception:
        logger.debug("Token decode failed")
        return None


def generate_otp() -> str:
    """Generate a 6-digit OTP code."""
    return f"{secrets.randbelow(900000) + 100000}"


def hash_otp(otp: str, salt: str = "") -> str:
    """Hash an OTP code with HMAC-SHA256 for storage.

    Uses the session_token as salt to prevent rainbow table attacks.
    """
    key = (settings.jwt_secret_key + salt).encode()
    return hmac.new(key, otp.encode(), hashlib.sha256).hexdigest()


def verify_otp(plain_otp: str, hashed_otp: str, salt: str = "") -> bool:
    """Verify an OTP against its hash using constant-time comparison."""
    return hmac.compare_digest(hash_otp(plain_otp, salt), hashed_otp)


# --- JWT helpers (abstracts library choice) ---

def _jwt_encode(payload: dict) -> str:
    """Encode a JWT payload. Wraps the JWT library."""
    from jose import jwt as jose_jwt
    return jose_jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _jwt_decode(token: str) -> dict:
    """Decode a JWT token. Wraps the JWT library."""
    from jose import jwt as jose_jwt
    return jose_jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
