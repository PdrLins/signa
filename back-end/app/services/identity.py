"""Email accounts (migration 018): sign-up, email codes, password reset,
changing the email address, deleting the account.

Codes reuse `otp_codes` (the Telegram login code table) with a `purpose`:
  login   sign-in code (Telegram or email) and the sign-up confirmation
  reset   forgot-password code (proves the user owns the email)
  email   confirms a new address before it replaces the old one
A code only works for its purpose, expires after
settings.email_code_expire_seconds and allows
settings.max_otp_attempts_per_session wrong guesses.

Nothing here reveals whether an email has an account: sign-up and forgot-
password answer the same way either way (a session_token that only works
when a real code was sent).

Sign-up creates the user INACTIVE with the email unverified; confirming the
code (POST /auth/verify-otp) activates it and signs in. Public sign-up is
off unless settings.signup_enabled.
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger

from app.core.api_errors import api_error
from app.core.cache import TTLCache
from app.core.config import settings
from app.core.security import create_session_token, generate_otp, hash_otp, hash_password, verify_password

MIGRATION = "018_email_sign_in.sql"
PURPOSES = ("login", "reset", "email")
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
MIN_PASSWORD = 8   # same rule as sign-up (registration.check_password)
_USER_COLS = ("id, username, password_hash, telegram_chat_id, is_active, last_login, login_attempts, "
              "locked_until, access_level, email, email_verified_at")


# ---------------------------------------------------------------- pure

def normalize_email(value: Optional[str]) -> Optional[str]:
    """Lower-cased, trimmed address, or None when it isn't an email. Pure."""
    e = (value or "").strip().lower()
    return e if len(e) <= 254 and _EMAIL.match(e) else None


def password_problem(password: str) -> Optional[str]:
    """Error code for a password we refuse, else None. bcrypt reads 72 bytes. Pure."""
    if len(password or "") < MIN_PASSWORD:
        return "password_too_short"
    if len(password.encode("utf-8")) > 72:
        return "password_too_long"
    return None


def new_username(email: str) -> str:
    """Internal username for an email account (the email is what people type)."""
    base = re.sub(r"[^a-z0-9]", "", email.split("@")[0])[:16] or "user"
    return f"{base}_{secrets.token_hex(3)}"


def _422(code: str, message: str, field: str):
    return api_error(code, message, 422, field=field)


PASSWORD_MESSAGES = {
    "password_too_short": f"Use at least {MIN_PASSWORD} characters.",
    "password_too_long": "That password is too long.",
}


# ---------------------------------------------------------------- database

def _db():
    from app.db.supabase import get_client
    return get_client()


def find_user_by_email(email: str) -> Optional[dict]:
    from app.db import queries
    return queries.get_user_by_email(email)


def find_user_for_login(identifier: str) -> Optional[dict]:
    """By email when it looks like one (active or not), else by username
    (active only). Before 018 there is no email column: email look-ups find
    nobody."""
    from app.core.api_errors import is_missing_schema
    from app.db import queries

    ident = (identifier or "").strip().lower()
    if "@" not in ident:
        return queries.get_user_by_username(ident)
    email = normalize_email(ident)
    if not email:
        return None
    try:
        return find_user_by_email(email)
    except Exception as e:
        if is_missing_schema(e):
            return None
        raise


def issue_code(user_id: str, purpose: str, email: Optional[str] = None) -> tuple[str, str]:
    """Store a new code for `purpose`. Returns (session_token, code)."""
    assert purpose in PURPOSES
    code = generate_otp()
    token = create_session_token()
    _db().table("otp_codes").insert({
        "user_id": user_id, "session_token": token, "code_hash": hash_otp(code, salt=token),
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=settings.email_code_expire_seconds)).isoformat(),
        "attempts": 0, "purpose": purpose, "email": email,
    }).execute()
    return token, code


def check_code(session_token: str, code: str, purpose: str) -> dict:
    """Validate a code for `purpose` and consume it. Returns the otp row.
    Raises the same errors as the Telegram flow (AuthenticationError,
    OTPExpiredError, OTPInvalidError)."""
    from app.core.exceptions import AuthenticationError, OTPExpiredError, OTPInvalidError
    from app.core.security import verify_otp
    from app.db import queries

    rec = queries.get_otp_by_session_token(session_token)
    if rec is None or (rec.get("purpose") or "login") != purpose:
        raise AuthenticationError("Invalid or expired code. Please start again.")
    if datetime.now(timezone.utc) > datetime.fromisoformat(rec["expires_at"]):
        queries.invalidate_otp(rec["id"])
        raise OTPExpiredError("This code has expired. Please ask for a new one.")
    attempts = rec.get("attempts", 0) or 0
    if attempts >= settings.max_otp_attempts_per_session:
        queries.invalidate_otp(rec["id"])
        raise AuthenticationError("Too many wrong codes. Please ask for a new one.")
    if not verify_otp(code, rec["code_hash"], salt=session_token):
        queries.increment_otp_attempts(rec["id"])
        raise OTPInvalidError(detail="Invalid code",
                              attempts_remaining=max(0, settings.max_otp_attempts_per_session - attempts - 1))
    if not queries.mark_otp_used(rec["id"]):
        raise AuthenticationError("Invalid or expired code. Please start again.")
    return rec


def _language(user_id: Optional[str], fallback: str = "en") -> str:
    if not user_id:
        return fallback
    try:
        rows = _db().table("user_settings").select("language").eq("user_id", user_id).limit(1).execute().data
        lang = (rows[0] if rows else {}).get("language")
        return lang if lang in ("en", "pt") else fallback
    except Exception:
        return fallback


def send_login_code(user: dict) -> str:
    """Email sign-in code to a verified address. Returns the session_token."""
    from app.services import email_sender
    token, code = issue_code(user["id"], "login", user.get("email"))
    email_sender.send_code(user["email"], "login", code, _language(user["id"]))
    return token


# ---------------------------------------------------------------- sign-up

def signup(email: str, password: str, language: str = "en") -> dict:
    """Create an inactive account and email a confirmation code.

    Always answers {"session_token", "message"}: when the email already has a
    verified account, that address gets an "you already have an account"
    email and the token is a decoy (no code exists for it)."""
    if not settings.signup_enabled:
        raise api_error("signup_closed", "New accounts are not open yet.", 403)
    e = normalize_email(email)
    if not e:
        raise _422("invalid_email", "Enter a valid email address.", "email")
    problem = password_problem(password)
    if problem:
        raise _422(problem, PASSWORD_MESSAGES[problem], "password")
    from app.services import email_sender

    lang = language if language in ("en", "pt") else "en"
    msg = "We sent a code to your email."
    existing = find_user_by_email(e)
    if existing and existing.get("email_verified_at"):
        email_sender.send_code(e, "exists", None, _language(existing["id"], lang))
        return {"session_token": create_session_token(), "message": msg}
    if existing:   # an earlier sign-up never confirmed: start over with the new password
        uid = existing["id"]
        _db().table("users").update({"password_hash": hash_password(password)}).eq("id", uid).execute()
    else:
        uid = _db().table("users").insert({
            "username": new_username(e), "password_hash": hash_password(password), "email": e,
            "is_active": False, "access_level": "free",
        }).execute().data[0]["id"]
        try:
            _db().table("user_settings").upsert({"user_id": uid, "language": lang}).execute()
        except Exception as err:
            logger.debug(f"signup: language not stored: {err}")
    token, code = issue_code(uid, "login", e)
    email_sender.send_code(e, "signup", code, lang)
    return {"session_token": token, "message": msg}


def activate_if_pending(otp: dict) -> None:
    """After a valid sign-up code: activate the account and mark the email
    verified. No-op for accounts that are already active."""
    rows = _db().table("users").select("id, is_active, email, email_verified_at").eq("id", otp["user_id"]).limit(1).execute().data
    u = rows[0] if rows else None
    if not u or u.get("is_active"):
        if u and otp.get("email") and u.get("email") == otp.get("email") and not u.get("email_verified_at"):
            _db().table("users").update({"email_verified_at": datetime.now(timezone.utc).isoformat()}).eq("id", u["id"]).execute()
        return
    if otp.get("email") and u.get("email") == otp.get("email"):
        _db().table("users").update({
            "is_active": True, "email_verified_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", u["id"]).execute()


# ---------------------------------------------------------------- password reset

RESET_MESSAGE = "If this account can receive a code, we sent one to its email or Telegram."
RESETS_PER_HOUR = 3
_resets = TTLCache(max_size=20000, default_ttl=3600)


def start_reset(identifier: str) -> tuple[dict, Optional[tuple[str, str, str]]]:
    """Forgot password, by username or email. The code goes to the account's
    verified email, else to its Telegram (two-step sign-in chat). Same answer
    whether or not the account exists or can get a code. Returns (response,
    (chat_id, code, language) for the route to send on Telegram, or None)."""
    from app.services import email_sender

    ident = (identifier or "").strip()
    if not ident or len(ident) > 254:
        raise _422("invalid_identifier", "Enter your username or email.", "identifier")
    decoy = {"session_token": create_session_token(), "message": RESET_MESSAGE}
    if "@" in ident:
        e = normalize_email(ident)
        user = find_user_by_email(e) if e else None
    else:
        from app.db import queries
        user = queries.get_user_by_username(ident.lower())
    if not user or user.get("is_active") is False:
        return decoy, None
    uid = str(user["id"])
    sent = _resets.get(uid) or 0
    if sent >= RESETS_PER_HOUR:   # no flood of codes to someone's inbox / Telegram
        return decoy, None
    email_ok = bool(user.get("email") and user.get("email_verified_at"))
    chat = user.get("telegram_chat_id") if settings.telegram_active else None
    if not email_ok and not chat:
        return decoy, None   # no way to reach the owner: support has to help
    _resets.set(uid, sent + 1)
    token, code = issue_code(uid, "reset", user.get("email") if email_ok else None)
    lang = _language(uid)
    if email_ok:
        email_sender.send_code(user["email"], "reset", code, lang)
        return {"session_token": token, "message": RESET_MESSAGE}, None
    return {"session_token": token, "message": RESET_MESSAGE}, (str(chat), code, lang)


def finish_reset(session_token: str, code: str, new_password: str) -> str:
    """Set the new password and sign out every device. Returns the user id."""
    from app.services import sessions

    problem = password_problem(new_password)
    if problem:
        raise _422(problem, PASSWORD_MESSAGES[problem], "password")
    rec = check_code(session_token, code, "reset")
    uid = rec["user_id"]
    _db().table("users").update({
        "password_hash": hash_password(new_password), "password_changed_at": datetime.now(timezone.utc).isoformat(),
        "login_attempts": 0, "locked_until": None,
    }).eq("id", uid).execute()
    try:
        sessions.revoke_others(uid, None, "password_changed")
    except Exception as e:
        logger.warning(f"reset: sessions not revoked: {type(e).__name__}")
    try:
        from app.db import queries
        queries.insert_audit_log(event_type="PASSWORD_RESET", success=True, user_id=uid)
    except Exception:
        pass
    logger.info(f"password reset for {uid[:8]}")
    return uid


# ---------------------------------------------------------------- email address

def _full_user(user_id: str) -> dict:
    rows = _db().table("users").select(_USER_COLS).eq("id", user_id).limit(1).execute().data
    if not rows:
        raise api_error("not_found", "Account not found.", 404)
    return rows[0]


def start_email_change(user_id: str, new_email: str, password: str) -> dict:
    """Send a code to the new address (password required)."""
    from app.services import email_sender

    e = normalize_email(new_email)
    if not e:
        raise _422("invalid_email", "Enter a valid email address.", "email")
    u = _full_user(user_id)
    if not verify_password(password or "", u["password_hash"]):
        raise api_error("wrong_password", "That password is not right.", 403)
    other = find_user_by_email(e)
    if other and str(other["id"]) != str(user_id):
        raise api_error("email_taken", "Another account uses this email.", 409)
    token, code = issue_code(user_id, "email", e)
    email_sender.send_code(e, "email", code, _language(user_id))
    return {"session_token": token, "message": "We sent a code to the new address."}


def confirm_email_change(user_id: str, session_token: str, code: str) -> dict:
    rec = check_code(session_token, code, "email")
    if str(rec["user_id"]) != str(user_id) or not rec.get("email"):
        raise api_error("invalid_code", "Invalid or expired code.", 400)
    other = find_user_by_email(rec["email"])
    if other and str(other["id"]) != str(user_id):
        raise api_error("email_taken", "Another account uses this email.", 409)
    now = datetime.now(timezone.utc).isoformat()
    _db().table("users").update({"email": rec["email"], "email_verified_at": now}).eq("id", user_id).execute()
    return {"email": rec["email"], "email_verified_at": now}


def account_status(user_id: str) -> dict:
    """{"email", "email_verified", "has_telegram", "signin_code": "telegram" | "email" | null}"""
    u = _full_user(user_id)
    verified = bool(u.get("email") and u.get("email_verified_at"))
    via = "telegram" if (u.get("telegram_chat_id") and settings.login_otp_enabled
                         and settings.telegram_active) else "email" if verified else None
    return {"email": u.get("email"), "email_verified": verified,
            "has_telegram": bool(u.get("telegram_chat_id") and settings.telegram_active), "signin_code": via}
