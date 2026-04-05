"""Self-learning feedback loop — analyzes trade outcomes and suggests brain improvements.

Flow:
1. record_outcome() — called when a position is closed or signal expires
2. run_weekly_analysis() — Claude reviews all recent outcomes + current rules
3. Claude generates specific brain_suggestions with reasoning
4. User approves/rejects in Brain Editor
5. apply_suggestion() — writes approved changes to investment_rules
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger

from app.db.supabase import get_client
from app.services.knowledge_service import KnowledgeService


def record_outcome(
    signal_id: str,
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
) -> dict:
    """Record the outcome of a trade for learning."""
    pnl_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
    pnl_amount = exit_price - entry_price  # Per-share P&L (consistent unit for cross-trade comparison)

    # Was the signal correct?
    if action == "BUY":
        signal_correct = pnl_pct > 0
    elif action in ("SELL", "AVOID"):
        signal_correct = pnl_pct <= 0  # Correct to avoid if price dropped
    else:
        signal_correct = abs(pnl_pct) < 3  # HOLD is correct if price didn't move much

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


def apply_suggestion(suggestion_id: str, user_id: str) -> dict:
    """Apply an approved suggestion to investment_rules."""
    client = get_client()

    # Get the suggestion
    result = client.table("brain_suggestions").select("*").eq("id", suggestion_id).limit(1).execute()
    if not result.data:
        return {"error": "Suggestion not found"}

    suggestion = result.data[0]
    if suggestion["status"] != "APPROVED":
        return {"error": "Suggestion must be APPROVED before applying"}

    ks = KnowledgeService()
    proposed = suggestion.get("proposed_value", {})
    rule_id = suggestion.get("rule_id")

    if suggestion["suggestion_type"] == "MODIFY_RULE" and rule_id:
        ks.update_rule(rule_id, proposed)
        logger.info(f"Applied suggestion {suggestion_id}: modified rule {suggestion.get('rule_name')}")
    elif suggestion["suggestion_type"] == "MODIFY_WEIGHT" and rule_id:
        ks.update_rule(rule_id, proposed)
        logger.info(f"Applied suggestion {suggestion_id}: modified weight for {suggestion.get('rule_name')}")
    elif suggestion["suggestion_type"] == "DISABLE_RULE" and rule_id:
        ks.update_rule(rule_id, {"is_active": False})
        logger.info(f"Applied suggestion {suggestion_id}: disabled rule {suggestion.get('rule_name')}")

    # Mark as applied
    client.table("brain_suggestions").update({
        "status": "APPLIED",
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "reviewed_by": user_id,
    }).eq("id", suggestion_id).execute()

    return {"status": "applied", "rule_name": suggestion.get("rule_name")}


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

    # Get current rules for context
    ks = KnowledgeService()
    rules = ks.get_all_rules()

    # Build analysis prompt
    outcomes_text = _format_outcomes(outcomes)
    rules_text = _format_rules(rules)

    prompt = f"""You are an investment signal engine optimizer. Analyze these real trade outcomes and suggest specific improvements to the scoring rules.

## TRADE OUTCOMES (last {period_days} days)
Total trades: {total}
Win rate: {win_rate:.1%}
Average return: {avg_return:+.2f}%

{outcomes_text}

## CURRENT INVESTMENT RULES
{rules_text}

## YOUR TASK
Based on the trade outcomes, identify patterns and suggest specific rule changes that would improve future signal quality. For each suggestion provide:

Return a JSON array of suggestions:
[
  {{
    "rule_name": "name of rule to modify (or NEW_RULE for new ones)",
    "suggestion_type": "MODIFY_RULE" | "MODIFY_WEIGHT" | "DISABLE_RULE" | "NEW_RULE",
    "current_value": {{"field": "current_value"}},
    "proposed_value": {{"field": "new_value"}},
    "reasoning": "2-3 sentences explaining WHY based on the outcome data",
    "confidence": 0-100,
    "expected_impact": "Expected improvement description"
  }}
]

Rules:
- Only suggest changes supported by the outcome data — no speculation
- Be conservative: small adjustments (5-10%) are better than large swings
- Focus on the rules that had the most incorrect signals
- Maximum 5 suggestions per analysis
- If win rate is above 60%, suggest refinements not overhauls
- If win rate is below 40%, suggest more aggressive changes
- Always explain which specific trades drove your suggestion

Return JSON only."""

    # Call Gemini directly for learning analysis
    try:
        import asyncio
        import json

        from app.core.config import settings
        from google import genai

        client = genai.Client(api_key=settings.gemini_api_key)
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=settings.gemini_model,
            contents=prompt,
        )

        from app.ai.prompts import clean_json_response
        text = clean_json_response(response.text)
        suggestions_data = json.loads(text)

        if not isinstance(suggestions_data, list):
            suggestions_data = [suggestions_data]

        # Store suggestions
        db_client = get_client()
        stored = []
        now = datetime.now(timezone.utc)
        period_start = (now - timedelta(days=period_days)).isoformat()

        for s in suggestions_data[:5]:  # Max 5
            # Find rule_id if modifying existing rule
            rule_id = None
            rule_name = s.get("rule_name", "")
            if rule_name and rule_name != "NEW_RULE":
                matching = [r for r in rules if r.get("name") == rule_name]
                if matching:
                    rule_id = matching[0].get("id")

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


def _format_rules(rules: list[dict]) -> str:
    """Format current rules for the AI prompt."""
    lines = []
    for r in rules:
        if not r.get("is_active"):
            continue
        lines.append(
            f"- [{r.get('rule_type')}] {r.get('name')}: "
            f"w_safe={r.get('weight_safe', 0)} w_risk={r.get('weight_risk', 0)} "
            f"blocker={r.get('is_blocker', False)}"
        )
    return "\n".join(lines)
