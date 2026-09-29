"""Point-in-time signal generation — the LIVE scan's tech-only path, replayed.

For each day t (a post-close scan):

  1. Eligible symbols: have a bar ON t and are in the universe on t.
  2. Window = that symbol's bars in (t − 1y, t] (the live scan fetches
     `period="1y"`). Nothing after t is ever sliced in.
  3. LIVE `_screening_features` → LIVE `prefilter_candidates` (top-N by
     trend quality, 5 crypto slots).
  4. Per candidate: LIVE bucket helpers, LIVE `compute_indicators`,
     LIVE `compute_score` with EMPTY grok/synthesis (the live tech-only
     pre-score call, verbatim), LIVE `_tech_only_action` (blockers →
     AVOID, `score_to_action`, earnings blackout → HOLD).

AI inputs are absent historically, so every signal is exactly what the
live pipeline emits for a candidate that did not get AI analysis
(`ai_status="skipped"`). The live brain never auto-buys those; the
backtest therefore measures the technical/trend layer only.
"""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from backtest import live
from backtest.macro import MacroSeries


@dataclass
class SignalConfig:
    entry_score: int | None = None   # None = live score_to_action BUY
    ai_veto: bool = False            # placeholder hook, never vetoes (no data)


class Bars:
    """Per-symbol OHLCV with O(log n) point-in-time slicing."""

    def __init__(self, bars: dict[str, pd.DataFrame]):
        self.df = bars
        self.idx = {s: df.index.values for s, df in bars.items()}

    def has_bar(self, sym: str, t: date) -> bool:
        idx = self.idx.get(sym)
        if idx is None or len(idx) == 0:
            return False
        ts = np.datetime64(pd.Timestamp(t))
        i = np.searchsorted(idx, ts, side="left")
        return i < len(idx) and idx[i] == ts

    def window(self, sym: str, t: date, days: int = 365) -> pd.DataFrame:
        """Bars in (t - days, t] — never anything after t."""
        idx = self.idx[sym]
        ts = pd.Timestamp(t)
        hi = np.searchsorted(idx, np.datetime64(ts), side="right")
        lo = np.searchsorted(idx, np.datetime64(ts - pd.Timedelta(days=days)), side="right")
        return self.df[sym].iloc[lo:hi]


def in_universe(windows: dict | None, sym: str, t: date) -> bool:
    if windows is None:
        return True
    w = windows.get(sym)
    if w is None:
        return False
    s, e = w
    return (s is None or t >= s) and (e is None or t <= e)


def signals_for_day(
    t: date,
    bars: Bars,
    symbols: list[str],
    fundamentals: dict[str, dict],
    macro: MacroSeries,
    universe_windows: dict | None = None,
) -> list[dict]:
    windows: dict[str, pd.DataFrame] = {}
    screening: dict[str, dict] = {}
    for s in symbols:
        if not in_universe(universe_windows, s, t) or not bars.has_bar(s, t):
            continue
        w = bars.window(s, t)
        if len(w) < 2:
            continue
        windows[s] = w
        try:
            screening[s] = live.screening_features(w)
        except Exception:
            continue
    if not screening:
        return []

    candidates = live.prefilter_candidates(screening)
    m = macro.at(t)
    regime = m["regime"]
    macro_data = {k: v for k, v in m.items() if k != "regime"}

    out = []
    for s in candidates:
        fund = dict(fundamentals.get(s) or {})
        bucket = live.classify_bucket(s, fund)
        if regime == "CRISIS" and bucket == "HIGH_RISK":
            continue  # live pre-score drops these before scoring
        ac = live.asset_class(s, fund)
        tech = live.compute_indicators(windows[s])
        if not tech:
            continue
        score, breakdown = live.compute_score(tech, fund, macro_data, {}, {}, bucket, regime, ac)
        action, reasons = live.tech_only_action(score, bucket, tech, fund, macro_data)
        blocked, block_reasons = live.check_blockers(tech, fund, macro_data)
        out.append({
            "date": t,
            "symbol": s,
            "score": int(score),
            "action": action,
            "reasons": reasons,
            "blocked": bool(blocked),
            "block_reasons": block_reasons,
            "blackout": live.check_entry_blackout(fund),
            "bucket": bucket,
            "asset_type": ac,
            "sector": (fund.get("sector") or "").strip() or None,
            "market_regime": regime,
            "price_at_signal": tech.get("current_price"),
            "technical_data": tech,
            "fundamental_data": fund,
            "breakdown": {k: v for k, v in breakdown.items() if not isinstance(v, dict)},
            "ai_status": "skipped",
        })
    return out


def ai_veto(sig: dict) -> bool:
    """PLACEHOLDER for the live AI veto. Historical AI sentiment/synthesis
    does not exist, so this NEVER vetoes — it exists so a future run with
    archived AI outputs can plug in here. It must not fabricate a verdict."""
    return False


def is_entry(sig: dict, cfg: SignalConfig) -> bool:
    """Would this signal open a long?

    Default: the live tech-only action is BUY (bucket threshold, 90-ceiling,
    blockers, blackout — all live). `entry_score` replaces only the bucket
    threshold; blockers, blackout and the >90 ceiling still come from live.
    """
    if cfg.entry_score is None:
        ok = sig["action"] == "BUY"
    else:
        score, bucket = sig["score"], sig["bucket"]
        thr = (live.settings.score_buy_safe if bucket == "SAFE_INCOME"
               else live.settings.score_buy_risk if bucket == "HIGH_RISK"
               else live.settings.score_buy)
        ceiling_hold = score >= thr and live.score_to_action(score, bucket) != "BUY"
        ok = (score >= cfg.entry_score and not sig["blocked"]
              and not sig["blackout"] and not ceiling_hold)
    if ok and cfg.ai_veto and ai_veto(sig):
        ok = False
    return ok


# ── Parallel driver ─────────────────────────────────────────

_W: dict = {}


def _init_worker(bars, symbols, fundamentals, spy, vix, universe_windows):
    live.quiet_live_logs()
    _W.update(bars=Bars(bars), symbols=symbols, fundamentals=fundamentals,
              macro=MacroSeries(spy, vix), uw=universe_windows)


def _run_chunk(days: list[date]) -> list[dict]:
    out = []
    for t in days:
        out.extend(signals_for_day(t, _W["bars"], _W["symbols"], _W["fundamentals"],
                                   _W["macro"], _W["uw"]))
    return out


def generate_signals(
    days: list[date],
    bars: dict[str, pd.DataFrame],
    symbols: list[str],
    fundamentals: dict[str, dict],
    spy: pd.DataFrame,
    vix: pd.DataFrame | None,
    universe_windows: dict | None = None,
    workers: int = 1,
    progress=None,
) -> dict[date, list[dict]]:
    """Signals keyed by day. Days are independent (tech-only exits never
    depend on the day's signals), so generation parallelises cleanly."""
    by_day: dict[date, list[dict]] = {d: [] for d in days}
    if workers <= 1:
        b, mac = Bars(bars), MacroSeries(spy, vix)
        for i, t in enumerate(days):
            by_day[t] = signals_for_day(t, b, symbols, fundamentals, mac, universe_windows)
            if progress and i % 50 == 0:
                progress(i, len(days))
        return by_day

    n = max(1, min(workers, os.cpu_count() or 1))
    chunk = max(5, len(days) // (n * 8) or 1)
    chunks = [days[i:i + chunk] for i in range(0, len(days), chunk)]
    with ProcessPoolExecutor(
        max_workers=n, initializer=_init_worker,
        initargs=(bars, symbols, fundamentals, spy, vix, universe_windows),
    ) as ex:
        for i, res in enumerate(ex.map(_run_chunk, chunks)):
            for sig in res:
                by_day[sig["date"]].append(sig)
            if progress:
                progress(min((i + 1) * chunk, len(days)), len(days))
    return by_day
