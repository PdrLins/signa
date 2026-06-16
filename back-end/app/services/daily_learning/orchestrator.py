"""Daily Learning orchestrator — the top-level coroutine.

============================================================
WHAT THIS MODULE DOES
============================================================

`run_daily_learning(target_date=None, *, dry_run=False, send_telegram=True,
force=False, strict=False)` is the public entrypoint. It is called by:

  - The scheduler job `daily_learning_loop()` (jobs.py), at 17:30 ET
  - The CLI `python -m app.services.daily_learning.cli`
  - Tests (via the module directly)

It glues together metrics + cohort_analyzer + explicit_patterns +
hypothesis_manager + digest, persists run metadata to
`daily_learning_runs`, writes the MD report atomically, inserts
`brain_suggestions` rows, and enqueues a Telegram digest.

============================================================
FAILURE MODES (DELIBERATE)
============================================================

  - Idempotency: existing COMPLETE row for target_date → SKIPPED_DUPLICATE.
    The DB unique-where-complete index is the hard guarantee; the
    pre-flight check is the fast path.
  - Stuck runs: existing RUNNING row >2h old → mark it FAILED and proceed.
  - Missing AFTER_CLOSE in strict mode → SKIPPED_NO_SCAN (default mode
    logs a warning and continues).
  - Any unexpected exception → the RUNNING row is updated to FAILED
    with error message before re-raising. The MD file is NOT written
    on partial runs.

============================================================
ATOMIC FILE WRITE
============================================================

The MD report is written to `{path}.tmp` then renamed to `{path}` so
a crash mid-write doesn't leave a half-written report on disk. The
tmp suffix is `.tmp-{run_id_short}` to avoid collisions across
concurrent runs (though concurrent runs shouldn't happen — idempotency
prevents it — defense in depth is cheap).
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger

from app.core.config import settings
from app.db.supabase import get_client
from app.services.daily_learning.cohort_analyzer import detect_cohort_drift
from app.services.daily_learning.digest import render_md_report, render_telegram_digest
from app.services.daily_learning.explicit_patterns import run_explicit_patterns
from app.services.daily_learning.hypothesis_manager import (
    auto_create_hypotheses,
    evaluate_active_hypotheses,
)
from app.services.daily_learning.metrics import compute_daily_metrics

ET = ZoneInfo("America/New_York")

# Where to write the daily MD reports. Resolved relative to backend repo
# root (one level above the app/ directory). The path is committed to git
# per Pedro's call — historical reports are searchable.
REPORT_DIR = Path(__file__).resolve().parents[3] / "docs" / "daily-reports"

# A RUNNING row older than this is treated as stuck → marked FAILED so
# the new attempt can proceed. Mirrors the scan stuck-run cleanup pattern
# documented in `feedback_stuck_scans_manual_cleanup`.
STUCK_RUN_MAX_AGE_MINUTES = 120


def _today_et() -> date:
    return datetime.now(ET).date()


def _et_day_bounds_utc_iso(target_date: date) -> tuple[str, str]:
    start_et = datetime.combine(target_date, datetime.min.time(), ET)
    end_et = start_et + timedelta(days=1)
    return (
        start_et.astimezone(timezone.utc).isoformat(),
        end_et.astimezone(timezone.utc).isoformat(),
    )


def _existing_complete_run_id(target_date: date) -> str | None:
    db = get_client()
    try:
        result = (
            db.table("daily_learning_runs")
            .select("id")
            .eq("target_date", target_date.isoformat())
            .eq("status", "COMPLETE")
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0]["id"]
    except Exception as e:
        logger.warning(f"daily_learning: existing-run check failed: {e}")
    return None


def _mark_stuck_runs_failed(target_date: date) -> None:
    db = get_client()
    try:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(minutes=STUCK_RUN_MAX_AGE_MINUTES)
        ).isoformat()
        stuck = (
            db.table("daily_learning_runs")
            .select("id,started_at")
            .eq("target_date", target_date.isoformat())
            .eq("status", "RUNNING")
            .lt("started_at", cutoff)
            .execute()
        ).data or []
        for row in stuck:
            db.table("daily_learning_runs").update(
                {
                    "status": "FAILED",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "error": "Auto-marked FAILED: RUNNING >2h with no completion",
                }
            ).eq("id", row["id"]).execute()
            logger.warning(
                f"daily_learning: stuck run {row['id'][:8]} (started "
                f"{row.get('started_at')}) marked FAILED before retry"
            )
    except Exception as e:
        logger.warning(f"daily_learning: stuck-run cleanup failed: {e}")


def _after_close_complete(target_date: date) -> bool:
    """True if the AFTER_CLOSE scan completed on target_date in ET."""
    db = get_client()
    start_iso, end_iso = _et_day_bounds_utc_iso(target_date)
    try:
        row = (
            db.table("scans")
            .select("status")
            .eq("scan_type", "AFTER_CLOSE")
            .eq("status", "COMPLETE")
            .gte("started_at", start_iso)
            .lt("started_at", end_iso)
            .limit(1)
            .execute()
        )
        return bool(row.data)
    except Exception as e:
        logger.warning(f"daily_learning: after-close check failed: {e}")
        return False


def _write_md_atomic(path: Path, content: str, run_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp-{run_id[:8]}")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _insert_suggestions(
    target_date: date,
    cohort_findings: list[Any],
    pattern_findings: list[Any],
    metrics: dict,
) -> list[dict]:
    """Build + INSERT brain_suggestions rows with suggestion_type='INVESTIGATE'.

    One row per Finding/CohortFinding. Each row's `reasoning` is the
    finding body (or headline if body is unavailable) — same shape Pedro
    sees in the UI today.
    """
    db = get_client()
    suggestions: list[dict] = []
    analysis_date = datetime.now(timezone.utc).isoformat()
    win_rate_30d = None
    # If wallet metrics have it, attach for context (best-effort).
    try:
        closes_count = metrics["closes"]["count"]
        wins = metrics["closes"]["wins"]
        if closes_count:
            win_rate_30d = round(wins / closes_count, 3)
    except Exception:
        pass

    def _emit(headline: str, reasoning: str, proposed: dict | None, rule_name: str) -> None:
        row = {
            "analysis_date": analysis_date,
            "trades_analyzed": metrics.get("total_closes_all_time") or 0,
            "win_rate": win_rate_30d,
            "rule_name": rule_name,
            "suggestion_type": "INVESTIGATE",
            "current_value": None,
            "proposed_value": proposed,
            "reasoning": reasoning,
            "confidence": 50,
            "expected_impact": "Pedro investigates manually; daily_learning does not propose code changes.",
            "status": "PENDING",
        }
        try:
            r = db.table("brain_suggestions").insert(row).execute()
            if r.data:
                row["id"] = r.data[0].get("id")
                suggestions.append(row)
        except Exception as e:
            logger.warning(f"daily_learning: suggestion insert failed: {e}")

    for cf in cohort_findings:
        _emit(
            headline=cf.headline(),
            reasoning=cf.headline(),
            proposed=cf.to_dict(),
            rule_name=f"cohort_{cf.dimension}_{cf.value}",
        )
    for pf in pattern_findings:
        sugg = pf.suggestion or {}
        _emit(
            headline=pf.headline,
            reasoning=sugg.get("reasoning") or pf.body[:1000],
            proposed=sugg or pf.to_dict(),
            rule_name=sugg.get("rule_name", pf.code.lower()),
        )
    return suggestions


async def _enqueue_telegram(digest_text: str) -> None:
    """Best-effort Telegram enqueue. Failures are logged, not raised."""
    chat_id = settings.telegram_chat_id
    if not chat_id:
        logger.info("daily_learning: telegram_chat_id not set; skipping digest")
        return
    try:
        # enqueue is sync (queue.put_nowait), called from async context fine.
        from app.notifications.telegram_bot import enqueue
        enqueue(chat_id, digest_text, parse_mode=None)
    except Exception as e:
        logger.warning(f"daily_learning: telegram enqueue failed: {e}")


async def run_daily_learning(
    target_date: date | None = None,
    *,
    dry_run: bool = False,
    send_telegram: bool = True,
    force: bool = False,
    strict: bool = False,
) -> dict[str, Any]:
    """Run the autonomous Daily Learning Loop for target_date.

    Args:
        target_date: ET calendar day to analyze. Defaults to today ET.
        dry_run: If True, compute everything but skip ALL writes
            (no MD file, no suggestions, no hypotheses, no Telegram,
            no daily_learning_runs row). Stdout/log-only.
        send_telegram: If False, skip the Telegram enqueue but do
            everything else.
        force: If True, bypass the idempotency lock and run anyway
            (a new RUNNING row will be inserted alongside any existing
            COMPLETE; both will live in the audit trail).
        strict: If True, return SKIPPED_NO_SCAN when AFTER_CLOSE didn't
            complete that day. Default False (log warning, continue).

    Returns: summary dict.
    """
    target_date = target_date or _today_et()
    db = get_client()
    started_at = datetime.now(timezone.utc)

    # ── Pre-flight: stuck-run cleanup + idempotency ─────────────────
    _mark_stuck_runs_failed(target_date)
    if not force and _existing_complete_run_id(target_date):
        logger.info(
            f"daily_learning({target_date}): already COMPLETE — skipping. "
            "Pass force=True to bypass."
        )
        return {"status": "SKIPPED_DUPLICATE", "target_date": target_date.isoformat()}

    # ── Insert RUNNING row (skip in dry-run) ────────────────────────
    run_id: str | None = None
    if not dry_run:
        try:
            ins = (
                db.table("daily_learning_runs")
                .insert(
                    {
                        "target_date": target_date.isoformat(),
                        "started_at": started_at.isoformat(),
                        "status": "RUNNING",
                    }
                )
                .execute()
            )
            run_id = ins.data[0]["id"] if ins.data else None
        except Exception as e:
            logger.error(f"daily_learning: RUNNING insert failed: {e}")
            return {"status": "FAILED", "error": str(e), "target_date": target_date.isoformat()}

    if run_id is None:
        # dry-run or insert failed: use a placeholder so the report still
        # has a stable run id field
        run_id = "dry-run-" + target_date.isoformat()

    try:
        # ── AFTER_CLOSE gate ────────────────────────────────────────
        after_close_ok = _after_close_complete(target_date)
        if not after_close_ok and strict:
            logger.warning(f"daily_learning({target_date}): AFTER_CLOSE not COMPLETE; --strict abort")
            if not dry_run:
                db.table("daily_learning_runs").update(
                    {
                        "status": "SKIPPED_NO_SCAN",
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                    }
                ).eq("id", run_id).execute()
            return {"status": "SKIPPED_NO_SCAN", "run_id": run_id, "target_date": target_date.isoformat()}
        if not after_close_ok:
            logger.warning(
                f"daily_learning({target_date}): AFTER_CLOSE not complete; "
                "continuing with available data"
            )

        # ── 2. Metrics ──────────────────────────────────────────────
        metrics = await asyncio.to_thread(compute_daily_metrics, target_date)
        logger.info(
            f"daily_learning: metrics computed — closes={metrics['closes']['count']} "
            f"entries={metrics['entries']['count']} "
            f"net={metrics['closes']['net_pnl']}"
        )

        # ── 3. Cohort drift (skipped on insufficient history) ───────
        if metrics.get("warning") == "insufficient_history":
            cohort_findings = []
            logger.info("daily_learning: cohort analysis skipped (insufficient history)")
        else:
            cohort_findings = await asyncio.to_thread(detect_cohort_drift, target_date)

        # ── 4. Explicit patterns ────────────────────────────────────
        pattern_findings = await asyncio.to_thread(run_explicit_patterns, target_date)

        # Combine for hypothesis creation + Telegram top-N. CohortFinding
        # and Finding are similar duck-typed — both expose .pattern_match,
        # both have a headline (method vs attribute, handled in digest).
        all_findings = list(cohort_findings) + list(pattern_findings)

        # ── 5a. Hypothesis lifecycle: evaluate active first ─────────
        if dry_run:
            hypothesis_actions = {"graduated": [], "rejected": [], "inconclusive": []}
            new_hypothesis_summary = {
                "created": [], "skipped_existing_active": [], "resurfaced_rejected": []
            }
        else:
            hypothesis_actions = await asyncio.to_thread(evaluate_active_hypotheses)
            # 5b. Auto-create from findings
            new_hypothesis_summary = await asyncio.to_thread(
                auto_create_hypotheses, all_findings
            )

        # ── 6a. Insert suggestions (one per finding) ────────────────
        if dry_run:
            suggestions: list[dict] = []
        else:
            suggestions = _insert_suggestions(
                target_date, cohort_findings, pattern_findings, metrics
            )

        # ── 6b. Render + write MD report ────────────────────────────
        completed_at = datetime.now(timezone.utc)
        md_text = render_md_report(
            metrics=metrics,
            cohorts=cohort_findings,
            patterns=pattern_findings,
            new_hypothesis_summary=new_hypothesis_summary,
            hypothesis_actions=hypothesis_actions,
            suggestions=suggestions,
            run_id=str(run_id),
            started_at=started_at,
            completed_at=completed_at,
        )
        md_path: Path | None = None
        if not dry_run:
            md_path = REPORT_DIR / f"{target_date.isoformat()}.md"
            _write_md_atomic(md_path, md_text, str(run_id))
            logger.info(f"daily_learning: report written to {md_path}")
        else:
            logger.info("daily_learning: dry-run, MD report NOT written. Preview:")
            for line in md_text.splitlines()[:30]:
                logger.info(f"  {line}")

        # ── 6c. Telegram digest ─────────────────────────────────────
        rel_path = None
        if md_path is not None:
            try:
                rel_path = str(md_path.relative_to(Path(__file__).resolve().parents[3]))
            except ValueError:
                rel_path = str(md_path)
        digest_text = render_telegram_digest(
            metrics=metrics,
            findings=all_findings,
            top_findings_count=2,
            md_relative_path=rel_path,
        )
        if send_telegram and not dry_run:
            await _enqueue_telegram(digest_text)
        else:
            logger.info(f"daily_learning: telegram suppressed. Preview:\n{digest_text}")

        # ── Mark COMPLETE ───────────────────────────────────────────
        runtime_ms = int((completed_at - started_at).total_seconds() * 1000)
        if not dry_run and run_id:
            try:
                db.table("daily_learning_runs").update(
                    {
                        "status": "COMPLETE",
                        "completed_at": completed_at.isoformat(),
                        "metrics": metrics,
                        "findings_count": len(all_findings),
                        "hypotheses_created": len(new_hypothesis_summary.get("created") or []),
                        "hypotheses_graduated": len(hypothesis_actions.get("graduated") or []),
                        "hypotheses_rejected": len(hypothesis_actions.get("rejected") or []),
                        "suggestions_created": len(suggestions),
                        "md_report_path": rel_path,
                        "runtime_ms": runtime_ms,
                    }
                ).eq("id", run_id).execute()
            except Exception as e:
                logger.warning(f"daily_learning: COMPLETE update failed: {e}")

        return {
            "status": "COMPLETE",
            "run_id": run_id,
            "target_date": target_date.isoformat(),
            "findings_count": len(all_findings),
            "cohorts_count": len(cohort_findings),
            "patterns_count": len(pattern_findings),
            "hypotheses_created": len(new_hypothesis_summary.get("created") or []),
            "hypotheses_graduated": len(hypothesis_actions.get("graduated") or []),
            "hypotheses_rejected": len(hypothesis_actions.get("rejected") or []),
            "suggestions_created": len(suggestions),
            "md_report_path": rel_path,
            "runtime_ms": runtime_ms,
        }

    except Exception as e:
        logger.exception(f"daily_learning({target_date}) FAILED: {e}")
        if not dry_run and run_id:
            try:
                db.table("daily_learning_runs").update(
                    {
                        "status": "FAILED",
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "error": str(e)[:5000],
                    }
                ).eq("id", run_id).execute()
            except Exception as inner:
                logger.warning(f"daily_learning: FAILED update failed: {inner}")
        raise
