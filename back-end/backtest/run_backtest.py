"""Signa backtest — LIVE scoring/blockers/prefilter/exits/sizing on history.

    python -m backtest.run_backtest --start 2021-01-01 --end 2026-09-01 \
        [--universe my_universe.csv] [--include-fundamentals] \
        [--out docs/backtests/<name>]

See backtest/README.md for the design, what is and isn't measured, and
every flag.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import data as bt_data
from backtest import live, metrics, report
from backtest.macro import warmup_start
from backtest.portfolio import FX, SimConfig, simulate
from backtest.signals import SignalConfig, generate_signals
from backtest.study import BANDS, band, by_tech_filter_reason, run_study, signal_class

BENCHMARKS = ("SPY", "XIU.TO")
BAND_ORDER = [b[2] for b in BANDS]


def _trading_days(bars: dict[str, pd.DataFrame], symbols, start: date, end: date) -> list[date]:
    idx = pd.DatetimeIndex([])
    for s in symbols:
        if s in bars:
            idx = idx.union(bars[s].index)
    idx = idx[(idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(end))]
    return [ts.date() for ts in idx]


def _score_distribution(signals_by_day) -> dict:
    s = live.settings
    thr = {"SAFE_INCOME": s.score_buy_safe, "HIGH_RISK": s.score_buy_risk}
    by_b: dict[str, list[int]] = {}
    actions: dict[str, int] = {}
    n = 0
    for sigs in signals_by_day.values():
        for g in sigs:
            n += 1
            by_b.setdefault(g["bucket"], []).append(g["score"])
            k = signal_class(g)
            actions[k] = actions.get(k, 0) + 1
    out = {}
    for b, sc in sorted(by_b.items()):
        a = np.array(sc)
        out[b] = {"n": len(a), "max": int(a.max()), "p95": float(np.percentile(a, 95)),
                  "mean": round(float(a.mean()), 1),
                  "ge_buy_threshold": int((a >= thr.get(b, s.score_buy)).sum()),
                  "ge_brain_min": int((a >= live.brain_min_score()).sum())}
    return {"n": n, "by_bucket": out, "actions": dict(sorted(actions.items(), key=lambda kv: -kv[1]))}


def _benchmarks(bench: dict, start: date, end: date, cal, usdcad) -> dict:
    fx_usd = None
    if usdcad is not None and not usdcad.empty:
        fx_usd = 1.0 / usdcad["Close"]
    return {
        name: metrics.benchmark(bench.get(name), start, end, cal,
                                fx_usd if name.endswith(".TO") else None)
        for name in BENCHMARKS
    }


def run(
    *,
    start: date,
    end: date,
    bars: dict[str, pd.DataFrame],
    symbols: list[str],
    bench: dict[str, pd.DataFrame],
    vix: pd.DataFrame | None,
    usdcad: pd.DataFrame | None,
    fundamentals: dict[str, dict],
    universe_windows: dict | None = None,
    sim: SimConfig | None = None,
    oos_start: date | None = None,
    workers: int = 1,
    meta: dict | None = None,
    progress=None,
) -> dict:
    sim = sim or SimConfig()
    spy = bench.get("SPY")
    days = _trading_days(bars, symbols, start, end)
    signals_by_day = generate_signals(days, bars, symbols, fundamentals, spy, vix,
                                      universe_windows, workers=workers, progress=progress)
    fx = FX(usdcad)
    res = simulate(days, signals_by_day, bars, fx, sim)
    study = run_study(signals_by_day, bars, spy, end)

    cal = spy.index if spy is not None and not spy.empty else None
    cal = cal[(cal >= pd.Timestamp(start)) & (cal <= pd.Timestamp(end))] if cal is not None else None
    eq = metrics.equity_metrics(res.equity, cal, res.invested)
    benches = _benchmarks(bench, start, end, cal, usdcad)
    excess = {}
    for name, b in benches.items():
        ref = (b.get("usd") or b) if b.get("available") else None
        if ref and eq.get("total_return_pct") is not None and ref.get("total_return_pct") is not None:
            excess[name] = round(eq["total_return_pct"] - ref["total_return_pct"], 2)

    # walk-forward split (reporting only — nothing is fitted)
    if oos_start is None and days:
        span = (end - start).days
        oos_start = start + pd.Timedelta(days=int(span * 0.7)).to_pytimedelta()
    wf = {}
    if oos_start and start < oos_start <= end:
        for seg, (a, b) in {"in_sample": (start, oos_start), "out_of_sample": (oos_start, end)}.items():
            hi = pd.Timestamp(b) - (pd.Timedelta(days=1) if seg == "in_sample" else pd.Timedelta(0))
            curve = res.equity[(res.equity.index >= pd.Timestamp(a)) & (res.equity.index <= hi)]
            inv = res.invested[(res.invested.index >= pd.Timestamp(a)) & (res.invested.index <= hi)]
            if curve.empty:
                continue
            seg_trades = [t for t in res.trades if pd.Timestamp(a) <= pd.Timestamp(t["entry_date"]) <= hi]
            seg_cal = cal[(cal >= pd.Timestamp(a)) & (cal <= hi)] if cal is not None else None
            wf[seg] = {
                "start": a.isoformat(), "end": hi.date().isoformat(),
                "equity": metrics.equity_metrics(curve, seg_cal, inv),
                "trades": metrics.trade_metrics(seg_trades),
                "benchmarks": _benchmarks(bench, a, hi.date(), seg_cal, usdcad),
            }

    s = live.settings
    meta = dict(meta or {})
    meta.update({
        "start": start.isoformat(), "end": end.isoformat(), "n_symbols": len(symbols),
        "trading_days": len(days), "oos_start": oos_start.isoformat() if oos_start else None,
        "brain_min_score": live.brain_min_score(),
        "slippage_bps_stock": s.brain_slippage_bps_stock,
        "slippage_bps_crypto": s.brain_slippage_bps_crypto,
        "commission_usd": s.brain_commission_usd if sim.commission_usd is None else sim.commission_usd,
        "buy_thresholds": f"SAFE_INCOME {s.score_buy_safe} / HIGH_RISK {s.score_buy_risk}",
        "entry_mode": sim.signal.mode,
        "filter_only_entries": bool(sim.signal.filter_only_entries),
        "entry_rule": _entry_rule(sim.signal),
        "ai_veto": sim.signal.ai_veto,
        "initial_cash": sim.initial_cash,
        "drawdown_breaker": sim.drawdown_breaker,
        "correlation_gate": sim.correlation_gate,
        "live_settings": {k: getattr(s, k) for k in (
            "brain_risk_per_trade_pct", "brain_max_position_pct", "brain_max_open_positions",
            "brain_max_per_sector", "brain_max_crypto_pct", "brain_reentry_cooldown_days",
            "brain_stop_atr_mult", "brain_target_r_mult", "brain_min_rr", "brain_trail_atr_mult",
            "brain_trail_activate_r", "brain_max_hold_days", "brain_max_drawdown_pct",
            "brain_drawdown_pause_trading_days", "brain_entry_mode", "tech_filter_max_rsi",
            "tech_filter_max_ext_sma50_pct", "tech_filter_min_dollar_volume",
            "tech_filter_min_dollar_volume_crypto",
            "max_candidates", "min_volume") if hasattr(s, k)},
    })
    meta.setdefault("generated_at", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    meta.setdefault("name", "backtest")

    out = {
        "meta": meta,
        "portfolio": {
            "equity": eq,
            "excess_return_pct": excess,
            "trades": metrics.trade_metrics(res.trades),
            "by_band": metrics.group_by(res.trades, lambda t: band(t["score"]), order=BAND_ORDER),
            "by_bucket": metrics.group_by(res.trades, "bucket"),
            "entry_decisions": dict(res.skips.most_common()),
            "breaker_days": res.breaker_days,
            "breaker_trips": res.breaker_trips,
            "breaker_resumes": res.breaker_resumes,
            "turnover_annual_x": metrics._r(metrics.turnover(res.notional_traded, res.equity)),
            "fees_usd": round(res.fees, 2),
            "trade_log": res.trades,
            "equity_curve": {k.date().isoformat(): round(v, 2) for k, v in res.equity.items()},
        },
        "benchmarks": benches,
        "walk_forward": wf,
        "study": {
            "all": metrics.trade_metrics(study, pnl_key="_", pct_key="ret_pct"),
            "by_band": metrics.group_by(study, "band", order=BAND_ORDER, pnl_key="_", pct_key="ret_pct"),
            "by_bucket": metrics.group_by(study, "bucket", pnl_key="_", pct_key="ret_pct"),
            "by_class": metrics.group_by(study, "class", pnl_key="_", pct_key="ret_pct"),
            "by_regime": metrics.group_by(study, "regime", pnl_key="_", pct_key="ret_pct"),
            "by_tech_filter": metrics.group_by(study, "tech_filter", order=["PASS", "FAIL"],
                                               pnl_key="_", pct_key="ret_pct"),
            "by_tech_filter_reason": by_tech_filter_reason(
                [t for t in study if t.get("tech_filter") == "FAIL"], pnl_key="_", pct_key="ret_pct"),
            "n_trades": len(study),
        },
        "score_distribution": _score_distribution(signals_by_day),
    }
    out["caveats"] = report.caveats(meta)
    return out


def _entry_rule(sc: SignalConfig) -> str:
    s = live.settings
    if sc.mode == "filter":
        if sc.filter_only_entries:
            return ("NON-LIVE --filter-only-entries: enter on a live technical_filter PASS alone "
                    "(the live brain also requires a validated AI BUY)")
        return "live filter mode: validated AI BUY + technical_filter PASS (no historical AI → no entries)"
    if sc.entry_score is None:
        return "live tech-only action == BUY (bucket thresholds %s/%s) [score mode]" % (
            s.score_buy_safe, s.score_buy_risk)
    return f"score >= {sc.entry_score} (NON-LIVE threshold), live blockers/ceiling [score mode]"


def _parse_args(argv=None):
    p = argparse.ArgumentParser(prog="python -m backtest.run_backtest", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", required=True, type=date.fromisoformat)
    p.add_argument("--end", required=True, type=date.fromisoformat)
    p.add_argument("--universe", help="CSV with symbol[,start,end] (point-in-time universe)")
    p.add_argument("--tickers", help="comma-separated override (quick runs)")
    p.add_argument("--max-tickers", type=int, help="cap the universe (first N) for quick runs")
    p.add_argument("--exclude-tsx", action="store_true", help="drop .TO listings (no FX)")
    p.add_argument("--include-fundamentals", action="store_true",
                   help="apply TODAY's fundamentals to past dates (LOOKAHEAD — flagged in report)")
    p.add_argument("--no-info", action="store_true",
                   help="skip yfinance .info (no sector → no sector cap; bucket from live lists only)")
    p.add_argument("--entry-score", type=int,
                   help="NON-LIVE: enter at score >= N instead of the bucket BUY threshold")
    p.add_argument("--entry-mode", choices=("filter", "score"),
                   help="filter (live default: AI BUY + technical_filter) or score (legacy "
                        "tech-only action / --entry-score). Default: score if --entry-score "
                        "is given, else filter")
    p.add_argument("--filter-only-entries", action="store_true",
                   help="NON-LIVE (filter mode): enter on a technical-filter pass alone, "
                        "without the AI BUY the live brain requires")
    p.add_argument("--ai-veto", action="store_true",
                   help="route entries through the AI-veto placeholder (no-op: no historical AI)")
    p.add_argument("--no-drawdown-breaker", action="store_true")
    p.add_argument("--no-correlation-gate", action="store_true")
    p.add_argument("--commission", type=float, help="USD per fill (default: live setting)")
    p.add_argument("--initial-cash", type=float, default=10_000.0)
    p.add_argument("--oos-start", type=date.fromisoformat,
                   help="walk-forward out-of-sample start (default: 70%% of the window)")
    p.add_argument("--workers", type=int, default=max(1, (__import__("os").cpu_count() or 2) - 1))
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--smoke", action="store_true", help="label the report as a smoke test")
    p.add_argument("--out", help="output dir (default docs/backtests/<name>)")
    p.add_argument("--name")
    return p.parse_args(argv)


def main(argv=None) -> int:
    a = _parse_args(argv)
    if a.entry_mode == "filter" and a.entry_score is not None:
        raise SystemExit("--entry-score only applies to --entry-mode score")
    if a.filter_only_entries and (a.entry_mode == "score" or a.entry_score is not None):
        raise SystemExit("--filter-only-entries only applies to --entry-mode filter")
    live.quiet_live_logs()
    t0 = time.time()

    windows = None
    if a.universe:
        windows = bt_data.load_universe_csv(a.universe)
        symbols = list(windows)
    elif a.tickers:
        symbols = [t.strip() for t in a.tickers.split(",") if t.strip()]
    else:
        symbols = live.get_all_tickers()
    if a.exclude_tsx:
        symbols = [s for s in symbols if not s.endswith(".TO")]
    if a.max_tickers:
        symbols = symbols[:a.max_tickers]

    ws = warmup_start(a.start)
    use_cache = not a.no_cache
    print(f"Loading {len(symbols)} symbols {ws} → {a.end} (cache={'on' if use_cache else 'off'})")
    bars = bt_data.load_ohlcv(symbols, ws, a.end, use_cache=use_cache)
    aux = bt_data.load_ohlcv(list(BENCHMARKS) + ["^VIX", "CAD=X"], ws, a.end, use_cache=use_cache)
    symbols = [s for s in symbols if s in bars]
    print(f"  {len(symbols)} symbols with data")

    fundamentals: dict[str, dict] = {}
    if not a.no_info:
        print("Loading fundamentals (.info, cached)…")
        raw = bt_data.load_fundamentals(symbols, use_cache=use_cache)
        fundamentals = {s: bt_data.filter_fundamentals(f, a.include_fundamentals) for s, f in raw.items()}

    name = a.name or (f"tech_only_{a.start}_{a.end}" + ("_LOOKAHEAD" if a.include_fundamentals else "")
                      + ("_FILTER_ONLY_NONLIVE" if a.filter_only_entries else ""))
    out_dir = Path(a.out or f"docs/backtests/{name}")

    def progress(i, n):
        print(f"  signals {i}/{n} days ({time.time() - t0:.0f}s)", flush=True)

    sim = SimConfig(
        initial_cash=a.initial_cash, commission_usd=a.commission,
        drawdown_breaker=not a.no_drawdown_breaker, correlation_gate=not a.no_correlation_gate,
        signal=SignalConfig(entry_score=a.entry_score, ai_veto=a.ai_veto, entry_mode=a.entry_mode,
                            filter_only_entries=a.filter_only_entries),
    )
    res = run(
        start=a.start, end=a.end, bars=bars, symbols=symbols,
        bench={k: aux.get(k) for k in BENCHMARKS}, vix=aux.get("^VIX"), usdcad=aux.get("CAD=X"),
        fundamentals=fundamentals, universe_windows=windows, sim=sim, oos_start=a.oos_start,
        workers=a.workers, progress=progress,
        meta={"name": name, "universe_csv": a.universe, "include_fundamentals": a.include_fundamentals,
              "exclude_tsx": a.exclude_tsx, "smoke": a.smoke, "runtime_s": None,
              "argv": sys.argv[1:] if argv is None else list(argv)},
    )
    res["meta"]["runtime_s"] = round(time.time() - t0, 1)
    md, js = report.write(res, out_dir)
    e = res["portfolio"]["equity"]
    print(f"\nStrategy total {e.get('total_return_pct')}% CAGR {e.get('cagr_pct')}% "
          f"MaxDD {e.get('max_drawdown_pct')}% Sharpe {e.get('sharpe')} · "
          f"trades {res['portfolio']['trades'].get('trades')}")
    for k, b in res["benchmarks"].items():
        if b.get("available"):
            print(f"{k} buy&hold total {b.get('total_return_pct')}%")
    print(f"Report: {md}\n        {js}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
