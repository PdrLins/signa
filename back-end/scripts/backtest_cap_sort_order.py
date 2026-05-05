"""Cap-by-score-DESC vs cap-by-random vs cap-by-score-ASC backtest.

Day 19 lesson #1 was *score is a filter, not a ranker*: ONDS at 91 was the
biggest loser, while CAMT at 81 was a winner. Today's per-day cap clips
the LOWEST-score signals first — so when 5 signals qualify and the cap is
3, the brain keeps the top-3 by score (e.g., 91, 86, 80) and discards the
75-79s. **If score isn't a ranker, this preserves the wrong cohort.**

This script replays the historical 52 closed brain trades, simulates a
3-per-day cap with three different sort orders, and compares the
admitted-trade outcomes:

  1. Score DESC (current): keep highest-scoring entries, discard lowest
  2. Score ASC (inverse): keep lowest-scoring entries, discard highest
  3. Random: keep a random 3 of N (averaged over many seeds)

If random beats score-DESC, we have evidence the cap's sort order is
hurting us. If score-DESC beats random, the current behavior is right
and Day 19 lesson was just one cohort, not a pattern.

INFORMATION ONLY — no DB writes, no code changes. Run:
    python -m scripts.backtest_cap_sort_order
"""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean

from app.db.supabase import get_client


def _stats(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "win_rate": 0.0, "avg_pct": 0.0, "total_pct": 0.0}
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
        f"  {label:<30} n={s['n']:>3} "
        f"W/L={s.get('wins', 0):>3}/{s.get('losses', 0):<3} "
        f"rate={s['win_rate']:>5.1f}% "
        f"avg={s['avg_pct']:+6.2f}% "
        f"total={s['total_pct']:+7.1f}%"
    )


def main():
    db = get_client()
    closed = (
        db.table("virtual_trades")
        .select("symbol, entry_score, entry_date, pnl_pct, is_win, source, status")
        .eq("source", "brain")
        .eq("status", "CLOSED")
        .order("entry_date")
        .execute()
    ).data or []

    if not closed:
        print("No closed trades. Nothing to test.")
        return

    print(f"═══ Cap-by-sort-order backtest on {len(closed)} closed brain trades ═══")
    print()
    print("Cap configuration: 3 entries per day per cohort.")
    print("'Day' is the entry_date date (UTC). Trades are grouped by day,")
    print("then the cap is applied with three different sort orders.")
    print()

    # Group trades by entry day.
    by_day: dict[str, list[dict]] = defaultdict(list)
    for t in closed:
        d = (t.get("entry_date") or "")[:10]
        if d:
            by_day[d].append(t)

    # Sort orders to test.
    cap = 3

    def admit_score_desc(trades_today: list[dict]) -> list[dict]:
        return sorted(trades_today, key=lambda x: -(x.get("entry_score") or 0))[:cap]

    def admit_score_asc(trades_today: list[dict]) -> list[dict]:
        return sorted(trades_today, key=lambda x: (x.get("entry_score") or 0))[:cap]

    def admit_random(trades_today: list[dict], rng: random.Random) -> list[dict]:
        if len(trades_today) <= cap:
            return list(trades_today)
        return rng.sample(trades_today, cap)

    # Score-DESC (current behavior)
    desc_admitted = []
    for d, ts in by_day.items():
        desc_admitted.extend(admit_score_desc(ts))

    # Score-ASC (inverse)
    asc_admitted = []
    for d, ts in by_day.items():
        asc_admitted.extend(admit_score_asc(ts))

    # Random — average over 200 seeds for stability.
    n_seeds = 200
    rand_runs = []
    for seed in range(n_seeds):
        rng = random.Random(seed)
        admitted = []
        for d, ts in by_day.items():
            admitted.extend(admit_random(ts, rng))
        rand_runs.append(_stats(admitted))

    rand_avg = {
        "n": mean(r["n"] for r in rand_runs),
        "win_rate": mean(r["win_rate"] for r in rand_runs),
        "avg_pct": mean(r["avg_pct"] for r in rand_runs),
        "total_pct": mean(r["total_pct"] for r in rand_runs),
        "wins": mean(r.get("wins", 0) for r in rand_runs),
        "losses": mean(r.get("losses", 0) for r in rand_runs),
    }

    # No-cap baseline (ALL trades)
    print("═══ BASELINE (no cap, all trades) ═══")
    print(_fmt("baseline", _stats(closed)))
    print()

    print("═══ CAP=3 PER DAY — sort order comparison ═══")
    print(_fmt("score DESC (current)", _stats(desc_admitted)))
    print(_fmt(f"random (avg of {n_seeds} seeds)", rand_avg))
    print(_fmt("score ASC (inverse)", _stats(asc_admitted)))
    print()

    # How many days actually hit the cap?
    capped_days = sum(1 for ts in by_day.values() if len(ts) > cap)
    total_days = len(by_day)
    print(f"  Days with > {cap} entries (cap actually fires): {capped_days}/{total_days}")
    print()

    # Conclusion logic
    desc_total = _stats(desc_admitted)["total_pct"]
    asc_total = _stats(asc_admitted)["total_pct"]
    rand_total = rand_avg["total_pct"]

    print("═══ INTERPRETATION ═══")
    if desc_total >= rand_total - 1.0 and desc_total >= asc_total - 1.0:
        print(f"  → Score-DESC ({desc_total:+.1f}%) is at least as good as random ({rand_total:+.1f}%)")
        print(f"    and ASC ({asc_total:+.1f}%). The current cap order is correct.")
    elif rand_total > desc_total + 1.0:
        print(f"  → Random ({rand_total:+.1f}%) beats Score-DESC ({desc_total:+.1f}%) by")
        print(f"    {rand_total - desc_total:+.1f}pp. Score is NOT acting as a ranker; the cap")
        print(f"    is biased toward the wrong cohort. Consider random or ASC sort.")
    elif asc_total > desc_total + 1.0:
        print(f"  → Score-ASC ({asc_total:+.1f}%) beats Score-DESC ({desc_total:+.1f}%) by")
        print(f"    {asc_total - desc_total:+.1f}pp. Lower-scoring entries actually outperform —")
        print(f"    strong evidence to invert the cap order.")
    else:
        print(f"  → Mixed: DESC={desc_total:+.1f}%, RAND={rand_total:+.1f}%, ASC={asc_total:+.1f}%.")
        print(f"    Differences are within noise. Need more data to draw a conclusion.")
    print()

    print("═══ CAVEATS ═══")
    print(f"  • Sample size: {len(closed)} trades total, but only {capped_days} days actually hit the cap.")
    print(f"    On uncapped days all sort orders produce the same result.")
    print("  • Past performance ≠ future. The cap's sort order matters most when")
    print("    the brain is admitting > 3 entries per day, which is the recent regime.")
    print("  • Random is averaged over 200 seeds for stability.")


if __name__ == "__main__":
    main()
