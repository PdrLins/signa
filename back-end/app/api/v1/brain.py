"""Brain Editor API — protected by JWT + Telegram 2FA.

Highlights endpoint: JWT only.
Challenge/Verify: JWT only.
All other endpoints: JWT + brain_token (X-Brain-Token header).
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from loguru import logger
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.core.security import generate_otp, hash_otp, verify_otp
from app.core.utils import get_client_ip
from app.db.queries import get_user_by_id, insert_audit_log
from app.db.supabase import get_client
from app.middleware.brain_auth import require_brain_token
from app.models.audit import AuditEvent
from app.notifications.messages import msg
from app.notifications.telegram_bot import enqueue as _tg_send
from app.services.knowledge_service import KnowledgeService


# ── Pydantic models ──

class BrainVerifyRequest(BaseModel):
    otp_code: str = Field(..., pattern=r"^\d{6}$")


class RuleUpdateRequest(BaseModel):
    description: Optional[str] = Field(None, max_length=2000)
    formula: Optional[str] = Field(None, max_length=500)
    threshold_min: Optional[float] = None
    threshold_max: Optional[float] = None
    threshold_unit: Optional[str] = Field(None, max_length=50)
    is_blocker: Optional[bool] = None
    weight_safe: Optional[float] = Field(None, ge=0, le=1)
    weight_risk: Optional[float] = Field(None, ge=0, le=1)
    is_active: Optional[bool] = None
    notes: Optional[str] = Field(None, max_length=1000)


class KnowledgeUpdateRequest(BaseModel):
    explanation: Optional[str] = Field(None, max_length=5000)
    formula: Optional[str] = Field(None, max_length=500)
    example: Optional[str] = Field(None, max_length=2000)
    is_active: Optional[bool] = None
    notes: Optional[str] = Field(None, max_length=1000)


router = APIRouter(prefix="/brain", tags=["Brain Editor"])
_ks = KnowledgeService()

from app.core.cache import brain_challenge_cache, brain_lockout_cache, brain_otp_attempt_cache


def _check_challenge_rate(user_id: str):
    now = datetime.now(timezone.utc).timestamp()
    window = settings.rate_limit_window_minutes * 60
    timestamps = brain_challenge_cache.get(f"ch:{user_id}") or []
    timestamps = [t for t in timestamps if t > now - window]
    brain_challenge_cache.set(f"ch:{user_id}", timestamps, ttl=int(window))
    if len(timestamps) >= settings.brain_max_challenges_per_window:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests. Try again in 15 minutes.")


def _check_lockout(user_id: str):
    lock_until = brain_lockout_cache.get(f"lock:{user_id}")
    if lock_until and datetime.now(timezone.utc).timestamp() < lock_until:
        remaining = int(lock_until - datetime.now(timezone.utc).timestamp())
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=f"Locked. Try again in {remaining}s.")


# ═══ HIGHLIGHTS (JWT only) ═══

@router.get("/highlights")
async def get_highlights(user: dict = Depends(get_current_user)):
    return _ks.get_highlights()


# ═══ BRAIN INSIGHTS FOR A TICKER (JWT only) ═══

@router.get("/insights/{ticker}")
async def get_brain_insights(ticker: str = Path(..., pattern=r"^[A-Z0-9.\-]{1,10}$"), user: dict = Depends(get_current_user)):
    """Return brain insights relevant to a specific ticker.

    No brain 2FA needed — read-only. Returns a bilingual summary,
    key rules that specifically affect this signal, and relevant knowledge.
    """
    lang = settings.language
    db = get_client()

    # Get latest signal with fundamentals
    sig_result = (
        db.table("signals")
        .select("action, score, bucket, market_regime, signal_style, contrarian_score, reasoning, "
                "target_price, stop_loss, risk_reward, price_at_signal, fundamental_data, technical_data")
        .eq("symbol", ticker.upper())
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    signal = sig_result.data[0] if sig_result.data else {}
    bucket = signal.get("bucket", "SAFE_INCOME")
    score = signal.get("score", 0)
    action = signal.get("action", "HOLD")
    regime = signal.get("market_regime", "TRENDING")
    reasoning = signal.get("reasoning", "")
    signal_style = signal.get("signal_style", "NEUTRAL")
    fund = signal.get("fundamental_data") or {}
    tech = signal.get("technical_data") or {}
    target = signal.get("target_price")
    stop = signal.get("stop_loss")
    price = signal.get("price_at_signal")

    # Get active knowledge entries relevant to context
    knowledge_result = (
        db.table("signal_knowledge")
        .select("topic, key_concept, explanation")
        .eq("is_active", True)
        .execute()
    )
    all_knowledge = knowledge_result.data or []

    # Pick knowledge by context
    ticker_upper = ticker.upper()
    is_energy = any(t in ticker_upper for t in ["CNQ", "SU.", "CVE", "ARX", "IMO", "BTE", "WCP", "TVE", "EOG", "COP", "XOM", "MPC", "OXY", "SLB"])
    is_mining = any(t in ticker_upper for t in ["ABX", "FNV", "WPM", "NTR", "TECK", "NEM", "FCX"])
    is_crypto = ticker_upper.endswith("-USD")

    relevant_topics = set()
    if regime != "TRENDING":
        relevant_topics.add("market_regime_detection")
    if signal_style == "CONTRARIAN":
        relevant_topics.add("contrarian_sentiment_in_commodities")
    if is_energy or is_mining:
        relevant_topics |= {"supply_deficit_asymmetry", "contrarian_sentiment_in_commodities"}
    if is_crypto:
        relevant_topics.add("bubble_detection_framework")

    relevant_knowledge = [
        k for k in all_knowledge
        if k.get("key_concept") in relevant_topics or k.get("topic") in relevant_topics
    ]

    # Generate bilingual summary with actual data
    summary = _generate_insight_summary(
        lang, ticker_upper, action, score, bucket, regime,
        signal_style, reasoning, fund, tech, target, stop, price,
    )

    # Generate specific key points (not generic rules)
    key_points = _generate_key_points(
        lang, ticker_upper, action, score, bucket, regime,
        signal_style, fund, tech, target, stop, price,
    )

    # Add track record for this score range
    track_record = None
    try:
        from app.services.signal_service import get_track_record
        record = await asyncio.to_thread(get_track_record)
        for r in record.get("ranges", []):
            label = r["score_range"]
            raw = label.replace("+", "").replace("<", "").replace(">", "")
            parts = raw.split("-")
            lo = int(parts[0])
            hi = int(parts[-1]) if len(parts) > 1 else 101
            if label.startswith("<"):
                lo = 0
            if lo <= score < hi or (label.endswith("+") and score >= lo):
                track_record = {
                    "score_range": r["score_range"],
                    "trades": r["trades"],
                    "win_rate": r["win_rate"],
                    "avg_return_pct": r["avg_return_pct"],
                }
                break
    except Exception as e:
        logger.warning(f"Track record lookup failed for {ticker}: {e}")

    return {
        "ticker": ticker_upper,
        "summary": summary,
        "key_points": key_points,
        "track_record": track_record,
        "knowledge": [
            {
                "concept": k.get("key_concept", "").replace("_", " ").title(),
                "explanation": k.get("explanation"),
            }
            for k in relevant_knowledge[:4]
        ],
    }


def _generate_insight_summary(
    lang: str, ticker: str, action: str, score: int, bucket: str,
    regime: str, style: str, reasoning: str,
    fund: dict, tech: dict, target, stop, price,
) -> str:
    """Generate a bilingual plain-language summary with actual ticker data."""
    is_pt = lang == "pt"

    # Bucket
    if is_pt:
        bucket_label = "Renda Segura" if bucket == "SAFE_INCOME" else "Alto Risco"
    else:
        bucket_label = "Safe Income" if bucket == "SAFE_INCOME" else "High Risk"

    parts = []

    # Action + score interpretation
    if action == "BUY" and score >= 75:
        if is_pt:
            parts.append(f"{ticker} ({bucket_label}) tem um sinal forte de COMPRA com score {score}/100.")
        else:
            parts.append(f"{ticker} ({bucket_label}) has a strong BUY signal at score {score}/100.")
    elif action == "BUY":
        if is_pt:
            parts.append(f"{ticker} ({bucket_label}) tem um sinal moderado de COMPRA com score {score}/100.")
        else:
            parts.append(f"{ticker} ({bucket_label}) has a moderate BUY signal at score {score}/100.")
    elif action == "AVOID":
        if is_pt:
            parts.append(f"{ticker} ({bucket_label}) tem score {score}/100 — abaixo do limite, o brain recomenda evitar por agora.")
        else:
            parts.append(f"{ticker} ({bucket_label}) scored {score}/100 — below the threshold, the brain recommends avoiding for now.")
    elif action == "SELL":
        if is_pt:
            parts.append(f"{ticker} ({bucket_label}) — o brain detectou condições deteriorando e recomenda vender.")
        else:
            parts.append(f"{ticker} ({bucket_label}) — the brain detected deteriorating conditions and recommends selling.")
    else:
        if is_pt:
            parts.append(f"{ticker} ({bucket_label}) está em HOLD com score {score}/100 — não forte para comprar, não fraco para vender.")
        else:
            parts.append(f"{ticker} ({bucket_label}) is in HOLD at score {score}/100 — not strong enough to buy, not weak enough to sell.")

    # Target/stop interpretation
    if target and stop and price:
        try:
            upside = ((float(target) - float(price)) / float(price)) * 100
            downside = ((float(stop) - float(price)) / float(price)) * 100
            if is_pt:
                parts.append(f"O preço atual é ${float(price):.2f} com alvo ${float(target):.2f} (+{upside:.1f}%) e stop ${float(stop):.2f} ({downside:.1f}%).")
            else:
                parts.append(f"Current price is ${float(price):.2f} with target ${float(target):.2f} (+{upside:.1f}%) and stop ${float(stop):.2f} ({downside:.1f}%).")
        except (ValueError, TypeError, ZeroDivisionError):
            pass

    # Regime context
    if regime == "VOLATILE":
        if is_pt:
            parts.append("O mercado está VOLÁTIL (VIX 20-30) — cautela extra recomendada, tamanho de posição reduzido.")
        else:
            parts.append("Market is VOLATILE (VIX 20-30) — extra caution recommended, position sizes reduced.")
    elif regime == "CRISIS":
        if is_pt:
            parts.append("O mercado está em CRISE (VIX 30+) — apenas posições de Renda Segura estão ativas.")
        else:
            parts.append("Market is in CRISIS (VIX 30+) — only Safe Income positions are active.")

    # Contrarian note
    if style == "CONTRARIAN":
        if is_pt:
            parts.append("Este é um sinal CONTRARIAN — o ativo está em queda mas indicadores sugerem reversão.")
        else:
            parts.append("This is a CONTRARIAN signal — the asset is beaten down but indicators suggest a reversal.")

    return " ".join(parts)


def _generate_key_points(
    lang: str, ticker: str, action: str, score: int, bucket: str,
    regime: str, style: str, fund: dict, tech: dict, target, stop, price,
) -> list[dict]:
    """Generate specific key points about this ticker based on actual data."""
    is_pt = lang == "pt"
    points = []

    # Fundamental highlights
    pe = fund.get("pe_ratio")
    div_yield = fund.get("dividend_yield")
    eps_growth = fund.get("eps_growth")
    debt_eq = fund.get("debt_to_equity")

    if pe is not None:
        try:
            pe_val = float(pe)
            if pe_val < 15:
                points.append({
                    "type": "positive",
                    "text": f"P/E {pe_val:.1f} — {'abaixo da média, ação pode estar subvalorizada' if is_pt else 'below average, stock may be undervalued'}",
                })
            elif pe_val > 30:
                points.append({
                    "type": "warning",
                    "text": f"P/E {pe_val:.1f} — {'acima da média, cuidado com sobrevalorização' if is_pt else 'above average, watch for overvaluation'}",
                })
        except (ValueError, TypeError):
            pass

    if div_yield is not None:
        try:
            dy = float(div_yield)
            if dy > 3:
                points.append({
                    "type": "positive",
                    "text": f"Dividend Yield {dy:.1f}% — {'rendimento atrativo para Renda Segura' if is_pt else 'attractive yield for Safe Income'}",
                })
        except (ValueError, TypeError):
            pass

    if eps_growth is not None:
        try:
            eg = float(eps_growth)
            if eg > 15:
                points.append({
                    "type": "positive",
                    "text": f"{'Crescimento LPA' if is_pt else 'EPS Growth'} {eg:.1f}% — {'forte crescimento de lucro' if is_pt else 'strong earnings growth'}",
                })
            elif eg < -10:
                points.append({
                    "type": "warning",
                    "text": f"{'Crescimento LPA' if is_pt else 'EPS Growth'} {eg:.1f}% — {'lucros em declínio' if is_pt else 'declining earnings'}",
                })
        except (ValueError, TypeError):
            pass

    # Technical highlights
    rsi = tech.get("rsi")
    if rsi is not None:
        try:
            rsi_val = float(rsi)
            if rsi_val > 70:
                points.append({
                    "type": "warning",
                    "text": f"RSI {rsi_val:.0f} — {'sobrecomprado, risco de correção no curto prazo' if is_pt else 'overbought, short-term pullback risk'}",
                })
            elif rsi_val < 30:
                points.append({
                    "type": "positive",
                    "text": f"RSI {rsi_val:.0f} — {'sobrevendido, possível oportunidade de entrada' if is_pt else 'oversold, potential entry opportunity'}",
                })
            elif 50 <= rsi_val <= 65:
                points.append({
                    "type": "positive",
                    "text": f"RSI {rsi_val:.0f} — {'zona ideal de entrada (backtest validado)' if is_pt else 'sweet spot entry zone (backtest validated)'}",
                })
        except (ValueError, TypeError):
            pass

    vs_sma200 = tech.get("vs_sma200")
    if vs_sma200 is not None:
        try:
            val = float(vs_sma200)
            if val > 5:
                points.append({
                    "type": "positive",
                    "text": f"{'Preço' if is_pt else 'Price'} {val:+.1f}% {'acima da SMA200 — tendência de alta' if is_pt else 'above SMA200 — uptrend'}",
                })
            elif val < -10:
                points.append({
                    "type": "warning",
                    "text": f"{'Preço' if is_pt else 'Price'} {val:+.1f}% {'abaixo da SMA200 — tendência de baixa' if is_pt else 'below SMA200 — downtrend'}",
                })
        except (ValueError, TypeError):
            pass

    # Regime impact
    if regime == "VOLATILE" and bucket == "HIGH_RISK":
        points.append({
            "type": "warning",
            "text": "VOLATILE — " + ("score reduzido em 15% para Alto Risco, Kelly pela metade" if is_pt else "score reduced 15% for High Risk, Kelly halved"),
        })

    # Contrarian
    if style == "CONTRARIAN":
        points.append({
            "type": "info",
            "text": "CONTRARIAN — " + ("3 de 4 condições Lopez atendidas (abaixo SMA200 + RSI baixo + volume alto + MACD virando)" if is_pt else "3 of 4 Lopez conditions met (below SMA200 + low RSI + high volume + MACD turning)"),
        })

    return points


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
            "user_id": user_id,
            "otp_hash": otp_hashed,
            "expires_at": expires_at.isoformat(),
            "ip_address": ip,
        }).execute()
    except Exception as e:
        logger.debug(f"brain_sessions insert skipped: {e}")

    timestamps = brain_challenge_cache.get(f"ch:{user_id}") or []
    timestamps.append(datetime.now(timezone.utc).timestamp())
    brain_challenge_cache.set(f"ch:{user_id}", timestamps, ttl=settings.rate_limit_window_minutes * 60)

    db_user = get_user_by_id(user_id)
    chat_id = db_user["telegram_chat_id"] if db_user else settings.telegram_chat_id
    _tg_send(chat_id, msg("brain_otp", otp=otp), urgent=True)

    insert_audit_log(event_type=AuditEvent.BRAIN_CHALLENGE_SENT, success=True, user_id=user_id, ip_address=ip)
    logger.info(f"Brain challenge sent for user {user_id}")
    return {"message": "Code sent to your Telegram"}


@router.post("/verify")
async def brain_verify(request: Request, body: BrainVerifyRequest, user: dict = Depends(get_current_user)):
    user_id = user["user_id"]
    ip = get_client_ip(request)
    otp_code = body.otp_code
    _check_lockout(user_id)

    attempts = brain_otp_attempt_cache.get(f"otp:{user_id}") or 0
    if attempts >= settings.brain_max_otp_attempts:
        lockout_ttl = settings.rate_limit_window_minutes * 60
        brain_lockout_cache.set(f"lock:{user_id}", datetime.now(timezone.utc).timestamp() + lockout_ttl, ttl=lockout_ttl)
        brain_otp_attempt_cache.delete(f"otp:{user_id}")
        insert_audit_log(event_type=AuditEvent.BRAIN_ACCESS_LOCKED, success=False, user_id=user_id, ip_address=ip)
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many failed attempts. Locked for 15 minutes.")

    client = get_client()
    now = datetime.now(timezone.utc).isoformat()
    query = client.table("brain_sessions").select("id, otp_hash, expires_at, user_id").is_("used_at", "null").gte("expires_at", now).order("created_at", desc=True).limit(1)
    query = query.eq("user_id", user_id)
    result = query.execute()

    if not result.data:
        brain_otp_attempt_cache.set(f"otp:{user_id}", attempts + 1, ttl=settings.rate_limit_window_minutes * 60)
        remaining = settings.brain_max_otp_attempts - attempts - 1
        insert_audit_log(event_type=AuditEvent.BRAIN_ACCESS_DENIED, success=False, user_id=user_id, ip_address=ip, metadata={"reason": "no_valid_session"})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Code expired or not found. {remaining} attempt(s) remaining.")

    session = result.data[0]

    if not verify_otp(otp_code, session["otp_hash"], salt=user_id):
        brain_otp_attempt_cache.set(f"otp:{user_id}", attempts + 1, ttl=settings.rate_limit_window_minutes * 60)
        remaining = settings.brain_max_otp_attempts - attempts - 1
        insert_audit_log(event_type=AuditEvent.BRAIN_ACCESS_DENIED, success=False, user_id=user_id, ip_address=ip, metadata={"reason": "invalid_otp", "remaining": remaining})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid code. {remaining} attempt(s) remaining.")

    jti = str(uuid.uuid4())
    from app.core.security import create_brain_token
    brain_token = create_brain_token(user_id, jti)

    now_dt = datetime.now(timezone.utc)
    client.table("brain_sessions").update({"used_at": now_dt.isoformat(), "brain_token_jti": jti}).eq("id", session["id"]).execute()
    brain_otp_attempt_cache.delete(f"otp:{user_id}")

    insert_audit_log(event_type=AuditEvent.BRAIN_ACCESS_GRANTED, success=True, user_id=user_id, ip_address=ip, metadata={"brain_jti": jti})
    logger.info(f"Brain access granted for user {user_id}")
    return {"brain_token": brain_token, "expires_in": settings.brain_token_expire_minutes * 60}


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
        user_id=user["user_id"], ip_address=get_client_ip(request),
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
        user_id=user["user_id"], ip_address=get_client_ip(request),
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
