"""Hypothesis lifecycle — auto-create new hypotheses + auto-graduate/reject active ones.

============================================================
WHAT THIS MODULE DOES
============================================================

Two distinct flows, both invoked by the daily orchestrator:

  auto_create_hypotheses(findings)
      Given a list of CohortFindings + Findings with pattern_match,
      INSERT new signal_thinking rows when:
        - No active hypothesis already matches the same pattern_match
          (dedupe via JSONB containment query — we ask Postgres "find
          me an active row whose pattern_match contains mine and mine
          contains its" which is the exact-match condition).
        - The Finding has a non-None pattern_match (DRAWDOWN_3D opts out).
      Every INSERT logs `thinking_created` to knowledge_events.

  evaluate_active_hypotheses()
      For each active signal_thinking row where the supporting +
      contradicting counters total >= graduation_threshold:
        - If supporting/total > 0.70: graduate. INSERT a signal_knowledge
          row (source_type='learned_from_thinking'), UPDATE thinking
          status='graduated', log `thinking_graduated`.
        - If contradicting/total > 0.70: reject. UPDATE thinking
          status='rejected', log `thinking_rejected`.
        - Otherwise leave active. The threshold may be met but the
          ratio is inconclusive; another N observations may resolve it.

============================================================
WHY 0.70 AS THE GRADUATION/REJECTION RATIO?
============================================================

A 70/30 supporting/contradicting split at n=5 means 3.5 supporting
observations. In practice that's 4/1 — strong but not unanimous. A
higher bar (e.g. 0.85) wouldn't graduate hypotheses with 5 supporting
and 1 contradicting, which is exactly the win-rate-shift evidence
pattern we want to graduate. Lower bars (0.60) graduate noise.

If the ratio is between 0.30 and 0.70, the hypothesis stays active.
The next day's observation accumulates and re-evaluation re-checks.

============================================================
THE JSONB CONTAINMENT TRICK FOR DEDUPE
============================================================

PostgreSQL: `WHERE pattern_match @> '{...}'::jsonb AND '{...}'::jsonb @> pattern_match`
means "pattern_match equals (as a set) the given object." That's
exactly the dedupe condition.

Supabase Python client: `.contains('pattern_match', payload)` produces
the `@>` half. We post-filter for full equality in Python because the
client doesn't expose the reverse direction cleanly. Cost is ~5 active
rows to scan per Finding — negligible.

If a REJECTED hypothesis with the same pattern_match exists, we log a
synthetic `thinking_observation_added` event with `{"resurfaced": true}`
and surface that in the report. We do NOT recreate the row — that would
re-litigate a previously rejected pattern.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Sequence
from uuid import UUID

from loguru import logger

from app.db.supabase import get_client
from app.services.knowledge_events import (
    EVENT_THINKING_CREATED,
    EVENT_THINKING_GRADUATED,
    EVENT_THINKING_OBSERVATION_ADDED,
    EVENT_THINKING_REJECTED,
    EVENT_KNOWLEDGE_CREATED,
    log_event,
)

# Match the existing 0.70 ratio used elsewhere. Tunable via config later
# if we observe a sustained mismatch with manual graduation calls.
GRADUATION_RATIO = 0.70
REJECTION_RATIO = 0.70


def _payload_equal(a: dict | None, b: dict | None) -> bool:
    """Strict dict equality for pattern_match dedupe. JSONB containment in
    both directions is set equality; in Python we just compare dicts.
    """
    if a is None or b is None:
        return False
    return a == b


def _find_existing_for_pattern(pattern_match: dict) -> Optional[dict]:
    """Return the FIRST signal_thinking row whose pattern_match equals the
    given one (regardless of status), or None.

    We need to know if there's an ACTIVE one (skip creation) OR a REJECTED
    one (log resurfaced event), so we query without a status filter.
    """
    if not pattern_match:
        return None
    db = get_client()
    try:
        result = (
            db.table("signal_thinking")
            .select("id,pattern_match,status")
            .contains("pattern_match", pattern_match)
            .execute()
        )
    except Exception as e:
        logger.warning(f"hypothesis_manager: dedupe query failed: {e}")
        return None
    for row in (result.data or []):
        if _payload_equal(row.get("pattern_match"), pattern_match):
            return row
    return None


def _generate_hypothesis_text(finding) -> tuple[str, str, dict]:
    """Build (hypothesis, prediction, invalidation_conditions) from a Finding-shaped object.

    Works for both CohortFinding (cohort_analyzer) and Finding (explicit_patterns).
    Both expose .pattern_match and either .headline (string property) or
    .headline (method). We probe both.
    """
    pm = finding.pattern_match
    # Robust headline extraction (CohortFinding.headline() is a method,
    # Finding.headline is an attribute).
    if callable(getattr(finding, "headline", None)):
        headline_text = finding.headline()
    else:
        headline_text = getattr(finding, "headline", "")

    code_or_dim = getattr(finding, "code", None) or getattr(finding, "dimension", "auto")

    hypothesis = (
        f"[auto] {headline_text} suggests the pattern_match cohort has shifted "
        f"vs prior baseline."
    )
    prediction = (
        f"Future trades matching {pm} will continue the observed direction (under/over-performance) "
        f"unless invalidated."
    )
    invalidation = {
        "any_of": [
            {"description": "Next 5 matching trades produce a win-rate within 10pp of the historical baseline."},
            {"description": "Cohort net P&L flips from current direction over a 30-day window."},
        ],
        "rationale": (
            f"Auto-generated by daily_learning on detection of {code_or_dim}. "
            "Manual review encouraged before treating as graduated knowledge."
        ),
    }
    return hypothesis, prediction, invalidation


def auto_create_hypotheses(findings: Sequence[Any]) -> dict[str, Any]:
    """For each finding with a non-None pattern_match, create a signal_thinking
    row unless an active one already exists with the same pattern_match.

    Returns a summary dict:
        {
          "created":    [{"id", "headline", "pattern_match"}],
          "skipped_existing_active": [...],
          "resurfaced_rejected":     [...],
        }
    """
    db = get_client()
    created = []
    skipped_active = []
    resurfaced = []

    for finding in findings:
        pm = getattr(finding, "pattern_match", None)
        if not pm:
            continue
        existing = _find_existing_for_pattern(pm)
        if existing:
            status = (existing.get("status") or "").lower()
            if status == "active":
                skipped_active.append({"id": existing["id"], "pattern_match": pm})
                continue
            if status == "rejected":
                # Surface in the report; don't recreate.
                log_event(
                    EVENT_THINKING_OBSERVATION_ADDED,
                    triggered_by="daily_learning",
                    thinking_id=existing["id"],
                    payload={"resurfaced": True, "pattern_match": pm},
                    reason=(
                        f"Pattern {pm} resurfaced today but is already in a "
                        "previously rejected hypothesis — not re-creating."
                    ),
                )
                resurfaced.append({"id": existing["id"], "pattern_match": pm})
                continue
            # 'graduated' or 'stale' — treat as 'don't re-create'
            skipped_active.append({"id": existing["id"], "pattern_match": pm})
            continue

        hypothesis, prediction, invalidation = _generate_hypothesis_text(finding)
        row = {
            "hypothesis": hypothesis,
            "prediction": prediction,
            "pattern_match": pm,
            "invalidation_conditions": invalidation,
            "created_by": "auto_analyzer",
            "status": "active",
            "graduation_threshold": 5,
        }
        try:
            result = db.table("signal_thinking").insert(row).execute()
            inserted_id = result.data[0]["id"] if result.data else None
        except Exception as e:
            logger.warning(f"hypothesis_manager: insert failed for {pm}: {e}")
            continue

        log_event(
            EVENT_THINKING_CREATED,
            triggered_by="daily_learning",
            thinking_id=inserted_id,
            payload={"pattern_match": pm, "headline": hypothesis[:200]},
            reason=f"Auto-created from daily_learning finding: {hypothesis[:200]}",
        )
        created.append({"id": inserted_id, "pattern_match": pm, "hypothesis": hypothesis})

    logger.info(
        f"hypothesis_manager.auto_create: created={len(created)} "
        f"skipped_active={len(skipped_active)} resurfaced={len(resurfaced)}"
    )
    return {
        "created": created,
        "skipped_existing_active": skipped_active,
        "resurfaced_rejected": resurfaced,
    }


def evaluate_active_hypotheses() -> dict[str, Any]:
    """Iterate active signal_thinking rows; graduate or reject those whose
    observation counters cross the graduation_threshold AND the ratio is
    decisive (>70% one direction).

    Returns a summary dict:
        {
          "graduated":  [{"id", "key_concept", "supporting", "contradicting"}],
          "rejected":   [{"id", "supporting", "contradicting"}],
          "inconclusive": [{"id", "supporting", "contradicting"}],
        }
    """
    db = get_client()
    try:
        rows = (
            db.table("signal_thinking")
            .select("*")
            .eq("status", "active")
            .execute()
        ).data or []
    except Exception as e:
        logger.warning(f"hypothesis_manager.evaluate: select failed: {e}")
        return {"graduated": [], "rejected": [], "inconclusive": []}

    graduated, rejected, inconclusive = [], [], []
    now_iso = datetime.now(timezone.utc).isoformat()

    for r in rows:
        sup = r.get("observations_supporting") or 0
        con = r.get("observations_contradicting") or 0
        threshold = r.get("graduation_threshold") or 5
        total = sup + con
        if total < threshold:
            continue
        ratio_sup = sup / total if total else 0
        ratio_con = con / total if total else 0
        thinking_id = r["id"]

        if ratio_sup > GRADUATION_RATIO:
            # Graduate: insert into signal_knowledge, mark thinking graduated.
            # Build a stable, unique key_concept for signal_knowledge.
            key_concept = f"learned:{thinking_id[:8]}"
            knowledge_row = {
                "topic": "learned_pattern",
                "key_concept": key_concept,
                "explanation": (
                    f"Graduated from hypothesis '{r.get('hypothesis','')[:200]}'. "
                    f"Supporting evidence: {sup}, contradicting: {con} "
                    f"(threshold {threshold})."
                ),
                "is_active": True,
                "source_type": "learned_from_thinking",
                "learned_from_thinking_id": thinking_id,
                "invalidation_conditions": r.get("invalidation_conditions"),
            }
            try:
                k_insert = db.table("signal_knowledge").insert(knowledge_row).execute()
                k_id = k_insert.data[0]["id"] if k_insert.data else None
            except Exception as e:
                logger.warning(
                    f"hypothesis_manager: knowledge insert failed for {thinking_id}: {e}"
                )
                continue
            try:
                db.table("signal_thinking").update(
                    {"status": "graduated", "graduated_to": k_id,
                     "last_evaluated_at": now_iso, "updated_at": now_iso}
                ).eq("id", thinking_id).execute()
            except Exception as e:
                logger.warning(f"hypothesis_manager: thinking update failed: {e}")
            log_event(
                EVENT_KNOWLEDGE_CREATED,
                triggered_by="daily_learning",
                thinking_id=thinking_id,
                knowledge_id=k_id,
                payload={"supporting": sup, "contradicting": con},
                reason=(
                    f"Auto-graduated thinking {thinking_id[:8]} to knowledge "
                    f"{(k_id or '?')[:8]} ({sup} supporting, {con} contradicting)."
                ),
            )
            log_event(
                EVENT_THINKING_GRADUATED,
                triggered_by="daily_learning",
                thinking_id=thinking_id,
                knowledge_id=k_id,
                payload={"supporting": sup, "contradicting": con, "ratio": round(ratio_sup, 2)},
                reason=f"Graduated: supporting/total = {ratio_sup:.0%}",
            )
            graduated.append(
                {"id": thinking_id, "key_concept": key_concept,
                 "supporting": sup, "contradicting": con, "knowledge_id": k_id}
            )
        elif ratio_con > REJECTION_RATIO:
            try:
                db.table("signal_thinking").update(
                    {"status": "rejected", "last_evaluated_at": now_iso, "updated_at": now_iso}
                ).eq("id", thinking_id).execute()
            except Exception as e:
                logger.warning(f"hypothesis_manager: rejection update failed: {e}")
            log_event(
                EVENT_THINKING_REJECTED,
                triggered_by="daily_learning",
                thinking_id=thinking_id,
                payload={"supporting": sup, "contradicting": con, "ratio_con": round(ratio_con, 2)},
                reason=f"Rejected: contradicting/total = {ratio_con:.0%}",
            )
            rejected.append({"id": thinking_id, "supporting": sup, "contradicting": con})
        else:
            inconclusive.append(
                {"id": thinking_id, "supporting": sup, "contradicting": con}
            )

    logger.info(
        f"hypothesis_manager.evaluate: graduated={len(graduated)} "
        f"rejected={len(rejected)} inconclusive={len(inconclusive)}"
    )
    return {"graduated": graduated, "rejected": rejected, "inconclusive": inconclusive}
