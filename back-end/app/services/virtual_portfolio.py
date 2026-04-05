"""Virtual Portfolio — tracks what would happen if you followed the brain's signals.

Two tracks:
- "watchlist" — brain tracks your watchlisted tickers (your picks, brain timing)
- "brain" — brain picks its own best signals (fully autonomous)

After 1-2 weeks, compare which track performs better.
"""

from datetime import datetime, timezone

from loguru import logger

from app.db.supabase import get_client


# Brain auto-pick criteria: only the strongest signals
BRAIN_MIN_SCORE = 72
BRAIN_MAX_OPEN = 10  # Max simultaneous brain positions


def process_virtual_trades(signals: list[dict], watchlist_symbols: set[str]) -> dict:
    """Process scan results to update virtual portfolio.

    Called at the end of each scan. Handles both watchlist and brain-auto tracks.
    """
    db = get_client()
    buys = 0
    sells = 0

    # Get current open virtual positions (both sources)
    open_result = (
        db.table("virtual_trades")
        .select("id, symbol, entry_price, entry_date, source")
        .eq("status", "OPEN")
        .execute()
    )
    all_open = open_result.data or []
    open_by_symbol = {}
    brain_open_count = 0
    for r in all_open:
        open_by_symbol[r["symbol"]] = r
        if r.get("source") == "brain":
            brain_open_count += 1

    now = datetime.now(timezone.utc).isoformat()

    for sig in signals:
        symbol = sig.get("symbol")
        action = sig.get("action")
        price = sig.get("price_at_signal")
        score = sig.get("score", 0)

        if not price:
            continue
        price = float(price)

        is_watchlisted = symbol in watchlist_symbols
        is_open = symbol in open_by_symbol

        # ── SELL: close any open position (watchlist or brain) ──
        if action in ("SELL", "AVOID") and is_open:
            pos = open_by_symbol[symbol]
            entry_price = float(pos["entry_price"])
            pnl_pct = ((price - entry_price) / entry_price) * 100
            pnl_amount = price - entry_price
            is_win = pnl_pct > 0
            source = pos.get("source", "watchlist")

            db.table("virtual_trades").update({
                "status": "CLOSED",
                "exit_price": price,
                "exit_date": now,
                "exit_score": score,
                "exit_action": action,
                "pnl_pct": round(pnl_pct, 2),
                "pnl_amount": round(pnl_amount, 2),
                "is_win": is_win,
            }).eq("id", pos["id"]).execute()
            sells += 1

            emoji = "✅" if is_win else "❌"
            logger.info(
                f"Virtual SELL [{source}]: {emoji} {symbol} @ ${price:.2f} "
                f"(entry ${entry_price:.2f}, P&L {pnl_pct:+.1f}%)"
            )
            continue

        # ── BUY: open new position ──
        if action != "BUY" or is_open:
            continue

        # Track 1: Watchlist picks (score 62+)
        if is_watchlisted and score >= 62:
            db.table("virtual_trades").insert({
                "symbol": symbol,
                "action": "BUY",
                "entry_price": price,
                "entry_date": now,
                "entry_score": score,
                "status": "OPEN",
                "bucket": sig.get("bucket"),
                "signal_style": sig.get("signal_style"),
                "source": "watchlist",
            }).execute()
            buys += 1
            logger.info(f"Virtual BUY [watchlist]: {symbol} @ ${price:.2f} (score {score})")

        # Track 2: Brain auto-picks (score 72+, limited slots)
        if not is_watchlisted and score >= BRAIN_MIN_SCORE and brain_open_count < BRAIN_MAX_OPEN:
            # Only pick if it has AI analysis (target/stop filled)
            if sig.get("target_price") and sig.get("stop_loss"):
                db.table("virtual_trades").insert({
                    "symbol": symbol,
                    "action": "BUY",
                    "entry_price": price,
                    "entry_date": now,
                    "entry_score": score,
                    "status": "OPEN",
                    "bucket": sig.get("bucket"),
                    "signal_style": sig.get("signal_style"),
                    "source": "brain",
                }).execute()
                buys += 1
                brain_open_count += 1
                logger.info(f"Virtual BUY [brain]: {symbol} @ ${price:.2f} (score {score})")

    return {"buys": buys, "sells": sells}


def get_virtual_summary() -> dict:
    """Get virtual portfolio performance summary for the dashboard."""
    db = get_client()

    # All trades
    open_result = (
        db.table("virtual_trades")
        .select("symbol, entry_price, entry_date, entry_score, bucket, signal_style, source")
        .eq("status", "OPEN")
        .order("entry_date", desc=True)
        .execute()
    )
    open_trades = open_result.data or []

    closed_result = (
        db.table("virtual_trades")
        .select("symbol, entry_price, exit_price, pnl_pct, pnl_amount, is_win, entry_date, exit_date, bucket, source")
        .eq("status", "CLOSED")
        .order("exit_date", desc=True)
        .limit(50)
        .execute()
    )
    closed_trades = closed_result.data or []

    def _calc_stats(trades: list[dict]) -> dict:
        total = len(trades)
        wins = sum(1 for t in trades if t.get("is_win"))
        win_rate = (wins / total * 100) if total > 0 else 0
        avg_ret = sum(t.get("pnl_pct", 0) for t in trades) / total if total else 0
        total_ret = sum(t.get("pnl_pct", 0) for t in trades)
        best = max(trades, key=lambda t: t.get("pnl_pct", 0)) if trades else None
        worst = min(trades, key=lambda t: t.get("pnl_pct", 0)) if trades else None
        return {
            "closed_count": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": round(win_rate, 1),
            "avg_return_pct": round(avg_ret, 2),
            "total_return_pct": round(total_ret, 2),
            "best_trade": {"symbol": best["symbol"], "pnl_pct": best["pnl_pct"]} if best else None,
            "worst_trade": {"symbol": worst["symbol"], "pnl_pct": worst["pnl_pct"]} if worst else None,
        }

    # Split by source
    watchlist_open = [t for t in open_trades if t.get("source") == "watchlist"]
    brain_open = [t for t in open_trades if t.get("source") == "brain"]
    watchlist_closed = [t for t in closed_trades if t.get("source") == "watchlist"]
    brain_closed = [t for t in closed_trades if t.get("source") == "brain"]

    return {
        "open_count": len(open_trades),
        "open_trades": [
            {
                "symbol": t["symbol"],
                "entry_price": t["entry_price"],
                "entry_score": t.get("entry_score"),
                "bucket": t.get("bucket"),
                "source": t.get("source", "watchlist"),
            }
            for t in open_trades[:10]
        ],
        # Combined stats
        **_calc_stats(closed_trades),
        "recent_closed": [
            {
                "symbol": t["symbol"],
                "pnl_pct": t["pnl_pct"],
                "is_win": t["is_win"],
                "source": t.get("source", "watchlist"),
            }
            for t in closed_trades[:5]
        ],
        # Per-source breakdown
        "watchlist": {
            "open_count": len(watchlist_open),
            **_calc_stats(watchlist_closed),
        },
        "brain": {
            "open_count": len(brain_open),
            **_calc_stats(brain_closed),
        },
    }
