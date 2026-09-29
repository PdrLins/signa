"""Per-symbol, non-overlapping signal study (score bands / buckets / actions).

Independent of portfolio capacity: for each symbol, walk its candidate
signals in date order; whenever the symbol is FREE (no open study trade,
i.e. the signal day is after the previous study trade's exit day) open a
one-share study trade at the next bar's open with the live slippage and
live stop/target levels, and exit it with the same live exit replay as
the portfolio. A position occupies its symbol, so trades never overlap
and consecutive-day signals are not double-counted.

Every candidate signal is eligible (BUY, HOLD, AVOID, blocked), so the
study shows whether the score and the blockers actually separate outcomes.
Returns are net of slippage on both sides (commission is per-fill dollars
and size-dependent, so it is excluded here; the portfolio includes it).
Each trade also carries SPY's return over the same holding window.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from backtest import execution, live

BANDS = [(0, 50, "<50"), (50, 55, "50-54"), (55, 60, "55-59"), (60, 65, "60-64"),
         (65, 70, "65-69"), (70, 75, "70-74"), (75, 80, "75-79"), (80, 90, "80-89"),
         (90, 101, "90+")]


def band(score: int) -> str:
    for lo, hi, name in BANDS:
        if lo <= score < hi:
            return name
    return "?"


def signal_class(sig: dict) -> str:
    if sig["blocked"]:
        return "BLOCKED"
    return sig["action"]


def _spy_px(spy: pd.DataFrame, d: date, col: str) -> float | None:
    s = spy[col]
    s = s[s.index <= pd.Timestamp(d)]
    return float(s.iloc[-1]) if not s.empty else None


def run_study(signals_by_day: dict[date, list[dict]], bars: dict[str, pd.DataFrame],
              spy: pd.DataFrame, end: date) -> list[dict]:
    by_sym: dict[str, list[dict]] = {}
    for d in sorted(signals_by_day):
        for sig in signals_by_day[d]:
            by_sym.setdefault(sig["symbol"], []).append(sig)

    trades = []
    for sym, sigs in by_sym.items():
        df = bars[sym]
        idx = df.index.values
        o, h, low, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
        free_after: date | None = None
        for sig in sigs:
            t = sig["date"]
            if free_after is not None and t <= free_after:
                continue
            i = int(np.searchsorted(idx, np.datetime64(pd.Timestamp(t)), side="right"))
            if i >= len(idx):
                break
            d_entry = pd.Timestamp(idx[i]).date()
            if d_entry > end:
                break
            fill = live.apply_slippage(o[i], "BUY", sym)
            levels = live.compute_entry_levels(sig, fill)
            if levels["reason"]:
                continue
            pos = execution.new_position(sym, d_entry, fill, levels)
            exit_reason, ref, d_exit = None, None, None
            j = i
            while j < len(idx):
                d = pd.Timestamp(idx[j]).date()
                if d > end:
                    break
                r = execution.step_bar(pos, (o[j], h[j], low[j], c[j]), d, entered_today=(j == i))
                if r:
                    exit_reason, ref, d_exit = r[0], r[1], d
                    break
                j += 1
            if exit_reason is None:
                j = min(j, len(idx) - 1)
                while j > i and pd.Timestamp(idx[j]).date() > end:
                    j -= 1
                exit_reason, ref, d_exit = "END_OF_WINDOW", c[j], pd.Timestamp(idx[j]).date()
            exit_fill = live.apply_slippage(ref, "SELL", sym)
            ret = (exit_fill - fill) / fill * 100
            s0, s1 = _spy_px(spy, d_entry, "Open"), _spy_px(spy, d_exit, "Close")
            spy_ret = (s1 / s0 - 1) * 100 if s0 and s1 else None
            risk = fill - levels["stop"]
            trades.append({
                "symbol": sym, "signal_date": t.isoformat(), "entry_date": d_entry.isoformat(),
                "exit_date": d_exit.isoformat(), "score": sig["score"], "band": band(sig["score"]),
                "bucket": sig["bucket"], "class": signal_class(sig), "regime": sig["market_regime"],
                "ret_pct": round(ret, 3),
                "r_multiple": round((exit_fill - fill) / risk, 3) if risk > 0 else None,
                "spy_ret_pct": round(spy_ret, 3) if spy_ret is not None else None,
                "excess_pct": round(ret - spy_ret, 3) if spy_ret is not None else None,
                "exit_reason": exit_reason, "hold_days": (d_exit - d_entry).days,
            })
            free_after = d_exit
    return trades
