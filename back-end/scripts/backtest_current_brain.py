"""Replay every historical brain signal through the CURRENT entry pipeline.

What this answers
-----------------
"If today's brain (with Filter D + per-day cap + per-symbol cap +
BRAIN_MIN_SCORE=75 + the LONG-horizon kill) had been running over the
full lifetime of the project, what would have been admitted, what would
have been blocked, and what would the realized P&L have been?"

This is NOT a full simulation. We don't replay exit paths (watchdog grace,
QUALITY_PRUNE timing changes, thesis-tracker re-evals, etc.) because those
need intra-day price ticks we don't store. Instead we use the actual
historical outcome of each admitted trade. The premise: if today's gates
admit the same trade, the trade's outcome is roughly the same.

Caveats:
  • Watchdog grace might have changed an exit time (e.g., SOUN would have
    closed earlier without the grace), so realized P&L is a lower bound
    for the post-Filter-D era.
  • Per-symbol cap removes duplicate same-day attempts from the candidate
    pool — admittedly a rare event, but it does happen (SEZL May 1).
  • All trades are 1-share equivalent for the historical legacy era;
    we ignore wallet sizing in this replay because position-size data is
    absent on legacy rows. This means we sum pnl_pct (per-trade %) not
    pnl_amount ($) — the % comparison is direction-stable.

Run:
    python -m scripts.backtest_current_brain
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean

from app.core.config import settings
from app.db.supabase import get_client
from app.services.virtual_portfolio import (
    BRAIN_MIN_SCORE,
    FILTER_D_BLOCKED_SECTORS,
)


def _stats(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "avg_pct": 0.0, "total_pct": 0.0}
    n = len(trades)
    wins = sum(1 for t in trades if t.get("is_win"))
    pcts = [t.get("pnl_pct") or 0 for t in trades]
    return {
        "n": n,
        "wins": wins,
        "losses": n - wins,
        "win_rate": wins / n * 100,
        "avg_pct": mean(pcts),
        "total_pct": sum(pcts),
    }


def _fmt(label: str, s: dict) -> str:
    return (
        f"  {label:<55} n={s['n']:>3} W/L={s['wins']:>3}/{s['losses']:<3} "
        f"rate={s['win_rate']:>5.1f}% avg={s['avg_pct']:+6.2f}% total={s['total_pct']:+7.1f}%"
    )


def _enrich_with_signal(closed: list[dict], db) -> list[dict]:
    """Attach the at-entry signal so we can re-evaluate the gates against
    the same data the brain saw at decision time."""
    for t in closed:
        sym = t["symbol"]
        try:
            sig = (
                db.table("signals")
                .select(
                    "score, ai_status, fundamental_data, sentiment_score, "
                    "risk_reward, grok_data"
                )
                .eq("symbol", sym)
                .lte("created_at", t["entry_date"])
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            ).data or []
        except Exception:
            sig = []
        t["_sig"] = sig[0] if sig else {}
        fund = t["_sig"].get("fundamental_data") or {}
        t["_sector"] = (fund.get("sector") or "Unknown").strip()
        t["_score"] = t.get("entry_score") or 0
        t["_ai"] = t["_sig"].get("ai_status") or "skipped"
        t["_horizon"] = t.get("trade_horizon") or "SHORT"
        t["_bucket"] = t.get("bucket") or ""
    return closed


def _passes_filter_d(t: dict) -> tuple[bool, str]:
    """Replay the Filter D entry gate against an enriched trade row.
    Returns (admitted, reason)."""
    if t["_ai"] == "failed":
        return False, "ai_failed"
    if t["_sector"] in FILTER_D_BLOCKED_SECTORS:
        return False, f"sector_blocked_{t['_sector']}"
    # Tier 1: validated AI + score >= BRAIN_MIN_SCORE
    if t["_ai"] == "validated" and t["_score"] >= BRAIN_MIN_SCORE:
        # LONG-horizon suspension (Day 20)
        if t["_horizon"] == "LONG":
            return False, "long_horizon_suspended"
        return True, "tier1_validated"
    # Tier 2/3 thresholds (approximated)
    if t["_ai"] == "low_confidence" and t["_score"] >= 80:
        if t["_horizon"] == "LONG":
            return False, "long_horizon_suspended"
        return True, "tier2_low_confidence"
    if t["_ai"] == "skipped" and t["_score"] >= 82:
        # Tier 3 also requires technical confirmations we can't easily
        # replay. Approximate: admit if score >= 82 and not LONG.
        if t["_horizon"] == "LONG":
            return False, "long_horizon_suspended"
        return True, "tier3_tech_only_approx"
    return False, f"no_tier_score{t['_score']}_{t['_ai']}"


def _apply_caps(admitted: list[dict]) -> list[dict]:
    """Apply per-day cap (3) + per-symbol-per-day cap (1).

    Sorted by score DESC within day so the cap clips lowest-score first
    (matches the current implementation, validated by backtest_cap_sort_order).
    """
    per_day_cap = settings.wallet_max_entries_per_day  # 3
    per_sym_cap = settings.wallet_max_entries_per_symbol_per_day  # 1

    # Group by entry day.
    by_day: dict[str, list[dict]] = defaultdict(list)
    for t in admitted:
        d = (t.get("entry_date") or "")[:10]
        by_day[d].append(t)

    survivors: list[dict] = []
    for day, day_trades in by_day.items():
        # Sort by score DESC so cap clips lowest-score
        day_trades.sort(key=lambda x: -(x.get("entry_score") or 0))
        per_sym_count: dict[str, int] = defaultdict(int)
        admitted_today = 0
        for t in day_trades:
            sym = t["symbol"]
            if per_sym_cap > 0 and per_sym_count[sym] >= per_sym_cap:
                continue
            if per_day_cap > 0 and admitted_today >= per_day_cap:
                continue
            survivors.append(t)
            per_sym_count[sym] += 1
            admitted_today += 1
    return survivors


def main():
    db = get_client()
    closed = (
        db.table("virtual_trades")
        .select(
            "symbol, entry_date, exit_date, entry_score, pnl_pct, is_win, "
            "bucket, trade_horizon, source, status, exit_reason"
        )
        .eq("source", "brain")
        .eq("status", "CLOSED")
        .order("entry_date")
        .execute()
    ).data or []

    if not closed:
        print("No closed trades. Nothing to replay.")
        return

    print(f"═══ Replaying current brain logic against {len(closed)} historical brain trades ═══")
    print(f"  Filter D: BRAIN_MIN_SCORE={BRAIN_MIN_SCORE}, blocked sectors={sorted(FILTER_D_BLOCKED_SECTORS)}")
    print(f"  Per-day cap: {settings.wallet_max_entries_per_day}, per-symbol cap: {settings.wallet_max_entries_per_symbol_per_day}")
    print()
    print("  Note: this replays the ENTRY pipeline only. Exit paths (watchdog")
    print("  grace, QUALITY_PRUNE timing) are NOT re-simulated — actual closed")
    print("  outcomes are reused. So the % numbers are a LOWER bound for the")
    print("  post-Filter-D era because watchdog grace would likely have saved")
    print("  some trades that died historically.")
    print()

    # Enrich with at-entry signals
    print("Loading signals for each trade (this may take ~30s)...")
    closed = _enrich_with_signal(closed, db)

    # Baseline (no filter)
    baseline = _stats(closed)
    print()
    print("═══ BASELINE (no filter, all historical trades as they actually closed) ═══")
    print(_fmt("baseline", baseline))
    print()

    # Filter D only
    filter_d_admitted = []
    filter_d_blocks: dict[str, int] = defaultdict(int)
    for t in closed:
        admitted, reason = _passes_filter_d(t)
        if admitted:
            filter_d_admitted.append(t)
        else:
            filter_d_blocks[reason] += 1

    print("═══ STAGE 1: Filter D entry gate only ═══")
    print(_fmt("after Filter D", _stats(filter_d_admitted)))
    print(f"  Blocked: {sum(filter_d_blocks.values())} trades")
    for reason, n in sorted(filter_d_blocks.items(), key=lambda x: -x[1])[:6]:
        print(f"    {reason:<45} {n}")
    print()

    # Filter D + caps
    final_admitted = _apply_caps(filter_d_admitted)
    cap_removed = len(filter_d_admitted) - len(final_admitted)

    print("═══ STAGE 2: Filter D + per-day cap (3) + per-symbol cap (1) ═══")
    print(_fmt("after Filter D + caps", _stats(final_admitted)))
    print(f"  Cap removed an additional {cap_removed} trades (would have been admitted by Filter D")
    print(f"  but cap-clipped because the day already had its allotment).")
    print()

    # Show day-by-day breakdown for cap-affected days
    if cap_removed > 0:
        print("═══ Days where the cap actually clipped trades ═══")
        admitted_ids = {id(t) for t in final_admitted}
        by_day: dict[str, list[dict]] = defaultdict(list)
        for t in filter_d_admitted:
            d = (t.get("entry_date") or "")[:10]
            by_day[d].append(t)
        for day, day_trades in sorted(by_day.items()):
            kept = [t for t in day_trades if id(t) in admitted_ids]
            dropped = [t for t in day_trades if id(t) not in admitted_ids]
            if dropped:
                kept_str = ", ".join(f"{t['symbol']}({t['_score']})" for t in kept)
                drop_str = ", ".join(f"{t['symbol']}({t['_score']})" for t in dropped)
                print(f"  {day}: kept [{kept_str}] dropped [{drop_str}]")
        print()

    # Compare improvement
    print("═══ SUMMARY ═══")
    print(f"  Baseline (no filter):       n={baseline['n']:>3}  total={baseline['total_pct']:+7.1f}%  win={baseline['win_rate']:>5.1f}%")
    fd = _stats(filter_d_admitted)
    print(f"  Filter D only:              n={fd['n']:>3}  total={fd['total_pct']:+7.1f}%  win={fd['win_rate']:>5.1f}%")
    fc = _stats(final_admitted)
    print(f"  Filter D + caps (current):  n={fc['n']:>3}  total={fc['total_pct']:+7.1f}%  win={fc['win_rate']:>5.1f}%")
    print()
    print(f"  Δ vs baseline (current brain): {fc['total_pct'] - baseline['total_pct']:+.1f}pp total, ")
    print(f"  {fc['win_rate'] - baseline['win_rate']:+.1f}pp win rate, "
          f"{baseline['n'] - fc['n']} fewer trades")
    print()
    print("  Reading: if the current brain had been live across all history,")
    print("  it would have produced these admitted-trade outcomes. Watchdog")
    print("  grace effects on exit timing are NOT included; they would likely")
    print("  improve the win rate further (SOUN-style saves) but cannot be")
    print("  proven without intra-day price replay.")


if __name__ == "__main__":
    main()
