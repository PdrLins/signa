"""Signed-in devices (sessions) and rotating refresh tokens — migration 017.

Every sign-in creates one session row per device. Access tokens (JWT) carry
its id as the `sid` claim; the auth middleware rejects a token whose session
was revoked (checked through a short cache, so a sign-out takes effect within
settings.session_check_cache_seconds).

iOS (client "ios") also gets an opaque refresh token:
  * stored only as a SHA-256 hash (auth_refresh_tokens)
  * single use: POST /auth/token/refresh returns a NEW refresh token and marks
    the old one used
  * reuse detection: a used token presented again means it was copied, so the
    whole session is revoked (reason "reuse_detected") and the user signs in
    again on every device that shared it
Lifetimes: iOS sessions slide forward settings.session_refresh_days on each
refresh, capped at settings.session_absolute_days since sign-in; owner
sessions are capped at settings.session_owner_days. Web sessions end with the
web's existing cap (settings.jwt_max_session_hours) and get no refresh token
(the web keeps refreshing its access token through /auth/refresh until it
moves to an HttpOnly cookie).

Before migration 017 every function degrades: create() returns no session,
is_active() says True, and the API routes answer 503 migration_required.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger

from app.core.cache import TTLCache
from app.core.config import settings

MIGRATION = "017_auth_sessions.sql"
CLIENTS = ("web", "ios")

# session id -> active (bool). Revocations in this process clear the entry at once.
_active_cache = TTLCache(max_size=20000, default_ttl=60)


class SessionError(Exception):
    """A refresh was refused. code: invalid_refresh | session_revoked |
    session_expired | reuse_detected."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------- pure helpers

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def normalize_client(client: Optional[str]) -> str:
    c = (client or "web").strip().lower()
    return c if c in CLIENTS else "web"


_UA_RULES = (
    (r"iPhone", "iPhone"), (r"iPad", "iPad"), (r"Android", "Android"),
    (r"Macintosh|Mac OS X", "macOS"), (r"Windows", "Windows"), (r"Linux", "Linux"),
)
_BROWSERS = (
    (r"Edg/", "Edge"), (r"OPR/|Opera", "Opera"), (r"Firefox/", "Firefox"),
    (r"Chrome/|CriOS/", "Chrome"), (r"Safari/", "Safari"),
)


def device_label(client: str, device_name: Optional[str], user_agent: Optional[str]) -> str:
    """What the user sees in "Your devices". The app's own name wins
    ("Pedro's iPhone"); else a label from the browser's User-Agent. Pure."""
    name = " ".join((device_name or "").split())[:80]
    if name:
        return name
    ua = user_agent or ""
    os_name = next((label for pat, label in _UA_RULES if re.search(pat, ua)), None)
    browser = next((label for pat, label in _BROWSERS if re.search(pat, ua)), None)
    if client == "ios":
        return os_name if os_name in ("iPhone", "iPad") else "iPhone"
    if browser and os_name:
        return f"{browser} on {os_name}"
    return browser or os_name or "Web browser"


def lifetimes(client: str, level: str, now: datetime) -> tuple[datetime, datetime]:
    """(expires_at, absolute_expires_at) for a new session. Pure."""
    if client != "ios":
        end = now + timedelta(hours=settings.jwt_max_session_hours)
        return end, end
    if level == "owner":
        end = now + timedelta(days=settings.session_owner_days)
        return end, end
    return (now + timedelta(days=settings.session_refresh_days),
            now + timedelta(days=settings.session_absolute_days))


def slide(absolute_expires_at: datetime, level: str, now: datetime) -> datetime:
    """New sliding expiry after a refresh, never past the absolute cap. Pure."""
    days = settings.session_owner_days if level == "owner" else settings.session_refresh_days
    return min(now + timedelta(days=days), absolute_expires_at)


def access_minutes(client: str) -> int:
    return settings.ios_access_token_minutes if client == "ios" else settings.jwt_access_token_expire_minutes


def _ts(v) -> Optional[datetime]:
    if not v:
        return None
    d = v if isinstance(v, datetime) else datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def public_view(row: dict, current_sid: Optional[str]) -> dict:
    """A session as GET /auth/sessions shows it. Pure."""
    return {
        "id": str(row["id"]),
        "client": row.get("client"),
        "device_name": row.get("device_name"),
        "created_at": row.get("created_at"),
        "last_used_at": row.get("last_used_at"),
        "expires_at": row.get("expires_at"),
        "current": current_sid is not None and str(row["id"]) == str(current_sid),
    }


# ---------------------------------------------------------------- database

def _db():
    from app.db.supabase import get_client
    return get_client()


def _level(user_id: str) -> str:
    from app.core.access import get_user_access
    try:
        return get_user_access(user_id)["level"]
    except Exception:
        return "free"


def create(user: dict, client: str, device_name: Optional[str], ip: str, user_agent: str) -> dict:
    """New session for a successful sign-in.

    Returns {"session_id": str | None, "refresh_token": str | None,
             "expires_at": ISO | None}. Before migration 017 (or if the write
    fails) session_id is None and sign-in proceeds the old way."""
    from app.core.api_errors import is_missing_schema

    client = normalize_client(client)
    now = datetime.now(timezone.utc)
    level = user.get("access_level") or _level(user["id"])
    expires_at, absolute = lifetimes(client, level, now)
    try:
        row = _db().table("auth_sessions").insert({
            "user_id": user["id"],
            "client": client,
            "device_name": device_label(client, device_name, user_agent),
            "ip_address": (ip or "")[:64],
            "user_agent": (user_agent or "")[:300],
            "expires_at": expires_at.isoformat(),
            "absolute_expires_at": absolute.isoformat(),
        }).execute().data[0]
    except Exception as e:
        if is_missing_schema(e):
            logger.debug("sessions: migration 017 not applied, signing in without a session")
        else:
            logger.warning(f"sessions: could not create a session: {e}")
        return {"session_id": None, "refresh_token": None, "expires_at": None}

    sid = str(row["id"])
    _active_cache.set(sid, True)
    refresh = None
    if client == "ios":
        refresh = new_refresh_token()
        _db().table("auth_refresh_tokens").insert({"token_hash": hash_token(refresh), "session_id": sid}).execute()
    return {"session_id": sid, "refresh_token": refresh, "expires_at": expires_at.isoformat()}


def rotate(refresh_token: str, ip: str, user_agent: str) -> dict:
    """Exchange a refresh token for a new one (see module docstring).

    Returns {"session": row, "refresh_token": str, "level": str}. Raises
    SessionError; raises the DB error unchanged when the tables are missing
    (the route turns that into 503 migration_required)."""
    db = _db()
    now = datetime.now(timezone.utc)
    h = hash_token(refresh_token or "")
    rows = db.table("auth_refresh_tokens").select("token_hash, session_id, used_at").eq("token_hash", h).limit(1).execute().data
    if not rows:
        raise SessionError("invalid_refresh", "Unknown refresh token. Please sign in again.")
    tok = rows[0]
    sid = str(tok["session_id"])

    if tok.get("used_at"):
        revoke(sid, None, "reuse_detected")
        raise SessionError("reuse_detected", "This sign-in was used from another place and has been ended. Please sign in again.")

    srows = db.table("auth_sessions").select("*").eq("id", sid).limit(1).execute().data
    if not srows:
        raise SessionError("invalid_refresh", "Unknown refresh token. Please sign in again.")
    session = srows[0]
    if session.get("revoked_at"):
        raise SessionError("session_revoked", "You were signed out on this device. Please sign in again.")
    exp, absolute = _ts(session.get("expires_at")), _ts(session.get("absolute_expires_at"))
    if (exp and now >= exp) or (absolute and now >= absolute):
        raise SessionError("session_expired", "Your sign-in expired. Please sign in again.")

    # Mark used only if still unused: of two concurrent refreshes with the
    # same token exactly one wins; the other is treated as reuse.
    won = db.table("auth_refresh_tokens").update({"used_at": now.isoformat()}) \
        .eq("token_hash", h).is_("used_at", "null").execute().data
    if not won:
        revoke(sid, None, "reuse_detected")
        raise SessionError("reuse_detected", "This sign-in was used from another place and has been ended. Please sign in again.")

    new_token = new_refresh_token()
    db.table("auth_refresh_tokens").insert({"token_hash": hash_token(new_token), "session_id": sid}).execute()
    level = _level(str(session["user_id"]))
    new_exp = slide(absolute or now, level, now)
    db.table("auth_sessions").update({
        "last_used_at": now.isoformat(), "expires_at": new_exp.isoformat(),
        "ip_address": (ip or "")[:64], "user_agent": (user_agent or "")[:300],
    }).eq("id", sid).execute()
    session = {**session, "expires_at": new_exp.isoformat(), "last_used_at": now.isoformat()}
    return {"session": session, "refresh_token": new_token, "level": level}


def is_active(sid: Optional[str]) -> bool:
    """True when the session may still be used. Tokens without a session
    (issued before 017) count as active. Fails open on DB errors so an outage
    doesn't sign everyone out; the token's own expiry still applies."""
    if not sid:
        return True
    cached = _active_cache.get(sid)
    if cached is not None:
        return cached
    now = datetime.now(timezone.utc)
    try:
        rows = _db().table("auth_sessions").select("revoked_at, expires_at, absolute_expires_at") \
            .eq("id", sid).limit(1).execute().data
    except Exception as e:
        logger.debug(f"sessions: active check failed for {sid}: {e}")
        return True
    if not rows:
        active = False
    else:
        r = rows[0]
        exp, absolute = _ts(r.get("expires_at")), _ts(r.get("absolute_expires_at"))
        active = not r.get("revoked_at") and not (exp and now >= exp) and not (absolute and now >= absolute)
    _active_cache.set(sid, active, ttl=settings.session_check_cache_seconds)
    return active


def touch(sid: Optional[str], ip: str, user_agent: str) -> None:
    """Record activity (web access-token refresh). Never raises."""
    if not sid:
        return
    try:
        _db().table("auth_sessions").update({
            "last_used_at": datetime.now(timezone.utc).isoformat(),
            "ip_address": (ip or "")[:64], "user_agent": (user_agent or "")[:300],
        }).eq("id", sid).is_("revoked_at", "null").execute()
    except Exception as e:
        logger.debug(f"sessions: touch failed for {sid}: {e}")


def revoke(sid: str, user_id: Optional[str], reason: str) -> bool:
    """Revoke one session. With user_id, only that user's session (API
    callers); without it, any session (reuse detection). True if a session
    was revoked by this call."""
    q = _db().table("auth_sessions").update({
        "revoked_at": datetime.now(timezone.utc).isoformat(), "revoked_reason": reason[:24],
    }).eq("id", sid).is_("revoked_at", "null")
    if user_id:
        q = q.eq("user_id", user_id)
    done = bool(q.execute().data)
    _active_cache.set(str(sid), False, ttl=settings.session_check_cache_seconds)
    if done:
        logger.info(f"sessions: revoked {sid} ({reason})")
    return done


def revoke_others(user_id: str, keep_sid: Optional[str], reason: str = "others") -> int:
    """Revoke every active session of the user except keep_sid. Returns the count."""
    q = _db().table("auth_sessions").update({
        "revoked_at": datetime.now(timezone.utc).isoformat(), "revoked_reason": reason[:24],
    }).eq("user_id", user_id).is_("revoked_at", "null")
    if keep_sid:
        q = q.neq("id", keep_sid)
    rows = q.execute().data or []
    for r in rows:
        _active_cache.set(str(r["id"]), False, ttl=settings.session_check_cache_seconds)
    return len(rows)


def list_for_user(user_id: str, current_sid: Optional[str]) -> list[dict]:
    """Active (not revoked, not expired) sessions, most recently used first."""
    now = datetime.now(timezone.utc)
    rows = _db().table("auth_sessions").select("*").eq("user_id", user_id).is_("revoked_at", "null") \
        .order("last_used_at", desc=True).limit(100).execute().data or []
    out = []
    for r in rows:
        exp = _ts(r.get("expires_at"))
        if exp and now >= exp:
            continue
        out.append(public_view(r, current_sid))
    return out
