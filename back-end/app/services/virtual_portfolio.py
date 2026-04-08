"""Virtual Portfolio — tracks what would happen if you followed the brain's signals.

Two tracks:
- "watchlist" — brain tracks your watchlisted tickers (your picks, brain timing)
- "brain" — brain picks its own best signals (fully autonomous)

After 1-2 weeks, compare which track performs better.
"""

from datetime import datetime, timezone

from loguru import logger

from app.core.cache import TTLCache
from app.core.config import settings
from app.db.supabase import get_client, with_retry
from app.services.price_cache import _fetch_prices_batch


# Brain auto-pick criteria: only the strongest signals
BRAIN_MIN_SCORE = 72

# Queued notifications (sent async after sync function returns)
_pending_notifications: list[tuple[str, dict]] = []


def process_virtual_trades(signals: list[dict], watchlist_symbols: set[str]) -> dict:
    """Process scan results to update virtual portfolio.

    Called at the end of each scan. Handles both watchlist and brain-auto tracks.
    """
    _pending_notifications.clear()  # Prevent stale buildup from previous runs
    db = get_client()
    buys = 0
    sells = 0

    # Get current open virtual positions (both sources)
    open_result = (
        db.table("virtual_trades")
        .select("id, symbol, entry_price, entry_date, entry_score, source")
        .eq("status", "OPEN")
        .execute()
    )
    all_open = open_result.data or []
    open_watchlist = set()   # symbols with open watchlist positions
    open_brain = set()       # symbols with open brain positions
    brain_open_count = 0
    weakest_brain = None     # pre-computed for rotation
    weakest_brain_score = 999
    for r in all_open:
        if r.get("source") == "brain":
            open_brain.add(r["symbol"])
            brain_open_count += 1
            es = r.get("entry_score", 0) or 0
            if es < weakest_brain_score:
                weakest_brain_score = es
                weakest_brain = r
        else:
            open_watchlist.add(r["symbol"])

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

        # ── SELL: close all open positions for this symbol ──
        if action in ("SELL", "AVOID"):
            for pos in all_open:
                if pos["symbol"] != symbol:
                    continue

                entry_score = pos.get("entry_score", 0) or 0
                score_drop = entry_score - score

                # Guard: if score dropped 25+ points, don't auto-close.
                # This usually means the ticker lost AI analysis (tech-only fallback)
                # rather than a real deterioration. Wait for next scan to confirm.
                if score_drop >= 25 and score < 50:
                    source = pos.get("source", "watchlist")
                    logger.warning(
                        f"Virtual SELL BLOCKED [{source}]: {symbol} score dropped "
                        f"{entry_score} -> {score} (-{score_drop}pts). "
                        f"Likely methodology change, not real signal. Waiting for confirmation."
                    )
                    continue

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
                    "exit_reason": "SIGNAL",
                }).eq("id", pos["id"]).execute()
                sells += 1

                emoji = "✅" if is_win else "❌"
                logger.info(
                    f"Virtual SELL [{source}]: {emoji} {symbol} @ ${price:.2f} "
                    f"(entry ${entry_price:.2f}, P&L {pnl_pct:+.1f}%, score {entry_score}->{score})"
                )

                # Queue Telegram notification for brain sells
                if source == "brain":
                    verdict = f"{emoji} {'Win' if is_win else 'Loss'} -- brain learning from this outcome."
                    _pending_notifications.append(("brain_sell", {
                        "symbol": symbol, "price": f"{price:.2f}",
                        "pnl": f"{pnl_pct:+.1f}", "reason": f"Signal changed to {action}",
                        "entry_score": str(entry_score), "exit_score": str(score),
                        "verdict": verdict,
                    }))
            continue

        if action != "BUY":
            continue

        # Track 1: Watchlist picks (score 62+)
        if is_watchlisted and score >= 62 and symbol not in open_watchlist:
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
                "target_price": sig.get("target_price"),
                "stop_loss": sig.get("stop_loss"),
            }).execute()
            buys += 1
            logger.info(f"Virtual BUY [watchlist]: {symbol} @ ${price:.2f} (score {score})")

        # Track 2: Brain auto-picks (score 72+, limited slots)
        # Brain picks independently — watchlisted tickers can also be brain picks
        # Portfolio rotation: if full, replace weakest position if new signal is stronger
        if score >= BRAIN_MIN_SCORE and symbol not in open_brain:
            if brain_open_count >= settings.brain_max_open:
                # Only rotate if new signal is meaningfully better (+5 points) than weakest
                if weakest_brain and score >= weakest_brain_score + 5:
                    weakest = weakest_brain
                    weakest_score = weakest_brain_score
                    w_symbol = weakest["symbol"]
                    w_entry = float(weakest["entry_price"])
                    # Get actual current price for the position being closed
                    w_prices = _fetch_prices_batch([w_symbol])
                    w_current, _ = w_prices.get(w_symbol, (None, None))
                    w_exit_price = w_current if w_current else price  # fallback to signal price
                    w_pnl = ((w_exit_price - w_entry) / w_entry) * 100 if w_entry > 0 else 0
                    # Close the weakest position
                    db.table("virtual_trades").update({
                        "status": "CLOSED",
                        "exit_price": w_exit_price,
                        "exit_date": now,
                        "exit_score": score,
                        "pnl_pct": round(w_pnl, 2),
                        "pnl_amount": round(w_exit_price - w_entry, 2),
                        "is_win": w_pnl > 0,
                        "exit_reason": "ROTATION",
                    }).eq("id", weakest["id"]).execute()
                    open_brain.discard(w_symbol)
                    brain_open_count -= 1
                    logger.info(
                        f"Virtual ROTATION: closed {w_symbol} (score {weakest_score}, P&L {w_pnl:+.1f}%) "
                        f"to make room for {symbol} (score {score})"
                    )
                    _pending_notifications.append(("brain_sell", {
                        "symbol": w_symbol, "price": f"{w_exit_price:.2f}",
                        "pnl": f"{w_pnl:+.1f}", "reason": f"Rotated out for {symbol} (score {score})",
                        "entry_score": str(weakest_score), "exit_score": str(score),
                        "verdict": f"Replaced by stronger pick {symbol}.",
                    }))
                    # Update pre-computed weakest for next iteration
                    weakest_brain = None
                    weakest_brain_score = 999
                    for r in all_open:
                        if r.get("source") == "brain" and r.get("symbol") != w_symbol:
                            es = r.get("entry_score", 0) or 0
                            if es < weakest_brain_score:
                                weakest_brain_score = es
                                weakest_brain = r
                else:
                    continue  # No room and not strong enough to rotate
            target = sig.get("target_price")
            stop = sig.get("stop_loss")

            # For tech-only signals without AI target/stop, compute from ATR
            if not target or not stop:
                atr = (sig.get("technical_data") or {}).get("atr")
                if atr and price:
                    # Target = price + 2*ATR, Stop = price - 1.5*ATR (1.33 R/R)
                    target = round(price + 2 * float(atr), 2)
                    stop = round(price - 1.5 * float(atr), 2)

            if target and stop:
                # Crypto: tighten stop to 8% below entry (vs default which can be wider)
                if sig.get("asset_type") == "CRYPTO" or symbol.endswith("-USD"):
                    max_crypto_stop = price * 0.92  # 8% max drawdown
                    if float(stop) < max_crypto_stop:
                        stop = round(max_crypto_stop, 2)

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
                    "target_price": target,
                    "stop_loss": stop,
                }).execute()
                buys += 1
                brain_open_count += 1
                logger.info(f"Virtual BUY [brain]: {symbol} @ ${price:.2f} (score {score})")

                # Queue Telegram notification (sent after function returns)
                rr = round(float(target - price) / float(price - stop), 1) if stop and price > stop else 0
                _pending_notifications.append(("brain_buy", {
                    "symbol": symbol, "score": str(score),
                    "bucket": sig.get("bucket", ""),
                    "price": f"{price:.2f}", "target": f"{float(target):.2f}",
                    "stop": f"{float(stop):.2f}", "rr": f"{rr}",
                }))

                # Auto-add discovered tickers to the tickers table
                # so they keep getting scanned in future scans
                from app.db import queries as db_queries
                from app.scanners.universe import get_exchange
                try:
                    db_queries.upsert_ticker(
                        symbol,
                        name=sig.get("company_name", ""),
                        exchange=get_exchange(symbol),
                        bucket=sig.get("bucket"),
                    )
                except Exception:
                    pass

    return {"buys": buys, "sells": sells}


async def flush_brain_notifications():
    """Send all queued brain buy/sell notifications via Telegram."""
    if not _pending_notifications:
        return
    from app.notifications.messages import msg
    from app.notifications.telegram_bot import send_message
    for key, kwargs in list(_pending_notifications):
        try:
            await send_message(settings.telegram_chat_id, msg(key, **kwargs))
        except Exception as e:
            logger.debug(f"Brain notification failed ({key}): {e}")
    _pending_notifications.clear()


def check_virtual_exits() -> dict:
    """Check open virtual trades for stop/target hits and time-based exits.

    Called after each scan cycle. Fetches current prices via price_cache
    and closes trades that hit their stop, target, or max age.
    """
    db = get_client()
    max_days = settings.virtual_trade_max_days

    open_result = (
        db.table("virtual_trades")
        .select("id, symbol, entry_price, entry_score, entry_date, source, target_price, stop_loss")
        .eq("status", "OPEN")
        .execute()
    )
    open_trades = open_result.data or []
    if not open_trades:
        return {"stops_hit": 0, "targets_hit": 0, "profit_takes": 0, "expired": 0}

    # Batch-fetch current prices
    symbols = list({t["symbol"] for t in open_trades})
    prices = _fetch_prices_batch(symbols)

    # Batch fetch latest signal scores for exit tracking (1 query instead of N)
    current_scores: dict[str, int] = {}
    sig_result = (
        db.table("signals")
        .select("symbol, score")
        .in_("symbol", symbols)
        .order("created_at", desc=True)
        .execute()
    )
    for row in (sig_result.data or []):
        sym = row.get("symbol")
        if sym and sym not in current_scores:
            current_scores[sym] = row.get("score", 0)

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    stops_hit = 0
    targets_hit = 0
    expired = 0
    profit_takes = 0

    for trade in open_trades:
        symbol = trade["symbol"]
        entry_price = float(trade["entry_price"])
        current_price, _ = prices.get(symbol, (None, None))

        if current_price is None:
            continue

        target = float(trade["target_price"]) if trade.get("target_price") else None
        stop = float(trade["stop_loss"]) if trade.get("stop_loss") else None
        pnl_pct = ((current_price - entry_price) / entry_price) * 100

        # Parse entry_date for age check
        entry_date_str = trade.get("entry_date", "")
        try:
            entry_date = datetime.fromisoformat(entry_date_str.replace("Z", "+00:00"))
            days_held = (now - entry_date).days
        except (ValueError, TypeError):
            days_held = 0

        # Determine exit reason (priority: stop > target > profit_take > time)
        exit_reason = None
        if stop and current_price <= stop:
            exit_reason = "STOP_HIT"
            stops_hit += 1
        elif target and current_price >= target:
            exit_reason = "TARGET_HIT"
            targets_hit += 1
        # Profit-taking: lock in gains at +3%+ after 2+ days (let thesis play out first)
        elif pnl_pct >= 3.0 and days_held >= 2:
            exit_reason = "PROFIT_TAKE"
            profit_takes += 1
            logger.info(f"Virtual PROFIT TAKE: {symbol} at +{pnl_pct:.1f}% (locking in gains)")
            _pending_notifications.append(("brain_sell", {
                "symbol": symbol, "price": f"{current_price:.2f}",
                "pnl": f"{pnl_pct:+.1f}", "reason": "Profit take at +3%",
                "entry_score": str(trade.get("entry_score", 0)),
                "exit_score": str(current_scores.get(symbol, 0)),
                "verdict": "Gains locked in. Goal: make profit.",
            }))
        elif days_held >= max_days:
            exit_reason = "TIME_EXPIRED"
            expired += 1

        if not exit_reason:
            continue
        pnl_amount = current_price - entry_price
        is_win = pnl_pct > 0
        source = trade.get("source", "watchlist")

        exit_score = current_scores.get(symbol)

        db.table("virtual_trades").update({
            "status": "CLOSED",
            "exit_price": current_price,
            "exit_date": now_iso,
            "exit_score": exit_score,
            "pnl_pct": round(pnl_pct, 2),
            "pnl_amount": round(pnl_amount, 2),
            "is_win": is_win,
            "exit_reason": exit_reason,
        }).eq("id", trade["id"]).execute()

        emoji = "✅" if is_win else "❌"
        logger.info(
            f"Virtual EXIT [{source}]: {emoji} {symbol} @ ${current_price:.2f} "
            f"(entry ${entry_price:.2f}, P&L {pnl_pct:+.1f}%, reason={exit_reason}, exit_score={exit_score})"
        )

    total = stops_hit + targets_hit + profit_takes + expired
    if total:
        logger.info(f"Virtual exits: {stops_hit} stops, {targets_hit} targets, {profit_takes} profit takes, {expired} expired")

    return {"stops_hit": stops_hit, "targets_hit": targets_hit, "profit_takes": profit_takes, "expired": expired}


_vp_cache = TTLCache(max_size=2, default_ttl=300)


@with_retry
def get_virtual_summary() -> dict:
    """Get virtual portfolio performance summary for the dashboard.

    Includes live P&L for open positions via current price fetch.
    Cached for 5 minutes to avoid repeated DB + price queries on every page load.
    """
    cached = _vp_cache.get("summary")
    if cached is not None:
        return cached

    db = get_client()

    # All trades
    open_result = (
        db.table("virtual_trades")
        .select("symbol, entry_price, entry_date, entry_score, bucket, signal_style, source, target_price, stop_loss")
        .eq("status", "OPEN")
        .order("entry_date", desc=True)
        .execute()
    )
    open_trades = open_result.data or []

    closed_result = (
        db.table("virtual_trades")
        .select("symbol, entry_price, exit_price, pnl_pct, pnl_amount, is_win, "
                "entry_date, exit_date, entry_score, exit_score, bucket, source, exit_reason")
        .eq("status", "CLOSED")
        .order("exit_date", desc=True)
        .limit(50)
        .execute()
    )
    closed_trades = closed_result.data or []

    # Fetch current prices for open positions
    now = datetime.now(timezone.utc)
    current_prices = {}
    signal_context = {}
    if open_trades:
        symbols = list({t["symbol"] for t in open_trades})
        price_data = _fetch_prices_batch(symbols)
        current_prices = {sym: p for sym, (p, _) in price_data.items() if p is not None}

        # Batch fetch latest signal context for all open symbols (1 query instead of N)
        sig_result = (
            db.table("signals")
            .select("symbol, score, reasoning, risk_reward, signal_style, contrarian_score, market_regime")
            .in_("symbol", symbols)
            .order("created_at", desc=True)
            .execute()
        )
        for row in (sig_result.data or []):
            sym = row.get("symbol")
            if sym and sym not in signal_context:
                signal_context[sym] = row

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

    def _enrich_open_trade(t: dict) -> dict:
        symbol = t["symbol"]
        entry_price = float(t["entry_price"])
        current = current_prices.get(symbol)

        # Calculate days held
        entry_date_str = t.get("entry_date", "")
        try:
            entry_date = datetime.fromisoformat(entry_date_str.replace("Z", "+00:00"))
            days_held = (now - entry_date).days
        except (ValueError, TypeError):
            days_held = 0

        # Get signal reasoning (why the brain picked this)
        sig = signal_context.get(symbol, {})

        enriched = {
            "symbol": symbol,
            "entry_price": entry_price,
            "entry_score": t.get("entry_score"),
            "bucket": t.get("bucket"),
            "source": t.get("source", "watchlist"),
            "signal_style": t.get("signal_style") or sig.get("signal_style"),
            "target_price": t.get("target_price"),
            "stop_loss": t.get("stop_loss"),
            "days_held": days_held,
            "current_score": sig.get("score"),
            "reasoning": sig.get("reasoning"),
            "risk_reward": sig.get("risk_reward"),
            "contrarian_score": sig.get("contrarian_score"),
            "market_regime": sig.get("market_regime"),
        }

        if current:
            pnl_pct = ((current - entry_price) / entry_price) * 100
            enriched["current_price"] = round(current, 2)
            enriched["unrealized_pnl_pct"] = round(pnl_pct, 2)
            enriched["unrealized_pnl_amount"] = round(current - entry_price, 2)

        return enriched

    # Enrich open trades with live P&L
    enriched_open = [_enrich_open_trade(t) for t in open_trades]

    # Calculate aggregate unrealized P&L per source
    def _unrealized_agg(trades: list[dict]) -> float:
        pnls = [t.get("unrealized_pnl_pct", 0) for t in trades if "unrealized_pnl_pct" in t]
        return round(sum(pnls) / len(pnls), 2) if pnls else 0

    # Split by source
    watchlist_open_enriched = [t for t in enriched_open if t.get("source") == "watchlist"]
    brain_open_enriched = [t for t in enriched_open if t.get("source") == "brain"]
    watchlist_closed = [t for t in closed_trades if t.get("source") == "watchlist"]
    brain_closed = [t for t in closed_trades if t.get("source") == "brain"]

    result = {
        "open_count": len(open_trades),
        "open_trades": enriched_open,
        # Combined stats
        **_calc_stats(closed_trades),
        "recent_closed": [
            {
                "symbol": t["symbol"],
                "pnl_pct": t["pnl_pct"],
                "is_win": t["is_win"],
                "source": t.get("source", "watchlist"),
                "exit_reason": t.get("exit_reason"),
                "entry_score": t.get("entry_score"),
                "exit_score": t.get("exit_score"),
            }
            for t in closed_trades[:5]
        ],
        # Per-source breakdown
        "watchlist": {
            "open_count": len(watchlist_open_enriched),
            "avg_unrealized_pnl_pct": _unrealized_agg(watchlist_open_enriched),
            **_calc_stats(watchlist_closed),
        },
        "brain": {
            "open_count": len(brain_open_enriched),
            "avg_unrealized_pnl_pct": _unrealized_agg(brain_open_enriched),
            **_calc_stats(brain_closed),
        },
        # Watchdog summary
        "watchdog": _get_watchdog_summary(db, len(brain_open_enriched)),
    }

    _vp_cache.set("summary", result)
    return result


def _get_watchdog_summary(db, positions_monitored: int) -> dict:
    """Get watchdog status for the dashboard."""
    try:
        recent = (
            db.table("watchdog_events")
            .select("symbol, event_type, created_at")
            .order("created_at", desc=True)
            .limit(5)
            .execute()
        )
        return {
            "active": settings.watchdog_enabled,
            "positions_monitored": positions_monitored,
            "recent_events": recent.data or [],
        }
    except Exception as e:
        logger.warning(f"Watchdog summary query failed: {e}")
        return {"active": settings.watchdog_enabled, "positions_monitored": positions_monitored, "recent_events": []}


@with_retry
def get_virtual_charts() -> dict:
    """Get chart data for the brain performance page.

    Returns pre-computed data structures the frontend can render directly.
    Cached for 5 minutes to avoid repeated DB queries on every page load.
    """
    cached = _vp_cache.get("charts")
    if cached is not None:
        return cached

    db = get_client()

    # All closed trades for charts
    result = (
        db.table("virtual_trades")
        .select("symbol, entry_price, exit_price, pnl_pct, is_win, entry_date, exit_date, "
                "entry_score, bucket, source, exit_reason, signal_style")
        .eq("status", "CLOSED")
        .order("exit_date", desc=True)
        .limit(200)
        .execute()
    )
    closed = result.data or []

    if not closed:
        return {
            "pnl_by_bucket": [],
            "monthly_returns": [],
            "exit_reasons": [],
            "score_vs_pnl": [],
            "win_rate_over_time": [],
        }

    # 1. P&L by bucket (brain vs watchlist, SAFE_INCOME vs HIGH_RISK)
    bucket_groups: dict[str, dict] = {}
    for t in closed:
        key = f"{t.get('source', 'watchlist')}_{t.get('bucket', 'UNKNOWN')}"
        if key not in bucket_groups:
            bucket_groups[key] = {"source": t.get("source"), "bucket": t.get("bucket"), "trades": 0, "total_pnl": 0, "wins": 0}
        bucket_groups[key]["trades"] += 1
        bucket_groups[key]["total_pnl"] += t.get("pnl_pct", 0)
        if t.get("is_win"):
            bucket_groups[key]["wins"] += 1

    pnl_by_bucket = [
        {
            "source": v["source"],
            "bucket": v["bucket"],
            "trades": v["trades"],
            "total_pnl_pct": round(v["total_pnl"], 2),
            "avg_pnl_pct": round(v["total_pnl"] / v["trades"], 2) if v["trades"] else 0,
            "win_rate": round(v["wins"] / v["trades"] * 100, 1) if v["trades"] else 0,
        }
        for v in bucket_groups.values()
    ]

    # 2. Monthly returns (brain track)
    brain_closed = [t for t in closed if t.get("source") == "brain"]
    monthly: dict[str, dict] = {}
    for t in brain_closed:
        exit_date = t.get("exit_date", "")
        if not exit_date:
            continue
        month_key = exit_date[:7]  # "2026-04"
        if month_key not in monthly:
            monthly[month_key] = {"month": month_key, "trades": 0, "total_pnl": 0, "wins": 0}
        monthly[month_key]["trades"] += 1
        monthly[month_key]["total_pnl"] += t.get("pnl_pct", 0)
        if t.get("is_win"):
            monthly[month_key]["wins"] += 1

    monthly_returns = sorted([
        {
            "month": v["month"],
            "trades": v["trades"],
            "total_pnl_pct": round(v["total_pnl"], 2),
            "avg_pnl_pct": round(v["total_pnl"] / v["trades"], 2) if v["trades"] else 0,
            "win_rate": round(v["wins"] / v["trades"] * 100, 1) if v["trades"] else 0,
        }
        for v in monthly.values()
    ], key=lambda x: x["month"])

    # 3. Exit reasons distribution
    reason_counts: dict[str, int] = {}
    for t in closed:
        reason = t.get("exit_reason", "SIGNAL") or "SIGNAL"
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    exit_reasons = [
        {"reason": reason, "count": count, "pct": round(count / len(closed) * 100, 1)}
        for reason, count in sorted(reason_counts.items())
    ]

    # 4. Score vs P&L scatter (for all closed trades)
    score_vs_pnl = [
        {
            "symbol": t["symbol"],
            "entry_score": t.get("entry_score"),
            "pnl_pct": t.get("pnl_pct"),
            "source": t.get("source"),
            "bucket": t.get("bucket"),
        }
        for t in closed
        if t.get("entry_score") is not None and t.get("pnl_pct") is not None
    ]

    # 5. Rolling win rate (last N trades, window of 10)
    win_rate_over_time = []
    # Reverse to chronological order
    chronological = list(reversed(closed))
    window = 10
    for i in range(window - 1, len(chronological)):
        batch = chronological[i - window + 1: i + 1]
        wins = sum(1 for t in batch if t.get("is_win"))
        trade = chronological[i]
        win_rate_over_time.append({
            "trade_num": i + 1,
            "symbol": trade.get("symbol"),
            "exit_date": trade.get("exit_date", "")[:10],
            "win_rate": round(wins / window * 100, 1),
        })

    result = {
        "pnl_by_bucket": pnl_by_bucket,
        "monthly_returns": monthly_returns,
        "exit_reasons": exit_reasons,
        "score_vs_pnl": score_vs_pnl,
        "win_rate_over_time": win_rate_over_time,
    }

    _vp_cache.set("charts", result)
    return result


def snapshot_virtual_portfolio() -> dict:
    """Take a daily snapshot of portfolio state for the equity curve.

    Call once per day (after the last scan). Upserts by snapshot_date.
    """
    db = get_client()
    summary = get_virtual_summary()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Get cumulative closed P&L (all time)
    all_closed = (
        db.table("virtual_trades")
        .select("pnl_pct, source")
        .eq("status", "CLOSED")
        .execute()
    )
    all_closed_data = all_closed.data or []
    brain_cum = sum(t.get("pnl_pct", 0) for t in all_closed_data if t.get("source") == "brain")
    watchlist_cum = sum(t.get("pnl_pct", 0) for t in all_closed_data if t.get("source") == "watchlist")

    # Fetch SPY price for benchmark
    spy_data = _fetch_prices_batch(["SPY"])
    spy_price, _ = spy_data.get("SPY", (None, None))

    snapshot = {
        "snapshot_date": today,
        "brain_open": summary.get("brain", {}).get("open_count", 0),
        "brain_unrealized_pnl": summary.get("brain", {}).get("avg_unrealized_pnl_pct", 0),
        "brain_cumulative_pnl": round(brain_cum, 2),
        "watchlist_open": summary.get("watchlist", {}).get("open_count", 0),
        "watchlist_unrealized_pnl": summary.get("watchlist", {}).get("avg_unrealized_pnl_pct", 0),
        "watchlist_cumulative_pnl": round(watchlist_cum, 2),
        "spy_price": spy_price,
    }

    # Upsert by snapshot_date
    db.table("virtual_snapshots").upsert(snapshot, on_conflict="snapshot_date").execute()
    logger.info(f"Virtual snapshot saved for {today}: brain_cum={brain_cum:+.1f}%, watchlist_cum={watchlist_cum:+.1f}%")

    return snapshot
