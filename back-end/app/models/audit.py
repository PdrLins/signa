"""Pydantic models for audit logging."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AuditEvent:
    """Audit event type constants."""
    LOGIN_ATTEMPT = "LOGIN_ATTEMPT"
    OTP_SENT = "OTP_SENT"
    OTP_VERIFIED = "OTP_VERIFIED"
    OTP_FAILED = "OTP_FAILED"
    OTP_EXPIRED = "OTP_EXPIRED"
    TOKEN_ISSUED = "TOKEN_ISSUED"
    TOKEN_REFRESHED = "TOKEN_REFRESHED"
    TOKEN_REVOKED = "TOKEN_REVOKED"
    UNAUTHORIZED_ACCESS = "UNAUTHORIZED_ACCESS"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    RATE_LIMIT_BLOCKED = "RATE_LIMIT_BLOCKED"
    # Brain Editor events
    BRAIN_CHALLENGE_SENT = "BRAIN_CHALLENGE_SENT"
    BRAIN_ACCESS_GRANTED = "BRAIN_ACCESS_GRANTED"
    BRAIN_ACCESS_DENIED = "BRAIN_ACCESS_DENIED"
    BRAIN_ACCESS_LOCKED = "BRAIN_ACCESS_LOCKED"
    BRAIN_TOKEN_USED = "BRAIN_TOKEN_USED"
    BRAIN_RULE_UPDATED = "BRAIN_RULE_UPDATED"
    BRAIN_KNOWLEDGE_UPDATED = "BRAIN_KNOWLEDGE_UPDATED"


class AuditLogEntry(BaseModel):
    """Audit log entry returned by the API."""
    id: str
    event_type: str
    user_id: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    metadata: Optional[dict] = None
    success: bool = True
    created_at: Optional[datetime] = None
