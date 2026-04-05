"""Brain Editor API — protected by JWT + Telegram 2FA.

Highlights endpoint: JWT only.
Challenge/Verify: JWT only.
All other endpoints: JWT + brain_token (X-Brain-Token header).
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from jose import jwt
from loguru import logger
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.core.security import generate_otp, hash_otp, verify_otp
from app.core.utils import get_client_ip
from app.db.queries import insert_audit_log
from app.db.supabase import get_client
from app.middleware.brain_auth import require_brain_token
from app.models.audit import AuditEvent
from app.notifications.messages import msg
from app.notifications.telegram_bot import send_message
from app.services.knowledge_service import KnowledgeService


# ── Pydantic models ──

class BrainVerifyRequest(BaseModel):
    otp_code: str = Field(..., pattern=r"^\d{6}$")


class RuleUpdateRequest(BaseModel):
    description: Optional[str] = None
    formula: Optional[str] = None
    threshold_min: Optional[float] = None
    threshold_max: Optional[float] = None
    threshold_unit: Optional[str] = None
    is_blocker: Optional[bool] = None
    weight_safe: Optional[float] = Field(None, ge=0, le=1)
    weight_risk: Optional[float] = Field(None, ge=0, le=1)
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class KnowledgeUpdateRequest(BaseModel):
    explanation: Optional[str] = None
    formula: Optional[str] = None
    example: Optional[str] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


router = APIRouter(prefix="/brain", tags=["Brain Editor"])
_ks = KnowledgeService()

# Rate limit tracking (in-memory)
_challenge_timestamps: dict[str, list[float]] = {}
_otp_attempts: dict[str, int] = {}
_lockouts: dict[str, float] = {}


def _safe_uid(user_id: str) -> str | None:
    """Return None for dev mode fake user IDs."""
    return user_id if user_id != "dev-user-id" else None


def _check_challenge_rate(user_id: str):
    now = datetime.now(timezone.utc).timestamp()
    window = settings.rate_limit_window_minutes * 60
    timestamps = _challenge_timestamps.get(user_id, [])
    timestamps = [t for t in timestamps if t > now - window]
    _challenge_timestamps[user_id] = timestamps
    if len(timestamps) >= settings.brain_max_challenges_per_window:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests. Try again in 15 minutes.")


def _check_lockout(user_id: str):
    lock_until = _lockouts.get(user_id, 0)
    if datetime.now(timezone.utc).timestamp() < lock_until:
        remaining = int(lock_until - datetime.now(timezone.utc).timestamp())
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=f"Locked. Try again in {remaining}s.")


# ═══ HIGHLIGHTS (JWT only) ═══

@router.get("/highlights")
async def get_highlights(user: dict = Depends(get_current_user)):
    return _ks.get_highlights()


# ═══ CHALLENGE / VERIFY (JWT only) ═══

@router.post("/challenge")
async def brain_challenge(request: Request, user: dict = Depends(get_current_user)):
    user_id = user["user_id"]
    ip = get_client_ip(request)
    _check_lockout(user_id)
    _check_challenge_rate(user_id)

    otp = generate_otp()
    otp_hashed = hash_otp(otp, salt=user_id)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.brain_otp_expire_seconds)

    try:
        client = get_client()
        client.table("brain_sessions").insert({
            "user_id": _safe_uid(user_id),
            "otp_hash": otp_hashed,
            "expires_at": expires_at.isoformat(),
            "ip_address": ip,
        }).execute()
    except Exception as e:
        logger.debug(f"brain_sessions insert skipped: {e}")

    _challenge_timestamps.setdefault(user_id, []).append(datetime.now(timezone.utc).timestamp())

    chat_id = settings.telegram_chat_id
    await send_message(chat_id, msg("brain_otp", otp=otp))

    insert_audit_log(event_type=AuditEvent.BRAIN_CHALLENGE_SENT, success=True, user_id=_safe_uid(user_id), ip_address=ip)
    logger.info(f"Brain challenge sent for user {user_id}")
    return {"message": "Code sent to your Telegram"}


@router.post("/verify")
async def brain_verify(request: Request, body: BrainVerifyRequest, user: dict = Depends(get_current_user)):
    user_id = user["user_id"]
    ip = get_client_ip(request)
    otp_code = body.otp_code
    _check_lockout(user_id)

    attempts = _otp_attempts.get(user_id, 0)
    if attempts >= settings.brain_max_otp_attempts:
        _lockouts[user_id] = datetime.now(timezone.utc).timestamp() + (settings.rate_limit_window_minutes * 60)
        _otp_attempts[user_id] = 0
        insert_audit_log(event_type=AuditEvent.BRAIN_ACCESS_LOCKED, success=False, user_id=_safe_uid(user_id), ip_address=ip)
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many failed attempts. Locked for 15 minutes.")

    client = get_client()
    now = datetime.now(timezone.utc).isoformat()
    query = client.table("brain_sessions").select("id, otp_hash, expires_at, user_id").is_("used_at", "null").gte("expires_at", now).order("created_at", desc=True).limit(1)
    if _safe_uid(user_id):
        query = query.eq("user_id", user_id)
    else:
        query = query.is_("user_id", "null")
    result = query.execute()

    if not result.data:
        _otp_attempts[user_id] = attempts + 1
        remaining = settings.brain_max_otp_attempts - attempts - 1
        insert_audit_log(event_type=AuditEvent.BRAIN_ACCESS_DENIED, success=False, user_id=_safe_uid(user_id), ip_address=ip, metadata={"reason": "no_valid_session"})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Code expired or not found. {remaining} attempt(s) remaining.")

    session = result.data[0]

    if not verify_otp(otp_code, session["otp_hash"], salt=user_id):
        _otp_attempts[user_id] = attempts + 1
        remaining = settings.brain_max_otp_attempts - attempts - 1
        insert_audit_log(event_type=AuditEvent.BRAIN_ACCESS_DENIED, success=False, user_id=_safe_uid(user_id), ip_address=ip, metadata={"reason": "invalid_otp", "remaining": remaining})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid code. {remaining} attempt(s) remaining.")

    jti = str(uuid.uuid4())
    expires_delta = timedelta(minutes=settings.brain_token_expire_minutes)
    now_dt = datetime.now(timezone.utc)

    brain_token = jwt.encode(
        {"sub": user_id, "type": "brain_editor", "iat": now_dt.timestamp(), "exp": (now_dt + expires_delta).timestamp(), "jti": jti},
        settings.brain_token_secret,
        algorithm=settings.jwt_algorithm,
    )

    client.table("brain_sessions").update({"used_at": now_dt.isoformat(), "brain_token_jti": jti}).eq("id", session["id"]).execute()
    _otp_attempts[user_id] = 0

    insert_audit_log(event_type=AuditEvent.BRAIN_ACCESS_GRANTED, success=True, user_id=_safe_uid(user_id), ip_address=ip, metadata={"brain_jti": jti})
    logger.info(f"Brain access granted for user {user_id}")
    return {"brain_token": brain_token, "expires_in": int(expires_delta.total_seconds())}


# ═══ RULES (JWT + brain_token) ═══

@router.get("/rules")
async def get_rules(user: dict = Depends(require_brain_token)):
    return _ks.get_all_rules()


@router.get("/rules/{rule_id}")
async def get_rule(rule_id: str, user: dict = Depends(require_brain_token)):
    rule = _ks.get_rule_by_id(rule_id)
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return rule


@router.put("/rules/{rule_id}")
async def update_rule(rule_id: str, body: RuleUpdateRequest, request: Request, user: dict = Depends(require_brain_token)):
    old = _ks.get_rule_by_id(rule_id)
    if not old:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")

    update_data = body.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid fields to update")

    ws = update_data.get("weight_safe", old.get("weight_safe", 0))
    wr = update_data.get("weight_risk", old.get("weight_risk", 0))
    if (ws or 0) + (wr or 0) > 1.0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="weight_safe + weight_risk must be <= 1.0")

    result = _ks.update_rule(rule_id, update_data)

    changed_fields = list(update_data.keys())
    before = {k: old.get(k) for k in changed_fields}
    after = {k: update_data[k] for k in changed_fields}

    insert_audit_log(
        event_type=AuditEvent.BRAIN_RULE_UPDATED, success=True,
        user_id=_safe_uid(user["user_id"]), ip_address=get_client_ip(request),
        metadata={"rule_id": rule_id, "rule_name": old.get("name"), "before": before, "after": after, "changed_fields": changed_fields},
    )
    return result


# ═══ KNOWLEDGE (JWT + brain_token) ═══

@router.get("/knowledge")
async def get_knowledge(user: dict = Depends(require_brain_token)):
    return _ks.get_all_knowledge()


@router.get("/knowledge/{knowledge_id}")
async def get_knowledge_entry(knowledge_id: str, user: dict = Depends(require_brain_token)):
    entry = _ks.get_knowledge_by_id(knowledge_id)
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge entry not found")
    return entry


@router.put("/knowledge/{knowledge_id}")
async def update_knowledge(knowledge_id: str, body: KnowledgeUpdateRequest, request: Request, user: dict = Depends(require_brain_token)):
    old = _ks.get_knowledge_by_id(knowledge_id)
    if not old:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge entry not found")

    update_data = body.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid fields to update")

    result = _ks.update_knowledge(knowledge_id, update_data)

    changed_fields = list(update_data.keys())
    before = {k: old.get(k) for k in changed_fields}
    after = {k: update_data[k] for k in changed_fields}

    insert_audit_log(
        event_type=AuditEvent.BRAIN_KNOWLEDGE_UPDATED, success=True,
        user_id=_safe_uid(user["user_id"]), ip_address=get_client_ip(request),
        metadata={"knowledge_id": knowledge_id, "key_concept": old.get("key_concept"), "before": before, "after": after, "changed_fields": changed_fields},
    )
    return result


# ═══ AUDIT LOG (JWT + brain_token) ═══

@router.get("/audit")
async def get_brain_audit(user: dict = Depends(require_brain_token)):
    client = get_client()
    result = client.table("audit_logs").select("*").like("event_type", "BRAIN_%").order("created_at", desc=True).limit(50).execute()
    events = result.data or []
    for event in events:
        ip = event.get("ip_address", "")
        if ip and "." in ip:
            parts = ip.split(".")
            event["ip_address"] = f"{parts[0]}.{parts[1]}.xxx.xxx"
    return events
