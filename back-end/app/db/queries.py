"""Reusable database query helpers for all Supabase tables."""

from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger

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


def get_user_by_telegram_chat_id(chat_id: str) -> dict | None:
    """Look up a user by Telegram chat ID."""
    client = get_client()
    result = (
        client.table("users")
        .select("id, username, telegram_chat_id, is_active")
        .eq("telegram_chat_id", chat_id)
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
# TICKERS
# ============================================================

def get_active_tickers() -> list[dict]:
    """Get all active tickers.

    The limit is set well above the plausible universe size. A previous
    500-row cap was silently truncating the bucket cache when the universe
    grew past 500: dropped tickers fell through to fresh classification
    with empty screening data and defaulted to SAFE_INCOME, polluting the
    HIGH_RISK growth-tech bucket. If you need to bound this, paginate —
    don't cap.
    """
    client = get_client()
    result = (
        client.table("tickers")
        .select("symbol, name, exchange, bucket, is_active")
        .eq("is_active", True)
        .limit(10000)
        .execute()
    )
    return result.data or []


def upsert_ticker(symbol: str, name: str = "", exchange: str = "", bucket: str | None = None) -> dict:
    """Insert or update a ticker.

    The `bucket` field is "sticky" — only set on initial insert. Once a
    ticker has a bucket, subsequent calls do NOT overwrite it. This
    matters because the per-scan classifier (`_classify_bucket`) can be
    overruled by the manual audit (`scripts/audit_ticker_buckets.py`),
    and an upsert that re-stamps `bucket` every scan would silently
    undo audit corrections. If the ticker is genuinely missing a bucket,
    callers can pass `bucket=...` and it'll be set on the next call.
    """
    client = get_client()
    sym = symbol.upper()

    existing = client.table("tickers").select("id, bucket").eq("symbol", sym).limit(1).execute().data
    if existing:
        # Update everything EXCEPT bucket (preserve any prior classification).
        # Only stamp bucket if the existing row has none AND a bucket was passed.
        patch: dict = {"name": name, "exchange": exchange, "is_active": True}
        if bucket and not existing[0].get("bucket"):
            patch["bucket"] = bucket
        result = client.table("tickers").update(patch).eq("symbol", sym).execute()
        return result.data[0] if result.data else existing[0]

    # New row — stamp bucket so first-scan classification persists.
    data = {
        "symbol": sym,
        "name": name,
        "exchange": exchange,
        "bucket": bucket,
        "is_active": True,
    }
    result = client.table("tickers").insert(data).execute()
    return result.data[0] if result.data else {}


# ============================================================
# SIGNALS
# ============================================================

# Light columns for list endpoints — excludes heavy JSONB blobs
_SIGNAL_LIST_COLUMNS = (
    "id, symbol, action, status, score, confidence, is_gem, bucket, "
    "asset_type, exchange, price_at_signal, target_price, stop_loss, "
    "risk_reward, catalyst, sentiment_score, reasoning, market_regime, "
    "catalyst_type, account_recommendation, signal_style, contrarian_score, "
    "kelly_recommendation, is_discovered, probability_vs_spy, factor_labels, "
    "scan_id, created_at, updated_at"
)


def insert_signal(signal_data: dict) -> dict:
    """Insert a signal record."""
    client = get_client()
    result = client.table("signals").insert(signal_data).execute()
    logger.debug(f"Inserted signal for {signal_data.get('symbol')}")
    return result.data[0] if result.data else {}


def insert_signals_batch(signals: list[dict]) -> list[dict]:
    """Batch insert signals. Strips non-DB fields before insert."""
    client = get_client()
    # Remove fields that aren't columns in the signals table
    _non_db_fields = {"company_name"}
    clean = [{k: v for k, v in s.items() if k not in _non_db_fields} for s in signals]
    result = client.table("signals").insert(clean).execute()
    logger.info(f"Batch inserted {len(signals)} signals")
    return result.data or []


def get_signals(
    bucket: str | None = None,
    action: str | None = None,
    status: str | None = None,
    period: str | None = None,
    min_score: int = 0,
    limit: int = 50,
    gems_only: bool = False,
) -> list[dict]:
    """Get latest signals with optional filters. Excludes heavy JSONB blobs."""
    client = get_client()
    query = client.table("signals").select(_SIGNAL_LIST_COLUMNS).order("created_at", desc=True).limit(limit)
    if bucket:
        query = query.eq("bucket", bucket)
    if action:
        query = query.eq("action", action)
    if status:
        query = query.eq("status", status)
    if period:
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        if period == "today":
            cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "week":
            cutoff = now - timedelta(days=7)
        elif period == "month":
            cutoff = now - timedelta(days=30)
        else:
            cutoff = None
        if cutoff:
            query = query.gte("created_at", cutoff.isoformat())
    if min_score > 0:
        query = query.gte("score", min_score)
    if gems_only:
        query = query.eq("is_gem", True)
    result = query.execute()
    # Deduplicate: keep the best signal per ticker.
    # Prefer signals with AI analysis (target_price filled) over tech-only.
    # Among same quality, keep the most recent.
    seen: dict[str, dict] = {}
    for row in result.data or []:
        symbol = row.get("symbol")
        if not symbol:
            continue
        has_ai = row.get("target_price") is not None
        existing = seen.get(symbol)
        if not existing:
            seen[symbol] = row
        elif has_ai and existing.get("target_price") is None:
            # New one has AI data, old one doesn't → replace
            seen[symbol] = row
    return list(seen.values())


def get_signals_by_ticker(symbol: str, limit: int = 20) -> list[dict]:
    """Get signal history for a specific ticker.

    Uses select("*") intentionally — the detail page needs technical_data,
    fundamental_data, and macro_data blobs for the full analysis view.
    """
    client = get_client()
    result = (
        client.table("signals")
        .select("*")  # All columns needed for ticker detail page
        .eq("symbol", symbol.upper())
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []


def get_latest_signals_map() -> dict[str, dict]:
    """Get the most recent signal for each ticker. Used for status comparison."""
    client = get_client()
    result = (
        client.table("signals")
        .select("symbol, score, action, created_at")
        .order("created_at", desc=True)
        .limit(500)
        .execute()
    )
    seen = {}
    for row in result.data or []:
        symbol = row.get("symbol")
        if symbol and symbol not in seen:
            seen[symbol] = row
    return seen


# ============================================================
# SCANS
# ============================================================

def insert_scan(scan_data: dict) -> dict:
    """Insert a new scan record."""
    client = get_client()
    result = client.table("scans").insert(scan_data).execute()
    return result.data[0] if result.data else {}


def update_scan(scan_id: str, **kwargs) -> dict:
    """Update a scan record."""
    client = get_client()
    data = {}
    for key, value in kwargs.items():
        if isinstance(value, datetime):
            data[key] = value.isoformat()
        else:
            data[key] = value
    result = client.table("scans").update(data).eq("id", scan_id).execute()
    return result.data[0] if result.data else {}


def get_scan_by_id(scan_id: str) -> dict | None:
    """Get a single scan by ID."""
    client = get_client()
    result = (
        client.table("scans")
        .select("*")
        .eq("id", scan_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


_SCAN_LIST_COLUMNS = (
    "id, scan_type, started_at, completed_at, tickers_scanned, "
    "candidates, signals_found, gems_found, status, error_message, "
    "progress_pct, phase, current_ticker, market_regime, triggered_by, created_at"
)


def get_scans(limit: int = 20) -> list[dict]:
    """Get recent scan history."""
    client = get_client()
    result = (
        client.table("scans")
        .select(_SCAN_LIST_COLUMNS)
        .order("started_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []


def get_last_completed_scan() -> dict | None:
    """Get the most recent completed scan."""
    client = get_client()
    result = (
        client.table("scans")
        .select(_SCAN_LIST_COLUMNS)
        .eq("status", "COMPLETE")
        .order("completed_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


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
            rows = build(HOLDING_COLUMNS + ", account_id").execute().data or []
            _holdings_no_account_id_at = None
            return rows
        except Exception as e:
            if not (_missing_schema(e) and "account_id" in str(e).lower()):
                raise
            logger.warning("holdings.account_id missing — apply migration 013_portfolio_foundation.sql")
            _holdings_no_account_id_at = time.time()
    rows = build(HOLDING_COLUMNS).execute().data or []
    return [{**r, "account_id": None} for r in rows]


def get_holdings(user_id: str) -> list[dict]:
    """All holdings for a user, oldest first (import order). Rows carry
    account_id (None before migration 013)."""
    client = get_client()
    return _select_holdings(lambda cols: (
        client.table("holdings").select(cols).eq("user_id", user_id).order("created_at").limit(2000)
    ))


def get_all_holdings() -> list[dict]:
    """Every user's holdings (scheduler monitor)."""
    client = get_client()
    return _select_holdings(lambda cols: client.table("holdings").select(cols).order("created_at").limit(5000))


def get_holding(holding_id: str, user_id: str) -> dict | None:
    client = get_client()
    rows = _select_holdings(lambda cols: (
        client.table("holdings").select(cols).eq("id", holding_id).eq("user_id", user_id).limit(1)
    ))
    return rows[0] if rows else None


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
        existing = (client.table("holdings").select("id, symbol, account_id")
                    .eq("user_id", user_id).limit(5000).execute().data or [])
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
    now_iso = datetime.now(timezone.utc).isoformat()
    for r in rows:
        hid = index.get((str(r.get("account_id") or ""), r["symbol"]))
        if hid:
            res = (client.table("holdings").update({**r, "updated_at": now_iso})
                   .eq("id", hid).eq("user_id", user_id).execute())
            out.extend(res.data or [])
        else:
            inserts.append({**r, "user_id": user_id})
    if inserts:
        out.extend(client.table("holdings").insert(inserts).execute().data or [])
    return out


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


def get_holdings_review_all_at(user_id: str) -> str | None:
    """Last "review all" run (user_settings.holdings_review_all_at)."""
    client = get_client()
    result = (
        client.table("user_settings")
        .select("holdings_review_all_at")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    return (result.data[0] or {}).get("holdings_review_all_at") if result.data else None


def set_holdings_review_all_at(user_id: str, at_iso: str) -> None:
    client = get_client()
    client.table("user_settings").upsert(
        {"user_id": user_id, "holdings_review_all_at": at_iso}, on_conflict="user_id",
    ).execute()


# ============================================================
# WATCHLIST
# ============================================================

def get_watchlist(user_id: str) -> list[dict]:
    """Get all watchlist items for a user."""
    client = get_client()
    result = (
        client.table("watchlist")
        .select("*")
        .eq("user_id", user_id)
        .order("added_at", desc=True)
        .limit(200)
        .execute()
    )
    return result.data or []


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


def get_open_brain_symbols() -> set[str]:
    """Get the set of symbols the brain currently has open virtual positions in.

    Used by `prefilter_candidates` to ALWAYS include held positions in the
    candidate list, regardless of day_change/volume filters. Without this,
    a brain position that's moving < 1% intraday gets filtered out and the
    Stage 6 thesis tracker has no fresh signal to re-evaluate against — so
    the position drifts unsupervised until the watchdog catches a price
    emergency or the catastrophic stop fires at -8%.

    Returns a set of symbol strings (e.g. {"PBR-A", "META", "ASML"}).
    Returns empty set if no brain positions are open or the brain user is
    unset.
    """
    client = get_client()
    try:
        result = (
            client.table("virtual_trades")
            .select("symbol")
            .eq("status", "OPEN")
            .eq("source", "brain")
            .execute()
        )
        return {row["symbol"] for row in (result.data or [])}
    except Exception:
        return set()


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
# ALERTS
# ============================================================

def insert_alert(alert_data: dict) -> dict:
    """Insert an alert record.

    alert_data should include user_id when created from a user-facing action.
    System-level alerts (scan pipeline) may omit user_id.
    """
    client = get_client()
    result = client.table("alerts").insert(alert_data).execute()
    return result.data[0] if result.data else {}


def update_alert_status(alert_id: str, status: str, sent_at: datetime | None = None) -> None:
    """Update alert delivery status."""
    client = get_client()
    data = {"status": status}
    if sent_at:
        data["sent_at"] = sent_at.isoformat()
    client.table("alerts").update(data).eq("id", alert_id).execute()


def get_pending_alerts() -> list[dict]:
    """Get all pending alerts (system-level, for the dispatcher)."""
    client = get_client()
    result = (
        client.table("alerts")
        .select("*")
        .eq("status", "PENDING")
        .order("created_at")
        .limit(500)
        .execute()
    )
    return result.data or []


def get_recent_alerts(user_id: str, limit: int = 5) -> list[dict]:
    """Get most recent sent alerts for a user."""
    client = get_client()
    result = (
        client.table("alerts")
        .select("id, alert_type, message, sent_at, status, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []


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
    client.table("user_settings").insert(default).execute()
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
# POSITIONS
# ============================================================

def get_open_positions(user_id: str) -> list[dict]:
    """Get all open positions for a user."""
    client = get_client()
    result = (
        client.table("positions")
        .select("*")
        .eq("user_id", user_id)
        .eq("status", "OPEN")
        .order("entry_date", desc=True)
        .limit(100)
        .execute()
    )
    return result.data or []


def get_all_open_positions() -> list[dict]:
    """Get all open positions across all users (for scan pipeline monitoring)."""
    client = get_client()
    result = (
        client.table("positions")
        .select("*")
        .eq("status", "OPEN")
        .order("entry_date", desc=True)
        .limit(500)
        .execute()
    )
    return result.data or []


def get_closed_positions(user_id: str, limit: int = 50) -> list[dict]:
    """Get closed positions (trade history) for a user."""
    client = get_client()
    result = (
        client.table("positions")
        .select("*")
        .eq("user_id", user_id)
        .neq("status", "OPEN")
        .order("exit_date", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []


def get_position_by_id(position_id: str) -> dict | None:
    """Get a single position."""
    client = get_client()
    result = (
        client.table("positions")
        .select("*")
        .eq("id", position_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def create_position(user_id: str, data: dict) -> dict:
    """Create a new open position."""
    client = get_client()
    result = client.table("positions").insert({**data, "user_id": user_id}).execute()
    logger.info(f"Position opened: {data.get('symbol')} x{data.get('shares')} @ ${data.get('entry_price')}")
    return result.data[0] if result.data else {}


def update_position(position_id: str, data: dict) -> dict:
    """Update a position (target, stop_loss, notes, signal tracking)."""
    client = get_client()
    update_data = {**data, "updated_at": datetime.now(timezone.utc).isoformat()}
    result = client.table("positions").update(update_data).eq("id", position_id).execute()
    return result.data[0] if result.data else {}


def close_position(
    position_id: str,
    exit_price: float,
    exit_reason: str,
    pnl_amount: float,
    pnl_percent: float,
) -> dict:
    """Close a position and record P&L."""
    client = get_client()
    data = {
        "status": "STOPPED_OUT" if exit_reason == "STOP_HIT" else "CLOSED",
        "exit_price": exit_price,
        "exit_date": datetime.now(timezone.utc).isoformat(),
        "exit_reason": exit_reason,
        "pnl_amount": round(pnl_amount, 2),
        "pnl_percent": round(pnl_percent, 4),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    result = client.table("positions").update(data).eq("id", position_id).execute()
    logger.info(f"Position closed: {position_id} | P&L: {pnl_percent:+.1f}% (${pnl_amount:+.2f}) | Reason: {exit_reason}")
    return result.data[0] if result.data else {}


# ============================================================
# BRAIN DECISIONS (entry funnel log — migration 006)
# ============================================================

def insert_brain_decisions(rows: list[dict]) -> int:
    """Batch-insert one brain_decisions row per candidate considered in a scan.

    Each row: scan_id, symbol, decided_at, decision ('ENTER' | 'SKIP'),
    reason, score, ai_status, ai_signal, details (jsonb). Returns rows sent.
    """
    if not rows:
        return 0
    get_client().table("brain_decisions").insert(rows).execute()
    return len(rows)


def get_brain_decisions(scan_id: str | None = None, symbol: str | None = None, limit: int = 200) -> list[dict]:
    """Read the entry funnel log, newest first (optionally for one scan / symbol)."""
    query = get_client().table("brain_decisions").select("*")
    if scan_id:
        query = query.eq("scan_id", scan_id)
    if symbol:
        query = query.eq("symbol", symbol)
    return (query.order("decided_at", desc=True).limit(limit).execute()).data or []


# ============================================================
# CANDIDATE OUTCOMES (counterfactual forward returns — migration 008)
# ============================================================

_OUTCOME_PAGE = 1000  # PostgREST default max rows per request
_OUTCOME_SIGNAL_COLUMNS = (
    "id, scan_id, symbol, exchange, asset_type, created_at, price_at_signal, "
    "action, score, ai_status, ai_signal, ai_provider, p_win, bucket, "
    "routine_ai_signal, decision_overturned"
)


def _select_all_pages(build_query, page_size: int = _OUTCOME_PAGE, max_rows: int = 50_000) -> list[dict]:
    """Page through a select with .range() until a short page comes back."""
    rows: list[dict] = []
    start = 0
    while start < max_rows:
        page = (build_query().range(start, start + page_size - 1).execute()).data or []
        rows.extend(page)
        if len(page) < page_size:
            break
        start += page_size
    return rows


def get_signals_for_outcomes(since_iso: str) -> list[dict]:
    """Signals created at/after `since_iso`, with the columns outcome tracking needs."""
    client = get_client()

    def _q():
        return (
            client.table("signals").select(_OUTCOME_SIGNAL_COLUMNS)
            .gte("created_at", since_iso).order("created_at")
        )
    return _select_all_pages(_q)


def get_candidate_outcome_signal_ids(since_iso: str) -> set[str]:
    """signal_ids that already have a candidate_outcomes row (signal_at >= since)."""
    client = get_client()

    def _q():
        return (
            client.table("candidate_outcomes").select("signal_id")
            .gte("signal_at", since_iso).order("signal_at")
        )
    return {r["signal_id"] for r in _select_all_pages(_q) if r.get("signal_id")}


def get_brain_decisions_for_scans(scan_ids: list[str], chunk: int = 100) -> list[dict]:
    """brain_decisions rows for the given scan ids (chunked IN queries)."""
    client = get_client()
    ids = [s for s in dict.fromkeys(scan_ids) if s]
    out: list[dict] = []
    for i in range(0, len(ids), chunk):
        part = ids[i:i + chunk]
        out.extend(
            (client.table("brain_decisions")
             .select("scan_id, symbol, decision, reason, decided_at")
             .in_("scan_id", part).execute()).data or []
        )
    return out


def insert_candidate_outcomes(rows: list[dict], chunk: int = 500) -> int:
    """Insert candidate_outcomes rows; duplicates on signal_id are ignored."""
    if not rows:
        return 0
    client = get_client()
    for i in range(0, len(rows), chunk):
        client.table("candidate_outcomes").upsert(
            rows[i:i + chunk], on_conflict="signal_id", ignore_duplicates=True,
        ).execute()
    return len(rows)


def get_unfilled_candidate_outcomes(since_iso: str) -> list[dict]:
    """Outcome rows with at least one horizon still empty (20d is filled last)."""
    client = get_client()

    def _q():
        return (
            client.table("candidate_outcomes").select("*")
            .gte("signal_at", since_iso).is_("filled_20d_at", "null").order("signal_at")
        )
    return _select_all_pages(_q)


def update_candidate_outcome(row_id: str, fields: dict) -> None:
    """Patch one candidate_outcomes row."""
    if fields:
        get_client().table("candidate_outcomes").update(fields).eq("id", row_id).execute()


def get_candidate_outcomes(since_iso: str) -> list[dict]:
    """All candidate_outcomes rows with signal_at >= since (for analysis)."""
    client = get_client()

    def _q():
        return (
            client.table("candidate_outcomes").select("*")
            .gte("signal_at", since_iso).order("signal_at")
        )
    return _select_all_pages(_q)


# ============================================================
# INSIGHTS (read-only helpers for /api/v1/insights/*)
# ============================================================
# All selects use "*" (or tolerant column lists) so a DB that is missing a
# later migration (008 / 009) still answers. Nothing here writes.

def get_latest_insight_scan() -> dict | None:
    """Most recent COMPLETE scan, falling back to the most recent scan of any status."""
    scan = get_last_completed_scan()
    if scan:
        return scan
    rows = get_scans(limit=1)
    return rows[0] if rows else None


def get_signals_for_scan(scan_id: str, limit: int = 500) -> list[dict]:
    """Every signal persisted by one scan (all columns — tolerates missing migrations)."""
    if not scan_id:
        return []
    client = get_client()
    return (
        client.table("signals").select("*").eq("scan_id", scan_id)
        .order("created_at", desc=True).limit(limit).execute()
    ).data or []


def get_latest_signal_for_symbol(symbol: str) -> dict | None:
    """Newest signal row for a symbol (all columns)."""
    client = get_client()
    rows = (
        client.table("signals").select("*").eq("symbol", symbol)
        .order("created_at", desc=True).limit(1).execute()
    ).data or []
    return rows[0] if rows else None


def get_brain_wallet_readonly(user_id: str | None) -> dict | None:
    """brain_wallet row for the brain user — read only (never lazy-creates)."""
    if not user_id:
        return None
    client = get_client()
    rows = (
        client.table("brain_wallet").select("*").eq("user_id", user_id).limit(1).execute()
    ).data or []
    return rows[0] if rows else None


def get_open_brain_trades() -> list[dict]:
    """Open brain virtual_trades (all columns)."""
    client = get_client()
    return (
        client.table("virtual_trades").select("*")
        .eq("status", "OPEN").eq("source", "brain")
        .order("entry_date", desc=False).execute()
    ).data or []


def get_virtual_trade_by_id(trade_id: str) -> dict | None:
    """One virtual_trades row by id."""
    if not trade_id:
        return None
    client = get_client()
    rows = (client.table("virtual_trades").select("*").eq("id", trade_id).limit(1).execute()).data or []
    return rows[0] if rows else None


def count_closed_brain_trades(since_iso: str | None = None) -> int:
    """Number of CLOSED brain trades (exit_date >= since when given)."""
    client = get_client()
    q = client.table("virtual_trades").select("id").eq("status", "CLOSED").eq("source", "brain")
    if since_iso:
        q = q.gte("exit_date", since_iso)
    return len((q.limit(10_000).execute()).data or [])


def get_virtual_snapshots_since(since_date: str | None = None, limit: int = 1000) -> list[dict]:
    """Daily virtual_snapshots (oldest first), optionally from a date (YYYY-MM-DD)."""
    client = get_client()
    q = client.table("virtual_snapshots").select("*")
    if since_date:
        q = q.gte("snapshot_date", since_date)
    return (q.order("snapshot_date", desc=False).limit(limit).execute()).data or []


def get_candidate_outcome_for_signal(signal_id: str) -> dict | None:
    """candidate_outcomes row for one signal, or None."""
    if not signal_id:
        return None
    client = get_client()
    rows = (
        client.table("candidate_outcomes").select("*").eq("signal_id", signal_id).limit(1).execute()
    ).data or []
    return rows[0] if rows else None


def get_signal_codex_verdicts(signal_ids: list[str], chunk: int = 100) -> dict[str, dict]:
    """{signal_id: grok_data._codex} for the given signals (read-only).
    Signals without a stored Codex review are omitted."""
    ids = [s for s in dict.fromkeys(str(i) for i in signal_ids if i)]
    if not ids:
        return {}
    client = get_client()
    out: dict[str, dict] = {}
    for i in range(0, len(ids), chunk):
        part = ids[i:i + chunk]
        rows = (client.table("signals").select("id, codex:grok_data->_codex").in_("id", part).execute()).data or []
        for r in rows:
            if isinstance(r.get("codex"), dict):
                out[str(r["id"])] = r["codex"]
    return out


_SIGNAL_VERDICT_COLUMNS = (
    "id, ai_status, ai_signal, p_win, routine_ai_signal, decision_overturned, "
    "tech_filter:technical_data->_tech_filter"
)
_SIGNAL_VERDICT_COLUMNS_MIN = "id, ai_status, tech_filter:technical_data->_tech_filter"


def get_signal_verdicts(signal_ids: list[str], chunk: int = 100) -> list[dict]:
    """AI-verdict columns for the given signal ids (read-only).

    Falls back to a minimal column set when migrations 005/008 columns are
    missing, so older databases still return ai_status + the tech filter.
    """
    ids = [s for s in dict.fromkeys(signal_ids) if s]
    if not ids:
        return []
    client = get_client()
    out: list[dict] = []
    cols = _SIGNAL_VERDICT_COLUMNS
    for i in range(0, len(ids), chunk):
        part = ids[i:i + chunk]
        try:
            out.extend((client.table("signals").select(cols).in_("id", part).execute()).data or [])
        except Exception as e:
            if cols == _SIGNAL_VERDICT_COLUMNS_MIN:
                raise
            logger.warning(f"signal verdict columns unavailable ({e}); using the minimal set")
            cols = _SIGNAL_VERDICT_COLUMNS_MIN
            out.extend((client.table("signals").select(cols).in_("id", part).execute()).data or [])
    return out


def get_ai_usage_breakdown(since_iso: str) -> dict[str, dict]:
    """Calls and estimated cost per provider since `since_iso` (ai_usage, paged)."""
    client = get_client()
    out: dict[str, dict] = {}
    start, page = 0, 1000
    while True:
        rows = (
            client.table("ai_usage").select("provider,estimated_cost")
            .gte("created_at", since_iso).order("created_at")
            .range(start, start + page - 1).execute()
        ).data or []
        for r in rows:
            p = r.get("provider") or "unknown"
            agg = out.setdefault(p, {"calls": 0, "cost_usd": 0.0})
            agg["calls"] += 1
            agg["cost_usd"] += float(r.get("estimated_cost") or 0)
        if len(rows) < page:
            return out
        start += page


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
        rows = client.table("users").select("*").eq("id", user_id).limit(1).execute().data or []
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
    return (client.table("accounts").select(ACCOUNT_COLUMNS).eq("user_id", user_id)
            .order("created_at").limit(500).execute().data or [])


def get_all_accounts() -> list[dict]:
    client = get_client()
    return _select_all_pages(lambda: client.table("accounts").select(ACCOUNT_COLUMNS).order("created_at"))


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
            rows = _select_all_pages(lambda t=table: client.table(t).select("symbol"))
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
        out.extend(q.order("check_date").limit(5000).execute().data or [])
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
            return (client.table("users").select(cols).eq("is_active", True).limit(10000).execute().data or [])
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
            out.extend(_select_all_pages(lambda t=table: client.table(t).select("user_id, symbol")))
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
    q = client.table("price_alerts").select(PRICE_ALERT_COLUMNS).eq("user_id", user_id)
    if symbol:
        q = q.eq("symbol", symbol)
    return q.order("created_at", desc=True).limit(1000).execute().data or []


def get_price_alert(alert_id: str, user_id: str) -> dict | None:
    client = get_client()
    rows = (client.table("price_alerts").select(PRICE_ALERT_COLUMNS).eq("id", alert_id)
            .eq("user_id", user_id).limit(1).execute().data or [])
    return rows[0] if rows else None


def count_active_price_alerts(user_id: str) -> int:
    client = get_client()
    rows = (client.table("price_alerts").select("id").eq("user_id", user_id).eq("active", True)
            .limit(10000).execute().data or [])
    return len(rows)


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
        out.extend(client.table("price_alerts").select(PRICE_ALERT_COLUMNS).eq("active", True)
                   .in_("symbol", symbols[i:i + 200]).limit(10000).execute().data or [])
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


def get_active_alert_follow_rows() -> list[dict]:
    """[{user_id, symbol}] of active alerts: their symbols need fresh quotes."""
    client = get_client()
    return _select_all_pages(lambda: client.table("price_alerts").select("user_id, symbol").eq("active", True))


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
    return _select_all_pages(lambda: client.table("telegram_links").select("user_id, chat_id, username"))


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
