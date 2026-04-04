"""Reusable database query helpers for all Supabase tables."""

from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger

from app.db.supabase import get_client


# ============================================================
# USERS
# ============================================================

def get_user_by_username(username: str) -> dict | None:
    """Look up a user by username."""
    client = get_client()
    result = (
        client.table("users")
        .select("id, username, password_hash, telegram_chat_id, is_active")
        .eq("username", username)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


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


def mark_otp_used(otp_id: str) -> None:
    """Mark an OTP as used."""
    client = get_client()
    client.table("otp_codes").update(
        {"used_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", otp_id).execute()


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
    client = get_client()
    client.table("token_blacklist").insert({
        "token_jti": token_jti,
        "user_id": user_id,
        "expires_at": expires_at.isoformat(),
    }).execute()


def is_token_blacklisted(token_jti: str) -> bool:
    """Check if a token has been blacklisted."""
    client = get_client()
    result = (
        client.table("token_blacklist")
        .select("id")
        .eq("token_jti", token_jti)
        .limit(1)
        .execute()
    )
    return len(result.data) > 0 if result.data else False


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
    """Get all active tickers."""
    client = get_client()
    result = (
        client.table("tickers")
        .select("*")
        .eq("is_active", True)
        .execute()
    )
    return result.data or []


def upsert_ticker(symbol: str, name: str = "", exchange: str = "", bucket: str | None = None) -> dict:
    """Insert or update a ticker."""
    client = get_client()
    data = {
        "symbol": symbol.upper(),
        "name": name,
        "exchange": exchange,
        "bucket": bucket,
        "is_active": True,
    }
    result = client.table("tickers").upsert(data, on_conflict="symbol").execute()
    return result.data[0] if result.data else {}


# ============================================================
# SIGNALS
# ============================================================

def insert_signal(signal_data: dict) -> dict:
    """Insert a signal record."""
    client = get_client()
    result = client.table("signals").insert(signal_data).execute()
    logger.debug(f"Inserted signal for {signal_data.get('symbol')}")
    return result.data[0] if result.data else {}


def insert_signals_batch(signals: list[dict]) -> list[dict]:
    """Batch insert signals."""
    client = get_client()
    result = client.table("signals").insert(signals).execute()
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
    """Get latest signals with optional filters."""
    client = get_client()
    query = client.table("signals").select("*").order("created_at", desc=True).limit(limit)
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
    return result.data or []


def get_signals_by_ticker(symbol: str, limit: int = 20) -> list[dict]:
    """Get signal history for a specific ticker."""
    client = get_client()
    result = (
        client.table("signals")
        .select("*")
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
        .select("*")
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


def get_scans(limit: int = 20) -> list[dict]:
    """Get recent scan history."""
    client = get_client()
    result = (
        client.table("scans")
        .select("*")
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
        .select("*")
        .eq("status", "COMPLETE")
        .order("completed_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


# ============================================================
# PORTFOLIO
# ============================================================

def get_portfolio() -> list[dict]:
    """Get all portfolio entries."""
    client = get_client()
    result = client.table("portfolio").select("*").order("created_at", desc=True).execute()
    return result.data or []


def add_portfolio_item(data: dict) -> dict:
    """Add an item to the portfolio."""
    client = get_client()
    result = client.table("portfolio").insert(data).execute()
    return result.data[0] if result.data else {}


def update_portfolio_item(item_id: str, data: dict) -> dict:
    """Update a portfolio item (does not mutate input dict)."""
    client = get_client()
    update_data = {**data, "updated_at": datetime.now(timezone.utc).isoformat()}
    result = client.table("portfolio").update(update_data).eq("id", item_id).execute()
    return result.data[0] if result.data else {}


def delete_portfolio_item(item_id: str) -> bool:
    """Delete a portfolio item."""
    client = get_client()
    result = client.table("portfolio").delete().eq("id", item_id).execute()
    return len(result.data) > 0 if result.data else False


# ============================================================
# WATCHLIST
# ============================================================

def get_watchlist() -> list[dict]:
    """Get all watchlist items."""
    client = get_client()
    result = client.table("watchlist").select("*").order("added_at", desc=True).execute()
    return result.data or []


def add_to_watchlist(symbol: str, notes: str | None = None) -> dict:
    """Add a ticker to the watchlist."""
    client = get_client()
    data = {"symbol": symbol.upper(), "notes": notes}
    result = client.table("watchlist").upsert(data, on_conflict="symbol").execute()
    logger.info(f"Added {symbol} to watchlist")
    return result.data[0] if result.data else {}


def remove_from_watchlist(symbol: str) -> bool:
    """Remove a ticker from the watchlist."""
    client = get_client()
    result = client.table("watchlist").delete().eq("symbol", symbol.upper()).execute()
    removed = len(result.data) > 0 if result.data else False
    if removed:
        logger.info(f"Removed {symbol} from watchlist")
    return removed


# ============================================================
# ALERTS
# ============================================================

def insert_alert(alert_data: dict) -> dict:
    """Insert an alert record."""
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
    """Get alerts that haven't been sent yet."""
    client = get_client()
    result = (
        client.table("alerts")
        .select("*")
        .eq("status", "PENDING")
        .order("created_at")
        .execute()
    )
    return result.data or []


# ============================================================
# POSITIONS
# ============================================================

def get_open_positions() -> list[dict]:
    """Get all open positions."""
    client = get_client()
    result = (
        client.table("positions")
        .select("*")
        .eq("status", "OPEN")
        .order("entry_date", desc=True)
        .execute()
    )
    return result.data or []


def get_closed_positions(limit: int = 50) -> list[dict]:
    """Get closed positions (trade history)."""
    client = get_client()
    result = (
        client.table("positions")
        .select("*")
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


def create_position(data: dict) -> dict:
    """Create a new open position."""
    client = get_client()
    result = client.table("positions").insert(data).execute()
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
