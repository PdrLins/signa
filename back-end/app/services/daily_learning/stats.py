"""Small-sample statistics for the learning loop.

Why this exists: the pre-reset loop graduated "knowledge" from 5
observations and flagged cohorts at n=5. A 4/5 win rate has a 95%
interval of roughly [38%, 96%] — it says almost nothing. Everything the
loop now concludes must clear:

  * a minimum sample (MIN_OBSERVATIONS = 30), AND
  * an interval that excludes the null: the Wilson interval on the win
    rate and/or a bootstrap interval on EXPECTANCY (mean P&L per trade).

Expectancy is the quantity that matters for money: a 40% win rate with
3:1 payoffs is a great strategy; a 70% win rate with 1:4 payoffs is not.

Pure functions, no DB — safe to import anywhere (pattern_stats uses them).
"""

from __future__ import annotations

import math
import random
from typing import Sequence

MIN_OBSERVATIONS = 30
Z_95 = 1.959963984540054


def wilson_interval(successes: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion. (0, 1) when n == 0."""
    if n <= 0:
        return 0.0, 1.0
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def expectancy(values: Sequence[float]) -> float:
    """Mean P&L per trade (0.0 for an empty sample)."""
    return sum(values) / len(values) if values else 0.0


def bootstrap_mean_ci(
    values: Sequence[float],
    *,
    n_resamples: int = 2000,
    alpha: float = 0.05,
    seed: int = 1729,
) -> tuple[float, float]:
    """Percentile bootstrap CI for the mean. Deterministic (fixed seed).

    Returns (nan, nan) for fewer than 2 values.
    """
    vals = [float(v) for v in values]
    n = len(vals)
    if n < 2:
        return float("nan"), float("nan")
    rng = random.Random(seed)
    means = []
    for _ in range(n_resamples):
        s = 0.0
        for _ in range(n):
            s += vals[rng.randrange(n)]
        means.append(s / n)
    means.sort()
    lo = means[int((alpha / 2) * n_resamples)]
    hi = means[min(n_resamples - 1, int((1 - alpha / 2) * n_resamples))]
    return lo, hi


def evidence_verdict(
    pnls: Sequence[float],
    expected: str,
    *,
    min_n: int = MIN_OBSERVATIONS,
) -> dict:
    """Decide whether a hypothesis is supported by its matched trades.

    `expected` is 'loss' (cohort under-performs) or 'win' (over-performs).
    Verdict:
      'insufficient' — fewer than min_n observations,
      'supported'    — expectancy CI entirely on the predicted side of 0
                        AND the Wilson interval of the predicted outcome
                        rate lies above 50%,
      'refuted'      — expectancy CI entirely on the OPPOSITE side of 0,
      'inconclusive' — otherwise.
    """
    n = len(pnls)
    out = {"n": n, "expectancy": expectancy(pnls), "verdict": "insufficient"}
    if n < min_n:
        return out
    wins = sum(1 for v in pnls if v > 0)
    hits = wins if expected == "win" else n - wins
    w_lo, w_hi = wilson_interval(hits, n)
    lo, hi = bootstrap_mean_ci(pnls)
    out.update({"hit_rate": hits / n, "wilson": (w_lo, w_hi), "expectancy_ci": (lo, hi)})
    if expected == "win":
        supported, refuted = lo > 0, hi < 0
    else:
        supported, refuted = hi < 0, lo > 0
    if supported and w_lo > 0.5:
        out["verdict"] = "supported"
    elif refuted:
        out["verdict"] = "refuted"
    else:
        out["verdict"] = "inconclusive"
    return out
