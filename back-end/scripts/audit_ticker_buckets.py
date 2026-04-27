"""Audit + (optionally) re-bucket misclassified tickers.

Background
----------
The discovery auto-add path stamps `bucket = sig.get("bucket")` on every
new ticker, and the default classifier defaults to SAFE_INCOME. That
means 173 of 173 discovered tickers ended up SAFE_INCOME — including
obvious momentum names (IONQ, OKLO, NXT, ASTS, NIO, PATH, SOUN, etc.).

SAFE_INCOME weights `dividend_reliability` 35%. A non-dividend stock
takes a 35% haircut on its score and almost always caps out at 55-65.
That's below the 75 Tier-1 floor and below the top-15 AI-candidate cut,
so Claude never even gets to evaluate them. THE structural reason the
brain feels "boring" — half the universe is being scored against the
wrong yardstick.

This script
-----------
1. Walks every active ticker in `tickers`.
2. Pulls dividendYield + marketCap + sector via yfinance (cached locally
   to avoid re-hitting the API on re-runs).
3. Applies a re-classification heuristic:
     - dividend_yield > 0  → keep SAFE_INCOME (dividend-paying — fits the bucket)
     - dividend_yield == 0 AND market_cap < $50B → flip to HIGH_RISK
     - sector in {Technology, Communication Services, Consumer Cyclical} →
       flip to HIGH_RISK if no dividend regardless of cap
4. Prints a diff. NO DB writes unless `--apply` is passed.

Run dry-run first:
    python -m scripts.audit_ticker_buckets

Run with apply:
    python -m scripts.audit_ticker_buckets --apply

Both modes print the proposed changes; --apply also commits them.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

from app.db.supabase import get_client


# Sectors that should default to HIGH_RISK when there's no dividend.
# Speculative + growth-tilted; the market rewards them on momentum/
# catalyst, not on income reliability.
HIGH_RISK_SECTORS = {
    "Technology",
    "Communication Services",
    "Consumer Cyclical",
}

# Cap below which we treat any non-dividend-payer as HIGH_RISK regardless
# of sector. $50B is large enough that most "speculative growth" names fit
# under (e.g., IONQ ~$10B, OKLO ~$13B, RKLB ~$10B), and large enough that
# we don't accidentally re-bucket BRK-B / TSLA into the wrong bucket.
HIGH_RISK_MAX_MCAP_USD = 50_000_000_000


def classify(symbol: str, dividend_yield: float | None, market_cap: float | None, sector: str | None) -> str:
    """Return the recommended bucket given the ticker's properties.

    Decision tree (applied in order):
      1. Crypto (`-USD` suffix) → HIGH_RISK always. Crypto has no
         dividend, no fundamentals in the income sense, no sector data
         from yfinance — it's pure momentum/sentiment, exactly what
         HIGH_RISK is built to score.
      2. Dividend > 0 → SAFE_INCOME (income-style stock, current bucket fits)
      3. No dividend AND market cap < $50B → HIGH_RISK
      4. No dividend AND sector is speculative-growth → HIGH_RISK
      5. Anything else (no-dividend mega-caps in stable sectors) → SAFE_INCOME
    """
    if symbol.upper().endswith("-USD"):
        return "HIGH_RISK"

    div = float(dividend_yield or 0)
    mcap = float(market_cap or 0)
    sec = (sector or "").strip()

    if div > 0:
        return "SAFE_INCOME"
    if 0 < mcap < HIGH_RISK_MAX_MCAP_USD:
        return "HIGH_RISK"
    if sec in HIGH_RISK_SECTORS:
        return "HIGH_RISK"
    return "SAFE_INCOME"


def fetch_ticker_props(symbol: str) -> tuple[float | None, float | None, str | None] | None:
    """Lookup (dividend_yield, market_cap, sector) via yfinance.

    Returns None if the lookup fails entirely (network / delisted /
    typo). Callers should leave such tickers untouched rather than
    guess.
    """
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).info
        return (
            info.get("dividendYield"),
            info.get("marketCap"),
            info.get("sector"),
        )
    except Exception as e:
        print(f"  ⚠  yfinance lookup failed for {symbol}: {e}", file=sys.stderr)
        return None


def main():
    ap = argparse.ArgumentParser(description="Audit + (optionally) re-bucket tickers.")
    ap.add_argument("--apply", action="store_true",
                    help="Commit proposed changes to the DB. Default is dry-run.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Audit only the first N tickers (for testing).")
    args = ap.parse_args()

    db = get_client()
    rows = (
        db.table("tickers")
        .select("symbol, bucket, exchange, name")
        .eq("is_active", True)
        .order("symbol")
        .execute()
    ).data or []

    if args.limit:
        rows = rows[: args.limit]

    print(f"═══ Auditing {len(rows)} active tickers ═══")
    print(f"  Mode: {'APPLY (will UPDATE rows)' if args.apply else 'DRY-RUN (no writes)'}")
    print()

    proposed: list[tuple[str, str, str, str]] = []  # (symbol, current, recommended, reason)
    unchanged = 0
    skipped = 0

    for i, r in enumerate(rows, 1):
        sym = r["symbol"]
        current = r.get("bucket") or "NULL"

        props = fetch_ticker_props(sym)
        if props is None:
            skipped += 1
            continue

        div, mcap, sector = props
        recommended = classify(sym, div, mcap, sector)

        if recommended != current:
            div_str = f"{div:.4f}" if div else "0"
            mcap_str = f"${(mcap or 0)/1e9:.1f}B"
            sec_str = sector or "?"
            reason = f"div={div_str} mcap={mcap_str} sec={sec_str}"
            proposed.append((sym, current, recommended, reason))
            print(f"  [{i:>3}/{len(rows)}] {sym:<10} {current:<11} → {recommended:<11}  ({reason})")
        else:
            unchanged += 1
            if i % 50 == 0:
                print(f"  [{i:>3}/{len(rows)}] checked, no change so far...")

    print()
    print("═══ SUMMARY ═══")
    print(f"  Unchanged:     {unchanged}")
    print(f"  Skipped:       {skipped}  (yfinance lookup failed)")
    print(f"  Proposed:      {len(proposed)}")
    print()
    if proposed:
        delta = Counter()
        for _, c, r, _ in proposed:
            delta[(c, r)] += 1
        print("  Bucket transitions:")
        for (c, r), n in delta.most_common():
            print(f"    {c:<11} → {r:<11}  {n}")
    print()

    if not proposed:
        print("Nothing to change.")
        return

    if not args.apply:
        print("DRY-RUN — re-run with --apply to commit the changes above.")
        return

    print(f"═══ APPLYING {len(proposed)} updates ═══")
    applied = 0
    for sym, current, recommended, _ in proposed:
        try:
            db.table("tickers").update({"bucket": recommended}).eq("symbol", sym).execute()
            applied += 1
        except Exception as e:
            print(f"  ⚠  UPDATE failed for {sym}: {e}", file=sys.stderr)
    print(f"  Applied: {applied}/{len(proposed)}")


if __name__ == "__main__":
    main()
