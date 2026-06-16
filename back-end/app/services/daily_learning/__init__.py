"""Daily Learning Loop — autonomous end-of-day analyst for the brain.

============================================================
WHAT THIS PACKAGE IS
============================================================

A scheduled job that runs every market day at 17:30 ET (Mon-Fri), after
the AFTER_CLOSE scan and the virtual_portfolio_snapshot. It replaces the
human-orchestrated "check the day / find lessons / propose changes" loop
Pedro currently runs manually with Claude.

The loop is DELIBERATELY analysis-only. It surfaces patterns, drift, and
suggestions; it does NOT apply rule changes. Code ships still require
Pedro's greenlight per `feedback_backtest_before_brain_changes` — this
package is the IDENTIFY step, not the SHIP step.

============================================================
THE 6-STEP FLOW (orchestrator.run_daily_learning)
============================================================

  1. Gate          — idempotency check + AFTER_CLOSE completeness
  2. Metrics       — closes/entries/P&L, wallet delta, 7d/30d rolling rates
  3. Cohort drift  — 30d-vs-90d-baseline diff across 5 dimensions
  4. Patterns      — 4 explicit matchers (watchdog cluster, repeat loser,
                     drawdown, new cohort emergence)
  5. Hypotheses    — auto-create new from findings, auto-graduate/reject
                     active ones whose threshold is reached
  6. Emit          — MD report file, Telegram digest, brain_suggestions
                     INVESTIGATE rows, structured console logs

============================================================
PUBLIC ENTRYPOINTS
============================================================

  run_daily_learning(target_date=None)
      The top-level coroutine. Call from the scheduler or CLI. Returns
      a dict summary {status, run_id, findings_count, ...}.

  CLI:  python -m app.services.daily_learning.cli --date YYYY-MM-DD ...
      Flags: --dry-run, --no-telegram, --force, --strict.

============================================================
WHY A PACKAGE NOT A SINGLE FILE
============================================================

The 6 steps have genuinely different shapes (SQL aggregation vs text
generation vs scheduling glue). Splitting lets each module carry its
own substantial docstring per `feedback_brain_files_must_be_documented`
and makes unit testing tractable (each module gets its own test file).

See individual module docstrings for design rationale.
"""

from app.services.daily_learning.orchestrator import run_daily_learning

__all__ = ["run_daily_learning"]
