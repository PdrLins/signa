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
      For each active signal_thinking row, collect the P&L of every trade
      that matched it (from knowledge_events observation payloads) and
      run `stats.evidence_verdict`:
        - n < MIN_OBSERVATIONS_TO_DECIDE (30) → stay active, no verdict.
        - 'supported' (bootstrap CI of expectancy entirely on the
          predicted side of 0 AND Wilson lower bound of the predicted
          outcome rate > 50%) → graduate to signal_knowledge.
        - 'refuted' (expectancy CI entirely on the other side) → reject.
        - otherwise stay active.

============================================================
2026-09 RESET — WHY NOT 0.70 AT n=5 ANY MORE
============================================================

The old rule graduated on a >70% supporting ratio after 5 observations.
The 95% Wilson interval for 4/5 is ~[0.38, 0.96] — indistinguishable from
a coin flip. Win/loss counts also ignore payoff size. Graduation now
needs n >= 30 AND an expectancy interval that excludes zero.

Graduated knowledge and every hypothesis are SUGGESTIONS for a human: the
learning loop never edits trading rules or config. Hypotheses whose
pattern_match describes a trade OUTCOME (exit_reason*) or uses keys the
brain can't check (window_days, count_threshold, new_cohorts, ...) are not
created — they would match nothing (strict matching) or be circular.

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
from app.services.daily_learning.stats import MIN_OBSERVATIONS, evidence_verdict
from app.services.knowledge_events import (
    EVENT_THINKING_CREATED,
    EVENT_THINKING_GRADUATED,
    EVENT_THINKING_OBSERVATION_ADDED,
    EVENT_THINKING_REJECTED,
    EVENT_KNOWLEDGE_CREATED,
    log_event,
)

# Evidence bar for a verdict (see module docstring). The old 0.70 ratio
# constants are gone: a point-estimate ratio is not evidence at small n.
MIN_OBSERVATIONS_TO_DECIDE = MIN_OBSERVATIONS
GRADUATION_THRESHOLD_DEFAULT = MIN_OBSERVATIONS


def _is_trade_predictive(pattern_match: dict | None) -> bool:
    """True when every key is an ENTRY-time attribute the brain can check.

    Outcome keys (exit_reason*) are circular; unknown keys never match.
    """
    from app.services.virtual_portfolio import OUTCOME_PATTERN_KEYS, PATTERN_MATCHERS

    if not pattern_match or not isinstance(pattern_match, dict):
        return False
    return all(k in PATTERN_MATCHERS and k not in OUTCOME_PATTERN_KEYS for k in pattern_match)


def _expected_direction(finding) -> str:
    """'win' for over-performing cohorts, 'loss' otherwise."""
    return "win" if getattr(finding, "direction", None) == "over" else "loss"


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

    expected = _expected_direction(finding)
    hypothesis = (
        f"[auto] {headline_text} suggests the pattern_match cohort has shifted "
        f"vs prior baseline."
    )
    prediction = (
        f"Future trades matching {pm} will "
        + ("OVER-perform (positive expectancy)" if expected == "win"
           else "UNDER-perform (negative expectancy)")
        + " unless invalidated."
    )
    invalidation = {
        "any_of": [
            {"description": "After >= 30 matching trades the expectancy CI includes 0 or sits on the other side."},
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
        if not _is_trade_predictive(pm):
            # Reported + suggested, but not a hypothesis the brain can test.
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
            "graduation_threshold": GRADUATION_THRESHOLD_DEFAULT,
            "expected_direction": _expected_direction(finding),
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
    """Iterate active signal_thinking rows; graduate or reject only when
    n >= 30 matched trades AND `stats.evidence_verdict` is decisive
    (expectancy CI excludes 0; Wilson bound on the predicted outcome rate).
    Graduation writes a signal_knowledge row for human review — it never
    changes trading rules.

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
        threshold = max(int(r.get("graduation_threshold") or 0), MIN_OBSERVATIONS_TO_DECIDE)
        thinking_id = r["id"]
        pnls = _observation_pnls(thinking_id)
        expected = (r.get("expected_direction") or "").lower() or _infer_expected(r)
        verdict = evidence_verdict(pnls, expected, min_n=threshold)
        if verdict["verdict"] == "insufficient":
            continue
        ratio_sup = verdict.get("hit_rate", 0.0)
        ratio_con = 1 - ratio_sup

        if verdict["verdict"] == "supported":
            # Graduate: insert into signal_knowledge, mark thinking graduated.
            # Build a stable, unique key_concept for signal_knowledge.
            key_concept = f"learned:{thinking_id[:8]}"
            knowledge_row = {
                "topic": "learned_pattern",
                "key_concept": key_concept,
                "explanation": (
                    f"Graduated from hypothesis '{r.get('hypothesis','')[:200]}'. "
                    f"n={verdict['n']}, expectancy {verdict['expectancy']:+.2f}%/trade, "
                    f"95% CI {verdict['expectancy_ci'][0]:+.2f}..{verdict['expectancy_ci'][1]:+.2f}, "
                    f"hit-rate Wilson {verdict['wilson'][0]:.0%}..{verdict['wilson'][1]:.0%}. "
                    f"SUGGESTION ONLY — not applied to trading."
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
        elif verdict["verdict"] == "refuted":
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


def _infer_expected(row: dict) -> str:
    from app.services.virtual_portfolio import _infer_expected_direction
    return _infer_expected_direction(row.get("prediction") or "")


def _observation_pnls(thinking_id: str) -> list[float]:
    """pnl_pct of every trade that matched this hypothesis (from the
    append-only knowledge_events log written by the close hook)."""
    try:
        rows = (
            get_client().table("knowledge_events")
            .select("payload")
            .eq("thinking_id", thinking_id)
            .eq("event_type", EVENT_THINKING_OBSERVATION_ADDED)
            .execute()
        ).data or []
    except Exception as e:
        logger.warning(f"hypothesis_manager: observation read failed for {thinking_id}: {e}")
        return []
    out: list[float] = []
    for r in rows:
        payload = r.get("payload") or {}
        if payload.get("resurfaced"):
            continue
        v = payload.get("pnl_pct")
        if isinstance(v, (int, float)):
            out.append(float(v))
    return out
