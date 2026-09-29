"""Self-learning feedback loop — analyzes trade outcomes and suggests brain improvements.

Flow:
1. record_outcome() — called when a position is closed or signal expires
2. run_weekly_analysis() — the model reviews recent outcomes against the
   PROMPT_CORE knowledge and the LIVE thresholds from settings
3. It generates specific brain_suggestions with reasoning
4. User approves/rejects in Brain Editor
5. apply_suggestion() — records the approval ONLY. Nothing is applied
   automatically: scoring, gating and exits read thresholds from code and
   settings, never from investment_rules, so an approved suggestion is
   marked "APPROVED — requires code/config change" and a human makes it.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger

from app.db.supabase import get_client
from app.services.knowledge_service import KnowledgeService, get_live_thresholds_block


def record_outcome(
    signal_id: str | None,
    symbol: str,
    action: str,
    score: int,
    bucket: str,
    signal_date: str,
    entry_price: float,
    exit_price: float,
    days_held: int,
    target_price: float | None = None,
    stop_loss: float | None = None,
    market_regime: str | None = None,
    catalyst_type: str | None = None,
    notes: str | None = None,
    pnl_pct_override: float | None = None,
) -> dict:
    """Record the outcome of a trade for learning.

    signal_id is OPTIONAL — virtual brain trades don't track which specific
    signal triggered them (the brain re-evaluates fresh signals at every scan,
    so there's no single "the signal" that owns the trade). For real positions
    that ARE tied to a signal, pass it; for virtual trades pass None.

    Direction-aware: action "SHORT" / "SHORT_SELL" is a short position
    (profit when price falls). `pnl_pct_override` lets the brain pass its
    net P&L % (after slippage, fees and FX) instead of the raw price move.
    """
    is_short = action in ("SHORT", "SHORT_SELL")
    if entry_price > 0:
        move = (entry_price - exit_price) if is_short else (exit_price - entry_price)
        pnl_pct = move / entry_price * 100
        pnl_amount = move  # per-share, direction-aware
    else:
        pnl_pct, pnl_amount = 0.0, 0.0
    if pnl_pct_override is not None:
        pnl_pct = float(pnl_pct_override)

    # Was the signal correct?
    if action == "BUY" or is_short:
        signal_correct = pnl_pct > 0
    elif action in ("SELL", "AVOID"):
        signal_correct = pnl_pct <= 0  # Correct to avoid if price dropped
    else:
        signal_correct = abs(pnl_pct) < 3  # HOLD is correct if price didn't move much

    if is_short:
        hit_target = exit_price <= target_price if target_price else False
        hit_stop = exit_price >= stop_loss if stop_loss else False
    else:
        hit_target = exit_price >= target_price if target_price else False
        hit_stop = exit_price <= stop_loss if stop_loss else False

    client = get_client()
    data = {
        "signal_id": signal_id,
        "symbol": symbol,
        "action": action,
        "score": score,
        "bucket": bucket,
        "signal_date": signal_date,
        "entry_price": round(entry_price, 4),
        "exit_price": round(exit_price, 4),
        "days_held": days_held,
        "pnl_pct": round(pnl_pct, 4),
        "pnl_amount": round(pnl_amount, 4),
        "target_price": target_price,
        "stop_loss": stop_loss,
        "hit_target": hit_target,
        "hit_stop": hit_stop,
        "signal_correct": signal_correct,
        "market_regime": market_regime,
        "catalyst_type": catalyst_type,
        "notes": notes,
    }
    result = client.table("trade_outcomes").insert(data).execute()
    logger.info(f"Trade outcome recorded: {symbol} {action} → {pnl_pct:+.2f}% ({'correct' if signal_correct else 'wrong'})")
    return result.data[0] if result.data else {}


def get_outcomes(days: int = 30, limit: int = 200) -> list[dict]:
    """Get recent trade outcomes."""
    client = get_client()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    result = (
        client.table("trade_outcomes")
        .select("*")
        .gte("signal_date", cutoff)
        .order("signal_date", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []


def get_suggestions(status: str | None = None, limit: int = 50) -> list[dict]:
    """Get brain suggestions."""
    client = get_client()
    query = client.table("brain_suggestions").select("*").order("confidence", desc=True).order("created_at", desc=True).limit(limit)
    if status:
        query = query.eq("status", status)
    return query.execute().data or []


REQUIRES_CODE_CHANGE_MESSAGE = (
    "APPROVED — requires code/config change. Signa's scoring, gates and exits "
    "read thresholds from code and settings, not from investment_rules, so "
    "nothing was changed automatically."
)


def apply_suggestion(suggestion_id: str, user_id: str) -> dict:
    """Record approval of a suggestion. Does NOT change any rule.

    investment_rules is documentation only (no scoring/gating/exit code reads
    it), so writing the proposed value there would be a silent no-op that
    pretends to apply. Instead the suggestion is marked APPROVED (reviewer +
    time recorded) and the response says a code/config change is required.
    """
    client = get_client()

    result = client.table("brain_suggestions").select("*").eq("id", suggestion_id).limit(1).execute()
    if not result.data:
        return {"error": "Suggestion not found"}

    suggestion = result.data[0]
    if suggestion.get("status") not in ("PENDING", "APPROVED"):
        return {"error": f"Suggestion is {suggestion.get('status')}; only PENDING or APPROVED can be approved"}

    client.table("brain_suggestions").update({
        "status": "APPROVED",
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "reviewed_by": user_id,
    }).eq("id", suggestion_id).execute()
    logger.info(
        f"Suggestion {suggestion_id} ({suggestion.get('rule_name')}) approved — "
        "requires a code/config change; nothing applied automatically"
    )

    return {
        "status": "approved",
        "applied": False,
        "requires_code_change": True,
        "message": REQUIRES_CODE_CHANGE_MESSAGE,
        "rule_name": suggestion.get("rule_name"),
        "proposed_value": suggestion.get("proposed_value"),
    }


_SUGGESTION_ITEM = {
    "type": "object",
    "properties": {
        "rule_name": {"type": "string"},
        "suggestion_type": {"type": "string", "enum": ["MODIFY_RULE", "MODIFY_WEIGHT", "DISABLE_RULE", "NEW_RULE"]},
        "current_value": {"type": "object"},
        "proposed_value": {"type": "object"},
        "reasoning": {"type": "string"},
        "confidence": {"type": "integer"},
        "expected_impact": {"type": "string"},
    },
    "required": ["rule_name", "suggestion_type", "reasoning", "confidence"],
}
_SUGGESTIONS_SCHEMA = {
    "type": "object",
    "properties": {"suggestions": {"type": "array", "items": _SUGGESTION_ITEM}},
    "required": ["suggestions"],
}


async def run_weekly_analysis(period_days: int = 7) -> list[dict]:
    """Run Claude analysis on recent trade outcomes and generate suggestions.

    This is the core self-learning function. Call it weekly or on-demand.
    """
    outcomes = get_outcomes(days=period_days)
    if not outcomes:
        logger.info("No trade outcomes to analyze")
        return []

    # Compute stats
    total = len(outcomes)
    correct = sum(1 for o in outcomes if o.get("signal_correct"))
    win_rate = correct / total if total > 0 else 0
    avg_return = sum(o.get("pnl_pct", 0) for o in outcomes) / total if total > 0 else 0

    # Context: the curated PROMPT_CORE knowledge + the LIVE thresholds.
    # (Not investment_rules: nothing in the scoring/gating/exit code reads
    # that table, so presenting it as "current rules" was misleading.)
    knowledge_text = KnowledgeService().get_prompt_knowledge_text()
    thresholds_text = get_live_thresholds_block()

    # Build analysis prompt
    outcomes_text = _format_outcomes(outcomes)

    prompt = f"""You are an investment signal engine optimizer. Analyze these real trade outcomes and suggest specific improvements to the live decision thresholds.

## TRADE OUTCOMES (last {period_days} days)
Total trades: {total}
Win rate: {win_rate:.1%}
Average return: {avg_return:+.2f}%

{outcomes_text}

## WHAT THE MODEL IS TOLD (curated knowledge)
{knowledge_text}

## LIVE THRESHOLDS (settings / code — these are what the system enforces)
{thresholds_text}

## YOUR TASK
Based on the trade outcomes, identify patterns and suggest specific rule changes that would improve future signal quality. For each suggestion provide:

Return a JSON object {{"suggestions": [...]}} where each suggestion is:
  {{
    "rule_name": "settings field or code rule to change (e.g. tech_filter_max_rsi), or NEW_RULE",
    "suggestion_type": "MODIFY_RULE" | "MODIFY_WEIGHT" | "DISABLE_RULE" | "NEW_RULE",
    "current_value": {{"field": "current_value"}},
    "proposed_value": {{"field": "new_value"}},
    "reasoning": "2-3 sentences explaining WHY based on the outcome data",
    "confidence": 0-100,
    "expected_impact": "Expected improvement description"
  }}

Rules:
- Only suggest changes supported by the outcome data — no speculation
- Fewer than 30 trades behind a pattern is not evidence; say so rather than suggest a change
- Any approved change is made by a human in code/config; nothing auto-applies
- Be conservative: small adjustments (5-10%) are better than large swings
- Focus on the rules that had the most incorrect signals
- Maximum 5 suggestions per analysis
- If win rate is above 60%, suggest refinements not overhauls
- If win rate is below 40%, suggest more aggressive changes
- Always explain which specific trades drove your suggestion

Return JSON only."""

    # Claude (CLI or budget-checked API, per CLAUDE_LOCAL) — structured output.
    try:
        from app.ai import provider as ai_provider

        data = await ai_provider.claude_structured(prompt, _SUGGESTIONS_SCHEMA, label="weekly_analysis")
        if data is None:
            logger.warning("Weekly analysis: Claude unavailable — no suggestions generated")
            return []
        suggestions_data = data.get("suggestions") if isinstance(data, dict) else data

        if not isinstance(suggestions_data, list):
            suggestions_data = [suggestions_data]

        # Store suggestions
        db_client = get_client()
        stored = []
        now = datetime.now(timezone.utc)
        period_start = (now - timedelta(days=period_days)).isoformat()

        for s in suggestions_data[:5]:  # Max 5
            # Suggestions target settings / code, not investment_rules rows.
            rule_id = None
            rule_name = s.get("rule_name", "")

            entry = {
                "analysis_date": now.isoformat(),
                "period_start": period_start,
                "period_end": now.isoformat(),
                "trades_analyzed": total,
                "win_rate": round(win_rate, 4),
                "avg_return_pct": round(avg_return, 4),
                "rule_id": rule_id,
                "rule_name": rule_name,
                "suggestion_type": s.get("suggestion_type", "MODIFY_RULE"),
                "current_value": s.get("current_value", {}),
                "proposed_value": s.get("proposed_value", {}),
                "reasoning": s.get("reasoning", ""),
                "confidence": s.get("confidence", 50),
                "expected_impact": s.get("expected_impact", ""),
                "status": "PENDING",
            }
            result = db_client.table("brain_suggestions").insert(entry).execute()
            if result.data:
                stored.append(result.data[0])

        logger.info(f"Weekly analysis complete: {total} trades, {win_rate:.1%} win rate, {len(stored)} suggestions generated")
        return stored

    except Exception as e:
        logger.error(f"Weekly analysis failed: {e}")
        return []


def _format_outcomes(outcomes: list[dict]) -> str:
    """Format outcomes for the AI prompt."""
    lines = []
    for o in outcomes[:30]:  # Limit to 30 for prompt size
        lines.append(
            f"- {o.get('symbol')} {o.get('action')} score={o.get('score')} "
            f"→ {o.get('pnl_pct', 0):+.2f}% in {o.get('days_held', '?')}d "
            f"({'✓' if o.get('signal_correct') else '✗'}) "
            f"bucket={o.get('bucket')} regime={o.get('market_regime', '?')}"
        )
    return "\n".join(lines)
