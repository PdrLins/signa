"""Account IDs, invite codes and referral rewards — migration 019.

Every user has a visible 8-character ACCOUNT ID (alphabet ALPHABET: no
0/O/1/I/L) that is also their INVITE CODE. Codes are case-insensitive: input
is upper-cased before lookup.

  * Sign-up (app/services/registration.py, create_user.py --referral) needs
    a valid code of an ACTIVE user; it sets users.referred_by and creates a
    `referrals` row (status 'pending', add_pending).
  * The referral becomes 'rewarded' when the invited user has followed a
    stock AND is a real returning user (earned(): account 7+ days old, used
    again 3+ days after signing up). Checked on each follow and nightly
    (reward_due). The conditional update (WHERE status = 'pending') makes it
    happen once even under concurrent requests; only the winner notifies.
  * Free slots: 15 + min(5 x rewarded, 25) (app.core.access.slot_limit).
    Premium / owner stay unlimited. users.slot_bonus is ignored.
  * The referrer gets a Telegram message ("Your friend joined Signa — +5
    stocks to follow") when they have a linked notification chat and
    feature.telegram_alerts (app/services/telegram_notify.py, migration 016).

Before migration 019: account_id_for() -> None, rewarded_count() -> 0,
reward_first_follow() -> no-op; the routes that need the tables answer 503
migration_required (run_db_for(MIGRATION, ...)).
"""

from __future__ import annotations

import asyncio
import secrets
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from app.core import access
from app.core.cache import TTLCache
from app.core.config import settings

MIGRATION = "019_referrals.sql"
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8

# user_id -> account_id (never changes)
_account_cache = TTLCache(max_size=5000, default_ttl=3600)
# user_id -> rewarded referral count (cleared in-process when one is rewarded)
_rewarded_cache = TTLCache(max_size=5000, default_ttl=60)
# user_id -> True once we know they have no pending referral (skips the DB
# write on every later holdings / watchlist save). Referrals are only
# created at sign-up, before any follow, so this can't go stale.
_settled_cache = TTLCache(max_size=20000, default_ttl=6 * 3600)
# keeps fire-and-forget notification tasks alive until they finish
_tasks: set[asyncio.Task] = set()


def _db():
    from app.db.supabase import get_client
    return get_client()


def clear_caches() -> None:
    _account_cache.clear()
    _rewarded_cache.clear()
    _settled_cache.clear()


# ---------------------------------------------------------------- codes

def new_account_id() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(code: object) -> Optional[str]:
    """Upper-cased code, or None when it can't be an account ID."""
    if not isinstance(code, str):
        return None
    c = code.strip().upper()
    if len(c) != CODE_LENGTH or any(ch not in ALPHABET for ch in c):
        return None
    return c


def unique_account_id(attempts: int = 8) -> str:
    """A fresh account ID not used by any user (raises before 019)."""
    db = _db()
    for _ in range(attempts):
        cand = new_account_id()
        rows = db.table("users").select("id").eq("account_id", cand).limit(1).execute().data or []
        if not rows:
            return cand
    raise RuntimeError("could not generate a unique account_id")


def find_referrer(code: object) -> Optional[dict]:
    """The ACTIVE user whose account ID is `code` ({id, username}), else None.
    Raises on a missing schema (before 019) so routes answer 503."""
    c = normalize_code(code)
    if not c:
        return None
    rows = (_db().table("users").select("id, username, is_active").eq("account_id", c)
            .limit(1).execute().data or [])
    row = rows[0] if rows else None
    if not row or row.get("is_active") is False:
        return None
    return {"id": str(row["id"]), "username": row.get("username")}


def is_valid_code(code: object) -> bool:
    return find_referrer(code) is not None


def add_pending(referrer_id: str, referred_id: str) -> None:
    """The pending referrals row for a new user (referred_id is UNIQUE, so a
    user has one referrer). users.referred_by is written with the user row."""
    _db().table("referrals").insert({"referrer_id": referrer_id, "referred_id": referred_id,
                                     "status": "pending"}).execute()
    _settled_cache.delete(referred_id)


# ---------------------------------------------------------------- reads

def account_id_for(user_id: str) -> Optional[str]:
    """The user's account ID, or None (before 019 / DB down). Never raises."""
    if not user_id:
        return None
    cached = _account_cache.get(user_id)
    if cached is not None:
        return cached
    try:
        rows = _db().table("users").select("account_id").eq("id", user_id).limit(1).execute().data or []
    except Exception as e:
        logger.debug(f"referrals: account_id unavailable for {user_id}: {e}")
        return None
    value = (rows[0].get("account_id") if rows else None) or None
    if value:
        _account_cache.set(user_id, value)
    return value


def _referral_rows(user_id: str) -> list[dict]:
    return (_db().table("referrals").select("status").eq("referrer_id", user_id).execute().data or [])


def rewarded_count(user_id: str) -> int:
    """How many of the user's referrals are rewarded. 0 before 019 or on a
    DB error (never raises: slot checks must keep working)."""
    if not user_id:
        return 0
    cached = _rewarded_cache.get(user_id)
    if cached is not None:
        return cached
    try:
        n = sum(1 for r in _referral_rows(user_id) if r.get("status") == "rewarded")
    except Exception as e:
        logger.debug(f"referrals: rewarded count unavailable for {user_id}: {e}")
        return 0
    _rewarded_cache.set(user_id, n)
    return n


def share_url(code: Optional[str]) -> Optional[str]:
    base = (settings.web_app_url or "").strip().rstrip("/")
    return f"{base}/signup?code={code}" if base and code else None


def summary(user: dict) -> dict:
    """GET /referrals. Raises on a missing schema (route maps it to 503)."""
    uid = user["user_id"]
    rows = (_db().table("users").select("account_id").eq("id", uid).limit(1).execute().data or [])
    code = rows[0].get("account_id") if rows else None
    refs = _referral_rows(uid)
    rewarded = sum(1 for r in refs if r.get("status") == "rewarded")
    pending = sum(1 for r in refs if r.get("status") == "pending")
    level = user.get("access_level") or "free"
    unlimited = access.slot_limit(level) is None
    return {
        "code": code,
        "share_url": share_url(code),
        "per_friend": access.REFERRAL_SLOTS_PER_FRIEND,
        "max_bonus": access.REFERRAL_SLOTS_MAX,
        "bonus_slots": access.referral_bonus(rewarded),
        "invited": len(refs),
        "rewarded": rewarded,
        "pending": pending,
        "unlimited": unlimited,
    }


# ---------------------------------------------------------------- reward

EARN_MIN_AGE_DAYS = 7      # the invited account must be a week old
EARN_CAME_BACK_DAYS = 3    # and used again at least 3 days after signing up


def earned(user: dict, now: datetime) -> bool:
    """A referral pays only for a real person: the friend's account is
    EARN_MIN_AGE_DAYS old and was used again EARN_CAME_BACK_DAYS or more after
    signing up (so 5 throwaway sign-ups can't farm +25 stocks). Pure."""
    def ts(v):
        try:
            t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    created, seen = ts(user.get("created_at")), ts(user.get("last_seen_at"))
    return bool(created and seen and (now - created).days >= EARN_MIN_AGE_DAYS
                and (seen - created).days >= EARN_CAME_BACK_DAYS)


def reward_first_follow(user_id: str) -> Optional[str]:
    """Mark the user's pending referral rewarded once it is earned (a follow
    plus earned()). Returns the referrer's id when THIS call rewarded it, else
    None. Idempotent and race-safe (conditional update on status = 'pending').
    Never raises. Not earned yet: stays pending; the nightly reward_due() pays it later."""
    if not user_id or _settled_cache.get(user_id):
        return None
    now_dt = datetime.now(timezone.utc)
    try:
        u = (_db().table("users").select("created_at, last_seen_at").eq("id", user_id).limit(1)
             .execute().data or [{}])[0]
    except Exception as e:
        logger.debug(f"referrals: reward check skipped: {type(e).__name__}")
        return None
    if not earned(u, now_dt):
        return None
    now = now_dt.isoformat()
    try:
        rows = (_db().table("referrals").update({"status": "rewarded", "rewarded_at": now})
                .eq("referred_id", user_id).eq("status", "pending").execute().data or [])
    except Exception as e:
        logger.debug(f"referrals: reward skipped for {user_id}: {e}")
        return None
    _settled_cache.set(user_id, True)
    if not rows:
        return None
    referrer = str(rows[0]["referrer_id"])
    _rewarded_cache.delete(referrer)
    logger.info(f"referrals: referral of {referrer[:8]} rewarded")
    return referrer


def reward_due(now: Optional[datetime] = None) -> list[str]:
    """Nightly: pay pending referrals whose friend now qualifies (followed a
    stock + earned()). Returns the referrers rewarded (to notify). Blocking."""
    from app.db.queries import _select_all_pages
    now = now or datetime.now(timezone.utc)
    db = _db()
    pending = _select_all_pages(lambda: db.table("referrals").select("referred_id").eq("status", "pending")
                                .not_.is_("referred_id", "null").order("id"))
    out = []
    for r in pending:
        uid = str(r["referred_id"])
        try:
            followed = (db.table("holdings").select("id").eq("user_id", uid).limit(1).execute().data
                        or db.table("watchlist").select("id").eq("user_id", uid).limit(1).execute().data)
        except Exception:
            continue
        if followed:
            ref = reward_first_follow(uid)
            if ref:
                out.append(ref)
    return out


async def notify_referrer(referrer_id: str) -> bool:
    """Telegram "+5 stocks" message to the referrer when they have a linked
    notification chat and feature.telegram_alerts. Never raises."""
    from app.notifications.messages import msg_for
    from app.services import telegram_notify

    try:
        level = (await asyncio.to_thread(access.get_user_access, referrer_id))["level"]
        if not access.can(level, telegram_notify.FEATURE):
            return False
        chat = await asyncio.to_thread(telegram_notify.linked_chat, referrer_id)
        if not chat:
            return False
        lang = await asyncio.to_thread(telegram_notify.user_language, referrer_id)
        return bool(await telegram_notify.send(chat, msg_for(lang, "user_tg_referral_rewarded",
                                                             per_friend=access.REFERRAL_SLOTS_PER_FRIEND)))
    except Exception as e:  # before 016, Telegram down, ...
        logger.debug(f"referrals: referrer {referrer_id} not notified: {type(e).__name__}")
        return False


async def after_follow(user_id: str) -> Optional[str]:
    """Call after a successful holdings save / watchlist add. Rewards a
    pending referral (awaited, cheap) and enqueues the referrer's Telegram
    message in the background. Returns the rewarded referrer's id or None."""
    referrer = await asyncio.to_thread(reward_first_follow, user_id)
    if referrer:
        task = asyncio.create_task(notify_referrer(referrer))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    return referrer
