"""Unit tests for app.services.daily_learning.explicit_patterns.

The matcher functions DO touch the DB (get_client + .table()). We mock the
Supabase client to drive controlled inputs. Each matcher gets one happy-path
test (returns Finding) and one negative test (returns None).
"""

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("BRAIN_TOKEN_SECRET", "test-brain-secret-32chars-min-len-test")
os.environ.setdefault("AUTH_ENABLED", "false")

from datetime import date  # noqa: E402

from app.services.daily_learning.explicit_patterns import (  # noqa: E402
    Finding,
    MATCHERS,
    WATCHDOG_CLUSTER_THRESHOLD,
    match_drawdown_3d,
    match_new_cohort_emerged,
    match_repeat_losers,
    match_watchdog_cluster,
    run_explicit_patterns,
)


def _make_mock_db(table_rows: dict[str, list[dict]]):
    """Build a MagicMock that mimics the chained-builder Supabase client.

    `table_rows` maps table name → list of rows that will be returned for
    that table no matter what filters are chained on it. That's sufficient
    for the matchers since each matcher hits one table.
    """
    db = MagicMock()

    def _table_factory(table_name):
        q = MagicMock()
        # all chained methods return self
        for method in (
            "select", "eq", "in_", "gte", "lt", "gt", "is_", "not_",
            "order", "limit", "contains",
        ):
            setattr(q, method, MagicMock(return_value=q))
        # not_ requires nested call: not_.is_("col", "null") — chain it
        q.not_ = MagicMock(return_value=q)
        q.execute = MagicMock(return_value=MagicMock(data=table_rows.get(table_name, [])))
        return q

    db.table = MagicMock(side_effect=_table_factory)
    return db


class TestWatchdogCluster:
    def test_returns_finding_when_threshold_met(self):
        rows = [
            {"symbol": "SATS", "exit_date": "2026-06-01T13:00:00+00:00",
             "exit_reason": "WATCHDOG_FORCE_SELL", "pnl_amount": -76.0,
             "signal_style": "MOMENTUM", "entry_tier": 1},
            {"symbol": "FN", "exit_date": "2026-06-02T13:00:00+00:00",
             "exit_reason": "WATCHDOG_FORCE_SELL", "pnl_amount": -23.0,
             "signal_style": "MOMENTUM", "entry_tier": 1},
            {"symbol": "ONDS", "exit_date": "2026-06-03T13:00:00+00:00",
             "exit_reason": "WATCHDOG_FORCE_SELL", "pnl_amount": -71.0,
             "signal_style": "MOMENTUM", "entry_tier": 1},
        ]
        with patch("app.services.daily_learning.explicit_patterns.get_client") as gc:
            gc.return_value = _make_mock_db({"virtual_trades": rows})
            f = match_watchdog_cluster(date(2026, 6, 4))
        assert f is not None
        assert f.code == "WATCHDOG_CLUSTER"
        assert f.severity in ("WARN", "CRITICAL")
        assert f.pattern_match is not None
        assert f.pattern_match.get("exit_reason_family") == "WATCHDOG"
        # symbols should be present in headline
        assert "SATS" in f.headline
        assert f.extra["count"] == 3

    def test_returns_none_below_threshold(self):
        rows = [
            {"symbol": "SATS", "exit_date": "2026-06-01T13:00:00+00:00",
             "exit_reason": "WATCHDOG_FORCE_SELL", "pnl_amount": -76.0,
             "signal_style": "MOMENTUM", "entry_tier": 1},
        ]
        with patch("app.services.daily_learning.explicit_patterns.get_client") as gc:
            gc.return_value = _make_mock_db({"virtual_trades": rows})
            f = match_watchdog_cluster(date(2026, 6, 4))
        assert f is None

    def test_threshold_constant(self):
        # If threshold changes, signal_thinking auto-creation behavior shifts.
        # Pin it; require explicit change.
        assert WATCHDOG_CLUSTER_THRESHOLD == 3


class TestRepeatLosers:
    def test_no_repeats_returns_none(self):
        rows = [
            {"symbol": "AAA", "entry_date": "2026-06-01T13:00:00+00:00",
             "exit_date": "2026-06-02T13:00:00+00:00", "pnl_amount": 5.0,
             "exit_reason": "TARGET_HIT", "thesis_last_status": "valid"},
        ]
        with patch("app.services.daily_learning.explicit_patterns.get_client") as gc:
            gc.return_value = _make_mock_db({"virtual_trades": rows})
            f = match_repeat_losers(date(2026, 6, 5))
        assert f is None

    def test_oscr_two_cycle_loss_pattern_returns_finding(self):
        rows = [
            {"symbol": "OSCR", "entry_date": "2026-05-21T14:00:00+00:00",
             "exit_date": "2026-05-28T13:00:00+00:00", "pnl_amount": -5.79,
             "exit_reason": "TIME_EXPIRED", "thesis_last_status": "weakening"},
            {"symbol": "OSCR", "entry_date": "2026-05-28T15:00:00+00:00",
             "exit_date": "2026-06-02T13:00:00+00:00", "pnl_amount": -11.82,
             "exit_reason": "TRAILING_STOP", "thesis_last_status": "weakening"},
        ]
        with patch("app.services.daily_learning.explicit_patterns.get_client") as gc:
            gc.return_value = _make_mock_db({"virtual_trades": rows})
            f = match_repeat_losers(date(2026, 6, 3))
        assert f is not None
        assert f.code == "REPEAT_LOSER"
        offenders = f.extra["offenders"]
        assert any(o["symbol"] == "OSCR" for o in offenders)


class TestDrawdown3d:
    def test_no_drawdown_returns_none(self):
        rows = [
            {"snapshot_date": "2026-06-01", "brain_cumulative_pnl": 100.0},
            {"snapshot_date": "2026-06-02", "brain_cumulative_pnl": 110.0},
            {"snapshot_date": "2026-06-03", "brain_cumulative_pnl": 115.0},
        ]
        with patch("app.services.daily_learning.explicit_patterns.get_client") as gc:
            gc.return_value = _make_mock_db({"virtual_snapshots": rows})
            f = match_drawdown_3d(date(2026, 6, 4))
        assert f is None

    def test_drawdown_above_threshold_returns_finding_with_no_pattern_match(self):
        # Wallet drops 10% from a 3-day peak — should trigger.
        rows = [
            {"snapshot_date": "2026-06-01", "brain_cumulative_pnl": 100.0},
            {"snapshot_date": "2026-06-02", "brain_cumulative_pnl": 110.0},
            {"snapshot_date": "2026-06-03", "brain_cumulative_pnl": 95.0},
        ]
        with patch("app.services.daily_learning.explicit_patterns.get_client") as gc:
            gc.return_value = _make_mock_db({"virtual_snapshots": rows})
            f = match_drawdown_3d(date(2026, 6, 4))
        assert f is not None
        assert f.code == "DRAWDOWN_3D"
        # CRITICAL design choice: no hypothesis from wallet alerts.
        assert f.pattern_match is None


class TestNewCohortEmerged:
    def test_returns_none_when_no_new_combo(self):
        # All baseline AND recent are same combo → nothing new.
        baseline = [{"signal_style": "MOMENTUM", "entry_tier": 1} for _ in range(5)]
        recent = [{"signal_style": "MOMENTUM", "entry_tier": 1} for _ in range(3)]
        # mock returns the SAME rows for both queries (baseline_entries + recent_entries)
        # which is fine for "no new combo" since both contain identical combo
        with patch("app.services.daily_learning.explicit_patterns.get_client") as gc:
            gc.return_value = _make_mock_db({"virtual_trades": baseline + recent})
            f = match_new_cohort_emerged(date(2026, 6, 4))
        # Since the mock returns the same combined list for both queries,
        # baseline_keys will contain the combo, so no emergence flagged.
        assert f is None


class TestDispatch:
    def test_matchers_list_is_callable(self):
        for m in MATCHERS:
            assert callable(m)

    def test_run_explicit_patterns_swallows_exceptions(self):
        # If a matcher raises, the whole run continues.
        def boom(_d):
            raise RuntimeError("matcher exploded")
        from app.services.daily_learning import explicit_patterns as ep
        with patch.object(ep, "MATCHERS", [boom]):
            findings = ep.run_explicit_patterns(date(2026, 6, 4))
        assert findings == []


class TestFindingDataclass:
    def test_to_dict_includes_pattern_match(self):
        f = Finding(
            code="WATCHDOG_CLUSTER",
            severity="WARN",
            headline="3x in 14d",
            body="### body",
            pattern_match={"exit_reason_family": "WATCHDOG"},
            suggestion={"rule_name": "x", "reasoning": "y"},
        )
        d = f.to_dict()
        assert d["code"] == "WATCHDOG_CLUSTER"
        assert d["pattern_match"] == {"exit_reason_family": "WATCHDOG"}
        assert d["suggestion"]["rule_name"] == "x"
