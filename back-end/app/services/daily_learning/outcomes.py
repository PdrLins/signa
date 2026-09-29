"""Counterfactual-outcome analytics for the daily learning loop.

Input: candidate_outcomes rows (migration 008, filled by
app/services/decision_outcomes.py). Output: plain dicts the digest renders
and the orchestrator turns into brain_suggestions. Pure — no DB, no I/O.

Statistical discipline (same as stats.py):
  * A group is only *described* below MIN_OBSERVATIONS; claims (flags,
    verdicts, suggestions) need n >= MIN_OBSERVATIONS AND a 95% interval
    that excludes zero.
  * Observations are de-duplicated to one per (symbol, ET signal day)
    inside every group — the same ticker scanned 5x a day is one
    observation, not five. Forward windows of consecutive days still
    overlap, so intervals remain somewhat optimistic; treat borderline
    results as "investigate", which is all a suggestion ever is.
  * Suggestions are INVESTIGATE rows only — nothing here changes a rule.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from app.services.daily_learning.stats import MIN_OBSERVATIONS, bootstrap_mean_ci, wilson_interval

ET = ZoneInfo("America/New_York")
CALIBRATION_EDGES: tuple[float, ...] = (0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0000001)
CALIBRATION_MIN_BUCKET_N = 10
DEFAULT_HORIZON = 10
N_RESAMPLES = 2000
_SEED = 1729


# ============================================================
# Basic helpers
# ============================================================

def _num(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _signal_day(row: Mapping) -> str:
    v = row.get("signal_at")
    try:
        dt = v if isinstance(v, datetime) else datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ET).date().isoformat()
    except (TypeError, ValueError):
        return str(v)[:10]


def dedupe_symbol_day(rows: Iterable[Mapping]) -> list[Mapping]:
    """First row per (symbol, ET signal date), in signal_at order."""
    ordered = sorted(rows, key=lambda r: str(r.get("signal_at") or ""))
    seen: set[tuple] = set()
    out = []
    for r in ordered:
        key = (r.get("symbol"), _signal_day(r))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _bootstrap_means(values: Sequence[float], n_resamples: int, seed: int):
    import numpy as np
    arr = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(arr), size=(n_resamples, len(arr)))
    return arr[idx].mean(axis=1)


def mean_ci(values: Sequence[float], *, n_resamples: int = N_RESAMPLES, seed: int = _SEED) -> tuple[float, float]:
    """95% percentile-bootstrap CI of the mean (nan, nan) for n < 2."""
    vals = [float(v) for v in values]
    if len(vals) < 2:
        return float("nan"), float("nan")
    try:
        import numpy as np
        means = _bootstrap_means(vals, n_resamples, seed)
        return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))
    except ImportError:  # pragma: no cover - numpy ships with pandas
        return bootstrap_mean_ci(vals, n_resamples=n_resamples, seed=seed)


def diff_ci(a: Sequence[float], b: Sequence[float], *, n_resamples: int = N_RESAMPLES,
            seed: int = _SEED) -> tuple[float, float]:
    """95% bootstrap CI of mean(a) - mean(b) (independent resampling)."""
    if len(a) < 2 or len(b) < 2:
        return float("nan"), float("nan")
    import numpy as np
    d = _bootstrap_means(a, n_resamples, seed) - _bootstrap_means(b, n_resamples, seed + 1)
    return float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


def summarize(values: Sequence[float], *, min_n: int = MIN_OBSERVATIONS) -> dict:
    """n, mean, 95% CI, whether the sample is large enough to claim anything,
    and the sign of the CI ('pos' / 'neg' / None) when it excludes zero."""
    vals = [float(v) for v in values if _num(v) is not None]
    n = len(vals)
    out = {"n": n, "mean": (sum(vals) / n) if n else None, "ci": None,
           "sufficient": n >= min_n, "excludes_zero": None}
    if n >= 2:
        lo, hi = mean_ci(vals)
        out["ci"] = (lo, hi)
        if n >= min_n:
            out["excludes_zero"] = "pos" if lo > 0 else ("neg" if hi < 0 else None)
    return out


def _values(rows: Iterable[Mapping], field: str) -> list[float]:
    out = []
    for r in dedupe_symbol_day(rows):
        v = _num(r.get(field))
        if v is not None:
            out.append(v)
    return out


# ============================================================
# 1. Skip-reason effectiveness
# ============================================================

_NUMERIC_TOKEN = re.compile(r"^-?\d+(\.\d+)?[a-z%]{0,3}$", re.IGNORECASE)


def normalize_skip_reason(reason: str | None) -> str:
    """Collapse parametrised reasons into their gate name.

    'rr_below_min_1.40' -> 'rr_below_min', 'max_open_positions_8' ->
    'max_open_positions', 'reentry_cooldown_3d' -> 'reentry_cooldown',
    'sector_cap_technology' -> 'sector_cap'.
    """
    if not reason:
        return "unknown"
    reason = str(reason).strip()
    prefix = ""
    if ":" in reason:
        prefix, reason = reason.split(":", 1)
        prefix += ":"
    tokens = [t for t in reason.split("_") if t and not _NUMERIC_TOKEN.match(t)]
    name = "_".join(tokens) or "unknown"
    if name.startswith("sector_cap"):
        name = "sector_cap"
    return prefix + name


def skip_reason_effectiveness(rows: Iterable[Mapping], horizon: int = DEFAULT_HORIZON) -> dict:
    """Per SKIP gate: forward excess return of the candidates it blocked.

    A gate whose skipped candidates have mean excess > 0 with a CI above
    zero is keeping the brain out of winners (verdict 'costing'); a CI
    below zero means the gate protects ('protective'). ENTER rows are the
    baseline for comparison.
    """
    field = f"excess_ret_{horizon}d"
    rows = [r for r in rows if _num(r.get(field)) is not None]
    groups: dict[str, list[Mapping]] = {}
    entered: list[Mapping] = []
    for r in rows:
        if r.get("brain_decision") == "SKIP":
            groups.setdefault(normalize_skip_reason(r.get("skip_reason")), []).append(r)
        elif r.get("brain_decision") == "ENTER":
            entered.append(r)
    gates = []
    for name, grp in groups.items():
        s = summarize(_values(grp, field))
        s["reason"] = name
        s["verdict"] = (
            "costing" if s["excludes_zero"] == "pos"
            else "protective" if s["excludes_zero"] == "neg"
            else ("inconclusive" if s["sufficient"] else f"insufficient data (n={s['n']})")
        )
        gates.append(s)
    gates.sort(key=lambda g: -g["n"])
    return {"horizon": horizon, "gates": gates, "entered": summarize(_values(entered, field))}


# ============================================================
# 2. p_win calibration
# ============================================================

def _bucket_label(lo: float, hi: float) -> str:
    return f"<{hi:.1f}" if lo == 0.0 else f"{lo:.1f}-{min(hi, 1.0):.1f}"


def calibration_table(rows: Iterable[Mapping], horizon: int = 5, *,
                      min_bucket_n: int = CALIBRATION_MIN_BUCKET_N,
                      min_overall_n: int = MIN_OBSERVATIONS) -> dict:
    """Reliability of p_win vs realised wins at `horizon`.

    Two outcome definitions: raw win (fwd_ret > 0) and benchmark win
    (excess_ret > 0). NB p_win is the model's P(target before stop), so
    perfect calibration against "up after N days" is not expected — the
    table shows whether higher p_win at least ranks better outcomes.
    Buckets with n < min_bucket_n are hidden; overall Brier scores are
    reported only for n >= min_overall_n.
    """
    fwd_f, exc_f = f"fwd_ret_{horizon}d", f"excess_ret_{horizon}d"
    obs = []
    for r in dedupe_symbol_day(r for r in rows if _num(r.get("p_win")) is not None
                               and _num(r.get(fwd_f)) is not None):
        p = min(max(_num(r["p_win"]), 0.0), 1.0)
        fwd = _num(r.get(fwd_f))
        exc = _num(r.get(exc_f))
        obs.append((p, 1 if fwd > 0 else 0, None if exc is None else (1 if exc > 0 else 0)))

    buckets, hidden = [], 0
    for lo, hi in zip(CALIBRATION_EDGES[:-1], CALIBRATION_EDGES[1:]):
        b = [o for o in obs if lo <= o[0] < hi]
        if not b:
            continue
        if len(b) < min_bucket_n:
            hidden += 1
            continue
        n = len(b)
        wins = sum(o[1] for o in b)
        exc_obs = [o[2] for o in b if o[2] is not None]
        exc_wins = sum(exc_obs)
        buckets.append({
            "bucket": _bucket_label(lo, hi),
            "n": n,
            "mean_p_win": sum(o[0] for o in b) / n,
            "win_rate": wins / n,
            "win_ci": wilson_interval(wins, n),
            "excess_win_rate": (exc_wins / len(exc_obs)) if exc_obs else None,
            "excess_win_ci": wilson_interval(exc_wins, len(exc_obs)) if exc_obs else None,
        })

    overall = None
    n = len(obs)
    if n >= min_overall_n:
        base = sum(o[1] for o in obs) / n
        exc_obs = [o for o in obs if o[2] is not None]
        overall = {
            "n": n,
            "brier": sum((o[0] - o[1]) ** 2 for o in obs) / n,
            # climatology reference: always forecasting the base rate
            "brier_base_rate": sum((base - o[1]) ** 2 for o in obs) / n,
            "brier_excess": (sum((o[0] - o[2]) ** 2 for o in exc_obs) / len(exc_obs)) if exc_obs else None,
            "mean_p_win": sum(o[0] for o in obs) / n,
            "win_rate": base,
        }
    return {"horizon": horizon, "n": n, "buckets": buckets, "hidden_buckets": hidden, "overall": overall}


def brier_score(pairs: Iterable[tuple[float, int]]) -> float | None:
    """Mean squared error between probability and 0/1 outcome."""
    pairs = list(pairs)
    if not pairs:
        return None
    return sum((p - o) ** 2 for p, o in pairs) / len(pairs)


# ============================================================
# 3. Routine (Sonnet) vs decision (Opus) model
# ============================================================

def overturn_stats(rows: Iterable[Mapping], horizon: int = DEFAULT_HORIZON, *,
                   min_n: int = MIN_OBSERVATIONS) -> dict:
    """Escalated routine BUYs: decision-model vetoed vs confirmed.

    decision_overturned TRUE = the decision model said something other
    than the routine BUY (veto); FALSE = it confirmed. If vetoed candidates
    go on to beat confirmed ones, the veto is costing money.
    """
    rows = [r for r in rows if r.get("decision_overturned") is not None]
    vetoed = [r for r in rows if r.get("decision_overturned") is True]
    confirmed = [r for r in rows if r.get("decision_overturned") is False]
    out: dict = {"horizon": horizon, "metrics": {}}
    for metric in ("fwd_ret", "excess_ret"):
        field = f"{metric}_{horizon}d"
        v_vals, c_vals = _values(vetoed, field), _values(confirmed, field)
        v, c = summarize(v_vals, min_n=min_n), summarize(c_vals, min_n=min_n)
        entry = {"vetoed": v, "confirmed": c, "diff": None, "diff_ci": None}
        if v["n"] < min_n or c["n"] < min_n:
            entry["verdict"] = f"insufficient data (n={v['n']} vetoed / {c['n']} confirmed)"
            entry["direction"] = None
        else:
            entry["diff"] = c["mean"] - v["mean"]
            lo, hi = diff_ci(c_vals, v_vals)
            entry["diff_ci"] = (lo, hi)
            if lo > 0:
                entry["direction"] = "veto_helps"
                entry["verdict"] = (
                    f"decision model adds value: confirmed beat vetoed by "
                    f"{entry['diff'] * 100:+.2f}pp (CI {lo * 100:+.2f}..{hi * 100:+.2f})"
                )
            elif hi < 0:
                entry["direction"] = "veto_costs"
                entry["verdict"] = (
                    f"decision model vetoes are costing: vetoed beat confirmed by "
                    f"{-entry['diff'] * 100:+.2f}pp (CI {-hi * 100:+.2f}..{-lo * 100:+.2f})"
                )
            else:
                entry["direction"] = None
                entry["verdict"] = "no significant difference between vetoed and confirmed"
        out["metrics"][metric] = entry
    return out


# ============================================================
# 4. AI-status cohorts
# ============================================================

AI_STATUS_ORDER = ("validated", "low_confidence", "rejected", "failed", "skipped")


def ai_status_cohorts(rows: Iterable[Mapping]) -> dict:
    """Forward excess returns per ai_status at every horizon."""
    rows = list(rows)
    cohorts = []
    statuses = [s for s in AI_STATUS_ORDER if any(r.get("ai_status") == s for r in rows)]
    statuses += sorted({r.get("ai_status") for r in rows if r.get("ai_status")} - set(statuses))
    for st in statuses:
        grp = [r for r in rows if r.get("ai_status") == st]
        cohorts.append({
            "ai_status": st,
            **{f"excess_{h}d": summarize(_values(grp, f"excess_ret_{h}d")) for h in (5, 10, 20)},
        })
    return {"cohorts": cohorts}


# ============================================================
# Combined report + suggestions
# ============================================================

def build_outcome_report(rows: Iterable[Mapping], horizon: int = DEFAULT_HORIZON) -> dict:
    rows = list(rows)
    filled = [r for r in rows if _num(r.get(f"excess_ret_{horizon}d")) is not None]
    return {
        "rows": len(rows),
        "filled": len(filled),
        "horizon": horizon,
        "skip_reasons": skip_reason_effectiveness(rows, horizon),
        "calibration": calibration_table(rows, 5),
        "overturn": overturn_stats(rows, horizon),
        "ai_status": ai_status_cohorts(rows),
    }


def outcome_suggestions(report: Mapping) -> list[dict]:
    """INVESTIGATE suggestions — only where n >= 30 AND the CI excludes zero
    in the costly direction. Never auto-applied."""
    out: list[dict] = []
    h = report.get("horizon", DEFAULT_HORIZON)
    for g in (report.get("skip_reasons") or {}).get("gates", []):
        if g.get("verdict") == "costing":
            lo, hi = g["ci"]
            out.append({
                "rule_name": f"outcome_skip_gate_{g['reason']}",
                "reasoning": (
                    f"SKIP gate '{g['reason']}' blocked {g['n']} candidates whose "
                    f"{h}d excess return vs SPY averaged {g['mean'] * 100:+.2f}% "
                    f"(95% CI {lo * 100:+.2f}..{hi * 100:+.2f}%). The gate is keeping "
                    f"the brain out of outperformers — investigate its threshold."
                ),
                "proposed": {"kind": "skip_gate", **_jsonable(g)},
            })
    ex = ((report.get("overturn") or {}).get("metrics") or {}).get("excess_ret") or {}
    if ex.get("direction") == "veto_costs":
        out.append({
            "rule_name": "outcome_decision_model_veto",
            "reasoning": f"Routine-vs-decision model ({h}d excess): {ex['verdict']}.",
            "proposed": {"kind": "decision_model_veto", **_jsonable(ex)},
        })
    for c in (report.get("ai_status") or {}).get("cohorts", []):
        s = c.get(f"excess_{h}d") or {}
        bad = (c["ai_status"] == "validated" and s.get("excludes_zero") == "neg") or (
            c["ai_status"] in ("rejected", "skipped") and s.get("excludes_zero") == "pos")
        if bad:
            lo, hi = s["ci"]
            out.append({
                "rule_name": f"outcome_ai_status_{c['ai_status']}",
                "reasoning": (
                    f"ai_status='{c['ai_status']}' candidates (n={s['n']}) returned "
                    f"{s['mean'] * 100:+.2f}% vs SPY over {h}d "
                    f"(95% CI {lo * 100:+.2f}..{hi * 100:+.2f}%) — the AI verdict is "
                    f"pointing the wrong way for this cohort; investigate."
                ),
                "proposed": {"kind": "ai_status_cohort", "ai_status": c["ai_status"], **_jsonable(s)},
            })
    return out


def _jsonable(d: Mapping) -> dict:
    """Round floats and turn tuples into lists so the dict fits a JSONB column."""
    def conv(v):
        if isinstance(v, float):
            return None if not math.isfinite(v) else round(v, 6)
        if isinstance(v, (tuple, list)):
            return [conv(x) for x in v]
        if isinstance(v, Mapping):
            return {k: conv(x) for k, x in v.items()}
        return v
    return {k: conv(v) for k, v in d.items()}
