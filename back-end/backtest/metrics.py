"""Performance metrics: equity curve, trades, benchmarks, groupings.

Conventions (stated in the report too):
  * Returns are simple; CAGR uses calendar days / 365.25.
  * Sharpe = mean / std of DAILY returns × √252, risk-free = 0. Daily
    returns are taken on the benchmark's (SPY's) trading calendar, so
    weekend crypto marks don't inflate the observation count.
  * Max drawdown on the same sampled curve (peak-to-trough, %).
  * Benchmarks are buy-and-hold of adjusted prices (dividends included),
    bought at the first session's OPEN and valued at the last CLOSE, no
    costs. XIU.TO is reported in CAD and converted to USD.
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd


def _r(x, n=2):
    if x is None:
        return None
    try:
        if math.isnan(x) or math.isinf(x):
            return None
    except TypeError:
        return x
    return round(float(x), n)


def cagr(start_value: float, end_value: float, days: int) -> float | None:
    if start_value <= 0 or end_value <= 0 or days <= 0:
        return None
    return (end_value / start_value) ** (365.25 / days) - 1


def max_drawdown(curve: pd.Series) -> float:
    """Most negative peak-to-trough move as a fraction (e.g. -0.23)."""
    if curve.empty:
        return 0.0
    peak = curve.cummax()
    return float((curve / peak - 1).min())


def sharpe(curve: pd.Series, periods: int = 252) -> float | None:
    rets = curve.pct_change().dropna()
    if len(rets) < 2:
        return None
    sd = rets.std(ddof=1)
    if not sd or sd == 0 or math.isnan(sd):
        return None
    return float(rets.mean() / sd * math.sqrt(periods))


def on_calendar(curve: pd.Series, calendar: pd.DatetimeIndex | None) -> pd.Series:
    """Resample an equity curve to a trading calendar (last value <= date)."""
    if calendar is None or len(calendar) == 0 or curve.empty:
        return curve
    cal = calendar[(calendar >= curve.index[0]) & (calendar <= curve.index[-1])]
    if len(cal) < 2:
        return curve
    return curve.reindex(curve.index.union(cal)).ffill().reindex(cal)


def equity_metrics(curve: pd.Series, calendar: pd.DatetimeIndex | None = None,
                   invested: pd.Series | None = None) -> dict:
    if curve.empty:
        return {}
    c = on_calendar(curve, calendar)
    days = (curve.index[-1] - curve.index[0]).days
    start_v, end_v = float(curve.iloc[0]), float(curve.iloc[-1])
    out = {
        "start": curve.index[0].date().isoformat(),
        "end": curve.index[-1].date().isoformat(),
        "start_equity": _r(start_v),
        "end_equity": _r(end_v),
        "total_return_pct": _r((end_v / start_v - 1) * 100),
        "cagr_pct": _r((cagr(start_v, end_v, days) or 0) * 100) if days > 0 else None,
        "max_drawdown_pct": _r(max_drawdown(c) * 100),
        "sharpe": _r(sharpe(c)),
        "ann_vol_pct": _r(c.pct_change().dropna().std() * math.sqrt(252) * 100)
        if len(c) > 2 else None,
    }
    if invested is not None and not invested.empty:
        inv = invested.reindex(curve.index).fillna(0.0)
        frac = (inv / curve).clip(lower=0)
        frac = on_calendar(frac, calendar)
        out["exposure_avg_pct"] = _r(float(frac.mean()) * 100)
        out["days_invested_pct"] = _r(float((frac > 0).mean()) * 100)
    return out


def trade_metrics(trades: list[dict], pnl_key: str = "pnl_usd", pct_key: str = "pnl_pct") -> dict:
    n = len(trades)
    if n == 0:
        return {"trades": 0}
    pct = np.array([t[pct_key] for t in trades], dtype=float)
    val = np.array([t.get(pnl_key, t[pct_key]) for t in trades], dtype=float)
    wins, losses = val[val > 0], val[val <= 0]
    wpct, lpct = pct[pct > 0], pct[pct <= 0]
    avg_w = float(wpct.mean()) if len(wpct) else 0.0
    avg_l = float(lpct.mean()) if len(lpct) else 0.0
    out = {
        "trades": n,
        "win_rate_pct": _r(len(wins) / n * 100, 1),
        "avg_win_pct": _r(avg_w),
        "avg_loss_pct": _r(avg_l),
        "payoff_ratio": _r(avg_w / abs(avg_l)) if avg_l < 0 else None,
        "expectancy_pct": _r(float(pct.mean()), 3),
        "median_pct": _r(float(np.median(pct)), 3),
    }
    if pnl_key in trades[0]:
        out["expectancy_usd"] = _r(float(val.mean()))
        out["total_pnl_usd"] = _r(float(val.sum()))
    rs = [t["r_multiple"] for t in trades if t.get("r_multiple") is not None]
    if rs:
        out["avg_r"] = _r(float(np.mean(rs)), 3)
    ex = [t["excess_pct"] for t in trades if t.get("excess_pct") is not None]
    if ex:
        out["avg_excess_vs_spy_pct"] = _r(float(np.mean(ex)), 3)
        out["beat_spy_pct"] = _r(float(np.mean(np.array(ex) > 0)) * 100, 1)
    hd = [t["hold_days"] for t in trades if t.get("hold_days") is not None]
    if hd:
        out["avg_hold_days"] = _r(float(np.mean(hd)), 1)
    reasons: dict[str, int] = {}
    for t in trades:
        reasons[t["exit_reason"]] = reasons.get(t["exit_reason"], 0) + 1
    out["exit_reasons"] = dict(sorted(reasons.items(), key=lambda kv: -kv[1]))
    return out


def group_by(trades: list[dict], key, order: list[str] | None = None, **kw) -> dict[str, dict]:
    groups: dict[str, list[dict]] = {}
    for t in trades:
        k = key(t) if callable(key) else t.get(key)
        groups.setdefault(str(k), []).append(t)
    rank = {k: i for i, k in enumerate(order or [])}
    keys = sorted(groups, key=lambda k: (rank.get(k, len(rank)), k))
    return {k: trade_metrics(groups[k], **kw) for k in keys}


def benchmark(df: pd.DataFrame | None, start: date, end: date,
              calendar: pd.DatetimeIndex | None = None, fx_usd: pd.Series | None = None) -> dict:
    """Buy-and-hold: first OPEN in [start, end] to last CLOSE."""
    if df is None or df.empty:
        return {"available": False}
    w = df[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]
    if len(w) < 2:
        return {"available": False}
    curve = w["Close"].copy()
    curve.iloc[0] = w["Open"].iloc[0]  # entry at the first open
    out = {"available": True, **equity_metrics(curve / curve.iloc[0], calendar)}
    out.pop("start_equity", None)
    out.pop("end_equity", None)
    if fx_usd is not None and not fx_usd.empty:
        rate = fx_usd.reindex(curve.index.union(fx_usd.index)).ffill().reindex(curve.index)
        usd = (curve * rate).dropna()
        if len(usd) >= 2:
            m = equity_metrics(usd / usd.iloc[0], calendar)
            out["usd"] = {k: m[k] for k in ("total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe")}
    return out


def turnover(notional: float, curve: pd.Series) -> float | None:
    """Annualised one-way turnover: (buys+sells)/2 / average equity / years."""
    if curve.empty:
        return None
    years = max((curve.index[-1] - curve.index[0]).days / 365.25, 1e-9)
    avg = float(curve.mean())
    return (notional / 2) / avg / years if avg > 0 else None
