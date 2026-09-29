"""Technical score → pass/fail technical FILTER for brain entry.

Evidence (docs/backtests/live-2021-2026/report.md, 8,996 study trades): a
higher compute_score did not predict better returns, so the brain gates an
AI BUY on `technical_filter` and orders candidates by AI p_win / confidence.
"""

from tests.brain_fakes import FakeDB, patch_db, wallet_row  # noqa: I001

import pytest

from app.ai.signal_engine import technical_filter
from app.core.config import settings
from app.scanners import indicators
from app.services import scan_service
from app.services import virtual_portfolio as vp
from backtest.run_backtest import run
from backtest.report import render_markdown
from backtest.portfolio import SimConfig
from backtest.signals import SignalConfig, is_entry
from tests.test_backtest_engine import make_bars, market  # noqa: F401  (fixture)
from tests.test_brain_entry_gate import brain_trades, make_sig, passing_tech


class TestFilterMatrix:
    def test_defaults(self):
        assert settings.brain_entry_mode == "filter"
        assert settings.tech_filter_max_rsi == 75.0
        assert settings.tech_filter_max_ext_sma50_pct == 15.0
        assert settings.tech_filter_min_dollar_volume == 10_000_000
        assert settings.tech_filter_min_dollar_volume_crypto == 50_000_000

    def test_clean_uptrend_passes(self):
        assert technical_filter(passing_tech(), {}, "STOCK") == (True, [])

    @pytest.mark.parametrize("over,reason", [
        ({"sma_200": None}, "insufficient_history"),
        ({"sma_50": None}, "insufficient_history"),
        ({"last_close": None, "current_price": None}, "insufficient_history"),
        ({"sma_200": 101.0, "sma_50": 102.0}, "below_sma200"),
        ({"sma_50": 90.0, "sma_200": 92.0}, "sma50_below_sma200"),
        ({"rsi": 76.0}, "rsi_overbought"),
        ({"sma_50": 100 / 1.16}, "overextended_vs_sma50"),
        ({"dollar_volume_avg_20": 9_000_000}, "low_liquidity"),
        ({"dollar_volume_avg_20": None, "volume_avg_20": None, "volume_avg": None}, "no_liquidity_data"),
    ])
    def test_each_condition_fails(self, over, reason):
        passed, reasons = technical_filter(passing_tech(**over), {}, "STOCK")
        assert not passed and reasons[0] == reason

    def test_rsi_boundary_and_missing_rsi(self):
        assert technical_filter(passing_tech(rsi=75.0), {}, "STOCK")[0]
        assert technical_filter(passing_tech(rsi=None), {}, "STOCK")[0]

    def test_blockers_fail(self):
        passed, reasons = technical_filter(passing_tech(), {}, "STOCK", ["RSI overbought"])
        assert not passed and reasons == ["active_blocker"]
        assert technical_filter(passing_tech(), {}, "STOCK", [])[0]

    def test_all_failures_reported_in_order(self):
        t = passing_tech(sma_50=80.0, sma_200=110.0, rsi=80.0, dollar_volume_avg_20=1.0)
        _, reasons = technical_filter(t, {}, "STOCK", ["x"])
        assert reasons == ["below_sma200", "sma50_below_sma200", "rsi_overbought",
                           "overextended_vs_sma50", "low_liquidity", "active_blocker"]

    def test_empty_input(self):
        passed, reasons = technical_filter(None, None, None)
        assert not passed and reasons == ["insufficient_history", "no_liquidity_data"]

    def test_share_volume_fallback_times_price(self):
        t = passing_tech(dollar_volume_avg_20=None, volume_avg_20=200_000)  # 200k × $100 = $20M
        assert technical_filter(t, {}, "STOCK")[0]
        t = passing_tech(dollar_volume_avg_20=None, volume_avg_20=50_000)   # $5M
        assert technical_filter(t, {}, "STOCK")[1] == ["low_liquidity"]

    def test_crypto_volume_is_already_usd_with_higher_floor(self):
        t = passing_tech(price=0.10, volume_avg_20=60_000_000, dollar_volume_avg_20=6_000_000)
        assert technical_filter(t, {}, "CRYPTO")[0]            # not multiplied by $0.10
        t = passing_tech(price=0.10, volume_avg_20=40_000_000)
        assert technical_filter(t, {}, "CRYPTO")[1] == ["low_liquidity"]
        assert technical_filter(t, {"quote_type": "CRYPTOCURRENCY"}, None)[1] == ["low_liquidity"]

    def test_thresholds_are_settings(self, monkeypatch):
        t = passing_tech(sma_50=100 / 1.20, sma_200=100 / 1.40)
        assert not technical_filter(t, {}, "STOCK")[0]
        monkeypatch.setattr(settings, "tech_filter_max_ext_sma50_pct", 25.0)
        assert technical_filter(t, {}, "STOCK")[0]

    def test_runs_on_real_indicator_output(self):
        df = make_bars(n=300, seed=4, drift=0.002, vol=0.005, volume=500_000)
        tech = indicators.compute_indicators(df, exchange=None)
        assert tech["volume_avg_20"] > 0
        assert tech["dollar_volume_avg_20"] == pytest.approx(
            float((df["Close"].iloc[-20:] * df["Volume"].iloc[-20:]).mean()), rel=1e-6)
        passed, reasons = technical_filter(tech, {}, "STOCK")
        assert isinstance(passed, bool) and (passed or reasons)


def _run(signals, db=None):
    db = db or FakeDB({"brain_wallet": [wallet_row()], "virtual_trades": []})
    with patch_db(db):
        vp.process_virtual_trades(signals, set(), [])
    return db


class TestBrainEntryPath:
    def test_filter_mode_skips_failing_ai_buy(self):
        db = _run([make_sig(technical_data=passing_tech(sma_200=101.0, sma_50=102.0))])
        assert brain_trades(db) == []
        (d,) = db.rows("brain_decisions")
        assert d["reason"] == "technical_filter:below_sma200"
        assert d["details"]["tech_filter"] == {"passed": False, "reasons": ["below_sma200"]}
        assert d["details"]["entry_mode"] == "filter"

    def test_filter_mode_still_requires_ai_buy(self):
        db = _run([make_sig(ai_status="skipped", ai_signal=None)])
        assert brain_trades(db) == []

    def test_filter_mode_still_requires_rr(self):
        db = _run([make_sig(stop=94.0, target=108.0)])
        assert brain_trades(db) == []
        assert db.rows("brain_decisions")[0]["reason"].startswith("rr_below_min")

    def test_legacy_score_mode_ignores_filter(self, monkeypatch):
        monkeypatch.setattr(settings, "brain_entry_mode", "score")
        db = _run([make_sig(score=80, technical_data=passing_tech(sma_200=101.0, sma_50=102.0))])
        assert len(brain_trades(db)) == 1

    def test_entries_ordered_by_p_win_not_score(self, monkeypatch):
        monkeypatch.setattr(settings, "brain_max_open_positions", 1)
        sigs = [make_sig("HIGHSCORE", score=95, p_win=0.52),
                make_sig("HIGHPWIN", score=40, p_win=0.70)]
        (t,) = brain_trades(_run(sigs))
        assert t["symbol"] == "HIGHPWIN"

    def test_confidence_breaks_p_win_tie(self, monkeypatch):
        monkeypatch.setattr(settings, "brain_max_open_positions", 1)
        sigs = [make_sig("LOWCONF", p_win=0.6, confidence=60),
                make_sig("HIGHCONF", p_win=0.6, confidence=85)]
        (t,) = brain_trades(_run(sigs))
        assert t["symbol"] == "HIGHCONF"

    def test_score_mode_orders_by_score(self, monkeypatch):
        monkeypatch.setattr(settings, "brain_max_open_positions", 1)
        monkeypatch.setattr(settings, "brain_entry_mode", "score")
        sigs = [make_sig("HIGHPWIN", score=80, p_win=0.70), make_sig("HIGHSCORE", score=95, p_win=0.52)]
        (t,) = brain_trades(_run(sigs))
        assert t["symbol"] == "HIGHSCORE"

    def test_sort_key_missing_values_last(self):
        sigs = [{"symbol": "N", "p_win": None}, {"symbol": "P", "p_win": 0.1}]
        assert [s["symbol"] for s in sorted(sigs, key=vp.brain_entry_sort_key)] == ["P", "N"]


def _pre(ticker, score, bucket="SAFE_INCOME", passed=True):
    tech = passing_tech() if passed else passing_tech(sma_200=101.0, sma_50=102.0)
    return (ticker, score, bucket, tech, {})


class TestPass2Selection:
    def test_stamp_records_filter_on_technical_data(self):
        pre = [_pre("OK", 60), _pre("BAD", 90, passed=False)]
        scan_service._stamp_tech_filter(pre, {}, {})
        assert pre[0][3]["_tech_filter"] == {"passed": True, "reasons": []}
        assert pre[1][3]["_tech_filter"] == {"passed": False, "reasons": ["below_sma200"]}

    def test_failing_candidates_get_no_ai_call(self):
        pre = [_pre("BAD1", 95, passed=False), _pre("OK1", 50), _pre("BAD2", 90, passed=False),
               _pre("OK2", 40, "HIGH_RISK")]
        scan_service._stamp_tech_filter(pre, {}, {})
        picked = [x[0] for x in scan_service._select_ai_candidates(pre, {}, 15, "filter")]
        assert sorted(picked) == ["OK1", "OK2"]

    def test_passing_ranked_by_trend_quality_and_capped(self):
        pre = [_pre("A", 90), _pre("B", 50), _pre("C", 70)]
        scan_service._stamp_tech_filter(pre, {}, {})
        screening = {  # trend_quality_score: B strongest, then C, then A
            "A": {"vs_sma50": -0.01, "vs_sma200": 0.05},
            "B": {"vs_sma50": 0.03, "vs_sma200": 0.2, "sma50_above_sma200": True, "ret_3m_ex_1w": 0.2},
            "C": {"vs_sma50": 0.03, "vs_sma200": 0.2},
        }
        picked = [x[0] for x in scan_service._select_ai_candidates(pre, screening, 2, "filter")]
        assert picked == ["B", "C"]

    def test_falls_back_to_pre_score_without_screening(self):
        pre = [_pre("A", 60), _pre("B", 80)]
        scan_service._stamp_tech_filter(pre, {}, {})
        assert [x[0] for x in scan_service._select_ai_candidates(pre, {}, 5, "filter")] == ["B", "A"]

    def test_legacy_score_mode_uses_pre_score(self):
        pre = [_pre("BAD", 95, passed=False), _pre("OK", 50)]
        scan_service._stamp_tech_filter(pre, {}, {})
        assert [x[0] for x in scan_service._select_ai_candidates(pre, {}, 1, "score")] == ["BAD"]


class TestBacktestFilter:
    def test_is_entry_filter_modes(self):
        sig = {"action": "BUY", "score": 70, "bucket": "HIGH_RISK", "blocked": False, "blackout": None,
               "ai_status": "skipped", "tech_filter_passed": True}
        assert SignalConfig().mode == "filter"
        assert not is_entry(sig, SignalConfig())                        # no historical AI BUY
        assert is_entry(sig, SignalConfig(filter_only_entries=True))    # NON-LIVE study rule
        assert not is_entry({**sig, "tech_filter_passed": False}, SignalConfig(filter_only_entries=True))
        assert SignalConfig(entry_score=50).mode == "score"

    def test_study_has_filter_table_and_filter_mode_makes_no_entries(self, market):  # noqa: F811
        bars, spy, vix = market
        start, end = bars["AAA"].index[300].date(), bars["AAA"].index[-1].date()
        kw = dict(start=start, end=end, bars=bars, symbols=list(bars),
                  bench={"SPY": spy, "XIU.TO": spy}, vix=vix, usdcad=None, fundamentals={})
        res = run(**kw, sim=SimConfig(correlation_gate=False))
        assert res["meta"]["entry_mode"] == "filter"
        assert res["portfolio"]["trades"].get("trades", 0) == 0
        st = res["study"]
        assert set(st["by_tech_filter"]) <= {"PASS", "FAIL"} and st["by_tech_filter"]
        n = sum(v["trades"] for v in st["by_tech_filter"].values())
        assert n == st["n_trades"]
        md = render_markdown(res)
        assert "### By technical filter" in md and "No entries (expected)" in md

        res2 = run(**kw, sim=SimConfig(correlation_gate=False,
                                       signal=SignalConfig(filter_only_entries=True)))
        assert "NON-LIVE" in res2["meta"]["entry_rule"]
        assert any("--filter-only-entries" in c for c in res2["caveats"])
