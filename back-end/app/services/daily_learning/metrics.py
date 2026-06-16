"""Daily metrics — the 'day at a glance' snapshot for the daily learning loop.

============================================================
WHAT THIS MODULE COMPUTES
============================================================

`compute_daily_metrics(target_date)` returns a dict that captures the
state of the wallet at end-of-target_date:

    {
      "target_date": date,
      "closes": {
        "count": 4, "wins": 3, "losses": 1, "net_pnl": 87.40,
        "by_exit_reason": {"TRAILING_STOP": 2, ...},
        "list": [{symbol, exit_reason, pnl_amount, pnl_pct}, ...],
      },
      "entries": {
        "count": 2,
        "by_tier": {1: 1, 2: 1},
        "by_style": {"NEUTRAL": 1, "MOMENTUM": 1},
        "list": [{symbol, entry_score, signal_style, entry_tier,
                  position_size_usd}, ...],
      },
      "wallet": {
        "cumulative_realized": 403.94,
        "daily_pnl": 87.40,
        "daily_pct": 0.81,           # vs prior day cumulative
        "rolling_7d_pnl": ..., "rolling_7d_pct": 3.4,
        "rolling_30d_pnl": ..., "rolling_30d_pct": 6.8,
      },
      "open": {
        "count": 11, "deployed_usd": 6_500, "unrealized_pnl": 210,
      },
      "regime": "VOLATILE",           # most recent scan's market_regime
      "vix": 22.4,                    # from latest macro snapshot if present
      "warning": None,                # 'insufficient_history' if <25 closes
    }

============================================================
DATA SOURCES
============================================================

All from existing tables — no new schema needed:

  virtual_trades                wallet closes + opens + open positions
  scans                         latest market_regime (for regime label)
  portfolio_snapshots           rolling wallet curve

============================================================
WHY 'TARGET_DATE' INSTEAD OF 'TODAY'
============================================================

The CLI offline-replay flag `--date 2026-06-04` requires every step to
accept an explicit target_date. This makes the loop deterministic and
backfillable — you can re-run any past day's analysis against current
data and produce a report identical to (or improved over) what the
live loop would have written.

All time windows are anchored on target_date in America/New_York. The
"end of target_date" is 23:59:59 ET, so a 5:30 PM ET fire on the same
target_date already sees the day's closes and the AFTER_CLOSE scan.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger

from app.db.supabase import get_client

# Below this threshold (closed wallet trades all-time), cohort analysis is
# meaningless and gets skipped via warning='insufficient_history'. The
# daily report still emits — metrics + explicit patterns still run.
MIN_TOTAL_CLOSES_FOR_COHORTS = 25

ET = ZoneInfo("America/New_York")


def _et_day_bounds_utc(target_date: date) -> tuple[str, str]:
    """Return (start_iso, end_iso) in UTC for the ET calendar day.

    A "day" anchored on ET is what Pedro reads on the journal — using UTC
    naive bounds would split trades across days depending on when the
    market close UTC timestamp falls.
    """
    start_et = datetime.combine(target_date, datetime.min.time(), ET)
    end_et = start_et + timedelta(days=1)
    return (
        start_et.astimezone(timezone.utc).isoformat(),
        end_et.astimezone(timezone.utc).isoformat(),
    )


def _safe_sum(rows: list[dict], key: str) -> float:
    return float(sum((r.get(key) or 0) for r in rows))


def compute_daily_metrics(target_date: date) -> dict[str, Any]:
    """Build the day-at-a-glance dict for the orchestrator + report.

    Tolerant to missing data: if no closes happened, returns counts=0 and
    net_pnl=0 rather than raising. The warning field surfaces structural
    gaps (insufficient history for cohort analysis) so downstream steps
    can short-circuit cleanly.
    """
    db = get_client()
    start_iso, end_iso = _et_day_bounds_utc(target_date)

    # ── Today's closes ────────────────────────────────────────────────
    closes = (
        db.table("virtual_trades")
        .select(
            "symbol,exit_date,exit_reason,pnl_amount,pnl_pct,"
            "entry_tier,signal_style,bucket,is_wallet_trade,entry_score"
        )
        .eq("is_wallet_trade", True)
        .gte("exit_date", start_iso)
        .lt("exit_date", end_iso)
        .order("exit_date")
        .execute()
    ).data or []

    wins = sum(1 for c in closes if (c.get("pnl_amount") or 0) > 0)
    losses = sum(1 for c in closes if (c.get("pnl_amount") or 0) < 0)
    net_pnl = round(_safe_sum(closes, "pnl_amount"), 2)

    by_exit_reason: dict[str, int] = {}
    for c in closes:
        r = c.get("exit_reason") or "UNKNOWN"
        by_exit_reason[r] = by_exit_reason.get(r, 0) + 1

    # ── Today's entries ───────────────────────────────────────────────
    entries = (
        db.table("virtual_trades")
        .select(
            "symbol,entry_date,entry_score,signal_style,entry_tier,"
            "bucket,position_size_usd,is_wallet_trade"
        )
        .eq("is_wallet_trade", True)
        .gte("entry_date", start_iso)
        .lt("entry_date", end_iso)
        .order("entry_date")
        .execute()
    ).data or []

    by_tier: dict[int, int] = {}
    by_style: dict[str, int] = {}
    for e in entries:
        t = e.get("entry_tier") or 0
        s = e.get("signal_style") or "UNCLASSIFIED"
        by_tier[t] = by_tier.get(t, 0) + 1
        by_style[s] = by_style.get(s, 0) + 1

    # ── Wallet cumulative (all-time + rolling) ────────────────────────
    # Single SELECT all wallet closes; compute cumulative + 7d/30d in memory.
    all_closes = (
        db.table("virtual_trades")
        .select("exit_date,pnl_amount")
        .eq("is_wallet_trade", True)
        .not_.is_("exit_date", "null")
        .order("exit_date")
        .execute()
    ).data or []
    total_pnl_all = round(_safe_sum(all_closes, "pnl_amount"), 2)

    end_dt = datetime.combine(target_date, datetime.min.time(), ET) + timedelta(days=1)
    end_utc = end_dt.astimezone(timezone.utc)
    seven_d_utc = (end_dt - timedelta(days=7)).astimezone(timezone.utc)
    thirty_d_utc = (end_dt - timedelta(days=30)).astimezone(timezone.utc)

    def _sum_in_window(rows: list[dict], start: datetime, end: datetime) -> float:
        total = 0.0
        for r in rows:
            ed = r.get("exit_date")
            if not ed:
                continue
            t = datetime.fromisoformat(ed.replace("Z", "+00:00"))
            if start <= t < end:
                total += r.get("pnl_amount") or 0
        return round(total, 2)

    rolling_7d_pnl = _sum_in_window(all_closes, seven_d_utc, end_utc)
    rolling_30d_pnl = _sum_in_window(all_closes, thirty_d_utc, end_utc)

    # Daily pct: today's pnl / cumulative-before-today. Falls back to
    # net_pnl / 5000 (wallet seed proxy) when cumulative is zero so we
    # don't divide by zero on the first profitable day.
    prior_cum = max(total_pnl_all - net_pnl, 1.0)  # avoid /0; small but >0
    daily_pct = round((net_pnl / prior_cum) * 100, 2) if prior_cum else 0.0
    rolling_7d_pct = round((rolling_7d_pnl / max(prior_cum, 1.0)) * 100, 2)
    rolling_30d_pct = round((rolling_30d_pnl / max(prior_cum, 1.0)) * 100, 2)

    # ── Open positions snapshot (end-of-day-as-of-now) ────────────────
    open_pos = (
        db.table("virtual_trades")
        .select("symbol,position_size_usd,entry_price")
        .eq("status", "OPEN")
        .eq("is_wallet_trade", True)
        .execute()
    ).data or []
    deployed_usd = round(_safe_sum(open_pos, "position_size_usd"), 2)
    # Unrealized P&L requires current price — virtual_portfolio_snapshot
    # writes to virtual_snapshots (brain_unrealized_pnl). Best-effort
    # — table or column missing returns 0.0.
    unrealized_pnl = 0.0
    try:
        snap = (
            db.table("virtual_snapshots")
            .select("brain_unrealized_pnl,snapshot_date")
            .order("snapshot_date", desc=True)
            .limit(1)
            .execute()
        ).data
        if snap:
            unrealized_pnl = float(snap[0].get("brain_unrealized_pnl") or 0)
    except Exception as e:
        logger.debug(f"daily_learning.metrics: virtual_snapshots unavailable: {e}")

    # ── Regime label (latest scan in target_date window) ──────────────
    regime = None
    try:
        scan = (
            db.table("scans")
            .select("market_regime,started_at")
            .gte("started_at", start_iso)
            .lt("started_at", end_iso)
            .order("started_at", desc=True)
            .limit(1)
            .execute()
        ).data
        if scan:
            regime = scan[0].get("market_regime")
    except Exception:
        pass

    # ── Insufficient-history guard for cohort step ────────────────────
    total_closes_all_time = len(all_closes)
    warning = None
    if total_closes_all_time < MIN_TOTAL_CLOSES_FOR_COHORTS:
        warning = "insufficient_history"

    return {
        "target_date": target_date.isoformat(),
        "closes": {
            "count": len(closes),
            "wins": wins,
            "losses": losses,
            "net_pnl": net_pnl,
            "by_exit_reason": by_exit_reason,
            "list": [
                {
                    "symbol": c.get("symbol"),
                    "exit_reason": c.get("exit_reason"),
                    "pnl_amount": round(c.get("pnl_amount") or 0, 2),
                    "pnl_pct": round(c.get("pnl_pct") or 0, 2),
                    "signal_style": c.get("signal_style"),
                    "entry_tier": c.get("entry_tier"),
                }
                for c in closes
            ],
        },
        "entries": {
            "count": len(entries),
            "by_tier": by_tier,
            "by_style": by_style,
            "list": [
                {
                    "symbol": e.get("symbol"),
                    "entry_score": e.get("entry_score"),
                    "signal_style": e.get("signal_style"),
                    "entry_tier": e.get("entry_tier"),
                    "bucket": e.get("bucket"),
                    "position_size_usd": round(e.get("position_size_usd") or 0, 2),
                }
                for e in entries
            ],
        },
        "wallet": {
            "cumulative_realized": total_pnl_all,
            "daily_pnl": net_pnl,
            "daily_pct": daily_pct,
            "rolling_7d_pnl": rolling_7d_pnl,
            "rolling_7d_pct": rolling_7d_pct,
            "rolling_30d_pnl": rolling_30d_pnl,
            "rolling_30d_pct": rolling_30d_pct,
        },
        "open": {
            "count": len(open_pos),
            "deployed_usd": deployed_usd,
            "unrealized_pnl": round(unrealized_pnl, 2),
        },
        "regime": regime,
        "warning": warning,
        "total_closes_all_time": total_closes_all_time,
    }
