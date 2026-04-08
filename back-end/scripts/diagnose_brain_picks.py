"""Diagnose why the brain didn't pick anything after the wipe + scan.

Checks, in order:
  1. virtual_trades — confirm it's still empty (or what's there)
  2. signals — top 30 BUYs by score, to see what the scan produced
  3. signals — counts by action and bucket
  4. _eval_brain_trust_tier dry-run — for each top BUY, what tier does it
     evaluate to under the current rules? (Tier 0 = brain rejects.)
  5. Watchlist contents and brain_user_id resolution
  6. Market hours sanity (the brain skips equity BUYs outside RTH)

Read-only. Run from back-end/:
    venv/bin/python -m scripts.diagnose_brain_picks
"""

from __future__ import annotations
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, ".")

from app.db.supabase import get_client
from app.db import queries
from app.services.virtual_portfolio import _eval_brain_trust_tier, _is_us_market_open

ET = ZoneInfo("America/New_York")


def main() -> int:
    db = get_client()

    print("=" * 100)
    print("1. virtual_trades current state")
    print("=" * 100)
    vt = db.table("virtual_trades").select("status, source").execute().data or []
    if not vt:
        print("  EMPTY (0 rows)")
    else:
        from collections import Counter
        c = Counter((r.get("status"), r.get("source")) for r in vt)
        for (status, source), n in sorted(c.items()):
            print(f"  {status:8} / {source:10}: {n}")
    print()

    print("=" * 100)
    print("2. signals — top 30 by score (any action)")
    print("=" * 100)
    sigs = (
        db.table("signals")
        .select("symbol, action, score, bucket, asset_type, target_price, stop_loss, contrarian_score, market_regime, signal_style, technical_data")
        .order("score", desc=True)
        .limit(30)
        .execute()
    ).data or []
    print(f"  Total signals in table: ", end="")
    total = db.table("signals").select("id", count="exact").execute()
    print(total.count if hasattr(total, "count") else len(total.data or []))
    print()
    for s in sigs:
        print(f"  {s['symbol']:10}  {s.get('action', '?'):6}  score={s.get('score'):3}  "
              f"bucket={s.get('bucket'):12}  asset={s.get('asset_type'):8}  "
              f"target={s.get('target_price')}  stop={s.get('stop_loss')}")
    print()

    print("=" * 100)
    print("3. signals — distribution by action")
    print("=" * 100)
    all_sigs = (
        db.table("signals")
        .select("action, score, bucket")
        .execute()
    ).data or []
    from collections import Counter
    by_action = Counter(s.get("action") for s in all_sigs)
    for action, n in by_action.most_common():
        print(f"  {action:8}: {n}")
    print()
    score_bands = {">=72": 0, "65-71": 0, "55-64": 0, "<55": 0}
    for s in all_sigs:
        sc = s.get("score") or 0
        if sc >= 72:
            score_bands[">=72"] += 1
        elif sc >= 65:
            score_bands["65-71"] += 1
        elif sc >= 55:
            score_bands["55-64"] += 1
        else:
            score_bands["<55"] += 1
    print("  Score distribution (all signals):")
    for k, v in score_bands.items():
        print(f"    {k}: {v}")
    print()

    print("=" * 100)
    print("4. Brain trust tier evaluation — top 30 BUY signals")
    print("=" * 100)
    buys = [s for s in sigs if s.get("action") == "BUY"]
    if not buys:
        print("  NO BUY signals in top 30. The brain has nothing to consider.")
    else:
        for s in buys:
            tier, mult, reason = _eval_brain_trust_tier(s)
            tag = "PICK" if tier > 0 else "skip"
            print(f"  [{tag}] {s['symbol']:10} score={s.get('score'):3}  tier={tier}  "
                  f"trust={mult:.0%}  reason={reason}")
    print()

    print("=" * 100)
    print("5. Brain user + watchlist resolution")
    print("=" * 100)
    bu = queries.get_brain_user_id()
    print(f"  brain_user_id resolved to: {bu}")
    wl = queries.get_all_watchlist_symbols()
    print(f"  watchlist for that user: {sorted(wl) or '(empty)'}")
    print()

    print("=" * 100)
    print("6. Market hours")
    print("=" * 100)
    now_et = datetime.now(timezone.utc).astimezone(ET)
    print(f"  Now (ET): {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"  _is_us_market_open(): {_is_us_market_open()}")
    print(f"  → If False, brain skips equity BUYs (crypto unaffected)")
    crypto_in_buys = [s for s in buys if s.get("asset_type") == "CRYPTO" or s["symbol"].endswith("-USD")]
    print(f"  Crypto BUYs in top 30: {len(crypto_in_buys)}")
    print()

    print("=" * 100)
    print("DIAGNOSIS HINTS")
    print("=" * 100)
    if not all_sigs:
        print("  • signals table is EMPTY — the scan never ran or didn't write anything.")
    elif by_action.get("BUY", 0) == 0:
        print("  • No BUY signals at all. The scan ran but every ticker was HOLD/AVOID/SELL.")
    elif score_bands[">=72"] == 0:
        print("  • No signal scored 72+. Brain tier model needs at least 72 to consider.")
        print("    → Check `_eval_brain_trust_tier` thresholds in virtual_portfolio.py")
    elif buys and not any(_eval_brain_trust_tier(s)[0] > 0 for s in buys):
        print("  • Top BUYs exist but ALL get tier=0 from `_eval_brain_trust_tier`.")
        print("    → Inspect the rejection reasons in section 4 above.")
    elif not _is_us_market_open() and not crypto_in_buys:
        print("  • Market is closed AND there are no crypto BUYs to fall back on.")
        print("    → Equity BUYs are correctly suppressed outside RTH.")
    else:
        print("  • At least one signal SHOULD have qualified. If virtual_trades is still")
        print("    empty, the bug is in `process_virtual_trades` itself — not in the scan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
