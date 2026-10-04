"""Invite-only sign-up — POST /api/v1/auth/register (migration 019).

A new account needs the invite code (= account ID) of an ACTIVE user. The
account is created free, without Telegram (password-only sign-in), with the
password hashed exactly like create_user.py (bcrypt, app.core.security).
The response is the same token payload a password-only login returns: the
tokens come from auth_service._issue_access_token (session per device,
refresh token for client "ios" once migration 017 is applied).

Checks, in order (errors are {"detail": {"code", "message"}}):
  422 invalid_username   3-30 chars of a-z 0-9 _ . after lower-casing
  422 weak_password      fewer than 8 characters or more than 72 bytes
  422 invalid_referral   unknown code, or its owner is inactive
  409 username_taken     (checked after the code, so people without an
                         invite can't probe which usernames exist)
Every attempt is audited (USER_REGISTERED / REGISTER_FAILED).
"""

from __future__ import annotations

import re

from fastapi import status
from loguru import logger

from app.core.api_errors import api_error, is_missing_schema
from app.core.security import hash_password
from app.db import queries
from app.models.audit import AuditEvent
from app.services import referrals

USERNAME_RE = re.compile(r"^[a-z0-9_.]+$")
USERNAME_MIN, USERNAME_MAX = 3, 30
PASSWORD_MIN_CHARS, PASSWORD_MAX_BYTES = 8, 72


class RegistrationError(Exception):
    def __init__(self, code: str, message: str, http: int):
        super().__init__(message)
        self.code, self.message, self.http = code, message, http


def normalize_username(username: str) -> str:
    u = (username or "").strip().lower()
    if not (USERNAME_MIN <= len(u) <= USERNAME_MAX) or not USERNAME_RE.match(u):
        raise RegistrationError("invalid_username",
                                "Usernames are 3-30 characters: letters, numbers, _ and .",
                                422)
    return u


def check_password(password: str) -> None:
    if len(password or "") < PASSWORD_MIN_CHARS or len((password or "").encode("utf-8")) > PASSWORD_MAX_BYTES:
        raise RegistrationError("weak_password",
                                "Use at least 8 characters (and at most 72 bytes).",
                                422)


def _username_exists(username: str) -> bool:
    rows = (referrals._db().table("users").select("id").eq("username", username)
            .limit(1).execute().data or [])
    return bool(rows)


def _is_duplicate(err: Exception) -> bool:
    text = str(err).lower()
    return "duplicate key" in text or "23505" in text or "already exists" in text


def create_account(username: str, password: str, referrer_id: str | None) -> dict:
    """Insert the user row (free, active, no Telegram) + the pending referral.
    Returns the user row. Raises RegistrationError(username_taken)."""
    db = referrals._db()
    password_hash = hash_password(password)
    user = None
    for _ in range(3):  # retry only an account_id collision
        row = {
            "username": username,
            "password_hash": password_hash,
            "telegram_chat_id": None,
            "access_level": "free",
            "is_active": True,
            "account_id": referrals.unique_account_id(),
            "referred_by": referrer_id,
        }
        try:
            result = db.table("users").insert(row).execute()
        except Exception as e:
            if _is_duplicate(e) and "account_id" in str(e).lower():
                continue
            if _is_duplicate(e):
                raise RegistrationError("username_taken", "That username is taken.", status.HTTP_409_CONFLICT)
            raise
        user = (result.data or [None])[0]
        break
    if not user:
        raise RuntimeError("user insert returned no row")
    if not referrer_id:   # open sign-up without a friend's code
        return user
    try:
        referrals.add_pending(referrer_id, str(user["id"]))
    except Exception as e:  # the account exists: don't fail the sign-up for this
        if is_missing_schema(e):
            raise
        logger.error(f"register: referral row not written for {user['id']}: {e}")
    return user


def _audit(event: str, success: bool, ip: str, ua: str, user_id: str | None = None, **meta) -> None:
    try:
        queries.insert_audit_log(event_type=event, success=success, user_id=user_id,
                                 ip_address=ip, user_agent=ua, metadata=meta)
    except Exception as e:
        logger.debug(f"register: audit not written: {e}")


def register(username: str, password: str, referral_code: str, ip_address: str, user_agent: str,
             client: str = "web", device_name: str | None = None, settings: dict | None = None,
             source: dict | None = None) -> dict:
    """Create the account and sign it in. Blocking (bcrypt + DB): run via
    run_db_for(referrals.MIGRATION, ...) so a missing schema answers 503."""
    from app.services import auth_service

    try:
        name = normalize_username(username)
        check_password(password)
        from app.core.config import settings as app_settings
        code = (referral_code or "").strip()
        referrer = referrals.find_referrer(code) if code else None
        # A code that was typed must be valid; no code is fine when sign-up is open.
        if (code or app_settings.signup_invite_required) and not referrer:
            raise RegistrationError("invalid_referral", "That invite code isn't valid.",
                                    422)
        if _username_exists(name):
            raise RegistrationError("username_taken", "That username is taken.", status.HTTP_409_CONFLICT)
        user = create_account(name, password, referrer["id"] if referrer else None)
    except RegistrationError as e:
        _audit(AuditEvent.REGISTER_FAILED, False, ip_address, user_agent, reason=e.code)
        raise api_error(e.code, e.message, e.http)

    if settings:
        try:   # country / currency / language from the phone; never fail the sign-up for this
            queries.upsert_profile_settings(str(user["id"]), settings)
        except Exception as e:
            logger.warning(f"register: first settings not saved for {user['id']}: {type(e).__name__}")
    from app.services import growth
    growth.record_signup(str(user["id"]), source, client, (settings or {}).get("country"),
                         invite="friend" if referrer else "none")   # never fails the sign-up
    _audit(AuditEvent.USER_REGISTERED, True, ip_address, user_agent, user_id=str(user["id"]),
           referrer_id=referrer["id"] if referrer else None, client=client)
    logger.info(f"register: new account {name}" + (f" invited by {referrer['id']}" if referrer else ""))
    token = auth_service._issue_access_token(user, ip_address, user_agent, client, device_name)
    return {"message": "Account created", "session_token": None, **token}
