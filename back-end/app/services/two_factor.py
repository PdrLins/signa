"""Two-step sign-in (migration 020): Telegram now, SMS later.

Setting it up proves the Telegram chat belongs to the user:
  1. POST /auth/2fa/telegram/start → a one-time link t.me/<bot>?start=2fa_<code>
     (10 minutes). The user opens it and presses Start in the Signa bot.
     (Or use_connected_chat=true: use the chat already connected for
     notifications, migration 016, and skip to step 2.)
  2. The bot (webhook or polling: app/notifications/telegram_updates.py)
     receives "/start 2fa_<code>", remembers that chat and sends it a
     6-digit code.
  3. POST /auth/2fa/telegram/confirm {"code"} → users.telegram_chat_id =
     that chat, two_factor_method = 'telegram'. From then on every password
     sign-in asks for a code sent to that chat (auth_service.login).
Only hashes are stored: the start code as SHA-256, the 6-digit code as HMAC
(salted with the user id); 3 wrong codes end the setup.

The owner account must keep two-step sign-in (it guards the brain).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import status
from loguru import logger

from app.core.api_errors import api_error
from app.core.cache import TTLCache
from app.core.config import settings
from app.core.security import generate_otp, hash_otp, verify_otp, verify_password

MIGRATION = "020_two_factor.sql"
START_PREFIX = "2fa_"
SETUP_TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 3


# ---------------------------------------------------------------- pure

def hash_start_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def is_enabled(user_row: dict) -> bool:
    """Two-step on for this user row. Before 020 (no two_factor_method
    column) a sign-in chat alone means on, as it always did. Off while
    Telegram is off (TELEGRAM_ENABLED=false): no code could be sent."""
    if not settings.telegram_active:
        return False
    if "two_factor_method" in user_row:
        return user_row.get("two_factor_method") == "telegram" and bool(user_row.get("telegram_chat_id"))
    return bool(user_row.get("telegram_chat_id"))


def setup_view(row: Optional[dict], bot: Optional[str], now: datetime) -> Optional[dict]:
    """The "setup" object of the API, or None when there is none / it expired. Pure."""
    if not row:
        return None
    exp = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
    if exp <= now:
        return None
    if row.get("chat_id") and row.get("otp_hash"):
        return {"step": "enter_code", "url": None, "chat_label": row.get("chat_label"), "expires_at": exp.isoformat()}
    return {"step": "open_telegram", "url": row.get("_url"), "chat_label": None, "expires_at": exp.isoformat()}


# ---------------------------------------------------------------- database

def _db():
    from app.db.supabase import get_client
    return get_client()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _user(user_id: str) -> dict:
    rows = _db().table("users").select("*").eq("id", user_id).limit(1).execute().data
    if not rows:
        raise api_error("not_found", "Account not found.", status.HTTP_404_NOT_FOUND)
    return rows[0]


def _setup_row(user_id: str) -> Optional[dict]:
    rows = _db().table("two_factor_setup").select("*").eq("user_id", user_id).limit(1).execute().data
    return rows[0] if rows else None


def _connected_chat(user_id: str) -> Optional[dict]:
    try:
        rows = _db().table("telegram_links").select("chat_id, username").eq("user_id", user_id).limit(1).execute().data
        return rows[0] if rows else None
    except Exception:
        return None


def status_payload(user_id: str, bot: Optional[str]) -> dict:
    """GET /auth/2fa (see the route docstring for the shape)."""
    u = _user(user_id)
    level = u.get("access_level") or "free"
    connected = _connected_chat(user_id)
    on = is_enabled(u)
    return {
        "enabled": on,
        "method": "telegram" if on else None,
        "can_disable": on and level != "owner",
        "telegram": {
            "available": bool(settings.telegram_active and bot),
            "bot_username": bot,
            "connected_chat": (connected.get("username") or "Telegram") if connected else None,
        },
        "sms": {"available": False},
        "setup": None if on else setup_view(_setup_row(user_id), None, _now()),
    }


def _send_code_to(user_id: str, chat_id: str, chat_label: Optional[str], reset_attempts: bool = True) -> str:
    """Store a fresh 6-digit code for the setup chat. Returns the plain code
    (the caller sends it to Telegram). A resend keeps the wrong-code count,
    so resending can't be used to get unlimited guesses."""
    code = generate_otp()
    row = {"chat_id": chat_id, "chat_label": chat_label, "otp_hash": hash_otp(code, salt=user_id),
           "expires_at": (_now() + SETUP_TTL).isoformat()}
    if reset_attempts:
        row["otp_attempts"] = 0
    _db().table("two_factor_setup").update(row).eq("user_id", user_id).execute()
    return code


RESEND_COOLDOWN_S = 60
RESEND_PER_HOUR = 5
_resend_last = TTLCache(max_size=20000, default_ttl=RESEND_COOLDOWN_S)
_resend_hour = TTLCache(max_size=20000, default_ttl=3600)


def _check_resend(user_id: str) -> None:
    """60 s between codes and 5 an hour per user (the bot is shared by everyone)."""
    import time
    last = _resend_last.get(user_id)
    if last:
        wait = max(1, int(RESEND_COOLDOWN_S - (time.time() - last)))
        raise api_error("resend_too_soon", f"Wait {wait} s before asking for another code.", 429,
                        retry_after=wait)
    sent = _resend_hour.get(user_id) or 0
    if sent >= RESEND_PER_HOUR:
        raise api_error("resend_too_soon", "Too many codes this hour. Try again later.", 429, retry_after=3600)
    _resend_last.set(user_id, time.time())
    _resend_hour.set(user_id, sent + 1)


def start_telegram(user_id: str, bot: Optional[str], use_connected_chat: bool,
                   password: Optional[str] = None) -> tuple[dict, Optional[tuple[str, str]]]:
    """Begin (or restart) setup. Returns (setup view, (chat_id, code) to send
    now or None). The route does the Telegram send. The password is required:
    a stolen session must not be able to tie the account to the thief's Telegram."""
    if not settings.telegram_active or not bot:
        raise api_error("telegram_not_configured", "Telegram isn't set up on this server yet.",
                        status.HTTP_503_SERVICE_UNAVAILABLE)
    u = _user(user_id)
    if is_enabled(u):
        raise api_error("already_enabled", "Two-step sign-in is already on.", status.HTTP_409_CONFLICT)
    if not password:
        raise api_error("password_required", "Enter your password to turn on two-step sign-in.", 422,
                        field="password")
    if not verify_password(password, u["password_hash"]):
        raise api_error("wrong_password", "That password is not right.", status.HTTP_403_FORBIDDEN)
    start_code = secrets.token_urlsafe(18)
    _db().table("two_factor_setup").upsert({
        "user_id": user_id, "method": "telegram", "code_hash": hash_start_code(start_code),
        "chat_id": None, "chat_label": None, "otp_hash": None, "otp_attempts": 0,
        "expires_at": (_now() + SETUP_TTL).isoformat(), "created_at": _now().isoformat(),
    }, on_conflict="user_id").execute()
    if use_connected_chat:
        chat = _connected_chat(user_id)
        if not chat:
            raise api_error("not_connected", "Connect Telegram for notifications first, or use the link.",
                            status.HTTP_409_CONFLICT)
        label = chat.get("username") or "Telegram"
        code = _send_code_to(user_id, str(chat["chat_id"]), label)
        return setup_view(_setup_row(user_id), bot, _now()), (str(chat["chat_id"]), code)
    view = setup_view(_setup_row(user_id), bot, _now()) or {}
    view["url"] = f"https://t.me/{bot}?start={START_PREFIX}{start_code}"
    return view, None


def chat_pressed_start(start_code: str, chat_id: str, label: Optional[str]) -> Optional[tuple[str, str]]:
    """The bot got "/start 2fa_<code>". Returns (user_id, 6-digit code) to
    send to that chat, or None when the link is unknown or expired."""
    if not start_code or len(start_code) > 64:
        return None
    rows = _db().table("two_factor_setup").select("*").eq("code_hash", hash_start_code(start_code)).limit(1).execute().data
    row = rows[0] if rows else None
    if not row or setup_view(row, None, _now()) is None:
        return None
    user_id = str(row["user_id"])
    # the link is single use: forget it, keep the setup row
    _db().table("two_factor_setup").update({"code_hash": None}).eq("user_id", user_id).execute()
    return user_id, _send_code_to(user_id, chat_id, label)


def resend(user_id: str) -> tuple[dict, tuple[str, str]]:
    row = _setup_row(user_id)
    if not row or not row.get("chat_id") or setup_view(row, None, _now()) is None:
        raise api_error("setup_expired", "This setup expired. Please start again.", status.HTTP_410_GONE)
    _check_resend(user_id)
    code = _send_code_to(user_id, str(row["chat_id"]), row.get("chat_label"), reset_attempts=False)
    return setup_view(_setup_row(user_id), None, _now()), (str(row["chat_id"]), code)


def confirm(user_id: str, code: str) -> str:
    """Check the code and turn two-step on. Returns the chat id (for the
    confirmation message)."""
    row = _setup_row(user_id)
    if not row or not row.get("otp_hash") or setup_view(row, None, _now()) is None:
        raise api_error("setup_expired", "This setup expired. Please start again.", status.HTTP_410_GONE)
    attempts = int(row.get("otp_attempts") or 0)
    if not verify_otp((code or "").strip(), row["otp_hash"], salt=user_id):
        attempts += 1
        if attempts >= MAX_ATTEMPTS:
            _db().table("two_factor_setup").delete().eq("user_id", user_id).execute()
            raise api_error("setup_expired", "Too many wrong codes. Please start again.", status.HTTP_410_GONE)
        _db().table("two_factor_setup").update({"otp_attempts": attempts}).eq("user_id", user_id).execute()
        raise api_error("invalid_code", "That code is not right.", 422,
                        attempts_remaining=MAX_ATTEMPTS - attempts)
    chat_id = str(row["chat_id"])
    other = _db().table("users").select("id").eq("telegram_chat_id", chat_id).neq("id", user_id).limit(1).execute().data
    if other:
        raise api_error("chat_in_use", "This Telegram is already used to sign in to another Signa account.",
                        status.HTTP_409_CONFLICT)
    _db().table("users").update({
        "telegram_chat_id": chat_id, "two_factor_method": "telegram", "two_factor_enabled_at": _now().isoformat(),
    }).eq("id", user_id).execute()
    _db().table("two_factor_setup").delete().eq("user_id", user_id).execute()
    logger.info(f"two-step sign-in turned on for {user_id}")
    return chat_id


def cancel(user_id: str) -> None:
    _db().table("two_factor_setup").delete().eq("user_id", user_id).execute()


def disable(user_id: str, password: str) -> Optional[str]:
    """Turn two-step off (password required). Returns the old chat id, to
    tell it. The owner can't turn it off."""
    u = _user(user_id)
    if (u.get("access_level") or "free") == "owner":
        raise api_error("owner_cannot_disable", "The owner account must keep two-step sign-in.",
                        status.HTTP_409_CONFLICT)
    if not verify_password(password or "", u["password_hash"]):
        raise api_error("wrong_password", "That password is not right.", status.HTTP_403_FORBIDDEN)
    old = u.get("telegram_chat_id")
    _db().table("users").update({"telegram_chat_id": None, "two_factor_method": None,
                                 "two_factor_enabled_at": None}).eq("id", user_id).execute()
    logger.info(f"two-step sign-in turned off for {user_id}")
    return str(old) if old else None


async def send(chat_id: str, key: str, user_id: str, **kw) -> bool:
    """Send one of the user_2fa_* messages in the user's language."""
    import asyncio

    from app.notifications.messages import msg_for
    from app.services.telegram_notify import send as tg_send, user_language
    lang = await asyncio.to_thread(user_language, user_id)
    return await tg_send(chat_id, msg_for(lang, key, **kw))
