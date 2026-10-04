"""Authentication service — login, OTP, token management."""

import math
import asyncio
from datetime import datetime, timedelta, timezone

from loguru import logger

from app.core.cache import TTLCache

from app.core.config import settings
from app.core.exceptions import (
    AccountLockedError,
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
from app.services import identity, sessions, two_factor
from app.models.audit import AuditEvent
from app.notifications.telegram_bot import send_otp_message

# Per-account lockout (secondary defence — the per-IP limit in
# RateLimitMiddleware is the primary brute-force control). Exponential
# backoff: after LOCKOUT_THRESHOLD consecutive failures the account is locked
# for LOCKOUT_BASE_SECONDS, doubling on each further failure, capped at
# LOCKOUT_MAX_SECONDS. Kept short so an attacker who knows the username
# can't lock the owner out for long.
LOCKOUT_THRESHOLD = 5
LOCKOUT_BASE_SECONDS = 60
LOCKOUT_MAX_SECONDS = 900
# Failure counter is forgotten this long after the last lock expired.
LOCKOUT_DECAY_SECONDS = 3600

# Generic message for every credential failure: never confirm whether the
# username exists or how many attempts remain.
INVALID_CREDENTIALS = "Invalid credentials."

# Valid bcrypt hash of a random throwaway value — used to equalise timing when
# the username doesn't exist (so response time doesn't reveal valid usernames).
_DUMMY_HASH = "$2b$12$6pxyrxnCXf11H1Wprx7.desTp9kmB9IIsFnnPfsi6.k3ylpbxMQCG"


# username|ip -> failed attempts in the last 15 min (see _login_sync)
_device_failures = TTLCache(max_size=50000, default_ttl=15 * 60)


def lockout_seconds(attempts: int) -> int:
    """Lock duration for a given consecutive-failure count (0 = no lock)."""
    if attempts < LOCKOUT_THRESHOLD:
        return 0
    return min(LOCKOUT_BASE_SECONDS * (2 ** (attempts - LOCKOUT_THRESHOLD)), LOCKOUT_MAX_SECONDS)


def _locked_error(remaining: int) -> AccountLockedError:
    minutes = max(1, math.ceil(remaining / 60))
    return AccountLockedError(
        detail=f"Too many failed attempts — temporarily locked. Try again in {minutes} minute{'s' if minutes != 1 else ''}.",
        retry_after=remaining,
    )


async def login(
    username: str,
    password: str,
    ip_address: str,
    user_agent: str,
    client: str = "web",
    device_name: str | None = None,
    restore_account: bool = False,
) -> dict:
    """Step 1: Validate credentials and send OTP via Telegram.

    The password hash check (bcrypt, ~250 ms of CPU) and the DB calls run in a
    worker thread, so a sign-in never freezes other users' requests. Only the
    Telegram enqueue (an asyncio queue) runs here."""
    result, otp = await asyncio.to_thread(_login_sync, username, password, ip_address, user_agent,
                                          client, device_name, restore_account)
    if otp:
        await send_otp_message(*otp)
    return result


def _login_sync(
    username: str,
    password: str,
    ip_address: str,
    user_agent: str,
    client: str = "web",
    device_name: str | None = None,
    restore_account: bool = False,
) -> tuple[dict, tuple[str, str] | None]:
    """(response, (chat_id, code) to send or None). Blocking."""
    from app.db.supabase import get_client
    db = get_client()

    # a username, or an email address (migration 018; active or not)
    user = identity.find_user_for_login(username) if "@" in username else queries.get_user_by_username(username.lower())

    # Failures from THIS device (username + IP): an account lock only stops
    # devices that have been failing. The owner, on a device that hasn't
    # failed, still gets in with the right password, so a stranger can't keep
    # an account locked by sending one wrong password every 15 minutes.
    fail_key = f"{username.strip().lower()}|{ip_address}"
    device_fails = _device_failures.get(fail_key) or 0
    if lockout_seconds(device_fails):
        raise _locked_error(LOCKOUT_BASE_SECONDS)   # same answer for real and unknown usernames

    # ── Check DB lockout ──
    locked_remaining = 0
    if user:
        locked_until = user.get("locked_until")
        if locked_until:
            lock_time = datetime.fromisoformat(locked_until)
            now = datetime.now(timezone.utc)
            if now < lock_time:
                locked_remaining = int((lock_time - now).total_seconds())
            elif (now - lock_time).total_seconds() > LOCKOUT_DECAY_SECONDS:
                # Lock expired long ago — forget the failure streak
                db.table("users").update({
                    "login_attempts": 0,
                    "locked_until": None,
                }).eq("id", user["id"]).execute()
                user["login_attempts"] = 0
                user["locked_until"] = None

    if user is None:
        verify_password(password, _DUMMY_HASH)  # constant-ish timing
        _device_failures.set(fail_key, device_fails + 1)
        raise AuthenticationError(INVALID_CREDENTIALS)

    password_ok = verify_password(password, user["password_hash"])
    if locked_remaining and not (password_ok and device_fails == 0):
        if not password_ok:
            _device_failures.set(fail_key, device_fails + 1)
        raise _locked_error(locked_remaining)

    if not password_ok:
        _device_failures.set(fail_key, device_fails + 1)
        # ── Increment failed attempts in DB ──
        attempts = (user.get("login_attempts") or 0) + 1
        lock_secs = lockout_seconds(attempts)
        update: dict = {"login_attempts": attempts}
        if lock_secs:
            update["locked_until"] = (datetime.now(timezone.utc) + timedelta(seconds=lock_secs)).isoformat()
        db.table("users").update(update).eq("id", user["id"]).execute()

        queries.insert_audit_log(
            event_type=AuditEvent.LOGIN_LOCKED if lock_secs else AuditEvent.LOGIN_ATTEMPT,
            success=False,
            user_id=user["id"],
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"attempts": attempts, "lockout_seconds": lock_secs},
        )
        if lock_secs:
            logger.warning(f"Account locked for {lock_secs}s after {attempts} failed attempts")
        # Same generic error whether or not this attempt triggered a lock.
        raise AuthenticationError(INVALID_CREDENTIALS)

    # ── Account waiting for deletion (migration 030): ask before restoring ──
    from app.services import account
    pending = account.pending_deletion_date(user)
    if pending:
        if not restore_account:
            from app.core.api_errors import api_error
            raise api_error("account_pending_deletion",
                            f"This account is scheduled for deletion on {pending}. Sign in again to restore it.",
                            403, deletion_date=pending)
        account.restore(str(user["id"]))

    # ── Inactive account: an unconfirmed sign-up gets a fresh code; any
    # other inactive account looks like a wrong password. ──
    if user.get("is_active") is False:
        if user.get("email") and not user.get("email_verified_at"):
            from app.services import email_sender
            token, code = identity.issue_code(user["id"], "login", user["email"])
            email_sender.send_code(user["email"], "signup", code, identity._language(user["id"]))
            return {"message": "We sent a code to your email", "session_token": token, "code_via": "email"}, None
        raise AuthenticationError(INVALID_CREDENTIALS)

    # ── Successful credentials — clear attempts in DB ──
    db.table("users").update({
        "login_attempts": 0,
        "locked_until": None,
    }).eq("id", user["id"]).execute()

    queries.insert_audit_log(
        event_type=AuditEvent.LOGIN_ATTEMPT,
        success=True,
        user_id=user["id"],
        ip_address=ip_address,
        user_agent=user_agent,
    )

    if not settings.login_otp_enabled or not two_factor.is_enabled(user):
        # Password-only sign-in: two-step sign-in is off for this account
        # (migration 020), or LOGIN_OTP_ENABLED=false.
        token = _issue_access_token(user, ip_address, user_agent, client, device_name)
        return {"message": "Logged in", "session_token": None, "code_via": None, **token}, None

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

    queries.insert_audit_log(
        event_type=AuditEvent.OTP_SENT,
        success=True,
        user_id=user["id"],
        ip_address=ip_address,
        user_agent=user_agent,
    )

    logger.info(f"OTP sent to user {str(user['id'])[:8]}")

    return {
        "message": "OTP sent to your Telegram",
        "session_token": session_token,
        "last_login": user.get("last_login"),
        "code_via": "telegram",
    }, (user["telegram_chat_id"], otp_code)


async def verify_otp_code(
    session_token: str,
    otp_code: str,
    ip_address: str,
    user_agent: str,
    client: str = "web",
    device_name: str | None = None,
) -> dict:
    """Step 2: Verify OTP and issue JWT (blocking work in a worker thread)."""
    return await asyncio.to_thread(_verify_otp_sync, session_token, otp_code, ip_address, user_agent,
                                   client, device_name)


def _verify_otp_sync(
    session_token: str,
    otp_code: str,
    ip_address: str,
    user_agent: str,
    client: str = "web",
    device_name: str | None = None,
) -> dict:
    otp_record = queries.get_otp_by_session_token(session_token)

    if otp_record is None:
        raise AuthenticationError("Invalid or expired session token")

    user_id = otp_record["user_id"]

    # A reset or new-email code can't sign anyone in (migration 018 purpose)
    if (otp_record.get("purpose") or "login") != "login":
        raise AuthenticationError("Invalid or expired session token")

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

    # OTP valid — mark used atomically (only succeeds if still unused, so two
    # concurrent requests with the same OTP can't both get a token)
    if not queries.mark_otp_used(otp_record["id"]):
        raise AuthenticationError("Invalid or expired session token")

    # A confirmed sign-up code activates the account (migration 018)
    if otp_record.get("email"):
        identity.activate_if_pending(otp_record)

    # Get user info (excludes password_hash)
    user = queries.get_user_by_id(user_id)
    if not user:
        raise AuthenticationError("User not found")

    queries.insert_audit_log(
        event_type=AuditEvent.OTP_VERIFIED,
        success=True,
        user_id=user["id"],
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return _issue_access_token(user, ip_address, user_agent, client, device_name)


def _issue_access_token(user: dict, ip_address: str, user_agent: str,
                        client: str = "web", device_name: str | None = None) -> dict:
    """Issue a JWT for an authenticated user, open a session for this device
    (migration 017) and record the login. iOS also gets a refresh token."""
    client = sessions.normalize_client(client)
    sess = sessions.create(user, client, device_name, ip_address, user_agent)
    minutes = sessions.access_minutes(client)
    access_token = create_access_token(
        user_id=user["id"],
        username=user["username"],
        expires_delta=timedelta(minutes=minutes),
        session_id=sess["session_id"],
        client=client if sess["session_id"] else None,
    )

    # Capture previous last_login before updating
    previous_login = user.get("last_login")
    queries.update_user_last_login(user["id"])

    queries.insert_audit_log(
        event_type=AuditEvent.TOKEN_ISSUED,
        success=True,
        user_id=user["id"],
        ip_address=ip_address,
        user_agent=user_agent,
    )

    logger.info(f"JWT issued for user {str(user['id'])[:8]}")

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": minutes * 60,
        "last_login": previous_login,
        "refresh_token": sess["refresh_token"],
        "session_id": sess["session_id"],
        "session_expires_at": sess["expires_at"],
    }


def logout(token: str, user_id: str, ip_address: str, user_agent: str) -> None:
    """Invalidate a JWT by adding it to the blacklist, and end its session
    (so the device's refresh token stops working too)."""
    payload = decode_token(token)
    if payload and payload.get("sid"):
        try:
            sessions.revoke(payload["sid"], user_id, "logout")
        except Exception as e:
            logger.warning(f"logout: could not revoke session: {e}")
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


class TokenRefreshError(AuthenticationError):
    """Refresh rejected (revoked, replayed, or session too old)."""


def refresh_token(payload: dict, ip_address: str, user_agent: str) -> dict:
    """Rotate a JWT: revoke the presented token's JTI and issue a new one.

    `payload` must be the already signature-verified claims of the presented
    token (it may be expired, within the grace window). Raises
    TokenRefreshError if the token is revoked, already rotated (replay), or
    the session exceeded the absolute maximum lifetime.
    """
    user_id = payload.get("sub")
    username = payload.get("username")
    jti = payload.get("jti")
    if not user_id or not username or not jti:
        raise TokenRefreshError("Invalid token")

    if queries.is_token_blacklisted(jti):
        raise TokenRefreshError("Token has been revoked")

    sid = payload.get("sid")
    u = queries.get_user_by_id(user_id)   # a disabled or deleted account can't refresh
    if not u or u.get("is_active") is False:
        raise TokenRefreshError("Account is not active")

    if sid and not sessions.is_active(sid):
        raise TokenRefreshError("Session has been revoked")

    # Absolute session cap: auth_time is carried across refreshes (falls back
    # to iat for tokens minted before this claim existed).
    now = datetime.now(timezone.utc)
    auth_time = payload.get("auth_time") or payload.get("iat")
    if not auth_time or now.timestamp() - float(auth_time) > settings.jwt_max_session_hours * 3600:
        raise TokenRefreshError("Session expired. Please login again.")

    # Revoke the presented token. token_jti is UNIQUE, so if two refreshes race
    # with the same token only one insert succeeds; the loser is rejected.
    exp = payload.get("exp")
    expires_at = datetime.fromtimestamp(exp, tz=timezone.utc) if exp else now
    try:
        queries.blacklist_token(jti, user_id, expires_at)
    except Exception as e:
        text = str(e).lower()
        if "23505" in text or "duplicate" in text:   # a concurrent refresh already used this token
            logger.warning("Refresh rejected: token JTI already revoked")
            raise TokenRefreshError("Token has been revoked")
        # a DB blip must not sign the user out: they retry the refresh
        logger.warning(f"Refresh failed: blacklist write failed ({type(e).__name__})")
        from app.core.api_errors import api_error
        raise api_error("service_unavailable", "Please try again in a moment.", 503)

    minutes = sessions.access_minutes(payload.get("cli") or "web")
    new_token = create_access_token(user_id=user_id, username=username, auth_time=int(float(auth_time)),
                                    expires_delta=timedelta(minutes=minutes),
                                    session_id=sid, client=payload.get("cli"))
    sessions.touch(sid, ip_address, user_agent)

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
        "expires_in": minutes * 60,
    }


def refresh_session(refresh_token: str, ip_address: str, user_agent: str) -> dict:
    """iOS: exchange a refresh token for a new access token AND a new refresh
    token (rotation, reuse detection: app.services.sessions.rotate).

    Raises sessions.SessionError (-> 401 with its code) or the DB error when
    migration 017 is missing."""
    try:
        r = sessions.rotate(refresh_token, ip_address, user_agent)
    except sessions.SessionError as e:
        queries.insert_audit_log(
            event_type=AuditEvent.SESSION_REFUSED, success=False, ip_address=ip_address,
            user_agent=user_agent, metadata={"reason": e.code},
        )
        raise
    session = r["session"]
    user_id = str(session["user_id"])
    user = queries.get_user_by_id(user_id)
    if not user:
        sessions.revoke(str(session["id"]), None, "admin")
        raise sessions.SessionError("session_revoked", "This account no longer exists.")
    client = session.get("client") or "ios"
    minutes = sessions.access_minutes(client)
    created = sessions._ts(session.get("created_at"))
    access = create_access_token(
        user_id=user_id, username=user["username"], expires_delta=timedelta(minutes=minutes),
        auth_time=int(created.timestamp()) if created else None,
        session_id=str(session["id"]), client=client,
    )
    queries.insert_audit_log(
        event_type=AuditEvent.TOKEN_REFRESHED, success=True, user_id=user_id,
        ip_address=ip_address, user_agent=user_agent,
        metadata={"session_id": str(session["id"]), "retry": bool(r.get("retry"))},
    )
    return {
        "access_token": access,
        "token_type": "bearer",
        "expires_in": minutes * 60,
        "refresh_token": r["refresh_token"],
        "session_id": str(session["id"]),
        "session_expires_at": session.get("expires_at"),
    }
