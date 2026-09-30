"""Counterfactual-outcome analytics: calibration, overturns, skip gates, cohorts."""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")

from datetime import datetime, timedelta, timezone

import pytest

from app.services.daily_learning import outcomes as oc
from app.services.daily_learning.digest import (
    outcomes_digest_line,
    render_md_report,
    render_outcomes_section,
)

BASE = datetime(2026, 6, 1, 14, tzinfo=timezone.utc)


def mk(i, **kw):
    """One candidate row; unique symbol per i so dedupe keeps it."""
    return {"symbol": f"S{i}", "signal_at": (BASE + timedelta(minutes=i)).isoformat(), **kw}


# ── dedupe ──────────────────────────────────────────────────────

def test_dedupe_one_obs_per_symbol_per_day():
    rows = [
        {"symbol": "A", "signal_at": "2026-06-01T14:00:00+00:00", "x": 1},
        {"symbol": "A", "signal_at": "2026-06-01T19:00:00+00:00", "x": 2},
        {"symbol": "A", "signal_at": "2026-06-02T14:00:00+00:00", "x": 3},
        {"symbol": "B", "signal_at": "2026-06-01T14:00:00+00:00", "x": 4},
    ]
    kept = oc.dedupe_symbol_day(rows)
    assert [r["x"] for r in kept] == [1, 4, 3]


def test_summarize_guard_and_ci_sign():
    small = oc.summarize([0.05] * 10 + [0.06] * 10)
    assert small["n"] == 20 and not small["sufficient"] and small["excludes_zero"] is None
    big = oc.summarize([0.04 + (i % 5) * 0.01 for i in range(40)])
    assert big["sufficient"] and big["excludes_zero"] == "pos"
    lo, hi = big["ci"]
    assert lo <= big["mean"] <= hi
    noisy = oc.summarize([(-1) ** i * 0.05 for i in range(40)])
    assert noisy["excludes_zero"] is None


# ── calibration ─────────────────────────────────────────────────

def test_calibration_buckets_and_brier():
    rows = []
    i = 0
    # 20 rows at p=0.55, 60% winners; 20 rows at p=0.75, 75% winners; 5 at p=0.95 (hidden)
    for p, n, wins in ((0.55, 20, 12), (0.75, 20, 15), (0.95, 5, 5)):
        for k in range(n):
            r = 0.02 if k < wins else -0.02
            rows.append(mk(i, p_win=p, fwd_ret_5d=r, excess_ret_5d=r - 0.01))
            i += 1
    cal = oc.calibration_table(rows, 5)
    assert cal["n"] == 45
    labels = [b["bucket"] for b in cal["buckets"]]
    assert labels == ["0.5-0.6", "0.7-0.8"]
    assert cal["hidden_buckets"] == 1
    b1 = cal["buckets"][0]
    assert b1["n"] == 20 and b1["win_rate"] == pytest.approx(0.6)
    assert b1["win_ci"][0] < 0.6 < b1["win_ci"][1]
    assert b1["excess_win_rate"] == pytest.approx(0.6)  # 0.02-0.01 > 0, -0.03 < 0
    # Brier by hand
    exp = (12 * (0.55 - 1) ** 2 + 8 * 0.55 ** 2 + 15 * (0.75 - 1) ** 2 + 5 * 0.75 ** 2
           + 5 * (0.95 - 1) ** 2) / 45
    assert cal["overall"]["brier"] == pytest.approx(exp)
    assert oc.brier_score([(1.0, 1), (0.0, 0)]) == 0.0


def test_calibration_overall_withheld_below_30():
    rows = [mk(i, p_win=0.65, fwd_ret_5d=0.01) for i in range(25)]
    cal = oc.calibration_table(rows, 5)
    assert cal["overall"] is None and len(cal["buckets"]) == 1


def test_calibration_ignores_unfilled_and_missing_p_win():
    rows = [mk(0, p_win=None, fwd_ret_5d=0.1), mk(1, p_win=0.6, fwd_ret_5d=None)]
    assert oc.calibration_table(rows, 5)["n"] == 0


# ── Sonnet vs Opus ──────────────────────────────────────────────

def test_overturn_insufficient_data_guard():
    rows = ([mk(i, decision_overturned=True, fwd_ret_10d=0.05, excess_ret_10d=0.04) for i in range(12)]
            + [mk(100 + i, decision_overturned=False, fwd_ret_10d=0.01, excess_ret_10d=0.0) for i in range(40)]
            + [mk(200 + i, decision_overturned=None, excess_ret_10d=0.5) for i in range(40)])
    st = oc.overturn_stats(rows, 10)
    e = st["metrics"]["excess_ret"]
    assert e["vetoed"]["n"] == 12 and e["confirmed"]["n"] == 40
    assert e["verdict"] == "insufficient data (n=12 vetoed / 40 confirmed)"
    assert e["direction"] is None and e["diff_ci"] is None


def test_overturn_veto_costs_when_vetoed_outperform():
    rows = ([mk(i, decision_overturned=True, fwd_ret_10d=0.06 + (i % 3) * 0.01,
                excess_ret_10d=0.05 + (i % 3) * 0.01) for i in range(35)]
            + [mk(100 + i, decision_overturned=False, fwd_ret_10d=(i % 3) * 0.01 - 0.01,
                  excess_ret_10d=(i % 3) * 0.01 - 0.02) for i in range(35)])
    st = oc.overturn_stats(rows, 10)
    e = st["metrics"]["excess_ret"]
    assert e["direction"] == "veto_costs"
    assert e["diff"] == pytest.approx(-0.07)
    assert "costing" in e["verdict"]
    sugg = oc.outcome_suggestions({"horizon": 10, "overturn": st})
    assert [s["rule_name"] for s in sugg] == ["outcome_decision_model_veto"]


def test_overturn_veto_helps_no_suggestion():
    rows = ([mk(i, decision_overturned=True, excess_ret_10d=-0.05 + (i % 2) * 0.01) for i in range(30)]
            + [mk(100 + i, decision_overturned=False, excess_ret_10d=0.03 + (i % 2) * 0.01) for i in range(30)])
    st = oc.overturn_stats(rows, 10)
    assert st["metrics"]["excess_ret"]["direction"] == "veto_helps"
    assert oc.outcome_suggestions({"horizon": 10, "overturn": st}) == []


# ── skip-reason effectiveness ───────────────────────────────────

def test_normalize_skip_reason():
    assert oc.normalize_skip_reason("rr_below_min_1.40") == "rr_below_min"
    assert oc.normalize_skip_reason("max_open_positions_8") == "max_open_positions"
    assert oc.normalize_skip_reason("reentry_cooldown_3d") == "reentry_cooldown"
    assert oc.normalize_skip_reason("sector_cap_technology") == "sector_cap"
    assert oc.normalize_skip_reason("short:rr_below_min_2") == "short:rr_below_min"
    assert oc.normalize_skip_reason(None) == "unknown"


def test_skip_reason_effectiveness_flags_costly_gate():
    rows = (
        # costly gate: skipped names beat SPY consistently
        [mk(i, brain_decision="SKIP", skip_reason=f"rr_below_min_1.{i % 5}",
            excess_ret_10d=0.03 + (i % 4) * 0.005) for i in range(35)]
        # protective gate
        + [mk(100 + i, brain_decision="SKIP", skip_reason="not_ai_buy_rejected_sell",
              excess_ret_10d=-0.04 + (i % 4) * 0.005) for i in range(35)]
        # small gate: never flagged
        + [mk(200 + i, brain_decision="SKIP", skip_reason="sector_cap_energy",
              excess_ret_10d=0.10) for i in range(8)]
        + [mk(300 + i, brain_decision="ENTER", excess_ret_10d=0.01) for i in range(5)]
        # unfilled rows ignored
        + [mk(400 + i, brain_decision="SKIP", skip_reason="rr_below_min_1.4", excess_ret_10d=None)
           for i in range(50)]
    )
    eff = oc.skip_reason_effectiveness(rows, 10)
    g = {x["reason"]: x for x in eff["gates"]}
    assert g["rr_below_min"]["n"] == 35 and g["rr_below_min"]["verdict"] == "costing"
    assert g["not_ai_buy_rejected_sell"]["verdict"] == "protective"
    assert g["sector_cap"]["verdict"] == "insufficient data (n=8)"
    assert eff["entered"]["n"] == 5
    sugg = oc.outcome_suggestions({"horizon": 10, "skip_reasons": eff})
    assert [s["rule_name"] for s in sugg] == ["outcome_skip_gate_rr_below_min"]
    assert sugg[0]["proposed"]["ci"][0] > 0  # JSON-able list


def test_repeated_same_day_signals_do_not_inflate_n():
    # 40 scans of the same symbol on one day = 1 observation
    rows = [{"symbol": "AAA", "signal_at": (BASE + timedelta(minutes=i)).isoformat(),
             "brain_decision": "SKIP", "skip_reason": "rr_below_min_1.4", "excess_ret_10d": 0.05}
            for i in range(40)]
    eff = oc.skip_reason_effectiveness(rows, 10)
    assert eff["gates"][0]["n"] == 1
    assert oc.outcome_suggestions({"horizon": 10, "skip_reasons": eff}) == []


# ── AI-status cohorts + full report ─────────────────────────────

def test_ai_status_cohorts_and_suggestion():
    rows = ([mk(i, ai_status="validated", excess_ret_5d=-0.01, excess_ret_10d=-0.03 + (i % 3) * 0.005,
                excess_ret_20d=None) for i in range(40)]
            + [mk(100 + i, ai_status="skipped", excess_ret_10d=(-1) ** i * 0.02) for i in range(40)])
    c = oc.ai_status_cohorts(rows)["cohorts"]
    assert [x["ai_status"] for x in c] == ["validated", "skipped"]
    assert c[0]["excess_10d"]["excludes_zero"] == "neg"
    assert c[0]["excess_20d"]["n"] == 0
    report = oc.build_outcome_report(rows, 10)
    names = [s["rule_name"] for s in oc.outcome_suggestions(report)]
    assert names == ["outcome_ai_status_validated"]


def test_report_and_digest_render():
    rows = ([mk(i, brain_decision="SKIP", skip_reason="rr_below_min_1.4", ai_status="rejected",
                p_win=0.62, fwd_ret_5d=0.02, excess_ret_5d=0.01, excess_ret_10d=0.03 + (i % 3) * 0.01,
                decision_overturned=bool(i % 2), fwd_ret_10d=0.03,
                fwd_ret_20d=0.04, excess_ret_20d=0.02)  # p_win is graded at 20d
             for i in range(40)])
    report = oc.build_outcome_report(rows)
    md = render_outcomes_section(report)
    assert "Skip-reason effectiveness" in md and "rr_below_min" in md and "costing" in md
    assert "p_win calibration" in md and "0.6-0.7" in md
    assert "insufficient data (n=20 vetoed / 20 confirmed)" in md
    assert "AI-status cohorts" in md and "rejected" in md
    assert "costly gates: rr_below_min" in outcomes_digest_line(report)
    assert "unavailable" in render_outcomes_section(None)
    assert "failed" in render_outcomes_section({"error": "boom"})


def test_md_report_includes_outcomes_section():
    now = datetime.now(timezone.utc)
    metrics = {
        "target_date": "2026-09-28",
        "closes": {"count": 0, "wins": 0, "losses": 0, "net_pnl": 0.0, "list": []},
        "entries": {"count": 0, "by_tier": {}, "by_style": {}, "list": []},
        "wallet": {"cumulative_realized": 0.0, "daily_pct": 0.0,
                   "rolling_7d_pct": 0.0, "rolling_30d_pct": 0.0},
        "open": {"count": 0, "deployed_usd": 0.0, "unrealized_pnl": 0.0},
    }
    md = render_md_report(
        metrics=metrics, cohorts=[], patterns=[],
        new_hypothesis_summary={}, hypothesis_actions={}, suggestions=[],
        run_id="r", started_at=now, completed_at=now,
        outcomes=oc.build_outcome_report([]),
    )
    assert "## Candidate outcomes (counterfactual)" in md
    # backwards compatible without the kwarg
    md2 = render_md_report(
        metrics=metrics, cohorts=[], patterns=[],
        new_hypothesis_summary={}, hypothesis_actions={}, suggestions=[],
        run_id="r", started_at=now, completed_at=now,
    )
    assert "unavailable" in md2


def test_outcome_suggestions_deduped_against_pending(monkeypatch):
    from app.services.daily_learning import orchestrator
    from tests.brain_fakes import FakeDB

    db = FakeDB({"brain_suggestions": [
        {"rule_name": "outcome_skip_gate_rr_below_min", "status": "PENDING"}]})
    monkeypatch.setattr(orchestrator, "get_client", lambda: db)
    report = {"horizon": 10, "skip_reasons": {"gates": [
        {"reason": "rr_below_min", "verdict": "costing", "n": 40, "mean": 0.03, "ci": (0.01, 0.05)},
        {"reason": "sector_cap", "verdict": "costing", "n": 40, "mean": 0.02, "ci": (0.005, 0.04)},
    ]}}
    ins = orchestrator._insert_outcome_suggestions(report, {})
    assert [r["rule_name"] for r in ins] == ["outcome_skip_gate_sector_cap"]
    new = db.rows("brain_suggestions")[1:]
    assert len(new) == 1
    assert new[0]["suggestion_type"] == "INVESTIGATE" and new[0]["status"] == "PENDING"
    assert orchestrator._insert_outcome_suggestions({"error": "x"}, {}) == []
