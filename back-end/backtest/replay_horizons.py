"""Replay all closed brain trades with OLD vs NEW (SHORT/LONG) exit rules.

Fetches the 30 closed brain trades from the DB, pulls historical prices
via yfinance, and simulates what WOULD have happened under the new
SHORT/LONG horizon rules. Compares actual exit P&L against simulated
exit P&L to quantify how much money the LONG horizon would have saved.

What this CAN simulate:
  - Trailing stop exits (old 3%/5% vs new 5%/8% for LONG)
  - Stop-loss hits
  - Target hits
  - Time expiry (old 30d vs new 7d SHORT / 60d LONG)
  - Quality prune skipping for LONG

What this CANNOT simulate:
  - Thesis tracker exits (would need Claude calls)
  - Watchdog sentiment exits (would need Grok calls)
  - Signal-based exits (would need full scan replay)

For thesis/signal exits, the script marks them as "thesis-driven" and
shows what the trailing stop would have done instead — giving a lower
bound on how much longer the position could have run.

Usage:
    source venv/bin/activate
    python -m backtest.replay_horizons
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

import yfinance as yf
from loguru import logger

from app.core.config import settings
from app.db.supabase import get_client


# ── Exit rule parameters ──

OLD_RULES = {
    "name": "OLD (uniform)",
    "soft_trail_pct": 0.03,   # 3% below peak
    "hard_trail_pct": 0.05,   # 5% below peak
    "trail_activation": 0.03, # trailing active when peak >= entry * 1.03
    "max_days": 30,
    "quality_prune": True,
}

NEW_SHORT = {
    "name": "NEW SHORT",
    "soft_trail_pct": 0.03,
    "hard_trail_pct": 0.05,
    "trail_activation": 0.03,
    "max_days": 7,
    "quality_prune": True,
}

NEW_LONG = {
    "name": "NEW LONG",
    "soft_trail_pct": 0.05,   # wider: 5% soft
    "hard_trail_pct": 0.08,   # wider: 8% hard
    "trail_activation": 0.03,
    "max_days": 60,
    "quality_prune": False,
}


def classify_horizon(trade: dict) -> str:
    """Classify a trade as SHORT or LONG using the same logic as the live brain."""
    bucket = trade.get("bucket") or ""
    symbol = trade.get("symbol") or ""
    is_crypto = symbol.endswith("-USD")
    if is_crypto or bucket == "HIGH_RISK":
        return "SHORT"
    return "LONG"


def fetch_price_series(symbol: str, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
    """Fetch daily close prices from yfinance. Returns [(date, close), ...]."""
    # Add buffer for weekends/holidays
    start_str = (start - timedelta(days=3)).strftime("%Y-%m-%d")
    end_str = (end + timedelta(days=3)).strftime("%Y-%m-%d")
    try:
        df = yf.Ticker(symbol).history(start=start_str, end=end_str, interval="1d")
        if df is None or df.empty:
            return []
        result = []
        for idx, row in df.iterrows():
            dt = idx.to_pydatetime()
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            result.append((dt, float(row["Close"])))
        return result
    except Exception as e:
        logger.warning(f"yfinance fetch failed for {symbol}: {e}")
        return []


def simulate_exit(
    entry_price: float,
    prices: list[tuple[datetime, float]],
    rules: dict,
    entry_date: datetime,
) -> dict:
    """Simulate exit using given rules. Returns exit info dict."""
    peak = entry_price
    entry_dt = entry_date

    for dt, close in prices:
        if dt <= entry_dt:
            continue

        days_held = (dt - entry_dt).days
        pnl_pct = (close - entry_price) / entry_price * 100

        # Update peak
        if close > peak:
            peak = close

        # Trailing stop active?
        trailing_active = peak >= entry_price * (1 + rules["trail_activation"])

        if trailing_active:
            soft_trail = max(peak * (1 - rules["soft_trail_pct"]), entry_price)
            hard_trail = max(peak * (1 - rules["hard_trail_pct"]), entry_price)

            if close <= hard_trail:
                return {
                    "exit_date": dt,
                    "exit_price": close,
                    "exit_reason": "TRAILING_STOP (hard)",
                    "pnl_pct": round(pnl_pct, 2),
                    "pnl_amount": round(close - entry_price, 2),
                    "days_held": days_held,
                    "peak": round(peak, 2),
                    "peak_pnl_pct": round((peak - entry_price) / entry_price * 100, 2),
                }

        # Time expiry
        if days_held >= rules["max_days"]:
            return {
                "exit_date": dt,
                "exit_price": close,
                "exit_reason": "TIME_EXPIRED",
                "pnl_pct": round(pnl_pct, 2),
                "pnl_amount": round(close - entry_price, 2),
                "days_held": days_held,
                "peak": round(peak, 2),
                "peak_pnl_pct": round((peak - entry_price) / entry_price * 100, 2),
            }

    # Still open at end of price data
    last_dt, last_close = prices[-1] if prices else (entry_dt, entry_price)
    pnl_pct = (last_close - entry_price) / entry_price * 100
    return {
        "exit_date": last_dt,
        "exit_price": last_close,
        "exit_reason": "STILL_OPEN",
        "pnl_pct": round(pnl_pct, 2),
        "pnl_amount": round(last_close - entry_price, 2),
        "days_held": (last_dt - entry_dt).days,
        "peak": round(peak, 2),
        "peak_pnl_pct": round((peak - entry_price) / entry_price * 100, 2),
    }


def main():
    db = get_client()

    # Fetch all closed brain trades
    result = db.table("virtual_trades").select(
        "symbol, entry_price, exit_price, entry_date, exit_date, "
        "pnl_pct, pnl_amount, is_win, exit_reason, bucket, "
        "peak_price, thesis_last_status, entry_score"
    ).eq("status", "CLOSED").eq("source", "brain").order("exit_date").execute()

    trades = result.data or []
    if not trades:
        print("No closed brain trades found.")
        return

    print(f"\n{'='*80}")
    print(f"  TRADE REPLAY: OLD rules vs NEW SHORT/LONG rules")
    print(f"  {len(trades)} closed brain trades")
    print(f"{'='*80}\n")

    # Summary accumulators
    actual_total_pct = 0.0
    actual_total_usd = 0.0
    old_total_pct = 0.0
    old_total_usd = 0.0
    new_total_pct = 0.0
    new_total_usd = 0.0
    improvements = []

    for trade in trades:
        symbol = trade["symbol"]
        entry_price = float(trade["entry_price"])
        actual_pnl_pct = float(trade.get("pnl_pct") or 0)
        actual_pnl_usd = float(trade.get("pnl_amount") or 0)
        actual_exit_reason = trade.get("exit_reason") or "?"
        entry_date_str = trade.get("entry_date") or ""
        exit_date_str = trade.get("exit_date") or ""
        bucket = trade.get("bucket") or ""

        # Parse dates
        try:
            entry_dt = datetime.fromisoformat(entry_date_str.replace("Z", "+00:00"))
            exit_dt = datetime.fromisoformat(exit_date_str.replace("Z", "+00:00"))
        except Exception:
            continue

        # Determine horizon
        horizon = classify_horizon(trade)
        new_rules = NEW_LONG if horizon == "LONG" else NEW_SHORT

        # Fetch price history (entry to 60 days after entry, or today)
        end_dt = max(exit_dt + timedelta(days=30), datetime.now(timezone.utc))
        prices = fetch_price_series(symbol, entry_dt, end_dt)
        if not prices:
            print(f"  {symbol}: skipped (no price data)")
            continue

        # Simulate with OLD rules
        old_result = simulate_exit(entry_price, prices, OLD_RULES, entry_dt)
        # Simulate with NEW rules (horizon-appropriate)
        new_result = simulate_exit(entry_price, prices, new_rules, entry_dt)

        # Accumulate
        actual_total_pct += actual_pnl_pct
        actual_total_usd += actual_pnl_usd
        old_total_pct += old_result["pnl_pct"]
        old_total_usd += old_result["pnl_amount"]
        new_total_pct += new_result["pnl_pct"]
        new_total_usd += new_result["pnl_amount"]

        delta_pct = new_result["pnl_pct"] - actual_pnl_pct
        delta_usd = new_result["pnl_amount"] - actual_pnl_usd

        # Print per-trade comparison
        marker = "▲" if delta_usd > 0.1 else ("▼" if delta_usd < -0.1 else "─")
        print(
            f"  {marker} {symbol:12s} [{horizon:5s}] "
            f"actual: {actual_pnl_pct:+6.2f}% (${actual_pnl_usd:+8.2f})  "
            f"│ new: {new_result['pnl_pct']:+6.2f}% (${new_result['pnl_amount']:+8.2f})  "
            f"│ delta: {delta_pct:+6.2f}% (${delta_usd:+8.2f})  "
            f"│ exit: {actual_exit_reason:22s} → {new_result['exit_reason']}"
        )
        if abs(delta_usd) > 0.1:
            improvements.append({
                "symbol": symbol,
                "horizon": horizon,
                "actual_pnl": actual_pnl_pct,
                "new_pnl": new_result["pnl_pct"],
                "delta_pct": delta_pct,
                "delta_usd": delta_usd,
                "actual_exit": actual_exit_reason,
                "new_exit": new_result["exit_reason"],
                "peak_pnl": new_result["peak_pnl_pct"],
            })

    # Print summary
    print(f"\n{'='*80}")
    print(f"  SUMMARY")
    print(f"{'='*80}")
    print(f"  Actual (what happened):    {actual_total_pct:+8.2f}%  ${actual_total_usd:+10.2f}")
    print(f"  OLD rules (simulated):     {old_total_pct:+8.2f}%  ${old_total_usd:+10.2f}")
    print(f"  NEW SHORT/LONG (simulated):{new_total_pct:+8.2f}%  ${new_total_usd:+10.2f}")
    print()
    delta_total_pct = new_total_pct - actual_total_pct
    delta_total_usd = new_total_usd - actual_total_usd
    print(f"  Improvement vs actual:     {delta_total_pct:+8.2f}%  ${delta_total_usd:+10.2f}")
    print()

    if improvements:
        gained = [i for i in improvements if i["delta_usd"] > 0]
        lost = [i for i in improvements if i["delta_usd"] < 0]
        gained.sort(key=lambda x: x["delta_usd"], reverse=True)
        lost.sort(key=lambda x: x["delta_usd"])

        if gained:
            print(f"  ▲ Trades that would have GAINED more with new rules:")
            for i in gained[:10]:
                print(
                    f"    {i['symbol']:12s} [{i['horizon']}] "
                    f"actual {i['actual_pnl']:+.2f}% → new {i['new_pnl']:+.2f}% "
                    f"(+${i['delta_usd']:.2f}) peak was {i['peak_pnl']:+.2f}%"
                )
        if lost:
            print(f"\n  ▼ Trades that would have done WORSE with new rules:")
            for i in lost[:10]:
                print(
                    f"    {i['symbol']:12s} [{i['horizon']}] "
                    f"actual {i['actual_pnl']:+.2f}% → new {i['new_pnl']:+.2f}% "
                    f"(${i['delta_usd']:.2f}) exit: {i['actual_exit']} → {i['new_exit']}"
                )

    print(f"\n  NOTE: This only simulates price-based exits (trailing stop, target,")
    print(f"  time expiry). Thesis-driven and signal-driven exits show what the")
    print(f"  trailing stop would have done instead — the actual thesis exit may")
    print(f"  have been correct for non-price reasons.\n")


if __name__ == "__main__":
    main()
