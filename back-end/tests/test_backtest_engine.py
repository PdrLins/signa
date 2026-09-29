"""Backtest engine tests — synthetic prices only, no network, no DB."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.ai import signal_engine
from app.core.config import settings
from app.services import virtual_portfolio as vp
from backtest import execution, metrics
from backtest.macro import MacroSeries
from backtest.portfolio import FX, SimConfig, Simulator
from backtest.run_backtest import run
from backtest.signals import Bars, SignalConfig, is_entry, signals_for_day
from backtest.study import run_study


def make_bars(n=600, start="2020-01-01", seed=0, drift=0.0006, vol=0.015, price=50.0,
              volume=2_000_000, freq="B"):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq=freq)
    close = price * np.exp(np.cumsum(rng.normal(drift, vol, n)))
    open_ = close * (1 + rng.normal(0, 0.004, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, n)))
    vol_ = volume * (1 + np.abs(rng.normal(0, 0.2, n)))
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close,
                         "Volume": vol_}, index=idx)


@pytest.fixture
def market():
    bars = {"AAA": make_bars(seed=1), "BBB": make_bars(seed=2, drift=0.001),
            "CCC": make_bars(seed=3, drift=-0.0003)}
    spy = make_bars(seed=10, price=300)
    vix = make_bars(seed=11, price=16, drift=0, vol=0.01)
    return bars, spy, vix


# ── no lookahead ─────────────────────────────────────────────

def test_signal_at_t_unchanged_when_future_bars_altered(market):
    bars, spy, vix = market
    t = bars["AAA"].index[450].date()
    base = signals_for_day(t, Bars(bars), list(bars), {}, MacroSeries(spy, vix))
    assert base, "synthetic symbols should pass the live prefilter"

    future = pd.Timestamp(t)
    tampered = {}
    for s, df in bars.items():
        df = df.copy()
        df.loc[df.index > future, ["Open", "High", "Low", "Close"]] *= 3.0
        df.loc[df.index > future, "Volume"] *= 0.01
        tampered[s] = df
    spy2 = spy.copy()
    spy2.loc[spy2.index > future, "Close"] *= 0.1
    vix2 = vix.copy()
    vix2.loc[vix2.index > future, "Close"] = 80.0

    again = signals_for_day(t, Bars(tampered), list(bars), {}, MacroSeries(spy2, vix2))
    key = lambda sigs: {g["symbol"]: (g["score"], g["action"], g["technical_data"], g["market_regime"])
                        for g in sigs}
    assert key(base) == key(again)


def test_window_never_includes_future_bars(market):
    bars, _, _ = market
    b = Bars(bars)
    t = bars["AAA"].index[300].date()
    w = b.window("AAA", t)
    assert w.index.max() == pd.Timestamp(t)
    assert (w.index > pd.Timestamp(t) - pd.Timedelta(days=365)).all()


# ── live code is what runs ───────────────────────────────────

def test_backtest_calls_live_compute_score(market, monkeypatch):
    bars, spy, vix = market
    calls = []
    real = signal_engine.compute_score

    def spy_score(*args, **kw):
        calls.append(args)
        real(*args, **kw)
        return 77, {"total": 77}

    monkeypatch.setattr(signal_engine, "compute_score", spy_score)
    t = bars["AAA"].index[450].date()
    sigs = signals_for_day(t, Bars(bars), list(bars), {}, MacroSeries(spy, vix))
    assert len(calls) == len(sigs) > 0
    assert all(g["score"] == 77 for g in sigs)
    # tech-only: grok_data and synthesis are empty, exactly like the live pre-score
    assert all(c[3] == {} and c[4] == {} for c in calls)


def test_entry_rule_uses_live_action():
    sig = {"action": "BUY", "score": 70, "bucket": "HIGH_RISK", "blocked": False, "blackout": None}
    assert is_entry(sig, SignalConfig())
    assert not is_entry({**sig, "action": "HOLD"}, SignalConfig())
    # override threshold keeps live blockers and the >90 ceiling
    assert is_entry({**sig, "action": "AVOID", "score": 52}, SignalConfig(entry_score=50))
    assert not is_entry({**sig, "blocked": True}, SignalConfig(entry_score=50))
    assert not is_entry({**sig, "score": 95}, SignalConfig(entry_score=50))
    # AI veto placeholder is a no-op
    assert is_entry(sig, SignalConfig(ai_veto=True))


# ── execution ────────────────────────────────────────────────

def _signal(sym, d, score=80, atr=2.0):
    return {"date": d, "symbol": sym, "score": score, "action": "BUY", "blocked": False,
            "blackout": None, "bucket": "HIGH_RISK", "sector": None, "market_regime": "TRENDING",
            "technical_data": {"atr": atr}}


def _flat_bars(days, o=100.0, h=101.0, low=99.0, c=100.0):
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in days])
    return pd.DataFrame({"Open": o, "High": h, "Low": low, "Close": c, "Volume": 1e6}, index=idx)


def test_entry_fills_next_bar_open_with_live_slippage():
    days = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
    df = _flat_bars(days, o=104.0, h=105.0, low=103.0, c=104.0)
    df.loc[pd.Timestamp(days[0]), ["Open", "High", "Low", "Close"]] = [100.0, 101.0, 99.0, 100.0]
    sim = Simulator(days, {days[0]: [_signal("AAA", days[0])]}, {"AAA": df}, FX(None),
                    SimConfig(correlation_gate=False))
    sim.run()
    assert len(sim.trades) == 1
    t = sim.trades[0]
    assert t["signal_date"] == "2024-01-02"
    assert t["entry_date"] == "2024-01-03"          # t+1, not signal-day close
    assert t["entry_fill"] == pytest.approx(vp.apply_slippage(104.0, "BUY", "AAA"), rel=1e-9)
    assert t["entry_fill"] > 104.0                    # pays the slippage
    assert t["exit_reason"] == "END_OF_WINDOW"


def test_sizing_uses_live_risk_budget():
    days = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
    df = _flat_bars(days)
    sim = Simulator(days, {days[0]: [_signal("AAA", days[0], atr=2.0)]}, {"AAA": df}, FX(None),
                    SimConfig(initial_cash=10_000, correlation_gate=False))
    sim.run()
    fill = vp.apply_slippage(100.0, "BUY", "AAA")
    stop = fill - settings.brain_stop_atr_mult * 2.0
    from app.services.wallet import calc_risk_position_size
    shares, _ = calc_risk_position_size(10_000, 10_000, fill, stop)
    assert sim.trades[0]["shares"] == pytest.approx(shares)


def _pos(entry=100.0, stop=96.0, target=108.0, atr=2.0, d=date(2024, 1, 2)):
    levels = {"stop": stop, "target": target, "atr": atr}
    return execution.new_position("AAA", d, entry, levels, 1.0)


def test_stop_checked_before_target_on_same_bar():
    pos = _pos()
    r = execution.step_bar(pos, (100.0, 110.0, 95.0, 100.0), date(2024, 1, 3), entered_today=False)
    assert r == ("STOP_HIT", 96.0)


def test_gap_through_stop_fills_at_open():
    pos = _pos()
    r = execution.step_bar(pos, (90.0, 92.0, 89.0, 91.0), date(2024, 1, 3), entered_today=False)
    assert r == ("STOP_HIT", 90.0)


def test_target_hit_fills_at_target():
    pos = _pos()
    r = execution.step_bar(pos, (101.0, 109.0, 99.0, 104.0), date(2024, 1, 3), entered_today=False)
    assert r == ("TARGET_HIT", 108.0)


def test_trailing_stop_follows_live_ratchet():
    pos = _pos(target=200.0)
    # +1R (4.0) reached at the high of 106 → live trail = peak − 2.5·ATR = 101
    r = execution.step_bar(pos, (100.0, 106.0, 99.5, 105.0), date(2024, 1, 3), entered_today=False)
    assert r is None
    expected = vp.evaluate_exit({**_pos(target=200.0)}, 106.0).stop
    assert pos["stop_loss"] == pytest.approx(expected)
    assert pos["stop_loss"] > 96.0
    r = execution.step_bar(pos, (104.0, 104.5, 100.0, 100.5), date(2024, 1, 4), entered_today=False)
    assert r[0] == "TRAILING_STOP" and r[1] == pytest.approx(expected)


def test_time_expiry_uses_live_max_hold():
    pos = _pos(target=500.0, stop=1.0)
    d = date(2024, 1, 2)
    later = pd.Timestamp(d) + pd.Timedelta(days=settings.brain_max_hold_days)
    r = execution.step_bar(pos, (100.0, 101.0, 99.0, 100.0), later.date(), entered_today=False)
    assert r == ("TIME_EXPIRED", 100.0)


# ── metrics & benchmark ──────────────────────────────────────

def test_metrics_on_known_equity_curve():
    idx = pd.to_datetime(["2023-01-02", "2023-01-03", "2023-01-04", "2023-01-05"])
    curve = pd.Series([100.0, 110.0, 99.0, 121.0], index=idx)
    m = metrics.equity_metrics(curve)
    assert m["total_return_pct"] == 21.0
    assert m["max_drawdown_pct"] == -10.0
    rets = np.array([0.10, -0.10, 121 / 99 - 1])
    assert m["sharpe"] == round(rets.mean() / rets.std(ddof=1) * np.sqrt(252), 2)
    assert metrics.cagr(100, 121, 730) == pytest.approx(1.21 ** (365.25 / 730) - 1)


def test_trade_metrics_win_rate_payoff_expectancy():
    trades = [{"pnl_usd": 20, "pnl_pct": 2.0, "exit_reason": "TARGET_HIT"},
              {"pnl_usd": -10, "pnl_pct": -1.0, "exit_reason": "STOP_HIT"},
              {"pnl_usd": 20, "pnl_pct": 2.0, "exit_reason": "TARGET_HIT"},
              {"pnl_usd": -10, "pnl_pct": -1.0, "exit_reason": "STOP_HIT"}]
    m = metrics.trade_metrics(trades)
    assert m["win_rate_pct"] == 50.0
    assert m["payoff_ratio"] == 2.0
    assert m["expectancy_pct"] == 0.5
    assert m["expectancy_usd"] == 5.0


def test_benchmark_buy_and_hold_open_to_close():
    idx = pd.to_datetime(["2023-01-03", "2023-06-30", "2024-01-03"])
    df = pd.DataFrame({"Open": [100.0, 0, 0], "Close": [105.0, 90.0, 120.0]}, index=idx)
    b = metrics.benchmark(df, date(2023, 1, 1), date(2024, 12, 31))
    assert b["total_return_pct"] == 20.0                # 100 open → 120 close
    assert b["max_drawdown_pct"] == -10.0               # 100 → 90
    assert b["cagr_pct"] == round((1.2 ** (365.25 / 365) - 1) * 100, 2)
    fx = pd.Series([0.5, 0.5, 0.5], index=idx)
    b2 = metrics.benchmark(df, date(2023, 1, 1), date(2024, 12, 31), fx_usd=fx)
    assert b2["usd"]["total_return_pct"] == 20.0


# ── study + end-to-end ───────────────────────────────────────

def test_study_trades_do_not_overlap(market):
    bars, spy, _ = market
    days = [ts.date() for ts in bars["AAA"].index[400:430]]
    sigs = {d: [_signal("AAA", d, atr=0.01)] for d in days}  # tiny ATR: exits fast
    trades = run_study(sigs, {"AAA": bars["AAA"]}, spy, days[-1])
    assert trades
    for a, b in zip(trades, trades[1:]):
        assert b["signal_date"] > a["exit_date"]
        assert b["entry_date"] > a["exit_date"]


def test_run_end_to_end_synthetic(market):
    bars, spy, vix = market
    start, end = bars["AAA"].index[300].date(), bars["AAA"].index[-1].date()
    res = run(start=start, end=end, bars=bars, symbols=list(bars),
              bench={"SPY": spy, "XIU.TO": spy}, vix=vix, usdcad=None, fundamentals={},
              sim=SimConfig(correlation_gate=False, signal=SignalConfig(entry_score=40)))
    p = res["portfolio"]
    assert p["equity"]["start_equity"] == 10_000.0
    assert p["trades"]["trades"] == len(p["trade_log"]) > 0
    assert res["benchmarks"]["SPY"]["available"]
    assert set(res["walk_forward"]) == {"in_sample", "out_of_sample"}
    assert any("TECHNICAL / TREND LAYER ONLY" in c for c in res["caveats"])
    assert any("SURVIVORSHIP" in c for c in res["caveats"])
    # one position per symbol at a time
    by_sym = {}
    for t in p["trade_log"]:
        by_sym.setdefault(t["symbol"], []).append(t)
    for ts in by_sym.values():
        for a, b in zip(ts, ts[1:]):
            assert b["entry_date"] > a["exit_date"]
    # cash accounting closes: final equity == initial + Σ pnl
    total = sum(t["pnl_usd"] for t in p["trade_log"])
    assert p["equity"]["end_equity"] == pytest.approx(10_000 + total, abs=0.05 * len(p["trade_log"]) + 0.01)


def test_lookahead_flag_is_loud_in_report():
    from backtest.report import caveats
    c = caveats({"include_fundamentals": True})
    assert any("LOOKAHEAD WARNING" in x for x in c)
