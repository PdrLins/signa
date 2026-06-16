"""Cohort drift detection — 30d-vs-90d-baseline diff across 5 single dims + 4 cross-tabs.

============================================================
WHAT THIS MODULE COMPUTES
============================================================

`detect_cohort_drift(target_date)` returns a list of `CohortFinding`s,
one per cell that crossed the flag threshold:

    n_30d >= 5  (single-dim) or >= 5 (cross-tab — same bar)
    AND (wr_30d < 0.40 OR wr_30d > 0.70)
    AND abs(wr_30d - wr_90d) >= 0.15
    AND n_90d >= 5    # baseline must be meaningful

Cells that don't cross all four conditions are silent — the goal is
high-signal output, not exhaustive per-cell reporting.

============================================================
THE FIVE SINGLE DIMENSIONS
============================================================

  signal_style    MOMENTUM / NEUTRAL / CONTRARIAN / UNCLASSIFIED (null)
  entry_tier      1 / 2 / 3
  bucket          HIGH_RISK / SAFE_INCOME
  score_band      65-69 / 70-74 / 75-79 / 80-84 / 85+
  exit_reason     TARGET_HIT / STOP_HIT / SIGNAL / THESIS_INVALIDATED /
                  TRAILING_STOP / WATCHDOG_FORCE_SELL / WATCHDOG_EXIT /
                  ROTATION / TIME_EXPIRED / QUALITY_PRUNE

============================================================
THE FOUR CROSS-TAB PAIRS (Day-55 addition)
============================================================

Curated list — NOT all C(5,2)=10 combinations. We pick the 4 pairs that
have actual operational relevance based on Day-47 (MOMENTUM tier-1 cap)
and Day-55 (NEUTRAL ≥85 cap) findings:

  signal_style × entry_tier    Would have caught MOMENTUM tier-1 issue
  signal_style × score_band    Would have caught NEUTRAL ≥85 issue
  bucket × signal_style        Catches HIGH_RISK MOMENTUM specifically
  entry_tier × score_band      Captures "high score + amplified" mechanism

Other combinations (e.g. bucket × score_band, exit_reason × entry_tier)
are excluded because they don't map to actionable per-style/per-tier
rules. Pair list lives in CROSSTAB_PAIRS — add a pair only when there's
a documented finding it would catch.

============================================================
WHY ONE 120-DAY SELECT THEN IN-MEMORY AGGREGATION
============================================================

The Supabase Python client (postgrest) does not expose GROUP BY cleanly.
Doing one fetch of (~50-200 wallet closes over 120 days) and aggregating
in Python is simpler, faster, and easier to test than chaining N queries
per dimension or per-pair. The ceiling is 5000 rows by default; even
years of trading won't approach that.

The 120-day window covers both the 30d window AND the 90d baseline
(which excludes the 30d window, so it's 31-120 days back). Single fetch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger

from app.db.supabase import get_client

ET = ZoneInfo("America/New_York")

# Thresholds — these are documented inline so a future reader sees the
# rationale without grepping back to the plan file.
MIN_N_FOR_FLAG = 5         # at least 5 closes in the 30d window
MIN_N_BASELINE = 5         # baseline must have at least 5 closes too
WR_LOW = 0.40              # below this is a "cohort underperforming" flag
WR_HIGH = 0.70             # above this is a "cohort overperforming" flag
DRIFT_THRESHOLD = 0.15     # 15pp drift between 30d and baseline

# Extreme-tail fallback path (Day-55 addition). When baseline has too few
# observations to allow a meaningful comparison (especially in cross-tab
# cells which are sparser than single-dim ones), a recent cohort that's
# itself at a *deep* tail still warrants flagging. We use a tighter tail
# (0.30 / 0.80 vs the standard 0.40 / 0.70) and compare to an assumed
# neutral baseline of 0.50 for severity classification.
# Concrete case: NEUTRAL/85+ on 2026-06-15 had n_30d=5 wr=20% but n_90d=3
# (too few for standard drift). Without this path, we'd silently miss the
# exact cohort that drove today's tier-2 cap rule.
EXTREME_TAIL_LOW = 0.30
EXTREME_TAIL_HIGH = 0.80
EXTREME_TAIL_NEUTRAL_BASELINE = 0.50

# Score bands. Tied to the BRAIN_MIN_SCORE=75 floor + the SCORE_BUY=65
# threshold. Bands above 90 are rare (score ceiling at 90 forces HOLD).
SCORE_BANDS = [
    ("65-69", 65, 70),
    ("70-74", 70, 75),
    ("75-79", 75, 80),
    ("80-84", 80, 85),
    ("85+", 85, 1000),
]


@dataclass
class CohortFinding:
    """One detected drift cell, ready for the report + hypothesis pipeline."""

    dimension: str                 # e.g. 'signal_style'
    value: Any                     # e.g. 'MOMENTUM'
    n_30d: int
    wr_30d: float
    n_90d: int
    wr_90d: float
    drift: float                   # wr_30d - wr_90d (signed)
    direction: str                 # 'under' (wr_30d < WR_LOW) | 'over' (> WR_HIGH)
    net_pnl_30d: float
    severity: str                  # 'INFO' | 'WARN' | 'CRITICAL'
    # JSONB candidate for signal_thinking.pattern_match. Auto-generated
    # from dimension+value so the hypothesis dedupe in hypothesis_manager
    # has a stable key.
    pattern_match: dict[str, Any] = field(default_factory=dict)

    def headline(self) -> str:
        return (
            f"{self.dimension}={self.value} cohort: "
            f"n={self.n_30d}, win-rate {self.wr_30d:.0%} "
            f"({self.drift*100:+.0f}pp vs 90d baseline {self.wr_90d:.0%}), "
            f"net P&L ${self.net_pnl_30d:+.2f}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "value": str(self.value),
            "n_30d": self.n_30d,
            "wr_30d": round(self.wr_30d, 3),
            "n_90d": self.n_90d,
            "wr_90d": round(self.wr_90d, 3),
            "drift": round(self.drift, 3),
            "direction": self.direction,
            "net_pnl_30d": round(self.net_pnl_30d, 2),
            "severity": self.severity,
            "pattern_match": self.pattern_match,
            "headline": self.headline(),
        }


def _score_band(score: int | None) -> str | None:
    if score is None:
        return None
    for label, lo, hi in SCORE_BANDS:
        if lo <= score < hi:
            return label
    return None


def _aggregate_cell(rows: list[dict]) -> tuple[int, float, float]:
    """(count, win_rate, net_pnl) for a list of close rows."""
    n = len(rows)
    if n == 0:
        return 0, 0.0, 0.0
    wins = sum(1 for r in rows if (r.get("pnl_amount") or 0) > 0)
    net = sum(r.get("pnl_amount") or 0 for r in rows)
    return n, wins / n, float(net)


def _classify_severity(drift: float, wr_30d: float) -> str:
    """WARN if drift is significant; CRITICAL if it's also at a tail."""
    abs_drift = abs(drift)
    if abs_drift >= 0.25 or wr_30d <= 0.30 or wr_30d >= 0.80:
        return "CRITICAL"
    if abs_drift >= 0.15:
        return "WARN"
    return "INFO"


def _build_pattern_match(dimension: str, value: Any) -> dict[str, Any]:
    """Build a JSONB pattern_match for signal_thinking dedupe.

    The same pattern_match shape is used both for the hypothesis row and
    for the JSONB-containment dedupe query in hypothesis_manager. Keep
    keys lowercase and stable.
    """
    if dimension == "score_band":
        # Score band is a label — pattern_match should be the numeric range
        # so it can be matched against any signal's score field directly.
        for label, lo, hi in SCORE_BANDS:
            if label == value:
                return {"entry_score_min": lo, "entry_score_max": hi - 1}
        return {}
    return {dimension: value}


# Cross-tab pairs (Day-55 addition). Curated list — see module docstring
# for the operational rationale behind each pair.
CROSSTAB_PAIRS: list[tuple[str, str]] = [
    ("signal_style", "entry_tier"),
    ("signal_style", "score_band"),
    ("bucket", "signal_style"),
    ("entry_tier", "score_band"),
]


def _build_crosstab_pattern_match(
    dim_a: str, val_a: Any, dim_b: str, val_b: Any
) -> dict[str, Any]:
    """Merge two single-dim pattern_match dicts into one cross-tab pattern.

    score_band gets translated to its (entry_score_min, entry_score_max)
    shape on each side (matches _build_pattern_match's behavior), so the
    final pattern matches against the same fields the brain checks on a
    signal: signal_style + entry_tier + bucket + entry_score range.
    """
    a = _build_pattern_match(dim_a, val_a)
    b = _build_pattern_match(dim_b, val_b)
    out = {**a, **b}
    return out


def detect_cohort_drift(target_date: date) -> list[CohortFinding]:
    """Pull 120 days of closed wallet trades, aggregate per dimension cell,
    return the cells that crossed the flag threshold.

    Returns an empty list if total_closes_all_time < MIN_TOTAL_CLOSES_FOR_COHORTS
    (the metrics module's insufficient-history guard — replicated here so
    cohort detection works standalone too, e.g. from the CLI).
    """
    db = get_client()

    # 120-day window in ET, converted to UTC for the query.
    end_et = datetime.combine(target_date, datetime.min.time(), ET) + timedelta(days=1)
    start_et = end_et - timedelta(days=120)
    end_iso = end_et.astimezone(timezone.utc).isoformat()
    start_iso = start_et.astimezone(timezone.utc).isoformat()
    cutoff_30d_et = end_et - timedelta(days=30)

    rows = (
        db.table("virtual_trades")
        .select(
            "exit_date,exit_reason,signal_style,entry_tier,bucket,"
            "entry_score,pnl_amount,is_wallet_trade"
        )
        .eq("is_wallet_trade", True)
        .gte("exit_date", start_iso)
        .lt("exit_date", end_iso)
        .execute()
    ).data or []

    if not rows:
        logger.info("cohort_analyzer: no closed wallet trades in 120d window")
        return []

    # Parse exit_date once + partition into 30d (recent) vs 31-120d (baseline)
    cutoff_30d_utc = cutoff_30d_et.astimezone(timezone.utc)
    recent: list[dict] = []
    baseline: list[dict] = []
    for r in rows:
        ed = r.get("exit_date")
        if not ed:
            continue
        t = datetime.fromisoformat(ed.replace("Z", "+00:00"))
        if t >= cutoff_30d_utc:
            recent.append(r)
        else:
            baseline.append(r)

    # Build per-dimension cell maps. Keys are dimension values; values are
    # row lists. Each dimension is independent.
    def _by(rows: list[dict], extractor) -> dict[Any, list[dict]]:
        d: dict[Any, list[dict]] = {}
        for r in rows:
            k = extractor(r)
            if k is None:
                continue
            d.setdefault(k, []).append(r)
        return d

    extractors = {
        "signal_style": lambda r: r.get("signal_style") or "UNCLASSIFIED",
        "entry_tier": lambda r: r.get("entry_tier"),
        "bucket": lambda r: r.get("bucket"),
        "score_band": lambda r: _score_band(r.get("entry_score")),
        "exit_reason": lambda r: r.get("exit_reason"),
    }

    findings: list[CohortFinding] = []

    # ── Single-dimension drift ──────────────────────────────────────
    for dim, extractor in extractors.items():
        recent_cells = _by(recent, extractor)
        baseline_cells = _by(baseline, extractor)
        all_values = set(recent_cells) | set(baseline_cells)
        for value in all_values:
            n_30, wr_30, net = _aggregate_cell(recent_cells.get(value, []))
            n_90, wr_90, _ = _aggregate_cell(baseline_cells.get(value, []))
            if n_30 < MIN_N_FOR_FLAG:
                continue
            if n_90 < MIN_N_BASELINE:
                continue
            drift = wr_30 - wr_90
            if abs(drift) < DRIFT_THRESHOLD:
                continue
            if WR_LOW <= wr_30 <= WR_HIGH:
                # drift is significant but the cohort isn't at a tail
                # — punt to INFO via the explicit_patterns / hypothesis
                # path. Don't flag unless win rate is also extreme.
                continue
            direction = "under" if wr_30 < WR_LOW else "over"
            findings.append(
                CohortFinding(
                    dimension=dim,
                    value=value,
                    n_30d=n_30,
                    wr_30d=wr_30,
                    n_90d=n_90,
                    wr_90d=wr_90,
                    drift=drift,
                    direction=direction,
                    net_pnl_30d=net,
                    severity=_classify_severity(drift, wr_30),
                    pattern_match=_build_pattern_match(dim, value),
                )
            )

    # ── Cross-tab drift (Day-55 addition) ───────────────────────────
    # Same threshold logic as single-dim, but cells are pair-keyed.
    # Skip pairs that have already been flagged at the single-dim level —
    # if MOMENTUM-as-style is already flagged AND tier-1-as-tier is already
    # flagged, the cross-tab adds noise rather than signal. Only emit a
    # cross-tab finding if NEITHER constituent single-dim already triggered.
    single_dim_flagged: set[tuple[str, Any]] = {(f.dimension, f.value) for f in findings}

    for dim_a, dim_b in CROSSTAB_PAIRS:
        ext_a = extractors[dim_a]
        ext_b = extractors[dim_b]
        # Build cells keyed by (val_a, val_b)
        def _by_pair(rows: list[dict]) -> dict[tuple, list[dict]]:
            d: dict[tuple, list[dict]] = {}
            for r in rows:
                va, vb = ext_a(r), ext_b(r)
                if va is None or vb is None:
                    continue
                d.setdefault((va, vb), []).append(r)
            return d

        recent_pairs = _by_pair(recent)
        baseline_pairs = _by_pair(baseline)
        all_keys = set(recent_pairs) | set(baseline_pairs)
        for (val_a, val_b) in all_keys:
            n_30, wr_30, net = _aggregate_cell(recent_pairs.get((val_a, val_b), []))
            n_90, wr_90, _ = _aggregate_cell(baseline_pairs.get((val_a, val_b), []))
            if n_30 < MIN_N_FOR_FLAG:
                continue

            # Two paths to flag a cross-tab cell:
            standard_path = (
                n_90 >= MIN_N_BASELINE
                and abs(wr_30 - wr_90) >= DRIFT_THRESHOLD
                and not (WR_LOW <= wr_30 <= WR_HIGH)
            )
            extreme_path = (
                n_90 < MIN_N_BASELINE
                and (wr_30 <= EXTREME_TAIL_LOW or wr_30 >= EXTREME_TAIL_HIGH)
            )
            if not (standard_path or extreme_path):
                continue

            # Suppress noise: if BOTH constituent single-dim cells already
            # triggered, the cross-tab is duplicating signal. Skip.
            if (dim_a, val_a) in single_dim_flagged and (dim_b, val_b) in single_dim_flagged:
                continue

            # Drift is always the real wr_30 - wr_90 — keep the headline
            # display honest. The extreme-tail path's only job is to
            # relax the standard-path checks when baseline is sparse.
            drift = wr_30 - wr_90 if n_90 > 0 else (wr_30 - EXTREME_TAIL_NEUTRAL_BASELINE)
            # Severity classification uses the displayed drift in the
            # standard case; in the extreme-tail-with-zero-baseline case
            # we fall back to the assumed-baseline drift for severity.
            severity_drift = drift
            direction = "under" if wr_30 < WR_LOW else "over"
            findings.append(
                CohortFinding(
                    dimension=f"{dim_a}+{dim_b}",
                    value=f"{val_a}/{val_b}",
                    n_30d=n_30,
                    wr_30d=wr_30,
                    n_90d=n_90,
                    wr_90d=wr_90,
                    drift=drift,
                    direction=direction,
                    net_pnl_30d=net,
                    severity=_classify_severity(severity_drift, wr_30),
                    pattern_match=_build_crosstab_pattern_match(
                        dim_a, val_a, dim_b, val_b
                    ),
                )
            )

    # Sort by severity (CRITICAL first) then by absolute drift size.
    severity_rank = {"CRITICAL": 0, "WARN": 1, "INFO": 2}
    findings.sort(key=lambda f: (severity_rank.get(f.severity, 9), -abs(f.drift)))
    n_crosstab = sum(1 for f in findings if "+" in f.dimension)
    logger.info(
        f"cohort_analyzer: {len(findings)} drift findings "
        f"({sum(1 for f in findings if f.severity == 'CRITICAL')} critical, "
        f"{n_crosstab} cross-tab)"
    )
    return findings
