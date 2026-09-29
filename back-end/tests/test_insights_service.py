"""insights_service: funnel, verdict, backtest parsing, sanitizer, trail."""

import json
import math
from datetime import datetime, timedelta, timezone

import pytest

from app.services import insights_service as svc


# ── sanitizer ────────────────────────────────────────────────

def test_clean_replaces_nan_and_tuples():
    out = svc._clean({"a": float("nan"), "b": (1.0, float("inf")), "c": [{"d": -float("inf")}], "e": 1.5})
    assert out == {"a": None, "b": [1.0, None], "c": [{"d": None}], "e": 1.5}
    json.dumps(out, allow_nan=False)


# ── funnel ───────────────────────────────────────────────────

def _sig(sym, **kw):
    return {"symbol": sym, "ai_status": "skipped", "technical_data": {}, **kw}


def test_funnel_counts():
    signals = [
        _sig("A", ai_status="validated", ai_signal="BUY", routine_ai_signal="BUY", decision_overturned=False,
             technical_data={"_tech_filter": {"passed": True, "reasons": []}}),
        _sig("B", ai_status="rejected", ai_signal="HOLD", routine_ai_signal="BUY", decision_overturned=True,
             technical_data={"_tech_filter": {"passed": True, "reasons": []}}),
        _sig("C", ai_status="rejected", ai_signal="HOLD", routine_ai_signal="HOLD",
             technical_data={"_tech_filter": {"passed": True, "reasons": []}}),
        _sig("D", technical_data={"_tech_filter": {"passed": False, "reasons": ["below_sma200"]}}),
    ]
    decisions = [{"symbol": "A", "decision": "ENTER"}, {"symbol": "B", "decision": "SKIP"}]
    f = svc.build_funnel({"tickers_scanned": 281}, signals, decisions)
    assert f == {"universe": 281, "candidates": 4, "passed_filter": 3, "ai_checked": 3,
                 "routine_buy": 2, "decision_confirmed": 1, "bought": 1}


def test_funnel_passed_filter_null_without_tech_filter_and_routine_fallback():
    signals = [_sig("A", ai_status="validated", ai_signal="BUY"), _sig("B")]
    f = svc.build_funnel(None, signals, [])
    assert f["passed_filter"] is None
    assert f["universe"] is None
    assert f["routine_buy"] == 1  # routine_ai_signal column absent -> ai_signal


def test_decisions_sorted_enter_first_then_pwin():
    signals = [
        _sig("LOW", ai_status="rejected", ai_signal="HOLD", p_win=0.4),
        _sig("TECH"),
        _sig("HIGH", ai_status="validated", ai_signal="BUY", p_win=0.6, risk_reward=2.3),
        _sig("BUY", ai_status="validated", ai_signal="BUY", p_win=0.5),
    ]
    decisions = [
        {"symbol": "BUY", "decision": "ENTER", "reason": "ai_buy", "details": {"rr": 2.1, "alloc_usd": 400}},
        {"symbol": "HIGH", "decision": "SKIP", "reason": "rr_below_min_1.40", "details": {}},
    ]
    rows = svc.build_decisions(signals, decisions)
    assert [r["symbol"] for r in rows] == ["BUY", "HIGH", "LOW", "TECH"]
    assert rows[0]["reason"]["code"] == "entered" and rows[0]["rr"] == 2.1
    assert rows[1]["rr"] == 2.3  # falls back to signals.risk_reward
    assert rows[3]["decision"] is None and rows[3]["reason"] is None


def test_positions_progress_clamped():
    now = datetime(2026, 9, 28, tzinfo=timezone.utc)
    trades = [{"id": 1, "symbol": "X", "entry_price": 100, "stop_loss": 90, "target_price": 120,
               "entry_date": (now - timedelta(days=3)).isoformat()},
              {"id": 2, "symbol": "Y", "entry_price": 100, "stop_loss": 90, "target_price": 120}]
    out = svc.build_positions(trades, {"X": 105.0, "Y": None}, now)
    assert out[0]["progress"] == 0.5 and out[0]["pnl_pct"] == 5.0 and out[0]["days_held"] == 3
    assert out[1]["progress"] is None and out[1]["pnl_pct"] is None
    assert svc.build_positions(trades[:1], {"X": 130.0}, now)[0]["progress"] == 1.0
    assert svc.build_positions(trades[:1], {"X": 80.0}, now)[0]["progress"] == 0.0


def test_status_without_breaker_column():
    wallet = {"balance": 4000, "collateral_reserved": 0, "total_deposited": 5000, "total_withdrawn": 0,
              "peak_equity": 5100, "created_at": "2026-09-20T00:00:00+00:00"}
    trades = [{"symbol": "X", "entry_price": 100, "position_size_usd": 1000}]
    snaps = [{"snapshot_date": "2026-09-20", "spy_price": 500}, {"snapshot_date": "2026-09-27", "spy_price": 505}]
    st = svc.build_status(wallet, trades, {"X": 110.0}, snaps, None)
    assert st["equity"] == 5100.0
    assert st["change_pct"] == 2.0
    assert st["spy_change_pct"] == 1.0
    assert st["invested_usd"] == 1000.0
    assert st["drawdown_pct"] == 0.0
    assert st["breaker"]["state"] == "normal" and st["breaker"]["tripped_at"] is None


# ── verdict ──────────────────────────────────────────────────

@pytest.mark.parametrize("stat,expected", [
    ({"n": 12, "excludes_zero": None}, "insufficient"),
    ({"n": 40, "excludes_zero": "pos"}, "positive"),
    ({"n": 40, "excludes_zero": "neg"}, "negative"),
    ({"n": 40, "excludes_zero": None}, "inconclusive"),
])
def test_verdict(stat, expected):
    assert svc.verdict_from_summary(stat, 30) == expected


def _outcome(i, excess, decision="ENTER", **kw):
    return {"symbol": f"S{i}", "signal_at": f"2026-08-{(i % 28) + 1:02d}T15:00:00+00:00",
            "brain_decision": decision, "excess_ret_10d": excess, "fwd_ret_10d": excess,
            "fwd_ret_5d": excess, "p_win": 0.6, "ai_status": "validated", **kw}


def test_build_performance_insufficient_and_positive():
    few = [_outcome(i, 0.01) for i in range(10)]
    p = svc.build_performance(few, [], 2)
    assert p["verdict"]["state"] == "insufficient" and p["verdict"]["n"] == 10
    assert p["counts"] == {"tracked": 10, "filled": 10, "validated_buys": 10, "closed_trades": 2}
    json.dumps(p, allow_nan=False)

    # 40 distinct symbols, all clearly positive
    many = [dict(_outcome(i, 0.02 + (i % 3) * 0.001), symbol=f"P{i}") for i in range(40)]
    p = svc.build_performance(many, [], 0)
    assert p["verdict"]["state"] == "positive"
    keys = [c["key"] for c in p["cohorts"]]
    assert keys == ["entered", "vetoed", "rejected", "ai_not_called"]


def test_skip_reason_verdict_normalized():
    rows = [_outcome(i, 0.01, decision="SKIP", skip_reason="rr_below_min_1.20") for i in range(5)]
    p = svc.build_performance(rows, [], 0)
    assert p["skip_reasons"][0]["reason"] == "rr_below_min"
    assert p["skip_reasons"][0]["verdict"] == "insufficient"


def test_equity_curve_normalized():
    snaps = [{"snapshot_date": "2026-09-20", "brain_equity": 5000, "spy_price": 500},
             {"snapshot_date": "2026-09-21", "brain_equity": 5100, "spy_price": 490}]
    ec = svc.build_equity_curve(snaps)
    assert ec["points"][0] == {"date": "2026-09-20", "signa": 0.0, "spy": 0.0, "xiu": None}
    assert ec["signa_pct"] == 2.0 and ec["spy_pct"] == -2.0 and ec["xiu_pct"] is None


# ── backtest parsing ─────────────────────────────────────────

def _report(name, gen, total):
    return {
        "meta": {"name": name, "generated_at": gen, "start": "2021-01-01", "end": "2026-09-01",
                 "entry_rule": "rule", "n_symbols": 281},
        "portfolio": {"equity": {"total_return_pct": total, "cagr_pct": 1.0, "max_drawdown_pct": -5.0,
                                 "sharpe": float("nan")}, "trades": {"trades": 12}},
        "benchmarks": {"SPY": {"available": True, "total_return_pct": 118.6, "cagr_pct": 14.8,
                               "max_drawdown_pct": -24.5}},
        "study": {"n_trades": 100, "by_band": {"<50": {"trades": 60, "avg_excess_vs_spy_pct": 0.02},
                                               "50-54": {"trades": 40, "avg_excess_vs_spy_pct": -0.5}},
                  "by_tech_filter": {"PASS": {"trades": 70}, "FAIL": {"trades": 30}},
                  "by_tech_filter_reason": {"below_sma200": {"trades": 20}}},
        "caveats": ["**TECH ONLY.** x"],
    }


def test_parse_backtests(tmp_path):
    for name, gen, total in (("old", "2026-09-01 00:00 UTC", -0.7), ("new", "2026-09-28 00:00 UTC", 5.0)):
        (tmp_path / name).mkdir()
        (tmp_path / name / "report.json").write_text(json.dumps(_report(name, gen, total)).replace("NaN", "NaN"))
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "report.json").write_text("{not json")
    out = svc.parse_backtests(tmp_path)
    assert [r["name"] for r in out["runs"]] == ["new", "old"]
    assert out["runs"][0]["sharpe"] is None and out["runs"][0]["trades"] == 12
    latest = out["latest"]
    assert latest["name"] == "new"
    assert [b["band"] for b in latest["by_band"]] == ["<50", "50-54"]
    assert [b["band"] for b in latest["by_filter"]] == ["PASS", "FAIL", "FAIL:below_sma200"]
    assert latest["benchmarks"]["SPY"]["total_return_pct"] == 118.6
    assert latest["caveats"] == ["TECH ONLY. x"]
    json.dumps(out, allow_nan=False)


def test_parse_backtests_ignores_symlink_escape(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "report.json").write_text(json.dumps(_report("evil", "2030-01-01", 1.0)))
    base = tmp_path / "base"
    base.mkdir()
    (base / "link").symlink_to(outside, target_is_directory=True)
    assert svc.parse_backtests(base) == {"runs": [], "latest": None}


def test_parse_backtests_missing_dir(tmp_path):
    assert svc.parse_backtests(tmp_path / "nope") == {"runs": [], "latest": None}


def test_real_reports_parse():
    out = svc.parse_backtests()
    json.dumps(out, allow_nan=False)


# ── trail ────────────────────────────────────────────────────

BASE_SIG = {"id": "s1", "symbol": "NVDA", "scan_id": "sc1", "created_at": "2026-09-28T14:00:00+00:00",
            "ai_status": "validated", "ai_signal": "BUY", "confidence": 72, "p_win": 0.63,
            "reasoning": "opus says buy", "score": 71, "price_at_signal": 198.3,
            "technical_data": {"last_close": 198.3, "sma_50": 187.0, "sma_200": 178.0, "rsi": 61,
                               "dollar_volume_avg_20": 3.2e10,
                               "_tech_filter": {"passed": True, "reasons": []}},
            "fundamental_data": {"sector": "Technology", "company_name": "NVIDIA"},
            "grok_data": {"summary": "s", "score": 64, "label": "bullish",
                          "citations": ["https://reuters.com/a", "javascript:alert(1)"],
                          "red_flags": [{"text": "suit", "url": "https://x.com/1", "severity": "low"}],
                          "_decision": "confirmed"}}


def test_model_verdicts_confirmed():
    sig = {**BASE_SIG, "routine_ai_signal": "BUY", "decision_overturned": False}
    routine, dec = svc.model_verdicts(sig)
    assert routine == {"signal": "BUY", "confidence": None, "p_win": None, "reasoning": None}
    assert dec["status"] == "confirmed" and dec["p_win"] == 0.63 and dec["reasoning"] == "opus says buy"


def test_model_verdicts_vetoed_not_escalated_unavailable_skipped():
    _, dec = svc.model_verdicts({**BASE_SIG, "ai_signal": "HOLD", "routine_ai_signal": "BUY",
                                 "decision_overturned": True})
    assert dec["status"] == "vetoed" and dec["signal"] == "HOLD"
    g = {k: v for k, v in BASE_SIG["grok_data"].items() if k != "_decision"}
    routine, dec = svc.model_verdicts({**BASE_SIG, "grok_data": g, "decision_overturned": None})
    assert routine["confidence"] == 72 and dec is None
    routine, dec = svc.model_verdicts({**BASE_SIG, "grok_data": {**g, "_decision": "unavailable"}})
    assert routine["signal"] == "BUY" and dec["status"] == "unavailable" and dec["signal"] is None
    assert svc.model_verdicts({**BASE_SIG, "grok_data": {}, "ai_status": "skipped"}) == (None, None)


def test_build_trail_full():
    decision = {"decision": "ENTER", "reason": "ai_buy", "decided_at": "2026-09-28T14:01:00+00:00",
                "details": {"fill": 198.5, "stop": 182.4, "target": 214.6, "rr": 2.1, "alloc_usd": 412,
                            "risk_usd": 50.61, "sector": "Technology", "trade_id": None,
                            "correlation": {"max_corr": 0.46, "max_corr_symbol": "AVGO", "corr": {"AVGO": 0.46},
                                            "rule": None, "max_pairwise": 0.8}}}
    open_trades = [{"symbol": "AVGO", "sector": "Technology"}]
    tr = svc.build_trail(BASE_SIG, decision, None, None, open_trades, 5061.0)
    assert tr["decision"]["reason"]["code"] == "entered"
    assert tr["tech_filter"]["passed"] is True
    assert {c["key"] for c in tr["tech_filter"]["checks"]} >= {"above_sma200", "rsi", "liquidity", "blockers"}
    assert all(c["ok"] for c in tr["tech_filter"]["checks"])
    assert tr["grok"]["citations"] == ["https://reuters.com/a"]
    assert tr["grok"]["red_flags"][0]["severity"] == "low"
    assert tr["order"]["risk_pct"] == round(50.61 / 5061 * 100, 2)
    assert tr["order"]["slippage_bps"] > 0
    assert tr["correlation"]["max_corr_symbol"] == "AVGO"
    assert tr["sector_exposure"] == {"sector": "Technology", "held": 1, "max": svc.settings.brain_max_per_sector}
    hz = tr["outcomes"]["horizons"]
    assert [h["days"] for h in hz] == [5, 10, 20]
    assert hz[0]["due_date"] == "2026-10-05" and hz[0]["excess_ret_frac"] is None


def test_build_trail_minimal_returns_nulls():
    sig = {"id": "s2", "symbol": "XYZ", "created_at": "2026-09-28T14:00:00+00:00", "ai_status": "skipped",
           "technical_data": {}, "grok_data": {}}
    tr = svc.build_trail(sig, None, None, None, [], None)
    assert tr["decision"] is None and tr["tech_filter"] is None and tr["grok"] is None
    assert tr["routine"] is None and tr["order"] is None and tr["correlation"] is None
    assert tr["sector_exposure"] is None
    assert math.isnan(float("nan"))  # sanity
