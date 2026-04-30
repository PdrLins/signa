"""GEM gate failure audit.

Background
----------
The GEM badge requires a signal to clear FIVE gates simultaneously:
  • score >= 85
  • ai_status == "validated"
  • sentiment_score >= 80
  • risk_reward >= 3.0
  • target_price + stop_loss filled

Day 19 audit revealed: 0 GEMs across 19 days of operation. Diagnostic
showed the sentiment threshold (>= 80) is the binding constraint —
top sentiment scores observed in practice are 60-70, never crossing
80. The threshold appears miscalibrated against the actual Grok
sentiment scoring distribution.

This script
-----------
For all signals scoring >= 80 in the last N days, compute the rate at
which each GEM gate fails. The gate that fails most often is the
binding constraint. INFORMATION ONLY — does not modify any DB rows or
config.

Run:
    python -m scripts.audit_gem_gates [--days N]

Use to:
  • Re-check whether sentiment is still the binding constraint
    (e.g., after a Grok prompt change or sentiment recalibration).
  • Compute "what if we lowered sentiment to 70?" by changing the
    threshold variable inline below.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta

from app.core.config import settings
from app.db.supabase import get_client


def main():
    ap = argparse.ArgumentParser(description="Audit GEM gate failures.")
    ap.add_argument("--days", type=int, default=7, help="Look back N days (default 7).")
    args = ap.parse_args()

    db = get_client()
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()

    sigs = (
        db.table("signals")
        .select(
            "symbol, score, action, ai_status, sentiment_score, risk_reward, "
            "target_price, stop_loss, gem_reason, is_gem, grok_data, created_at"
        )
        .gte("score", 80)
        .gte("created_at", since)
        .order("score", desc=True)
        .execute()
    ).data or []

    print(f"═══ GEM gate audit — last {args.days} days ═══")
    print(
        f"  Required: score >= {settings.gem_min_score}, ai_status = validated, "
        f"sentiment >= 80, R/R >= {settings.gem_min_rr_ratio}, target+stop filled"
    )
    print()
    print(f"  {len(sigs)} signals scored >= 80 in the window")
    print()

    gate_fails: Counter = Counter()
    eligible = 0

    for s in sigs:
        score = s.get("score") or 0
        ai = s.get("ai_status") or "skipped"
        # Sentiment may live on `sentiment_score` OR inside `grok_data`.
        # Take the max so we don't false-fail when one source is missing.
        sent_a = s.get("sentiment_score") or 0
        grok = s.get("grok_data") or {}
        sent_b = grok.get("sentiment_score") or grok.get("score") or 0
        sentiment = max(sent_a, sent_b)
        rr = s.get("risk_reward") or 0
        has_target = s.get("target_price") is not None
        has_stop = s.get("stop_loss") is not None

        fails: list[str] = []
        if score < settings.gem_min_score:
            fails.append("score<85")
        if ai != "validated":
            fails.append("ai_not_validated")
        if sentiment < 80:
            fails.append("sentiment<80")
        if rr < settings.gem_min_rr_ratio:
            fails.append("rr_low")
        if not has_target or not has_stop:
            fails.append("no_target_or_stop")

        if not fails:
            eligible += 1
        for g in fails:
            gate_fails[g] += 1

    print(f"  Passed all gates (would-be GEMs): {eligible}")
    print(f"  Failed at least one gate:         {len(sigs) - eligible}")
    print()
    print("  Failure rate by gate (each signal counted in every gate it fails):")
    for gate, n in gate_fails.most_common():
        pct = (n / len(sigs) * 100) if sigs else 0
        print(f"    {gate:<22} {n:>4}  ({pct:5.1f}% of 80+ signals)")
    print()

    if not eligible:
        print("  Conclusion: 0 GEMs in this window.")
        binding = gate_fails.most_common(1)
        if binding:
            gate, n = binding[0]
            print(f"  Binding constraint: {gate} ({n} of {len(sigs)})")
            print("  This is the gate to relax (or accept) if you want to unlock GEMs.")


if __name__ == "__main__":
    main()
