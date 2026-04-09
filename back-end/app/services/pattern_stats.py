"""Inline pattern stats — combines closed history + live open positions.

============================================================
WHAT THIS MODULE IS
============================================================

When the brain considers a new candidate during a scan, this module looks
up the brain's TRACK RECORD on similar setups and surfaces it to Claude
in the AI prompt as additional context.

A "pattern" is initially just (bucket, market_regime) — 6 cells total
(SAFE_INCOME/HIGH_RISK × TRENDING/VOLATILE/CRISIS). Granularity is
intentionally coarse: it has to follow data density. Once a cell hits
N >> 20 trades, finer dimensions (score band, MACD direction) can be
layered in. Start crude, refine when data justifies it.

============================================================
WHY BOTH CLOSED AND OPEN POSITIONS
============================================================

Closed-only learning is broken in two ways:

  1. **Slow feedback.** A position that's bleeding RIGHT NOW (META Day 3
     at -2.4%) wouldn't contribute anything to learning until it actually
     exits — which might be days or weeks. Pedro's correction.

  2. **Survivorship bias.** Trades that close FAST (stop-outs, target hits)
     dominate `trade_outcomes` quickly. The slow bleeders we hold patiently
     are usually the most valuable lessons but the slowest to arrive at
     "closed."

The fix: read BOTH tables. Closed trades from `trade_outcomes` are ground
truth (high signal). Open positions from `virtual_trades` are in-flight
evidence (lower signal, still real). The combined N is what we threshold.

============================================================
THRESHOLDS
============================================================

  N < 5 (combined)             → return None (insufficient evidence)
  N >= 5 AND combined_wr < 40% → return ⚠ PATTERN WARNING string
  N >= 5 AND combined_wr > 65% → return ✓ PATTERN GREEN LIGHT string
  Otherwise (40-65% dead zone) → return None (no edge to report)

The dead zone is intentional. A 50% win rate is the brain's coin-flip
state — there's no signal to teach Claude there.

============================================================
PRICE FEED FAILURE HANDLING
============================================================

If `_fetch_prices_batch` returns no prices for the open positions (rare,
but possible during a yfinance outage), the open positions are silently
SKIPPED rather than treated as zero-winners. This prevents a price-feed
outage from flipping a green light to a warning.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger

from app.db.supabase import get_client
from app.services.price_cache import _fetch_prices_batch


# Per-scan cache: (bucket, regime) → result string OR None for "no warning".
# Cleared at the start of every scan via `invalidate_cache()` (called from
# scan_service.run_scan). Avoids re-querying the same (bucket, regime) cell
# N times when multiple candidates in one scan share it. This is NOT a TTL
# cache — it's an explicit per-scan dedupe map, because the closed/open
# evidence MUST be re-read every scan and we explicitly bust on scan start.
_scan_cache: dict[tuple[str, str], Optional[str]] = {}


def invalidate_cache() -> None:
    """Clear the per-scan dedupe cache. Called at the start of every scan
    by `scan_service.run_scan`, and used by tests to start clean."""
    _scan_cache.clear()


def get_pattern_warning(signal: dict) -> Optional[str]:
    """Return a one-paragraph pattern stat string, or None if no signal.

    Called per-ticker from `scan_service._process_candidate`. The output
    is intended to be appended to `grok_data["_knowledge_block"]` so it
    lands in Claude's prompt under the existing knowledge section.

    Args:
        signal: A dict carrying at least `bucket` and one of
            `market_regime` or `macro_data.regime`. The function tolerates
            missing fields by returning None silently.

    Returns:
        Multi-line markdown string with the warning/green-light text, or
        None when there's nothing actionable to surface (insufficient
        sample, dead zone, or missing bucket/regime).
    """
    bucket = signal.get("bucket")
    regime = (
        signal.get("market_regime")
        or (signal.get("macro_data") or {}).get("regime")
    )
    if not bucket or not regime:
        return None

    key = (bucket, regime)
    if key in _scan_cache:
        return _scan_cache[key]

    result = _compute(bucket, regime)
    _scan_cache[key] = result
    return result


def _compute(bucket: str, regime: str) -> Optional[str]:
    """The actual query + math. See `get_pattern_warning` for the contract."""
    db = get_client()

    # ── Closed history (rolling 90 days, max 30 most recent) ──
    closed_rows = []
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        closed_rows = (
            db.table("trade_outcomes")
            .select("pnl_pct, signal_date, symbol")
            .eq("bucket", bucket)
            .eq("market_regime", regime)
            .gte("signal_date", cutoff)
            .order("signal_date", desc=True)
            .limit(30)
            .execute()
        ).data or []
    except Exception as e:
        logger.warning(f"pattern_stats closed query failed for {bucket}/{regime}: {e}")

    closed_n = len(closed_rows)
    closed_wins = sum(1 for r in closed_rows if (r.get("pnl_pct") or 0) > 0)
    closed_avg = (
        sum((r.get("pnl_pct") or 0) for r in closed_rows) / closed_n
        if closed_n
        else 0.0
    )

    # ── Live open positions matching this pattern ──
    open_rows = []
    try:
        open_rows = (
            db.table("virtual_trades")
            .select("symbol, entry_price, bucket, market_regime")
            .eq("status", "OPEN")
            .eq("source", "brain")
            .eq("bucket", bucket)
            .eq("market_regime", regime)
            .execute()
        ).data or []
    except Exception as e:
        logger.warning(f"pattern_stats open query failed for {bucket}/{regime}: {e}")

    open_n = 0
    open_winners = 0
    open_avg = 0.0
    open_symbols: list[str] = []
    if open_rows:
        symbols = [r["symbol"] for r in open_rows]
        try:
            prices = _fetch_prices_batch(symbols)
        except Exception as e:
            logger.warning(f"pattern_stats price fetch failed for {bucket}/{regime}: {e}")
            prices = {}
        live_pnls: list[float] = []
        for r in open_rows:
            sym = r["symbol"]
            entry = float(r.get("entry_price") or 0)
            now_px, _ = prices.get(sym, (None, None))
            if not now_px or not entry:
                continue
            live_pnl = (now_px - entry) / entry * 100
            live_pnls.append(live_pnl)
            open_symbols.append(sym)
            if live_pnl > 0:
                open_winners += 1
        if live_pnls:
            open_n = len(live_pnls)
            open_avg = sum(live_pnls) / len(live_pnls)
        # If we couldn't price ANY open positions, treat as no open evidence
        # so a transient yfinance outage doesn't flip warnings to green lights
        # or vice versa.

    # ── Combined ──
    combined_n = closed_n + open_n
    if combined_n < 5:
        return None
    combined_wins = closed_wins + open_winners
    combined_wr = combined_wins / combined_n

    # Dead zone: no actionable signal to teach Claude
    if 0.40 <= combined_wr <= 0.65:
        return None

    # Sample symbols (up to 6 distinct, prefer currently-open + recent closed)
    sample = list(open_symbols[:3])
    sample.extend(r["symbol"] for r in closed_rows[:3])
    sample_text = ", ".join(sorted(set(sample))) if sample else "(none)"

    breakdown = (
        f"({closed_n} closed @ {closed_wins}/{closed_n} winners, avg "
        f"{closed_avg:+.1f}%; {open_n} currently open @ {open_winners}/{open_n} "
        f"in green, avg {open_avg:+.1f}%)"
    )

    if combined_wr < 0.40:
        return (
            f"\n## Pattern Stats — Your Live Track Record on This Setup\n"
            f"⚠ **PATTERN WARNING:** This setup ({bucket} in {regime} regime) "
            f"has a {combined_wr:.0%} positive rate across {combined_n} brain "
            f"trades {breakdown}. Recent examples: {sample_text}. Be skeptical "
            f"— require a fresh catalyst or stronger conviction than the score "
            f"alone suggests. Open positions in this pattern are bleeding."
        )
    # combined_wr > 0.65 (the green light branch)
    return (
        f"\n## Pattern Stats — Your Live Track Record on This Setup\n"
        f"✓ **PATTERN GREEN LIGHT:** This setup ({bucket} in {regime} regime) "
        f"has a {combined_wr:.0%} positive rate across {combined_n} brain "
        f"trades {breakdown}. Recent examples: {sample_text}. Historically "
        f"favorable — the score is more reliable here."
    )
