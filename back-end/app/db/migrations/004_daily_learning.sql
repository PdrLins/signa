-- Migration 004: daily_learning_runs table + brain_suggestions vocab note
--
-- WHY: Stage 8 of the self-learning loop ships an autonomous Daily Learning
-- Loop that runs after AFTER_CLOSE scan + portfolio snapshot every market
-- day (17:30 ET Mon-Fri). It computes day metrics, detects cohort drift,
-- runs explicit pattern matchers, auto-creates signal_thinking hypotheses,
-- auto-graduates or auto-rejects active hypotheses, writes a daily MD
-- report under docs/daily-reports/, fires a Telegram digest, and inserts
-- brain_suggestions rows for actionable findings.
--
-- WITHOUT THIS table: the loop has no idempotency anchor. Re-running
-- against the same target_date would duplicate hypothesis creation and
-- spam Telegram. A unique-where-complete index on (target_date) is the
-- lock; pre-flight check in the orchestrator returns SKIPPED_DUPLICATE.
--
-- HOW TO APPLY: paste into Supabase Dashboard SQL editor and run.
-- Idempotent (uses IF NOT EXISTS).

-- ============================================================
-- 1. daily_learning_runs — one row per loop invocation
-- ============================================================
-- Lifecycle:
--   RUNNING            in-flight
--   COMPLETE           finished successfully
--   FAILED             raised an exception (error column populated)
--   SKIPPED_DUPLICATE  pre-flight saw an existing COMPLETE for same date
--   SKIPPED_NO_SCAN    --strict mode + AFTER_CLOSE did not complete that day
--
-- The partial unique index `uq_daily_learning_runs_date_complete`
-- enforces: at most one COMPLETE per target_date. FAILED / SKIPPED rows
-- can stack (so retries are visible in the audit trail without violating
-- the lock).

CREATE TABLE IF NOT EXISTS daily_learning_runs (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_date           DATE NOT NULL,
    started_at            TIMESTAMPTZ DEFAULT now(),
    completed_at          TIMESTAMPTZ,
    status                VARCHAR DEFAULT 'RUNNING',
    metrics               JSONB,
        -- snapshot of compute_daily_metrics() output: closes_count, wins,
        -- losses, net_pnl, wallet_total, daily_pct, rolling_7d_pct,
        -- rolling_30d_pct, open_count, unrealized_pnl, regime, vix.
    findings_count        INT DEFAULT 0,
        -- total findings emitted by cohort_analyzer + explicit_patterns
    hypotheses_created    INT DEFAULT 0,
        -- new signal_thinking rows inserted by this run
    hypotheses_graduated  INT DEFAULT 0,
        -- active hypotheses promoted to signal_knowledge by this run
    hypotheses_rejected   INT DEFAULT 0,
        -- active hypotheses set to status='rejected' by this run
    suggestions_created   INT DEFAULT 0,
        -- brain_suggestions rows inserted (suggestion_type='INVESTIGATE')
    md_report_path        TEXT,
        -- relative path under repo root, e.g. docs/daily-reports/2026-06-15.md
    runtime_ms            INT,
    error                 TEXT
);

-- The idempotency lock. At most one COMPLETE row per target_date.
-- Partial index (status='COMPLETE') so FAILED/SKIPPED retries can coexist.
CREATE UNIQUE INDEX IF NOT EXISTS uq_daily_learning_runs_date_complete
    ON daily_learning_runs(target_date) WHERE status = 'COMPLETE';

CREATE INDEX IF NOT EXISTS idx_daily_learning_runs_started
    ON daily_learning_runs(started_at DESC);

CREATE INDEX IF NOT EXISTS idx_daily_learning_runs_status
    ON daily_learning_runs(status);

-- ============================================================
-- 2. brain_suggestions.suggestion_type vocabulary extension
-- ============================================================
-- The column is VARCHAR with no CHECK constraint, so no DDL is required
-- to accept the new 'INVESTIGATE' value. We update the column COMMENT
-- so a future reader sees the canonical vocabulary in one place.
-- Existing values: MODIFY_RULE | MODIFY_WEIGHT | DISABLE_RULE | NEW_RULE
-- New value:       INVESTIGATE  (daily_learning emits these for findings)

COMMENT ON COLUMN brain_suggestions.suggestion_type IS
  'MODIFY_RULE | MODIFY_WEIGHT | DISABLE_RULE | NEW_RULE | INVESTIGATE. '
  'INVESTIGATE rows are emitted by the daily_learning_loop when a finding '
  'has no associated rule yet — Pedro investigates manually before any '
  'code change is proposed.';

-- ============================================================
-- VERIFICATION (should return 5 rows: the 5 named columns)
-- ============================================================
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'daily_learning_runs'
  AND column_name IN ('target_date', 'status', 'metrics', 'findings_count', 'md_report_path')
ORDER BY column_name;
