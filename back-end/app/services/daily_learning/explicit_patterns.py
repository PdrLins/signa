"""Explicit pattern matchers — hardcoded checks for things Pedro cares about.

============================================================
WHY HARDCODED INSTEAD OF GENERIC?
============================================================

The cohort_analyzer is the generic pass — it catches anything where a
single-dimension win-rate diverges from baseline. But some patterns
don't fit single-dimension cohort detection:

  - WATCHDOG_CLUSTER: count of an exit_reason FAMILY (not a single
    exit_reason) over a fixed time window
  - REPEAT_LOSER:     a per-SYMBOL pattern, not a per-cohort one
  - DRAWDOWN_3D:      a wallet-level state, not a per-trade one
  - NEW_COHORT_EMERGED: cross-tab pattern (style × tier) that didn't
    exist in baseline

Each gets its own matcher. The Day-48 force-sell cluster (SATS, FN,
ONDS) is the canonical case for WATCHDOG_CLUSTER. The Day-46/48 OSCR
2-cycle losing streak is the canonical case for REPEAT_LOSER.

============================================================
THE FINDING SHAPE
============================================================

Each matcher returns `Finding | None`:

    Finding(
      code='WATCHDOG_CLUSTER',
      severity='WARN' | 'CRITICAL',
      headline='4 WATCHDOG_FORCE_SELL closes in 14d',
      body='## WATCHDOG_CLUSTER ...',  # markdown for the report
      pattern_match={'exit_reason_family': 'WATCHDOG', 'window_days': 14},
      suggestion={'rule_name': 'watchdog_cluster_investigate', 'reasoning': '...'}
    )

DRAWDOWN_3D is the exception: its pattern_match is None because it's a
wallet alert, not a pattern claim. No hypothesis gets created from it.

============================================================
ADDING A NEW MATCHER
============================================================

  1. Add a `match_<name>()` function returning Finding | None
  2. Add it to the MATCHERS list at the bottom
  3. Add a fixture-driven test in tests/test_daily_learning_patterns.py
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from loguru import logger

from app.db.supabase import get_client

ET = ZoneInfo("America/New_York")


@dataclass
class Finding:
    """A finding from one of the explicit matchers."""

    code: str
    severity: str  # 'INFO' | 'WARN' | 'CRITICAL'
    headline: str
    body: str
    pattern_match: dict[str, Any] | None = None  # None = no hypothesis
    suggestion: dict[str, Any] | None = None     # for brain_suggestions
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "headline": self.headline,
            "body": self.body,
            "pattern_match": self.pattern_match,
            "suggestion": self.suggestion,
            "extra": self.extra,
        }


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────

def _et_window(target_date: date, days: int) -> tuple[str, str]:
    end_et = datetime.combine(target_date, datetime.min.time(), ET) + timedelta(days=1)
    start_et = end_et - timedelta(days=days)
    return (
        start_et.astimezone(timezone.utc).isoformat(),
        end_et.astimezone(timezone.utc).isoformat(),
    )


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────
# MATCHER 1: WATCHDOG_CLUSTER
# ─────────────────────────────────────────────────────────────────────────

WATCHDOG_CLUSTER_THRESHOLD = 3   # >=3 watchdog closes in window = cluster
WATCHDOG_CLUSTER_WINDOW_D = 14   # rolling 14-day window
WATCHDOG_EXIT_FAMILY = ("WATCHDOG_FORCE_SELL", "WATCHDOG_EXIT")


def match_watchdog_cluster(target_date: date) -> Finding | None:
    """Flag if 3+ WATCHDOG_FORCE_SELL or WATCHDOG_EXIT closes in last 14 days.

    Day-48 baseline: SATS Day 40, FN Day 44, ONDS Day 48 — 3 in 11 trading
    days, all amplified MOMENTUM, all -8% backstops. The MOMENTUM tier-1
    cap rule that shipped on Day 48 was driven by this exact cluster.
    """
    db = get_client()
    start_iso, end_iso = _et_window(target_date, WATCHDOG_CLUSTER_WINDOW_D)
    rows = (
        db.table("virtual_trades")
        .select("symbol,exit_date,exit_reason,pnl_amount,signal_style,entry_tier")
        .eq("is_wallet_trade", True)
        .in_("exit_reason", list(WATCHDOG_EXIT_FAMILY))
        .gte("exit_date", start_iso)
        .lt("exit_date", end_iso)
        .execute()
    ).data or []
    if len(rows) < WATCHDOG_CLUSTER_THRESHOLD:
        return None
    total_loss = round(sum(r.get("pnl_amount") or 0 for r in rows), 2)
    symbols = sorted({r.get("symbol") for r in rows if r.get("symbol")})
    severity = "CRITICAL" if len(rows) >= 5 else "WARN"
    body = (
        f"### WATCHDOG_CLUSTER ({severity})\n"
        f"{len(rows)} watchdog-family closes in the last {WATCHDOG_CLUSTER_WINDOW_D} "
        f"days ({', '.join(symbols)}). Net P&L from the cluster: ${total_loss:+.2f}. "
        f"These are emergency-backstop or sentiment-collapse exits — high-frequency "
        f"clustering of these usually means a sizing or cohort-selection rule needs "
        f"a look (cf. Day-48 MOMENTUM tier-1 cap)."
    )
    return Finding(
        code="WATCHDOG_CLUSTER",
        severity=severity,
        headline=(
            f"{len(rows)}× watchdog-family closes in {WATCHDOG_CLUSTER_WINDOW_D}d "
            f"({', '.join(symbols)})"
        ),
        body=body,
        pattern_match={
            "exit_reason_family": "WATCHDOG",
            "window_days": WATCHDOG_CLUSTER_WINDOW_D,
            "count_threshold": WATCHDOG_CLUSTER_THRESHOLD,
        },
        suggestion={
            "rule_name": "watchdog_cluster_investigate",
            "reasoning": (
                f"{len(rows)} watchdog-family closes in {WATCHDOG_CLUSTER_WINDOW_D}d — "
                "investigate sizing / cohort selection. See SATS/FN/ONDS on Day 48 "
                "for the canonical case."
            ),
            "symbols": symbols,
            "net_pnl": total_loss,
        },
        extra={"symbols": symbols, "net_pnl": total_loss, "count": len(rows)},
    )


# ─────────────────────────────────────────────────────────────────────────
# MATCHER 2: REPEAT_LOSER
# ─────────────────────────────────────────────────────────────────────────

REPEAT_LOSER_MIN_CONSECUTIVE = 2   # >=2 consecutive losing closes on same symbol
REPEAT_LOSER_GAP_DAYS = 14          # within 14d gap between cycles
REPEAT_LOSER_WINDOW_D = 60          # look back 60 days


def match_repeat_losers(target_date: date) -> Finding | None:
    """Flag symbols with >=2 consecutive losing closes within 14d gap.

    Day-46/48 baseline: OSCR closed -$5.79 Day 43 (TIME_EXPIRED) then
    re-entered same day → -$11.82 Day 48 (TRAILING_STOP). Both with
    thesis=weakening throughout. The 24h post-loss cooldown that shipped
    Day 47 specifically targets the same-day case, but multi-day repeat
    losers slip past that and deserve a separate flag.
    """
    db = get_client()
    start_iso, end_iso = _et_window(target_date, REPEAT_LOSER_WINDOW_D)
    rows = (
        db.table("virtual_trades")
        .select("symbol,entry_date,exit_date,pnl_amount,exit_reason,thesis_last_status")
        .eq("is_wallet_trade", True)
        .gte("exit_date", start_iso)
        .lt("exit_date", end_iso)
        .order("exit_date")
        .execute()
    ).data or []

    by_sym: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        sym = r.get("symbol")
        if sym:
            by_sym[sym].append(r)

    offenders: list[dict[str, Any]] = []
    for sym, trades in by_sym.items():
        if len(trades) < REPEAT_LOSER_MIN_CONSECUTIVE:
            continue
        # Walk consecutive closes; flag if 2+ in a row are losers with gap
        # between cycles <= REPEAT_LOSER_GAP_DAYS.
        run_pnl: list[float] = []
        run_start_date: datetime | None = None
        prev_exit: datetime | None = None
        for t in sorted(trades, key=lambda x: x.get("exit_date") or ""):
            pnl = t.get("pnl_amount") or 0
            this_exit = _parse_dt(t.get("exit_date"))
            this_entry = _parse_dt(t.get("entry_date"))
            if pnl < 0:
                if prev_exit and this_entry and (this_entry - prev_exit).days > REPEAT_LOSER_GAP_DAYS:
                    # gap too long; reset
                    run_pnl = [pnl]
                    run_start_date = this_entry
                else:
                    run_pnl.append(pnl)
                    if run_start_date is None:
                        run_start_date = this_entry
            else:
                run_pnl = []
                run_start_date = None
            prev_exit = this_exit
            if len(run_pnl) >= REPEAT_LOSER_MIN_CONSECUTIVE:
                offenders.append(
                    {
                        "symbol": sym,
                        "consecutive_losses": len(run_pnl),
                        "total_loss": round(sum(run_pnl), 2),
                    }
                )
                # Don't double-count: break inner loop on first hit per symbol
                break

    if not offenders:
        return None
    severity = "WARN" if max(o["consecutive_losses"] for o in offenders) >= 3 else "INFO"
    symbols_text = ", ".join(f"{o['symbol']} ({o['consecutive_losses']}× ${o['total_loss']:+.2f})" for o in offenders)
    body = (
        f"### REPEAT_LOSER ({severity})\n"
        f"{len(offenders)} symbol(s) with consecutive losing closes inside a "
        f"{REPEAT_LOSER_GAP_DAYS}d gap window: {symbols_text}. The 24h post-loss "
        f"cooldown only blocks same-day re-entries — multi-day repeats slip past. "
        f"Worth investigating whether a longer cooldown or per-symbol scoring "
        f"penalty would help."
    )
    return Finding(
        code="REPEAT_LOSER",
        severity=severity,
        headline=f"{len(offenders)} repeat-loser symbol(s) in {REPEAT_LOSER_WINDOW_D}d ({symbols_text})",
        body=body,
        pattern_match={
            "symbols": [o["symbol"] for o in offenders],
            "consecutive_losses_min": REPEAT_LOSER_MIN_CONSECUTIVE,
            "gap_days_max": REPEAT_LOSER_GAP_DAYS,
        },
        suggestion={
            "rule_name": "repeat_loser_investigate",
            "reasoning": "Symbols losing 2+ cycles inside a 14d window. Consider a longer cooldown or per-symbol penalty.",
            "offenders": offenders,
        },
        extra={"offenders": offenders},
    )


# ─────────────────────────────────────────────────────────────────────────
# MATCHER 3: DRAWDOWN_3D (alert only — no hypothesis)
# ─────────────────────────────────────────────────────────────────────────

DRAWDOWN_3D_THRESHOLD_PCT = 5.0


def match_drawdown_3d(target_date: date) -> Finding | None:
    """Flag if cumulative wallet realized P&L drops >5% from trailing 3-day peak.

    This is a WALLET ALERT, not a pattern claim. It does NOT create a
    signal_thinking hypothesis. The reason: wallet drawdown is a STATE,
    not a recurring pattern. The hypothesis system is for cohort-level
    predictions; this is a "hey check this" alert.

    Reads from virtual_snapshots (snapshot_date, brain_cumulative_pnl).
    Returns None if the table is empty or the column is missing.
    """
    db = get_client()
    # Pull last 14 days of cumulative wallet P&L from virtual_snapshots.
    end_date = target_date + timedelta(days=1)
    start_date = end_date - timedelta(days=14)

    try:
        snaps = (
            db.table("virtual_snapshots")
            .select("snapshot_date,brain_cumulative_pnl")
            .gte("snapshot_date", start_date.isoformat())
            .lt("snapshot_date", end_date.isoformat())
            .order("snapshot_date")
            .execute()
        ).data or []
        if not snaps:
            return None
        series = [(s.get("snapshot_date"), s.get("brain_cumulative_pnl") or 0) for s in snaps]
    except Exception:
        return None

    # Find trailing 3-day peak vs current
    if len(series) < 2:
        return None
    current_realized = series[-1][1]
    peak_3d = max(s[1] for s in series[-3:])  # over last 3 snapshots
    if peak_3d <= 0:
        return None
    drop_pct = ((peak_3d - current_realized) / peak_3d) * 100
    if drop_pct < DRAWDOWN_3D_THRESHOLD_PCT:
        return None
    severity = "CRITICAL" if drop_pct >= 10 else "WARN"
    body = (
        f"### DRAWDOWN_3D ({severity})\n"
        f"Wallet realized P&L dropped {drop_pct:.1f}% from trailing 3-day peak "
        f"(${peak_3d:.2f} → ${current_realized:.2f}). No hypothesis created — "
        f"this is a state alert, not a pattern claim. Investigate the closes "
        f"that drove the drawdown (see Today's Closes section)."
    )
    return Finding(
        code="DRAWDOWN_3D",
        severity=severity,
        headline=f"Wallet drawdown {drop_pct:.1f}% in 3d (peak ${peak_3d:.2f} → ${current_realized:.2f})",
        body=body,
        pattern_match=None,   # explicitly no hypothesis
        suggestion={
            "rule_name": "drawdown_3d_investigate",
            "reasoning": f"Wallet realized P&L dropped {drop_pct:.1f}% from trailing 3-day peak. Review the closes that drove it.",
            "drop_pct": round(drop_pct, 2),
            "peak": round(peak_3d, 2),
            "current": round(current_realized, 2),
        },
        extra={"drop_pct": round(drop_pct, 2)},
    )


# ─────────────────────────────────────────────────────────────────────────
# MATCHER 4: NEW_COHORT_EMERGED
# ─────────────────────────────────────────────────────────────────────────

NEW_COHORT_RECENT_MIN = 3   # >=3 trades in last 14d
NEW_COHORT_RECENT_WINDOW = 14
NEW_COHORT_BASELINE_WINDOW = 90


def match_new_cohort_emerged(target_date: date) -> Finding | None:
    """Flag (signal_style, entry_tier) combos that had 0 trades in baseline
    but ≥3 in last 14d.

    Catches regime shifts where the brain starts producing a new kind of
    entry that has no historical performance data. Worth a heads-up so
    Pedro can watch the cohort's first resolutions before they accumulate
    enough variance to skew cohort_analyzer flags.
    """
    db = get_client()
    end_et = datetime.combine(target_date, datetime.min.time(), ET) + timedelta(days=1)
    baseline_start_et = end_et - timedelta(days=NEW_COHORT_BASELINE_WINDOW)
    recent_start_et = end_et - timedelta(days=NEW_COHORT_RECENT_WINDOW)
    baseline_start_iso = baseline_start_et.astimezone(timezone.utc).isoformat()
    recent_start_iso = recent_start_et.astimezone(timezone.utc).isoformat()
    end_iso = end_et.astimezone(timezone.utc).isoformat()

    # Pull baseline (90d back to 14d back) entries
    baseline_entries = (
        db.table("virtual_trades")
        .select("signal_style,entry_tier")
        .eq("is_wallet_trade", True)
        .gte("entry_date", baseline_start_iso)
        .lt("entry_date", recent_start_iso)
        .execute()
    ).data or []
    baseline_keys = {
        (e.get("signal_style") or "UNCLASSIFIED", e.get("entry_tier"))
        for e in baseline_entries
    }

    # Pull recent (last 14d) entries
    recent_entries = (
        db.table("virtual_trades")
        .select("signal_style,entry_tier")
        .eq("is_wallet_trade", True)
        .gte("entry_date", recent_start_iso)
        .lt("entry_date", end_iso)
        .execute()
    ).data or []
    recent_counts: dict[tuple, int] = defaultdict(int)
    for e in recent_entries:
        k = (e.get("signal_style") or "UNCLASSIFIED", e.get("entry_tier"))
        recent_counts[k] += 1

    emerged: list[tuple] = [
        (k, n) for k, n in recent_counts.items()
        if n >= NEW_COHORT_RECENT_MIN and k not in baseline_keys
    ]
    if not emerged:
        return None
    cohorts_text = ", ".join(
        f"({style},tier={tier},n={n})" for (style, tier), n in emerged
    )
    body = (
        f"### NEW_COHORT_EMERGED (INFO)\n"
        f"{len(emerged)} (signal_style, entry_tier) combo(s) appeared in the last "
        f"{NEW_COHORT_RECENT_WINDOW} days with no historical record in the prior "
        f"{NEW_COHORT_BASELINE_WINDOW}d baseline: {cohorts_text}. Watch first "
        f"resolutions before treating performance metrics as meaningful."
    )
    return Finding(
        code="NEW_COHORT_EMERGED",
        severity="INFO",
        headline=f"{len(emerged)} new cohort(s) emerged: {cohorts_text}",
        body=body,
        pattern_match={
            "new_cohorts": [
                {"signal_style": s, "entry_tier": t, "recent_count": n}
                for (s, t), n in emerged
            ]
        },
        suggestion=None,
        extra={"cohorts": [(s, t, n) for (s, t), n in emerged]},
    )


# ─────────────────────────────────────────────────────────────────────────
# DISPATCH
# ─────────────────────────────────────────────────────────────────────────

# Each matcher takes (target_date,) and returns Finding | None.
MATCHERS: list[Callable[[date], Optional[Finding]]] = [
    match_watchdog_cluster,
    match_repeat_losers,
    match_drawdown_3d,
    match_new_cohort_emerged,
]


def run_explicit_patterns(target_date: date) -> list[Finding]:
    """Run all matchers; return non-None findings.

    Individual matcher failures are caught and logged — one matcher
    exception doesn't kill the whole daily report.
    """
    findings: list[Finding] = []
    for matcher in MATCHERS:
        try:
            f = matcher(target_date)
            if f is not None:
                findings.append(f)
        except Exception as e:
            logger.warning(f"explicit_patterns: matcher {matcher.__name__} failed: {e}")
    logger.info(f"explicit_patterns: {len(findings)} findings")
    return findings
