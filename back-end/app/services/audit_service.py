"""Audit logging service."""

from typing import Optional

from app.db.queries import insert_audit_log


def log_event(
    event_type: str,
    success: bool,
    user_id: Optional[str] = None,
    ip_address: str = "unknown",
    user_agent: str = "",
    metadata: Optional[dict] = None,
) -> dict:
    """Write an audit log entry.

    Thin wrapper around the DB query for service-level use.
    """
    return insert_audit_log(
        event_type=event_type,
        success=success,
        user_id=user_id,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata=metadata,
    )
