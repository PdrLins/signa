"""JWT token management and password hashing."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import bcrypt
from loguru import logger

from app.core.config import settings

# bcrypt only uses the first 72 bytes of input; bcrypt>=5 raises on longer
# input. We reject over-long passwords at creation time and treat them as a
# failed verification (never silently truncate).
BCRYPT_MAX_BYTES = 72
_BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    """Hash a password with bcrypt ($2b$, 12 rounds).

    Raises ValueError if the password exceeds bcrypt's 72-byte limit.
    """
    pw = password.encode("utf-8")
    if len(pw) > BCRYPT_MAX_BYTES:
        raise ValueError(f"Password too long (max {BCRYPT_MAX_BYTES} bytes in UTF-8)")
    return bcrypt.hashpw(pw, bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("ascii")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a standard bcrypt hash ($2a$/$2b$/$2y$).

    Never raises: malformed hashes or over-long passwords return False.
    """
    try:
        pw = plain_password.encode("utf-8")
        if len(pw) > BCRYPT_MAX_BYTES or not hashed_password:
            return False
        return bcrypt.checkpw(pw, hashed_password.encode("ascii"))
    except (ValueError, TypeError, UnicodeError):
        logger.debug("Password verification failed (malformed input/hash)")
        return False


def create_access_token(
    user_id: str,
    username: str,
    expires_delta: timedelta | None = None,
    auth_time: int | None = None,
    session_id: str | None = None,
    client: str | None = None,
) -> str:
    """Create a JWT access token.

    `auth_time` is the Unix time of the original OTP login; it is preserved
    across refreshes so the total session length can be capped.
    `session_id` (claim `sid`, migration 017) ties the token to a signed-in
    device: revoking the session rejects the token. `client` (claim `cli`)
    is "web" or "ios". Both are left out when not given (pre-016 tokens).
    """
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.jwt_access_token_expire_minutes)

    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "username": username,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(uuid4()),
        "auth_time": int(auth_time if auth_time is not None else now.timestamp()),
    }
    if session_id:
        payload["sid"] = session_id
    if client:
        payload["cli"] = client

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


def decode_token_allow_expired(token: str, max_age_hours: int | None = None) -> dict | None:
    """Decode a JWT token even if expired, within a grace period.

    Used for token refresh -- allows refreshing tokens that expired
    recently (within max_age_hours, default JWT_REFRESH_GRACE_HOURS)
    without forcing re-login. Signature is always verified.
    """
    import jwt as pyjwt

    if max_age_hours is None:
        max_age_hours = settings.jwt_refresh_grace_hours
    try:
        payload = pyjwt.decode(
            token, settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"verify_exp": False, "require": ["exp", "sub", "jti"]},
        )
        # Check the token isn't TOO old
        exp = payload.get("exp", 0)
        now = datetime.now(timezone.utc).timestamp()
        if now - exp > max_age_hours * 3600:
            logger.debug("Token too old for refresh")
            return None
        return payload
    except Exception:
        logger.debug("Token decode failed (even with expired allowed)")
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
    import jwt as pyjwt
    return pyjwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _jwt_decode(token: str) -> dict:
    """Decode a JWT token. Wraps the JWT library."""
    import jwt as pyjwt
    return pyjwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


def create_brain_token(user_id: str, jti: str) -> str:
    """Create a brain editor JWT signed with the separate brain secret."""
    import jwt as pyjwt
    now = datetime.now(timezone.utc)
    expires_delta = timedelta(minutes=settings.brain_token_expire_minutes)
    payload = {
        "sub": user_id,
        "type": "brain_editor",
        "iat": now,
        "exp": now + expires_delta,
        "jti": jti,
    }
    return pyjwt.encode(payload, settings.brain_token_secret, algorithm=settings.jwt_algorithm)


def supabase_key_role(key: str) -> str | None:
    """Return the `role` claim of a Supabase API key JWT, or None.

    Decodes the payload with base64 only — NO signature verification — purely
    to tell an anon key from a service_role key at startup. Never log `key`.
    New-style Supabase keys (sb_publishable_... / sb_secret_...) aren't JWTs;
    they are mapped by prefix.
    """
    import base64
    import json

    if not key:
        return None
    if key.startswith("sb_publishable_"):
        return "anon"
    if key.startswith("sb_secret_"):
        return "service_role"
    parts = key.split(".")
    if len(parts) != 3:
        return None
    try:
        seg = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(seg))
        role = claims.get("role") if isinstance(claims, dict) else None
        return role if isinstance(role, str) else None
    except Exception:
        return None
