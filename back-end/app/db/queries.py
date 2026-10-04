"""Reusable database query helpers for all Supabase tables."""

from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger

from postgrest.types import ReturnMethod

from app.db.supabase import get_client


# ============================================================
# USERS
# ============================================================

def get_user_by_username(username: str) -> dict | None:
    """Look up a user by exact (lower-cased) username.

    Uses .eq, not .ilike: ILIKE treats '%', '_' (and PostgREST '*') as
    wildcards, so a username of '%' would match the first user. Usernames are
    stored lower-case.
    """
    client = get_client()
    result = (
        client.table("users")
        # "*": also email / email_verified_at once migration 018 adds them
        .select("*")
        .eq("username", username.strip().lower())
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def get_user_by_email(email: str) -> dict | None:
    """Look up a user by (lower-cased) email, active or not (an unconfirmed
    sign-up is inactive). Migration 018; raises before it."""
    client = get_client()
    rows = client.table("users").select("*").eq("email", email.strip().lower()).limit(1).execute().data
    return rows[0] if rows else None


def get_user_by_id(user_id: str) -> dict | None:
    """Look up a user by ID (excludes password_hash)."""
    client = get_client()
    result = (
        client.table("users")
        .select("id, username, telegram_chat_id, is_active")
        .eq("id", user_id)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def update_user_last_login(user_id: str) -> None:
    """Update the last_login timestamp for a user."""
    client = get_client()
    client.table("users").update(
        {"last_login": datetime.now(timezone.utc).isoformat()}
    ).eq("id", user_id).execute()


# ============================================================
# OTP CODES
# ============================================================

def insert_otp(
    user_id: str,
    session_token: str,
    code_hash: str,
    expires_at: datetime,
) -> dict:
    """Store an OTP code."""
    client = get_client()
    data = {
        "user_id": user_id,
        "session_token": session_token,
        "code_hash": code_hash,
        "expires_at": expires_at.isoformat(),
        "attempts": 0,
    }
    result = client.table("otp_codes").insert(data).execute()
    return result.data[0] if result.data else {}


def get_otp_by_session_token(session_token: str) -> dict | None:
    """Look up an OTP record by session token."""
    client = get_client()
    result = (
        client.table("otp_codes")
        .select("*")
        .eq("session_token", session_token)
        .is_("used_at", "null")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def mark_otp_used(otp_id: str) -> bool:
    """Atomically mark an OTP as used.

    Conditional on used_at IS NULL, so only one of several concurrent
    verifications can succeed. Returns True if this call consumed the OTP.
    """
    client = get_client()
    result = (
        client.table("otp_codes")
        .update({"used_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", otp_id)
        .is_("used_at", "null")
        .execute()
    )
    return bool(result.data)


def increment_otp_attempts(otp_id: str) -> None:
    """Atomically increment the attempt counter for an OTP via RPC."""
    client = get_client()
    # Use raw SQL via rpc for atomic increment to prevent race conditions
    client.rpc("increment_otp_attempts", {"otp_uuid": str(otp_id)}).execute()


def invalidate_otp(otp_id: str) -> None:
    """Invalidate an OTP (mark used without verification)."""
    client = get_client()
    client.table("otp_codes").update(
        {"used_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", otp_id).execute()


# ============================================================
# TOKEN BLACKLIST
# ============================================================

def blacklist_token(token_jti: str, user_id: str, expires_at: datetime) -> None:
    """Add a token to the blacklist (on logout)."""
    from app.core.cache import blacklist_cache
    client = get_client()
    client.table("token_blacklist").insert({
        "token_jti": token_jti,
        "user_id": user_id,
        "expires_at": expires_at.isoformat(),
    }).execute()
    # Immediately mark as blacklisted in cache
    blacklist_cache.set(f"bl:{token_jti}", True, ttl=3600)


def is_token_blacklisted(token_jti: str) -> bool:
    """Check if a token has been blacklisted. Uses TTL cache to avoid DB hit per request."""
    from app.core.cache import blacklist_cache
    cache_key = f"bl:{token_jti}"

    cached = blacklist_cache.get(cache_key)
    if cached is not None:
        return cached

    client = get_client()
    result = (
        client.table("token_blacklist")
        .select("id")
        .eq("token_jti", token_jti)
        .limit(1)
        .execute()
    )
    is_blocked = len(result.data) > 0 if result.data else False
    # Cache: blacklisted tokens cached 5 min, non-blacklisted 30s
    blacklist_cache.set(cache_key, is_blocked, ttl=300 if is_blocked else 30)
    return is_blocked


# ============================================================
# AUDIT LOGS
# ============================================================

def insert_audit_log(
    event_type: str,
    success: bool,
    user_id: str | None = None,
    ip_address: str = "unknown",
    user_agent: str = "",
    metadata: dict | None = None,
) -> dict:
    """Write an audit log entry."""
    client = get_client()
    data = {
        "event_type": event_type,
        "user_id": user_id,
        "ip_address": ip_address,
        "user_agent": user_agent,
        "metadata": metadata or {},
        "success": success,
    }
    result = client.table("audit_logs").insert(data).execute()
    return result.data[0] if result.data else {}


# ============================================================
# PORTFOLIO
# ============================================================

def get_portfolio(user_id: str) -> list[dict]:
    """Get all portfolio entries for a user."""
    client = get_client()
    result = (
        client.table("portfolio")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(200)
        .execute()
    )
    return result.data or []


def add_portfolio_item(user_id: str, data: dict) -> dict:
    """Add an item to the portfolio."""
    client = get_client()
    result = client.table("portfolio").insert({**data, "user_id": user_id}).execute()
    return result.data[0] if result.data else {}


def update_portfolio_item(item_id: str, user_id: str, data: dict) -> dict:
    """Update a portfolio item (does not mutate input dict)."""
    client = get_client()
    update_data = {**data, "updated_at": datetime.now(timezone.utc).isoformat()}
    result = (
        client.table("portfolio")
        .update(update_data)
        .eq("id", item_id)
        .eq("user_id", user_id)
        .execute()
    )
    return result.data[0] if result.data else {}


def delete_portfolio_item(item_id: str, user_id: str) -> bool:
    """Delete a portfolio item."""
    client = get_client()
    result = (
        client.table("portfolio")
        .delete()
        .eq("id", item_id)
        .eq("user_id", user_id)
        .execute()
    )
    return len(result.data) > 0 if result.data else False


# ============================================================
# HOLDINGS (the owner's real long-term positions — migration 010)
# ============================================================

HOLDING_COLUMNS = (
    "id, user_id, symbol, input_symbol, name, exchange, currency, asset_type, shares, avg_cost, "
    "account, notes, holding_status, status_updated_at, alert_state, last_review, last_reviewed_at, "
    "created_at, updated_at"
)
# account_id arrives with migration 013. Until it is applied the column is
# missing: selects retry without it (re-probed every 5 minutes, so applying
# the migration takes effect without a restart).
_ACCOUNT_ID_RETRY_S = 300
_holdings_no_account_id_at: float | None = None


def _missing_schema(err: Exception) -> bool:
    from app.core.api_errors import is_missing_schema
    return is_missing_schema(err)


def holdings_have_account_id() -> bool:
    """False while migration 013 is known to be missing (re-probed every 5 min)."""
    import time
    at = _holdings_no_account_id_at
    return at is None or time.time() - at > _ACCOUNT_ID_RETRY_S


def _select_holdings(build) -> list[dict]:
    """Run `build(columns)` with account_id, falling back to the 010 columns."""
    global _holdings_no_account_id_at
    import time
    if holdings_have_account_id():
        try:
            rows = _select_all_pages(lambda: build(HOLDING_COLUMNS + ", account_id"))
            _holdings_no_account_id_at = None
            return rows
        except Exception as e:
            if not (_missing_schema(e) and "account_id" in str(e).lower()):
                raise
            logger.warning("holdings.account_id missing — apply migration 013_portfolio_foundation.sql")
            _holdings_no_account_id_at = time.time()
    rows = _select_all_pages(lambda: build(HOLDING_COLUMNS))
    return [{**r, "account_id": None} for r in rows]


def get_holdings(user_id: str) -> list[dict]:
    """All holdings for a user, oldest first (import order). Rows carry
    account_id (None before migration 013)."""
    client = get_client()
    return _select_holdings(lambda cols: (
        client.table("holdings").select(cols).eq("user_id", user_id).order("created_at").order("id")
    ))


def get_all_holding_names() -> list[dict]:
    """symbol, name, exchange, asset_type of every holding (symbol search), 4 columns only."""
    client = get_client()
    return _select_all_pages(lambda: client.table("holdings").select("id, symbol, name, exchange, asset_type")
                             .order("id"))


def get_all_holdings() -> list[dict]:
    """Every user's holdings (scheduler monitor)."""
    client = get_client()
    return _select_holdings(lambda cols: client.table("holdings").select(cols).order("id"))   # pk: cheap paging


def upsert_holdings(user_id: str, rows: list[dict]) -> list[dict]:
    """Insert or update holdings keyed on (user_id, account_id, symbol).

    Every row must carry the same keys; `user_id` is forced. After
    migration 013 the unique key is an expression index (COALESCE on
    account_id), which PostgREST's on_conflict can't target, so existing
    rows are matched here and updated by id; the rest are inserted in one
    call. Before 013 (no account_id column) the 010 upsert on
    (user_id, symbol) is used and account_id must be empty.
    """
    if not rows:
        return []
    client = get_client()
    try:
        existing = _select_all_pages(lambda: client.table("holdings").select("id, symbol, account_id")
                                     .eq("user_id", user_id).order("id"))
    except Exception as e:
        if not _missing_schema(e):
            raise
        if any(r.get("account_id") for r in rows):
            from app.core.api_errors import MigrationRequired
            raise MigrationRequired("holdings.account_id missing (013)")
        payload = [{**{k: v for k, v in r.items() if k != "account_id"}, "user_id": user_id} for r in rows]
        result = client.table("holdings").upsert(payload, on_conflict="user_id,symbol").execute()
        return result.data or []
    index = {(str(x.get("account_id") or ""), x["symbol"]): x["id"] for x in existing}
    out: list[dict] = []
    inserts: list[dict] = []
    updates: list[dict] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for r in rows:
        hid = index.get((str(r.get("account_id") or ""), r["symbol"]))
        if hid:
            updates.append({**r, "id": hid, "user_id": user_id, "updated_at": now_iso})
        else:
            inserts.append({**r, "user_id": user_id})
    # Existing rows: one bulk upsert on the primary key (only the sent columns
    # change), not one PATCH per holding.
    for i in range(0, len(updates), 500):
        out.extend(client.table("holdings").upsert(updates[i:i + 500], on_conflict="id").execute().data or [])
    if inserts:
        out.extend(client.table("holdings").insert(inserts).execute().data or [])
    return out


def move_holdings(user_id: str, holding_ids: list[str], account_id: str | None) -> None:
    """Move holdings to another account (or none) in chunks of 200 ids."""
    client = get_client()
    now_iso = datetime.now(timezone.utc).isoformat()
    for i in range(0, len(holding_ids), 200):
        (client.table("holdings").update({"account_id": account_id, "updated_at": now_iso},
                                         returning=ReturnMethod.minimal)
         .eq("user_id", user_id).in_("id", holding_ids[i:i + 200]).execute())


def set_symbol_status(symbol: str, data: dict, user_id: str | None = None) -> None:
    """Same holding_status on every holding of `symbol` (one user's, or everyone's)."""
    q = get_client().table("holdings").update(data, returning=ReturnMethod.minimal).eq("symbol", symbol)
    (q.eq("user_id", user_id) if user_id else q).execute()


def update_holding(holding_id: str, user_id: str, data: dict) -> dict | None:
    """Update one holding owned by `user_id` (does not mutate `data`)."""
    client = get_client()
    update_data = {**data, "updated_at": datetime.now(timezone.utc).isoformat()}
    result = (
        client.table("holdings")
        .update(update_data)
        .eq("id", holding_id)
        .eq("user_id", user_id)
        .execute()
    )
    return result.data[0] if result.data else None


def delete_holding(holding_id: str, user_id: str) -> bool:
    client = get_client()
    result = (
        client.table("holdings")
        .delete()
        .eq("id", holding_id)
        .eq("user_id", user_id)
        .execute()
    )
    return bool(result.data)


# ============================================================
# WATCHLIST
# ============================================================

def get_watchlist(user_id: str) -> list[dict]:
    """Get all watchlist items for a user."""
    client = get_client()
    # every row (Premium is unlimited), newest first; id breaks ties for stable paging
    return _select_all_pages(lambda: client.table("watchlist").select("*").eq("user_id", user_id)
                             .order("added_at", desc=True).order("id"))


def get_all_watchlist_symbols() -> set[str]:
    """Get watchlisted symbols for the brain user.

    Signa is currently single-tenant: the brain operates on behalf of one
    user (resolved via `get_brain_user_id`), so this returns only that
    user's watchlist. The function name is kept for backwards compatibility
    with existing call sites — the "all" used to mean "all users" before
    we added per-user scoping. Returning all users' symbols was the bug
    that caused stale `source='watchlist'` virtual_trades when symbols left
    the watchlist between scans.
    """
    user_id = get_brain_user_id()
    if not user_id:
        return set()
    client = get_client()
    result = (
        client.table("watchlist")
        .select("symbol")
        .eq("user_id", user_id)
        .limit(1000)
        .execute()
    )
    return {row["symbol"] for row in (result.data or [])}


_brain_user_id_cache: str | None = None


def get_brain_user_id() -> str | None:
    """Resolve the user_id the brain operates on behalf of.

    Single-tenant for now — returns the oldest user in the users table.
    Cached for the lifetime of the process; if the user is deleted/recreated
    you must restart the process. Returns None when the users table is empty
    (which only happens during a fresh install before signup).

    Used by `place_virtual_trades` to stamp `user_id` on every virtual_trades
    insert, and by `get_all_watchlist_symbols` to scope the watchlist read.
    """
    global _brain_user_id_cache
    if _brain_user_id_cache is not None:
        return _brain_user_id_cache
    client = get_client()
    result = (
        client.table("users")
        .select("id")
        .order("created_at")
        .limit(1)
        .execute()
    )
    if result.data:
        _brain_user_id_cache = result.data[0]["id"]
        return _brain_user_id_cache
    logger.warning("get_brain_user_id: no users in table — virtual_trades will be inserted without user_id")
    return None


def add_to_watchlist(user_id: str, symbol: str, notes: str | None = None) -> dict:
    """Add a ticker to the watchlist."""
    client = get_client()
    data = {"user_id": user_id, "symbol": symbol.upper(), "notes": notes}
    result = client.table("watchlist").upsert(data, on_conflict="user_id,symbol").execute()
    logger.info(f"Added {symbol} to watchlist for user {user_id}")
    return result.data[0] if result.data else {}


def remove_from_watchlist(user_id: str, symbol: str) -> bool:
    """Remove a ticker from the watchlist."""
    client = get_client()
    result = (
        client.table("watchlist")
        .delete()
        .eq("user_id", user_id)
        .eq("symbol", symbol.upper())
        .execute()
    )
    removed = len(result.data) > 0 if result.data else False
    if removed:
        logger.info(f"Removed {symbol} from watchlist for user {user_id}")
    return removed


# ============================================================
# USER SETTINGS
# ============================================================

def get_user_settings(user_id: str) -> dict:
    """Get user settings. Creates default if not exists."""
    client = get_client()
    result = client.table("user_settings").select("*").eq("user_id", user_id).limit(1).execute()
    if result.data:
        return result.data[0]
    # Create default settings
    default = {"user_id": user_id, "theme": "midnight", "language": "en"}
    # two first loads at once: the second insert is ignored (was a 500)
    client.table("user_settings").upsert(default, on_conflict="user_id", ignore_duplicates=True).execute()
    return default


def update_user_settings(user_id: str, data: dict) -> dict:
    """Update user settings."""
    client = get_client()
    allowed = {"theme", "language"}
    clean = {k: v for k, v in data.items() if k in allowed}
    if not clean:
        return get_user_settings(user_id)
    result = client.table("user_settings").upsert({"user_id": user_id, **clean}).execute()
    return result.data[0] if result.data else clean


# ============================================================
# Paging
# ============================================================

_PAGE = 1000  # PostgREST default max rows per request


def _select_all_pages(build_query, page_size: int = _PAGE, max_rows: int = 5_000_000) -> list[dict]:
    """Page through a select with .range() until a short page comes back.
    Whole-table reads (jobs) can be large: the cap is a safety net, logged."""
    rows: list[dict] = []
    start = 0
    while start < max_rows:
        page = (build_query().range(start, start + page_size - 1).execute()).data or []
        rows.extend(page)
        if len(page) < page_size:
            return rows
        start += page_size
    logger.warning(f"queries: read stopped at {max_rows} rows")
    return rows


# ============================================================
# PORTFOLIO TRACKER (migration 013): profile, people, accounts,
# transactions, quotes, snapshots, notification prefs
# ============================================================

PROFILE_COLUMNS = (
    "user_id, language, display_name, country, home_currency, dividend_tax_view, "
    "compare_index, holdings_native_currency"
)


def get_profile_settings(user_id: str) -> dict | None:
    """The profile columns of user_settings (None when the user has no row).
    Raises when migration 013 is missing (unknown columns)."""
    client = get_client()
    result = client.table("user_settings").select(PROFILE_COLUMNS).eq("user_id", user_id).limit(1).execute()
    return result.data[0] if result.data else None


def upsert_profile_settings(user_id: str, data: dict) -> dict:
    client = get_client()
    result = client.table("user_settings").upsert({**data, "user_id": user_id}, on_conflict="user_id").execute()
    return result.data[0] if result.data else {"user_id": user_id, **data}


def get_user_email(user_id: str) -> str | None:
    """users.email when that column exists (it doesn't in schema.sql yet)."""
    client = get_client()
    try:
        rows = client.table("users").select("email").eq("id", user_id).limit(1).execute().data or []
    except Exception:
        return None
    email = (rows[0] if rows else {}).get("email")
    return email if isinstance(email, str) and email else None


def get_user_home_currencies(user_ids: list[str]) -> dict[str, str]:
    """user_id -> home_currency for the given users (missing -> not in dict)."""
    if not user_ids:
        return {}
    client = get_client()
    out: dict[str, str] = {}
    for i in range(0, len(user_ids), 200):
        chunk = user_ids[i:i + 200]
        rows = (client.table("user_settings").select("user_id, home_currency")
                .in_("user_id", chunk).execute().data or [])
        out.update({str(r["user_id"]): r.get("home_currency") or "CAD" for r in rows})
    return out


# ---- people ----

PERSON_COLUMNS = "id, user_id, name, color, created_at"


def get_people(user_id: str) -> list[dict]:
    client = get_client()
    return (client.table("portfolio_people").select(PERSON_COLUMNS).eq("user_id", user_id)
            .order("created_at").limit(200).execute().data or [])


def insert_person(user_id: str, data: dict) -> dict:
    client = get_client()
    result = client.table("portfolio_people").insert({**data, "user_id": user_id}).execute()
    return result.data[0] if result.data else {}


def update_person(person_id: str, user_id: str, data: dict) -> dict | None:
    client = get_client()
    result = (client.table("portfolio_people").update(data).eq("id", person_id)
              .eq("user_id", user_id).execute())
    return result.data[0] if result.data else None


def delete_person(person_id: str, user_id: str) -> bool:
    client = get_client()
    result = client.table("portfolio_people").delete().eq("id", person_id).eq("user_id", user_id).execute()
    return bool(result.data)


# ---- accounts ----

ACCOUNT_COLUMNS = "id, user_id, person_id, name, account_type, currency, cash_balance, created_at, updated_at"


def get_accounts(user_id: str) -> list[dict]:
    client = get_client()
    return _select_all_pages(lambda: client.table("accounts").select(ACCOUNT_COLUMNS).eq("user_id", user_id)
                             .order("created_at").order("id"))


def get_all_accounts() -> list[dict]:
    client = get_client()
    return _select_all_pages(lambda: client.table("accounts").select(ACCOUNT_COLUMNS).order("id"))   # pk: cheap paging


def insert_accounts(user_id: str, rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    client = get_client()
    result = client.table("accounts").insert([{**r, "user_id": user_id} for r in rows]).execute()
    return result.data or []


def update_account(account_id: str, user_id: str, data: dict) -> dict | None:
    client = get_client()
    result = client.table("accounts").update(data).eq("id", account_id).eq("user_id", user_id).execute()
    return result.data[0] if result.data else None


def delete_account(account_id: str, user_id: str) -> bool:
    client = get_client()
    result = client.table("accounts").delete().eq("id", account_id).eq("user_id", user_id).execute()
    return bool(result.data)


def move_account_transactions(user_id: str, from_account_id: str, to_account_id: str | None) -> None:
    client = get_client()
    (client.table("transactions").update({"account_id": to_account_id})
     .eq("user_id", user_id).eq("account_id", from_account_id).execute())


# ---- transactions ----

TRANSACTION_COLUMNS = (
    "id, user_id, account_id, symbol, type, trade_date, quantity, price, amount, currency, fee, note, "
    "source, import_batch_id, created_at"
)


def list_transactions(user_id: str, filters: dict, limit: int, offset: int) -> tuple[list[dict], int]:
    """Newest first. filters: account_id, symbol, type, from, to (ISO dates)."""
    client = get_client()
    q = client.table("transactions").select(TRANSACTION_COLUMNS, count="exact").eq("user_id", user_id)
    if filters.get("account_id"):
        q = q.eq("account_id", filters["account_id"])
    if filters.get("symbol"):
        q = q.eq("symbol", filters["symbol"])
    if filters.get("type"):
        q = q.eq("type", filters["type"])
    if filters.get("from"):
        q = q.gte("trade_date", filters["from"])
    if filters.get("to"):
        q = q.lte("trade_date", filters["to"])
    result = (q.order("trade_date", desc=True).order("created_at", desc=True)
              .range(offset, offset + limit - 1).execute())
    rows = result.data or []
    total = result.count if isinstance(getattr(result, "count", None), int) else offset + len(rows)
    return rows, total


def get_all_transactions(user_id: str) -> list[dict]:
    """Every transaction of a user, oldest first (position derivation)."""
    client = get_client()
    return _select_all_pages(lambda: (client.table("transactions").select(TRANSACTION_COLUMNS)
                                      .eq("user_id", user_id).order("trade_date").order("created_at")))


def get_transaction(tx_id: str, user_id: str) -> dict | None:
    client = get_client()
    rows = (client.table("transactions").select(TRANSACTION_COLUMNS).eq("id", tx_id)
            .eq("user_id", user_id).limit(1).execute().data or [])
    return rows[0] if rows else None


def insert_transactions(user_id: str, rows: list[dict], chunk: int = 500) -> list[dict]:
    """Insert in chunks of `chunk`; every row must carry the same keys."""
    client = get_client()
    out: list[dict] = []
    for i in range(0, len(rows), chunk):
        part = [{**r, "user_id": user_id} for r in rows[i:i + chunk]]
        out.extend(client.table("transactions").insert(part).execute().data or [])
    return out


def update_transaction(tx_id: str, user_id: str, data: dict) -> dict | None:
    client = get_client()
    result = client.table("transactions").update(data).eq("id", tx_id).eq("user_id", user_id).execute()
    return result.data[0] if result.data else None


def delete_transaction(tx_id: str, user_id: str) -> bool:
    client = get_client()
    result = client.table("transactions").delete().eq("id", tx_id).eq("user_id", user_id).execute()
    return bool(result.data)


def delete_transaction_batch(user_id: str, batch_id: str) -> int:
    client = get_client()
    result = (client.table("transactions").delete().eq("user_id", user_id)
              .eq("import_batch_id", batch_id).execute())
    return len(result.data or [])


# ---- quotes (shared by all users) ----

QUOTE_COLUMNS = "symbol, price, prev_close, change_pct, currency, day_high, day_low, as_of, updated_at"
# as_of_source arrives with migration 014; until then reads/writes go without it.
_quotes_no_source_at: float | None = None


def _quotes_have_source() -> bool:
    import time
    at = _quotes_no_source_at
    return at is None or time.time() - at > _ACCOUNT_ID_RETRY_S


def _mark_quotes_no_source(err: Exception) -> bool:
    global _quotes_no_source_at
    import time
    if _missing_schema(err) and "as_of_source" in str(err).lower():
        logger.warning("quotes.as_of_source missing — apply migration 014_portfolio_insights.sql")
        _quotes_no_source_at = time.time()
        return True
    return False


def get_quote_rows(symbols: list[str]) -> list[dict]:
    if not symbols:
        return []
    client = get_client()

    def read(cols: str) -> list[dict]:
        out: list[dict] = []
        for i in range(0, len(symbols), 200):
            out.extend(client.table("quotes").select(cols).in_("symbol", symbols[i:i + 200])
                       .execute().data or [])
        return out
    if _quotes_have_source():
        try:
            return read(QUOTE_COLUMNS + ", as_of_source")
        except Exception as e:
            if not _mark_quotes_no_source(e):
                raise
    return read(QUOTE_COLUMNS)


def get_quote_extended_rows(symbols: list[str]) -> list[dict]:
    """{symbol, ext_price, ext_change_pct, ext_session, ext_as_of} (migration
    021; raises before it)."""
    if not symbols:
        return []
    client = get_client()
    out: list[dict] = []
    for i in range(0, len(symbols), 200):
        out.extend(client.table("quotes").select("symbol, ext_price, ext_change_pct, ext_session, ext_as_of")
                   .in_("symbol", symbols[i:i + 200]).execute().data or [])
    return out


def update_quote_extended(symbol: str, row: dict) -> None:
    """Store a pre/after-hours price on an existing quotes row (migration 021)."""
    get_client().table("quotes").update(row).eq("symbol", symbol).execute()


def upsert_quotes(rows: list[dict], chunk: int = 500) -> int:
    client = get_client()
    if not _quotes_have_source():
        rows = [{k: v for k, v in r.items() if k != "as_of_source"} for r in rows]
    n = 0
    for i in range(0, len(rows), chunk):
        part = rows[i:i + chunk]
        try:
            n += len(client.table("quotes").upsert(part, on_conflict="symbol").execute().data or [])
        except Exception as e:
            if not _mark_quotes_no_source(e):
                raise
            part = [{k: v for k, v in r.items() if k != "as_of_source"} for r in part]
            n += len(client.table("quotes").upsert(part, on_conflict="symbol").execute().data or [])
    return n


def get_all_followed_symbols() -> set[str]:
    """Distinct symbols in every user's holdings and watchlist (quote refresh)."""
    client = get_client()
    out: set[str] = set()
    for table in ("holdings", "watchlist"):
        try:
            rows = _select_all_pages(lambda t=table: client.table(t).select("symbol").order("id"))
        except Exception as e:
            logger.debug(f"followed symbols: {table} unavailable: {e}")
            rows = []
        out.update(str(r["symbol"]).upper() for r in rows if r.get("symbol"))
    return out


# ---- snapshots ----

def replace_portfolio_snapshots(user_id: str, snapshot_date: str, rows: list[dict]) -> int:
    """Idempotent: delete the user's rows for that date, insert the new ones."""
    client = get_client()
    client.table("portfolio_snapshots").delete().eq("user_id", user_id).eq("snapshot_date", snapshot_date).execute()
    if not rows:
        return 0
    payload = [{**r, "user_id": user_id, "snapshot_date": snapshot_date} for r in rows]
    return len(client.table("portfolio_snapshots").insert(payload).execute().data or [])


def replace_portfolio_snapshots_batch(snapshot_date: str, rows_by_user: dict[str, list[dict]],
                                     chunk: int = 200) -> tuple[int, int]:
    """replace_portfolio_snapshots for many users: one delete + one insert per
    `chunk` users instead of two calls per user. Returns (rows written, users failed)."""
    client = get_client()
    users = sorted(rows_by_user)
    written = failed = 0
    for i in range(0, len(users), chunk):
        part = users[i:i + chunk]
        payload = [{**r, "user_id": uid, "snapshot_date": snapshot_date} for uid in part for r in rows_by_user[uid]]
        try:
            client.table("portfolio_snapshots").delete().in_("user_id", part).eq("snapshot_date", snapshot_date).execute()
            for j in range(0, len(payload), 500):
                client.table("portfolio_snapshots").insert(payload[j:j + 500], returning=ReturnMethod.minimal).execute()
            written += len(payload)
        except Exception as e:
            failed += len(part)
            logger.warning(f"snapshots: {len(part)} users failed: {type(e).__name__}: {e}")
    return written, failed


# ---- notification prefs ----

def get_notification_prefs(user_id: str) -> dict | None:
    client = get_client()
    rows = (client.table("notification_prefs").select("prefs, updated_at").eq("user_id", user_id)
            .limit(1).execute().data or [])
    return rows[0] if rows else None


def upsert_notification_prefs(user_id: str, prefs: dict) -> dict:
    client = get_client()
    row = {"user_id": user_id, "prefs": prefs, "updated_at": datetime.now(timezone.utc).isoformat()}
    result = client.table("notification_prefs").upsert(row, on_conflict="user_id").execute()
    return result.data[0] if result.data else row


# ============================================================
# PORTFOLIO INSIGHTS (migration 014)
# ============================================================

SNAPSHOT_COLUMNS = "snapshot_date, account_id, market_value, cash, cost_basis, currency, unconverted"


def get_portfolio_snapshot_rows(user_id: str, since: str | None = None,
                                account_ids: list[str] | None = None) -> list[dict]:
    """portfolio_snapshots rows, oldest first. account_ids None -> the
    whole-portfolio rows (account_id NULL); a list -> those accounts' rows."""
    client = get_client()

    def build():
        q = client.table("portfolio_snapshots").select(SNAPSHOT_COLUMNS).eq("user_id", user_id)
        q = q.is_("account_id", "null") if account_ids is None else q.in_("account_id", account_ids)
        if since:
            q = q.gte("snapshot_date", since)
        return q.order("snapshot_date")
    return _select_all_pages(build)


def get_income_snapshots(user_id: str, since: str | None = None) -> list[dict]:
    """income_forecast_snapshots rows of a user, oldest first."""
    client = get_client()
    q = client.table("income_forecast_snapshots").select(
        "snapshot_date, total_home, currency, usdcad, per_symbol").eq("user_id", user_id)
    if since:
        q = q.gte("snapshot_date", since)
    return q.order("snapshot_date").limit(400).execute().data or []


def get_income_snapshot_bounds(user_id: str, cutoff: str, before: str) -> list[dict]:
    """The oldest snapshot before `before` and the newest on or before `cutoff`
    (what "why your income changed" compares), oldest first."""
    client = get_client()
    cols = "snapshot_date, total_home, currency, usdcad, per_symbol"

    def q():
        return client.table("income_forecast_snapshots").select(cols).eq("user_id", user_id).lt("snapshot_date", before)
    rows = (q().order("snapshot_date").limit(1).execute().data or []) + \
        (q().lte("snapshot_date", cutoff).order("snapshot_date", desc=True).limit(1).execute().data or [])
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: str(r["snapshot_date"])):
        if r["snapshot_date"] not in seen:
            seen.add(r["snapshot_date"])
            out.append(r)
    return out


def upsert_income_snapshot(user_id: str, snapshot_date: str, row: dict) -> int:
    client = get_client()
    payload = {**row, "user_id": user_id, "snapshot_date": snapshot_date}
    return len(client.table("income_forecast_snapshots")
               .upsert(payload, on_conflict="user_id,snapshot_date").execute().data or [])


def get_check_status_rows(symbols: list[str], since: str | None = None) -> list[dict]:
    """check_status_daily rows for symbols, oldest first."""
    if not symbols:
        return []
    client = get_client()
    out: list[dict] = []
    for i in range(0, len(symbols), 200):
        q = client.table("check_status_daily").select("symbol, check_date, statuses").in_(
            "symbol", symbols[i:i + 200])
        if since:
            q = q.gte("check_date", since)
        out.extend(_select_all_pages(lambda q=q: q.order("check_date").order("symbol")))
    return out


def upsert_check_status_rows(rows: list[dict], chunk: int = 500) -> int:
    """rows: [{symbol, check_date, statuses}] (idempotent per symbol/day)."""
    client = get_client()
    n = 0
    for i in range(0, len(rows), chunk):
        n += len(client.table("check_status_daily").upsert(rows[i:i + chunk], on_conflict="symbol,check_date")
                 .execute().data or [])
    return n


def get_allocation_targets(user_id: str) -> dict | None:
    """user_settings.allocation_targets (None when unset)."""
    client = get_client()
    rows = (client.table("user_settings").select("allocation_targets").eq("user_id", user_id)
            .limit(1).execute().data or [])
    return (rows[0] or {}).get("allocation_targets") if rows else None


def set_allocation_targets(user_id: str, targets: dict | None) -> dict | None:
    client = get_client()
    client.table("user_settings").upsert({"user_id": user_id, "allocation_targets": targets},
                                         on_conflict="user_id").execute()
    return targets


# ---- activity (cost control) ----

def touch_user_last_seen(user_id: str) -> None:
    """users.last_seen_at = now (migration 014)."""
    client = get_client()
    client.table("users").update({"last_seen_at": datetime.now(timezone.utc).isoformat()}).eq(
        "id", user_id).execute()


def get_users_activity() -> list[dict]:
    """[{id, access_level, last_seen_at, last_login}] for every active user.
    Falls back gracefully before 011 (no access_level) / 014 (no last_seen_at)."""
    client = get_client()
    for cols in ("id, access_level, last_seen_at, last_login", "id, access_level, last_login", "id, last_login"):
        try:
            return _select_all_pages(lambda c=cols: client.table("users").select(c).eq("is_active", True).order("id"))
        except Exception as e:
            if not _missing_schema(e):
                raise
    return []


def get_follow_rows() -> list[dict]:
    """[{user_id, symbol}] from every user's holdings and watchlist."""
    client = get_client()
    out: list[dict] = []
    for table in ("holdings", "watchlist"):
        try:
            out.extend(_select_all_pages(lambda t=table: client.table(t).select("user_id, symbol").order("id")))
        except Exception as e:
            logger.debug(f"follow rows: {table} unavailable: {e}")
    return out


# ---- usage metrics ----

def increment_data_usage(usage_date: str, metric: str, count: int) -> None:
    client = get_client()
    client.rpc("increment_data_usage", {"p_date": usage_date, "p_metric": metric, "p_count": int(count)}).execute()


def get_data_usage(since: str) -> list[dict]:
    client = get_client()
    return _select_all_pages(lambda: (client.table("data_usage_daily").select("usage_date, metric, count")
                                      .gte("usage_date", since).order("usage_date")))


# ---- price alerts (migration 015) ----

PRICE_ALERT_COLUMNS = ("id, user_id, symbol, direction, target_price, currency, note, active, "
                       "triggered_at, last_price, created_at")


def list_price_alerts(user_id: str, symbol: str | None = None) -> list[dict]:
    client = get_client()

    def build():
        q = client.table("price_alerts").select(PRICE_ALERT_COLUMNS).eq("user_id", user_id)
        return (q.eq("symbol", symbol) if symbol else q).order("created_at", desc=True).order("id")
    return _select_all_pages(build)


def get_price_alert(alert_id: str, user_id: str) -> dict | None:
    client = get_client()
    rows = (client.table("price_alerts").select(PRICE_ALERT_COLUMNS).eq("id", alert_id)
            .eq("user_id", user_id).limit(1).execute().data or [])
    return rows[0] if rows else None


def count_active_price_alerts(user_id: str) -> int:
    client = get_client()
    res = (client.table("price_alerts").select("id", count="exact").eq("user_id", user_id).eq("active", True)
           .limit(1).execute())
    return int(res.count or 0)


def insert_price_alert(user_id: str, data: dict) -> dict:
    client = get_client()
    rows = client.table("price_alerts").insert({**data, "user_id": user_id}).execute().data or []
    return rows[0] if rows else {}


def update_price_alert(alert_id: str, user_id: str, data: dict) -> dict | None:
    client = get_client()
    rows = (client.table("price_alerts").update(data).eq("id", alert_id).eq("user_id", user_id)
            .execute().data or [])
    return rows[0] if rows else None


def delete_price_alert(alert_id: str, user_id: str) -> bool:
    client = get_client()
    rows = client.table("price_alerts").delete().eq("id", alert_id).eq("user_id", user_id).execute().data or []
    return bool(rows)


def get_active_price_alerts(symbols: list[str]) -> list[dict]:
    """Active alerts of every user for `symbols` (quotes job)."""
    if not symbols:
        return []
    client = get_client()
    out: list[dict] = []
    for i in range(0, len(symbols), 200):
        chunk = symbols[i:i + 200]
        out.extend(_select_all_pages(lambda c=chunk: client.table("price_alerts").select(PRICE_ALERT_COLUMNS)
                                     .eq("active", True).in_("symbol", c).order("id")))
    return out


def mark_price_alert_triggered(alert_id: str, triggered_at: str, last_price: float) -> None:
    """Deactivate an alert that fired. Only an still-active row is updated
    (two overlapping job runs can't fire it twice)."""
    client = get_client()
    (client.table("price_alerts").update({"active": False, "triggered_at": triggered_at,
                                          "last_price": last_price})
     .eq("id", alert_id).eq("active", True).execute())


def get_triggered_price_alerts(user_id: str, since_iso: str) -> list[dict]:
    client = get_client()
    return (client.table("price_alerts").select(PRICE_ALERT_COLUMNS).eq("user_id", user_id)
            .gte("triggered_at", since_iso).order("triggered_at", desc=True).limit(500).execute().data or [])


def get_mover_quotes(min_abs_pct: float) -> list[dict]:
    """Quotes that moved at least min_abs_pct either way (live notifications)."""
    client = get_client()
    return _select_all_pages(lambda: client.table("quotes").select("symbol, change_pct, as_of")
                             .or_(f"change_pct.gte.{min_abs_pct},change_pct.lte.{-min_abs_pct}").order("symbol"))


def get_holder_ids(symbols: list[str]) -> set[str]:
    """Users holding any of `symbols`."""
    client = get_client()
    out: set[str] = set()
    for i in range(0, len(symbols), 200):
        rows = _select_all_pages(lambda part=symbols[i:i + 200]: client.table("holdings").select("user_id, id")
                                 .in_("symbol", part).order("id"))
        out |= {str(r["user_id"]) for r in rows if r.get("user_id")}
    return out


def get_recent_alert_user_ids(since_iso: str) -> set[str]:
    """Users with a price alert triggered since `since_iso`."""
    client = get_client()
    rows = _select_all_pages(lambda: client.table("price_alerts").select("user_id, id")
                             .gte("triggered_at", since_iso).order("id"))
    return {str(r["user_id"]) for r in rows if r.get("user_id")}


def get_active_alert_follow_rows() -> list[dict]:
    """[{user_id, symbol}] of active alerts: their symbols need fresh quotes."""
    client = get_client()
    return _select_all_pages(lambda: client.table("price_alerts").select("user_id, symbol").eq("active", True)
                             .order("id"))


# ============================================================
# TELEGRAM NOTIFICATIONS (migration 016)
# ============================================================

def get_telegram_link(user_id: str) -> dict | None:
    """The user's notification chat {user_id, chat_id, username, linked_at} or None."""
    client = get_client()
    rows = client.table("telegram_links").select("*").eq("user_id", user_id).limit(1).execute().data or []
    return rows[0] if rows else None


def get_telegram_links() -> list[dict]:
    """Every linked notification chat (delivery jobs)."""
    client = get_client()
    return _select_all_pages(lambda: client.table("telegram_links").select("user_id, chat_id, username")
                             .order("user_id"))


def upsert_telegram_link(user_id: str, chat_id: str, username: str | None) -> dict:
    """Link `chat_id` to the user. A chat belongs to one user: it is removed
    from any other user first (linking from a second account moves it)."""
    client = get_client()
    client.table("telegram_links").delete().eq("chat_id", chat_id).neq("user_id", user_id).execute()
    row = {"user_id": user_id, "chat_id": chat_id, "username": username,
           "linked_at": datetime.now(timezone.utc).isoformat()}
    result = client.table("telegram_links").upsert(row, on_conflict="user_id").execute()
    return result.data[0] if result.data else row


def delete_telegram_link(user_id: str) -> None:
    get_client().table("telegram_links").delete().eq("user_id", user_id).execute()


def replace_telegram_link_code(user_id: str, code_hash: str, expires_at: str) -> None:
    """Store a new one-time code; the user's older unused codes stop working."""
    client = get_client()
    client.table("telegram_link_codes").delete().eq("user_id", user_id).is_("used_at", "null").execute()
    client.table("telegram_link_codes").insert(
        {"code_hash": code_hash, "user_id": user_id, "expires_at": expires_at}).execute()


def get_pending_telegram_link_code(user_id: str, now_iso: str) -> dict | None:
    """The user's newest unused, unexpired code {expires_at} or None."""
    client = get_client()
    rows = (client.table("telegram_link_codes").select("expires_at").eq("user_id", user_id)
            .is_("used_at", "null").gt("expires_at", now_iso).order("expires_at", desc=True)
            .limit(1).execute().data or [])
    return rows[0] if rows else None


def consume_telegram_link_code(code_hash: str, now_iso: str) -> str | None:
    """Mark an unused, unexpired code used; returns its user_id, or None.
    Conditional update (used_at IS NULL): a code can be spent only once."""
    client = get_client()
    rows = (client.table("telegram_link_codes").update({"used_at": now_iso})
            .eq("code_hash", code_hash).is_("used_at", "null").gt("expires_at", now_iso)
            .execute().data or [])
    return str(rows[0]["user_id"]) if rows else None


def get_delivered_keys(user_id: str, keys: list[str]) -> set[str]:
    """Which of `keys` were already sent to the user."""
    if not keys:
        return set()
    client = get_client()
    rows = (client.table("notification_deliveries").select("dedupe_key").eq("user_id", user_id)
            .in_("dedupe_key", keys).execute().data or [])
    return {r["dedupe_key"] for r in rows}


def insert_deliveries(user_id: str, items: list[tuple[str, str]]) -> None:
    """Record sent notifications [(kind, dedupe_key)]; duplicates are ignored."""
    if not items:
        return
    rows = [{"user_id": user_id, "kind": k, "dedupe_key": key} for k, key in items]
    get_client().table("notification_deliveries").upsert(
        rows, on_conflict="user_id,dedupe_key", ignore_duplicates=True).execute()
