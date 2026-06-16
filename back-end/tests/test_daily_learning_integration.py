"""Lightweight integration tests for the daily_learning package wiring.

These tests verify that:
  - The package imports cleanly
  - The digest renderer doesn't crash on empty inputs (zero-finding day)
  - The CLI is invocable as a module
  - The Finding/CohortFinding objects round-trip through the digest
"""

import os
import sys
from datetime import datetime, timezone

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("BRAIN_TOKEN_SECRET", "test-brain-secret-32chars-min-len-test")
os.environ.setdefault("AUTH_ENABLED", "false")


class TestPackageImports:
    def test_top_level_run_daily_learning(self):
        from app.services.daily_learning import run_daily_learning
        assert callable(run_daily_learning)

    def test_submodules_import(self):
        # Each module should be importable on its own.
        from app.services.daily_learning import (  # noqa: F401
            cohort_analyzer,
            digest,
            explicit_patterns,
            hypothesis_manager,
            metrics,
            orchestrator,
        )


class TestDigestOnEmptyInputs:
    """The heartbeat fires every day, including days with zero findings.
    The renderers must not blow up on empty inputs."""

    def _empty_metrics(self):
        return {
            "target_date": "2026-06-04",
            "closes": {
                "count": 0, "wins": 0, "losses": 0, "net_pnl": 0.0,
                "by_exit_reason": {}, "list": [],
            },
            "entries": {
                "count": 0, "by_tier": {}, "by_style": {}, "list": [],
            },
            "wallet": {
                "cumulative_realized": 0.0, "daily_pnl": 0.0, "daily_pct": 0.0,
                "rolling_7d_pnl": 0.0, "rolling_7d_pct": 0.0,
                "rolling_30d_pnl": 0.0, "rolling_30d_pct": 0.0,
            },
            "open": {"count": 0, "deployed_usd": 0.0, "unrealized_pnl": 0.0},
            "regime": None,
            "warning": None,
            "total_closes_all_time": 0,
        }

    def test_md_report_renders_with_empty_inputs(self):
        from app.services.daily_learning.digest import render_md_report
        now = datetime.now(timezone.utc)
        md = render_md_report(
            metrics=self._empty_metrics(),
            cohorts=[],
            patterns=[],
            new_hypothesis_summary={
                "created": [], "skipped_existing_active": [], "resurfaced_rejected": []
            },
            hypothesis_actions={"graduated": [], "rejected": [], "inconclusive": []},
            suggestions=[],
            run_id="abcd-test",
            started_at=now,
            completed_at=now,
        )
        assert isinstance(md, str)
        assert "Daily Learning Report — 2026-06-04" in md
        # Bold markdown wraps the label
        assert "**Closes:** 0" in md
        assert "_No cohort drift flagged._" in md

    def test_telegram_digest_zero_findings_is_short(self):
        from app.services.daily_learning.digest import render_telegram_digest
        d = render_telegram_digest(
            metrics=self._empty_metrics(),
            findings=[],
            top_findings_count=2,
            md_relative_path="docs/daily-reports/2026-06-04.md",
        )
        assert "Daily Learning — 2026-06-04" in d
        assert "0 findings — all clear" in d
        # heartbeat should be ~250 chars
        assert len(d) < 400


class TestDigestWithFindings:
    def test_telegram_digest_caps_at_top_n(self):
        from app.services.daily_learning.digest import render_telegram_digest
        from app.services.daily_learning.explicit_patterns import Finding

        findings = [
            Finding(code="A", severity="WARN", headline=f"h{i}", body=f"b{i}")
            for i in range(5)
        ]
        d = render_telegram_digest(
            metrics={
                "target_date": "2026-06-04",
                "closes": {"count": 1, "wins": 0, "losses": 1, "net_pnl": -10.0,
                           "by_exit_reason": {}, "list": []},
                "wallet": {"cumulative_realized": 100.0, "daily_pnl": -10.0,
                           "daily_pct": -1.0, "rolling_7d_pnl": 0, "rolling_7d_pct": 0,
                           "rolling_30d_pnl": 0, "rolling_30d_pct": 0},
            },
            findings=findings,
            top_findings_count=2,
        )
        assert "5 findings detected" in d
        # Only the top 2 should be inlined
        assert "h0" in d
        assert "h1" in d
        assert "h2" not in d
        # The rest are summarized
        assert "+3 more" in d


class TestCliInvocable:
    def test_cli_main_function_exists(self):
        from app.services.daily_learning.cli import main
        assert callable(main)

    def test_cli_help_doesnt_raise(self):
        # argparse exits 0 on --help; capture SystemExit
        from app.services.daily_learning.cli import main
        try:
            main(["--help"])
        except SystemExit as e:
            assert e.code == 0
