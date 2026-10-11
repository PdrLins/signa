"""Account deletion and data export (migration 030). App Store 5.1.1(v),
LGPD art. 18 (deletion, access, portability), PIPEDA.

Delete (DELETE /api/v1/account {"password", "now"?})
  Default: the account waits GRACE_DAYS. It is signed out everywhere, its
  push devices are removed and no notification or suggestion uses it. Signing
  in before the date with "restore_account": true brings everything back;
  without it, sign-in answers 403 account_pending_deletion {deletion_date}.
  "now": true deletes at once.
  The nightly job (purge_due) deletes accounts whose date has passed.

Hard delete (purge)
  Every user-owned table cascades from users. Before that, what must stay is
  anonymized: security log rows lose the user id (they're kept 180 days),
  problem reports lose device details. The friend who invited the user keeps
  their reward (referrals.referred_id is set to NULL). The username is
  reserved for USERNAME_HOLD_DAYS so nobody can take a just-deleted name.

Export (GET /api/v1/account/export)
  One JSON document with everything stored about the user, in the same
  shapes the API returns (transactions use the import template's fields).

The owner account can't be deleted from the app.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from loguru import logger

from app.core.api_errors import api_error
from app.core.security import verify_password

MIGRATION = "030_account_lifecycle.sql"
GRACE_DAYS = 30
USERNAME_HOLD_DAYS = 90


def _db():
    from app.db.supabase import get_client
    return get_client()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _user(user_id: str) -> dict:
    rows = (_db().table("users").select("id, username, password_hash, access_level, deletion_scheduled_at")
            .eq("id", user_id).limit(1).execute().data or [])
    if not rows:
        raise api_error("not_found", "Account not found.", 404)
    return rows[0]


def _forget_in_memory(user_id: str) -> None:
    from app.core import access, user_cache
    user_cache.invalidate(user_id)
    access._level_cache.delete(user_id)
    access._last_level.delete(user_id)


def request_deletion(user_id: str, password: str, now: bool = False) -> dict:
    """Blocking. {"status": "pending_deletion", "deletion_date"} or {"status": "deleted"}."""
    u = _user(user_id)
    if (u.get("access_level") or "free") == "owner":
        raise api_error("owner_cannot_delete", "The owner account can't be deleted from the app.", 403)
    if not verify_password(password or "", u["password_hash"]):
        raise api_error("wrong_password", "That password is not right.", 403)
    from app.services import sessions
    sessions.revoke_others(user_id, None, "account_deleted")
    _audit("ACCOUNT_DELETE_REQUESTED", user_id, now=now)
    if now:
        purge(user_id)
        return {"status": "deleted"}
    when = _now() + timedelta(days=GRACE_DAYS)
    _db().table("users").update({"deletion_requested_at": _now().isoformat(),
                                 "deletion_scheduled_at": when.isoformat()}).eq("id", user_id).execute()
    _db().table("push_devices").delete().eq("user_id", user_id).execute()   # no pushes while pending
    _forget_in_memory(user_id)
    logger.info(f"account {user_id[:8]} scheduled for deletion on {when.date()}")
    return {"status": "pending_deletion", "deletion_date": when.date().isoformat()}


def pending_deletion_date(user: dict) -> str | None:
    """The date a pending account will be deleted, or None. Pure."""
    v = user.get("deletion_scheduled_at")
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def restore(user_id: str) -> None:
    """Cancel a pending deletion (the user signed in with restore_account)."""
    _db().table("users").update({"deletion_requested_at": None, "deletion_scheduled_at": None}) \
        .eq("id", user_id).execute()
    _forget_in_memory(user_id)
    _audit("ACCOUNT_RESTORED", user_id)
    logger.info(f"account {user_id[:8]} restored")


def purge(user_id: str) -> None:
    """Delete the account now (cascade), anonymizing what must stay. Blocking."""
    db = _db()
    rows = db.table("users").select("username").eq("id", user_id).limit(1).execute().data or []
    if rows and rows[0].get("username"):
        db.table("reserved_usernames").upsert(
            {"username": rows[0]["username"],
             "until": (_now() + timedelta(days=USERNAME_HOLD_DAYS)).isoformat()},
            on_conflict="username").execute()
    db.table("audit_logs").update({"user_id": None}).eq("user_id", user_id).execute()
    db.table("feedback_reports").update({"diagnostics": None, "device_model": None, "os_version": None,
                                         "locale": None}).eq("user_id", user_id).execute()
    db.table("users").delete().eq("id", user_id).execute()   # everything else cascades
    _forget_in_memory(user_id)
    logger.info(f"account {user_id[:8]} deleted")


def purge_due(now: datetime | None = None) -> dict:
    """Nightly: delete accounts whose grace period has ended. Never raises per account."""
    now = now or _now()
    rows = (_db().table("users").select("id").lt("deletion_scheduled_at", now.isoformat())
            .limit(500).execute().data or [])
    done = failed = 0
    for r in rows:
        try:
            purge(str(r["id"]))
            done += 1
        except Exception as e:
            failed += 1
            logger.error(f"account purge failed for {str(r['id'])[:8]}: {type(e).__name__}")
    return {"deleted": done, "failed": failed}


def username_reserved(username: str, now: datetime | None = None) -> bool:
    try:
        rows = (_db().table("reserved_usernames").select("until").eq("username", username)
                .gt("until", (now or _now()).isoformat()).limit(1).execute().data or [])
    except Exception:
        return False   # before migration 030
    return bool(rows)


# ---------------------------------------------------------------- export

EXPORT_TABLES = (   # (name in the export, table, columns, order for paging or None = one row, owner column)
    ("settings", "user_settings", "*", None, "user_id"),
    ("notification_prefs", "notification_prefs", "prefs, updated_at", None, "user_id"),
    ("sign_up_source", "signup_sources", "platform, country, heard_from, utm_source, utm_medium, utm_campaign, "
     "utm_content, utm_term, invite, created_at", None, "user_id"),
    ("people", "portfolio_people", "*", "id", "user_id"),
    ("accounts", "accounts", "*", "id", "user_id"),
    ("holdings", "holdings", "*", "id", "user_id"),
    ("transactions", "transactions", "*", "id", "user_id"),
    ("saved_imports", "import_mappings", "name, signature, headers, mapping, created_at, updated_at", "id",
     "user_id"),
    ("fixed_income", "fixed_income", "*", "id", "user_id"),
    ("dismissed_auto_dividends", "auto_dividend_dismissed", "auto_ref, created_at", "auto_ref", "user_id"),
    ("watchlist", "watchlist", "*", "id", "user_id"),
    ("price_alerts", "price_alerts", "*", "id", "user_id"),
    ("goals", "goals", "*", "id", "user_id"),
    ("problem_reports", "feedback_reports", "id, kind, message, symbol, status, platform, screen, app_version, "
     "os_version, device_model, created_at, resolved_at", "id", "user_id"),
    ("signed_in_devices", "auth_sessions", "client, device_name, created_at, last_used_at, revoked_at", "id",
     "user_id"),
    ("telegram", "telegram_links", "chat_id, username, linked_at", None, "user_id"),
    ("invites_sent", "referrals", "status, created_at, rewarded_at", "created_at", "referrer_id"),   # no friend ids
    ("active_days", "user_activity_days", "day", "day", "user_id"),
)
# What the export leaves out on purpose, and why (also written into the file as `left_out`).
EXPORT_LEFT_OUT = {
    "password, sign-in codes, refresh tokens": "security secrets; never shown, only checked",
    "IP addresses, browser/app user agents, audit logs": "security records kept to protect the account; "
                                                         "available on request through the privacy contact",
    "push notification tokens": "Apple device identifiers with no meaning outside push delivery",
    "portfolio and income snapshots": "computed from your holdings and transactions, which are included",
    "notifications already sent": "an internal list that stops the same alert being sent twice",
    "Apple Search Ads ids": "ad campaign ids from Apple, not entered by you; available on request",
}


def export(user_id: str) -> dict:
    """Everything the user entered or that describes them. Blocking."""
    from app.db.queries import _select_all_pages
    db = _db()
    cols = ("id", "username", "account_id", "email", "access_level", "created_at", "last_login",
            "two_factor_method")
    row = (db.table("users").select(", ".join(cols)).eq("id", user_id).limit(1).execute().data or [{}])[0]
    u = {k: row.get(k) for k in cols}   # explicit: never a password hash or internal column
    out: dict = {"exported_at": _now().isoformat(), "format": "signa-export-1", "account": u}
    for name, table, cols, order, owner in EXPORT_TABLES:
        try:
            if order:
                rows = _select_all_pages(lambda t=table, c=cols, o=order, w=owner:
                                         db.table(t).select(c).eq(w, user_id).order(o))
            else:
                rows = db.table(table).select(cols).eq(owner, user_id).limit(5).execute().data or []
        except Exception as e:
            logger.debug(f"export: {table} unavailable ({type(e).__name__})")
            rows = []
        for r in rows:
            r.pop("user_id", None)
        out[name] = rows
    out["left_out"] = EXPORT_LEFT_OUT
    return out


def _audit(event: str, user_id: str, **meta) -> None:
    try:
        from app.db import queries
        queries.insert_audit_log(event_type=event, success=True, user_id=user_id, metadata=meta)
    except Exception:
        pass
