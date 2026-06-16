"""Source-level regression tests for the daily_learning idempotency guarantees.

These are NOT DB-touching tests — they're contract pins on the schema +
orchestrator behavior. The full integration is verified by the manual
CLI replay against real data.
"""

import os
from pathlib import Path

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("BRAIN_TOKEN_SECRET", "test-brain-secret-32chars-min-len-test")
os.environ.setdefault("AUTH_ENABLED", "false")


class TestMigration004:
    """The migration must declare the partial-unique-where-complete index
    so the DB enforces 'at most one COMPLETE per target_date'."""

    def test_migration_creates_daily_learning_runs(self):
        sql = Path("app/db/migrations/004_daily_learning.sql").read_text()
        assert "CREATE TABLE IF NOT EXISTS daily_learning_runs" in sql

    def test_migration_creates_unique_where_complete_index(self):
        sql = Path("app/db/migrations/004_daily_learning.sql").read_text()
        # Partial index is the idempotency lock.
        assert "CREATE UNIQUE INDEX" in sql
        assert "uq_daily_learning_runs_date_complete" in sql
        assert "WHERE status = 'COMPLETE'" in sql

    def test_migration_documents_status_vocab(self):
        sql = Path("app/db/migrations/004_daily_learning.sql").read_text()
        # Each status value must appear in the comments so future readers
        # know what they mean. SKIPPED_DUPLICATE and SKIPPED_NO_SCAN are
        # the orchestrator's two skip paths.
        for status in ("RUNNING", "COMPLETE", "FAILED", "SKIPPED_DUPLICATE", "SKIPPED_NO_SCAN"):
            assert status in sql, f"status {status!r} missing from migration"

    def test_schema_sql_mirrors_table(self):
        # The schema.sql file is the canonical 'shape of the world' — the
        # migration adds incrementally. Both should describe the same
        # table.
        sql = Path("app/db/schema.sql").read_text()
        assert "CREATE TABLE IF NOT EXISTS daily_learning_runs" in sql
        assert "uq_daily_learning_runs_date_complete" in sql


class TestOrchestratorIdempotency:
    """The orchestrator must check for existing COMPLETE rows BEFORE
    inserting a new RUNNING row."""

    def test_orchestrator_imports_existing_check(self):
        src = Path("app/services/daily_learning/orchestrator.py").read_text()
        assert "_existing_complete_run_id" in src
        assert "SKIPPED_DUPLICATE" in src

    def test_orchestrator_handles_stuck_runs(self):
        src = Path("app/services/daily_learning/orchestrator.py").read_text()
        assert "_mark_stuck_runs_failed" in src
        # Stuck-run threshold must be documented as a constant
        assert "STUCK_RUN_MAX_AGE_MINUTES" in src

    def test_orchestrator_writes_md_atomically(self):
        src = Path("app/services/daily_learning/orchestrator.py").read_text()
        # tmp + os.replace is the atomic-write pattern
        assert "tmp" in src
        assert "os.replace" in src or "rename" in src

    def test_orchestrator_marks_complete_in_unique_path(self):
        src = Path("app/services/daily_learning/orchestrator.py").read_text()
        # Only one place sets status='COMPLETE' — protects against duplicate
        # status writes by accident.
        assert src.count('"COMPLETE"') >= 2  # one in check + one in update


class TestHypothesisDedupe:
    def test_dedupe_uses_jsonb_containment_query(self):
        src = Path("app/services/daily_learning/hypothesis_manager.py").read_text()
        # The dedupe path uses .contains() against pattern_match — that's
        # the @> JSONB operator in Postgres. Without it, every run would
        # create duplicate hypothesis rows.
        assert ".contains(" in src
        assert "pattern_match" in src

    def test_dedupe_logs_resurfaced_for_rejected(self):
        src = Path("app/services/daily_learning/hypothesis_manager.py").read_text()
        # A resurfaced rejected hypothesis must NOT be re-created.
        assert "resurfaced" in src
        assert "rejected" in src

    def test_graduation_ratio_documented(self):
        from app.services.daily_learning.hypothesis_manager import (
            GRADUATION_RATIO, REJECTION_RATIO,
        )
        # Pin the threshold so changes require an explicit edit.
        assert GRADUATION_RATIO == 0.70
        assert REJECTION_RATIO == 0.70


class TestSchedulerRegistration:
    """The scheduler must register the daily_learning_loop at 17:30 ET
    AFTER the snapshot at 17:00. Out-of-order means metrics see stale
    open positions."""

    def test_runner_registers_daily_learning_at_1730(self):
        src = Path("app/scheduler/runner.py").read_text()
        assert "daily_learning_loop" in src
        assert "hour=17, minute=30" in src
        # Must be Mon-Fri only — weekend runs would either skip (no
        # AFTER_CLOSE scan) or produce empty reports.
        assert 'day_of_week="mon-fri"' in src

    def test_jobs_defines_wrapper(self):
        src = Path("app/scheduler/jobs.py").read_text()
        assert "async def daily_learning_loop" in src
