"""Stage 6 — re-evaluate every open brain position's thesis at every scan.

============================================================
WHAT THIS MODULE IS
============================================================

The brain captures the REASON for every entry (`virtual_trades.entry_thesis`).
This module runs once per scan, AFTER `process_virtual_trades` and BEFORE
`check_virtual_exits`, and asks Claude:

    "You bought {symbol} on {date} because {entry_thesis}.
     Given today's data, is that reason still valid?"

If Claude returns `status='invalid'`, the position is closed with
`exit_reason='THESIS_INVALIDATED'` — regardless of P&L direction. A
winning position with a dead thesis is sold; a losing position with an
intact thesis is held.

The thesis status is also persisted on the position row so the existing
exit paths (STOP_HIT, TARGET_HIT, etc.) can READ it and suppress
themselves when the thesis is still valid (the HUM Day-1 fix). The only
exit that bypasses the thesis gate is the catastrophic stop carve-out
at `settings.brain_thesis_hard_stop_pct`.

============================================================
COST
============================================================

1 Claude call per open brain position per scan. With 5 open positions
and 8 scans/day at ~$0.012/call (paid Claude API), that's ~$0.48/day.
Most calls go through Claude Local (free) so actual cost is much lower.

If both Claude tiers are unavailable, `re_evaluate_thesis` returns None
and we silently skip the position — `thesis_last_*` fields are NOT
cleared, so any prior status from a previous scan remains in effect.

============================================================
PRE-STAGE-6 TRADES
============================================================

Trades that were opened BEFORE Stage 6 ships have NULL `entry_thesis`.
We silently skip them — they keep falling through the existing exit
paths with no thesis protection. Once they close and new positions open,
those new positions will have theses captured.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from app.core.config import settings
from app.core.dates import parse_iso_utc
from app.db.supabase import get_client
from app.services.knowledge_events import (
    EVENT_THESIS_EVALUATED,
    EVENT_THESIS_INVALIDATED_EXIT,
    log_event,
)
from app.services.price_cache import _fetch_prices_batch


# Cap on concurrent Claude re-evals. Claude Local CLI is a subprocess
# stampede risk above ~3 in parallel; the paid API tolerates more but
# we keep the cap conservative to limit token spend bursts.
THESIS_REEVAL_CONCURRENCY = 3


# Minimum confidence required from Claude before we'll act on an "invalid"
# thesis verdict. Without this floor, a parser glitch or hallucinated JSON
# (e.g., {"should_exit": true, "confidence": 5}) could close arbitrary
# winning positions. The combination of (status == 'invalid') AND
# (confidence >= floor) is what makes the gate trustworthy.
THESIS_INVALIDATION_MIN_CONFIDENCE = 60


async def reevaluate_open_theses(
    signals: list[dict],
    scan_started_at: Optional[datetime] = None,
    scan_type: Optional[str] = None,
) -> dict[str, dict]:
    """Re-evaluate every open brain position's thesis. Returns {symbol: ctx_dict}.

    Args:
        signals: Fresh signals from the current scan. Used to look up CURRENT
            conditions for each open position by symbol. If a position's
            symbol isn't in this scan's signals, we skip its re-eval (no
            fresh data) and the cached `thesis_last_*` from the prior scan
            stays in place.
        scan_started_at: Timestamp when the current scan began. Positions
            whose `entry_date` is at-or-after this timestamp were opened
            earlier in this same scan and MUST NOT be re-evaluated — the
            thesis has had no time to drift. Day 10 journal documented the
            bug: three fresh entries (ESE, CCO.TO, DIR-UN.TO) opened at
            14:01:57 were closed via THESIS_INVALIDATED at 14:02:54 inside
            the same MORNING scan because Claude re-read the same thesis
            and returned `invalid` on a position that was 57s old. The
            60-min re-buy cooldown doesn't help here because it fires
            AFTER a THESIS_INVALIDATED close, not before one.

    Returns:
        dict mapping symbol → context dict that includes:
            - "result": Claude's parsed re-eval result (status, confidence, ...)
            - "position": the full position row from virtual_trades
            - "live_price": the price used for the re-eval
            - "pnl_pct": the P&L at re-eval time
            - "days_held": days from entry to now
        The context bundle lets `execute_thesis_invalidation_exits` close
        positions WITHOUT re-fetching the row or the live price (eliminating
        the prior 2N+1 query pattern).
    """
    if not settings.brain_thesis_gate_enabled:
        return {}

    db = get_client()
    # Shared close-field list plus the thesis-re-eval extras.
    from app.services.virtual_portfolio import VIRTUAL_TRADES_CLOSE_FIELDS
    open_positions = (
        db.table("virtual_trades")
        .select(VIRTUAL_TRADES_CLOSE_FIELDS + ", entry_thesis, entry_thesis_keywords")
        .eq("status", "OPEN")
        .eq("source", "brain")
        .execute()
    ).data or []
    if not open_positions:
        return {}

    # Index fresh signals by symbol for O(1) lookup
    sig_by_sym = {s.get("symbol"): s for s in signals if s.get("symbol")}

    # Batch live prices once for ALL open positions
    symbols = [p["symbol"] for p in open_positions]
    try:
        prices = _fetch_prices_batch(symbols)
    except Exception as e:
        logger.warning(f"thesis_tracker price fetch failed: {e}")
        prices = {}

    # Lazy import to avoid circular dependency at module load
    from app.ai.provider import re_evaluate_thesis

    # Build the work list of (pos, prepared_kwargs) for positions that
    # actually need a Claude call. We do this BEFORE launching gather so
    # we can skip pre-Stage-6 trades and missing-signal cases without
    # paying for Claude time.
    semaphore = asyncio.Semaphore(THESIS_REEVAL_CONCURRENCY)
    work: list[dict] = []
    for pos in open_positions:
        sym = pos["symbol"]
        # Same-scan guard (Day 10 learning): a position opened earlier in
        # THIS scan has an entry_thesis built from the same signal we're
        # about to re-read — re-evaluating it is guaranteed to be stale
        # reasoning at best, or a flip-flop ("buy then sell in 57s") at
        # worst. Skip anything whose entry_date is at-or-after scan start.
        if scan_started_at is not None:
            entry_dt = parse_iso_utc(pos.get("entry_date"))
            if entry_dt is not None and entry_dt >= scan_started_at:
                logger.debug(
                    f"Thesis re-eval skipped for {sym}: opened this scan "
                    f"(entry={entry_dt.isoformat()} >= scan_start={scan_started_at.isoformat()})"
                )
                continue
        # LONG positions only get thesis re-eval during the AFTER_CLOSE scan.
        # This is the core of the SHORT/LONG split: LONG winners were being
        # killed by 5x/day conservative re-evals (WING +8.5% → +4.13%,
        # HMY +7.94% → +2.33%). One daily check catches real thesis death
        # while letting the trend compound intraday.
        horizon = pos.get("trade_horizon") or "SHORT"
        if horizon == "LONG" and scan_type and scan_type != "AFTER_CLOSE":
            logger.debug(
                f"Thesis re-eval skipped for {sym}: LONG horizon, "
                f"scan_type={scan_type} (only re-evals at AFTER_CLOSE)"
            )
            continue
        if not pos.get("entry_thesis"):
            logger.debug(
                f"Thesis re-eval skipped for {sym}: no entry_thesis "
                f"(pre-Stage-6 trade)"
            )
            continue
        fresh_sig = sig_by_sym.get(sym)
        if not fresh_sig:
            logger.debug(f"Thesis re-eval skipped for {sym}: no fresh signal this scan")
            continue
        live_price, _ = prices.get(sym, (None, None))
        if not live_price:
            live_price = fresh_sig.get("price_at_signal") or pos.get("entry_price")
        entry_price = float(pos.get("entry_price") or 0)
        if not entry_price or not live_price:
            continue
        direction = pos.get("direction") or "LONG"
        if direction == "SHORT":
            pnl_pct = (entry_price - live_price) / entry_price * 100
        else:
            pnl_pct = (live_price - entry_price) / entry_price * 100
        entry_dt = parse_iso_utc(pos.get("entry_date")) or datetime.now(timezone.utc)
        days_held = max(0, (datetime.now(timezone.utc) - entry_dt).days)
        work.append({
            "pos": pos,
            "live_price": float(live_price),
            "entry_price": entry_price,
            "pnl_pct": pnl_pct,
            "days_held": days_held,
            "entry_conditions": pos.get("entry_thesis_keywords") or {},
            "current_conditions": _build_current_conditions(fresh_sig),
        })

    if not work:
        return {}

    async def _eval_one(item: dict) -> tuple[dict, Optional[dict]]:
        """Single bounded re-eval call. Returns (work_item, result_or_None)."""
        async with semaphore:
            try:
                result = await re_evaluate_thesis(
                    symbol=item["pos"]["symbol"],
                    entry_date=item["pos"].get("entry_date") or "",
                    entry_price=item["entry_price"],
                    current_price=item["live_price"],
                    pnl_pct=item["pnl_pct"],
                    days_held=item["days_held"],
                    entry_thesis=item["pos"].get("entry_thesis") or "",
                    entry_conditions=item["entry_conditions"],
                    current_conditions=item["current_conditions"],
                )
                return item, result
            except Exception as e:
                logger.warning(
                    f"Thesis re-eval call failed for {item['pos']['symbol']}: {e}"
                )
                return item, None

    # Run all re-evals in parallel, bounded by the semaphore. With 5 open
    # positions and concurrency=3, this completes in ~2 batches instead of
    # 5 sequential waits — saves ~50s/scan when Claude Local is healthy.
    #
    # `return_exceptions=True` is required: without it, a BaseException
    # subclass (e.g. asyncio.CancelledError from a cancelled scan) would
    # propagate out of gather and kill in-flight siblings, potentially
    # orphaning Claude subprocesses. With it, each pair is either a
    # (item, result) tuple or a BaseException we filter out below.
    eval_pairs_raw = await asyncio.gather(
        *(_eval_one(w) for w in work),
        return_exceptions=True,
    )
    eval_pairs = []
    for entry in eval_pairs_raw:
        if isinstance(entry, BaseException):
            logger.warning(f"Thesis re-eval task raised: {entry!r}")
            continue
        eval_pairs.append(entry)

    # Persist results + emit audit events. We do this AFTER all gathered
    # results return so we don't interleave DB writes with Claude waits.
    results: dict[str, dict] = {}
    now_iso = datetime.now(timezone.utc).isoformat()
    for item, result in eval_pairs:
        if result is None:
            # Both Claude tiers unavailable; leave thesis_last_* untouched
            logger.debug(
                f"Thesis re-eval returned None for {item['pos']['symbol']} "
                f"(Claude unavailable)"
            )
            continue

        sym = item["pos"]["symbol"]
        new_status = (result.get("status") or "valid").lower()
        new_reason = (result.get("reason") or "")[:500]

        # Bundle everything `execute_thesis_invalidation_exits` would
        # otherwise re-fetch — eliminates the 2N+1 query pattern.
        results[sym] = {
            "result": result,
            "position": item["pos"],
            "live_price": item["live_price"],
            "pnl_pct": item["pnl_pct"],
            "days_held": item["days_held"],
        }

        try:
            db.table("virtual_trades").update({
                "thesis_last_checked_at": now_iso,
                "thesis_last_status": new_status,
                "thesis_last_reason": new_reason,
            }).eq("id", item["pos"]["id"]).execute()
        except Exception as e:
            logger.warning(f"Failed to persist thesis result for {sym}: {e}")

        log_event(
            EVENT_THESIS_EVALUATED,
            triggered_by="thesis_tracker",
            trade_id=item["pos"]["id"],
            payload={
                "symbol": sym,
                "status": new_status,
                "confidence": result.get("confidence"),
                "should_exit": bool(result.get("should_exit")),
                "pnl_pct_at_check": round(item["pnl_pct"], 2),
                "days_held": item["days_held"],
                "provider": result.get("_provider"),
                "current_thesis": result.get("current_thesis"),
            },
            reason=(
                f"Thesis re-eval for {sym}: {new_status} "
                f"(P&L {item['pnl_pct']:+.2f}%, day {item['days_held']}). "
                f"Claude says: {new_reason[:200]}"
            ),
        )

    return results


def _build_current_conditions(fresh_sig: dict) -> dict:
    """Pull the structured 'current conditions' from a fresh signal dict.

    Mirrors the shape of `entry_thesis_keywords` so the re-eval prompt can
    diff entry vs now field-by-field.
    """
    td = fresh_sig.get("technical_data") or {}
    md = fresh_sig.get("macro_data") or {}
    gd = fresh_sig.get("grok_data") or {}
    return {
        "regime": fresh_sig.get("market_regime") or md.get("regime"),
        "score_now": fresh_sig.get("score"),
        "macd_histogram": td.get("macd_histogram"),
        "rsi": td.get("rsi"),
        "vs_sma200": td.get("vs_sma200"),
        "sentiment_score": gd.get("score") if isinstance(gd, dict) else None,
        "sentiment_label": gd.get("label") if isinstance(gd, dict) else None,
        "fear_greed": md.get("fear_greed"),
        "current_action": fresh_sig.get("action"),
    }


def execute_thesis_invalidation_exits(
    thesis_results: dict[str, dict],
    notifications: list,
) -> int:
    """Close any brain position whose thesis re-evaluated to 'invalid'.

    Args:
        thesis_results: The dict returned by `reevaluate_open_theses` —
            each value bundles the position row, live price, P&L, and the
            Claude result, so this function does NOT need to re-fetch
            positions or prices (eliminates the prior 2N+1 query pattern).
        notifications: The brain notification queue (a list — we type it
            loosely to avoid importing the queue type and creating a
            circular dependency).

    Returns the count of closed positions. Exits set
    exit_reason='THESIS_INVALIDATED' so the journal can distinguish them
    from price-based exits.

    IMPORTANT: This runs BEFORE check_virtual_exits. Positions closed
    here will be ignored by the subsequent stop/target sweep thanks to
    the .eq("status","OPEN") guard on every UPDATE.
    """
    if not settings.brain_thesis_gate_enabled:
        return 0

    # Confidence-gated invalidation: both status == 'invalid' AND
    # confidence >= floor must hold. Blocks Claude parser glitches and
    # low-confidence "should_exit=true" hallucinations from force-closing
    # winning positions.
    invalid_ctxs: list[dict] = []
    for sym, ctx in thesis_results.items():
        result = ctx.get("result") or {}
        if (result.get("status") or "").lower() != "invalid":
            continue
        # Handle confidence as int ("60"), float (60.5), float-string ("60.5"),
        # or garbage ("high", None). Coerce via float() first to tolerate
        # stringified decimals Claude occasionally produces, then int() for
        # the floor comparison.
        raw_conf = result.get("confidence")
        if raw_conf is None:
            confidence = 0
        else:
            try:
                confidence = int(float(raw_conf))
            except (TypeError, ValueError):
                confidence = 0
        if confidence < THESIS_INVALIDATION_MIN_CONFIDENCE:
            logger.info(
                f"Thesis invalidation IGNORED for {sym}: status=invalid but "
                f"confidence={confidence} < {THESIS_INVALIDATION_MIN_CONFIDENCE} "
                f"(low-confidence verdict, holding the position)"
            )
            continue
        invalid_ctxs.append(ctx)

    if not invalid_ctxs:
        return 0

    db = get_client()

    # Batch the latest-score lookup for ALL symbols at once instead of
    # one query per symbol. Single query, in-memory dedup by latest
    # created_at per symbol.
    invalid_symbols = [c["position"]["symbol"] for c in invalid_ctxs]
    latest_scores: dict[str, int] = {}
    try:
        rows = (
            db.table("signals")
            .select("symbol, score, created_at")
            .in_("symbol", invalid_symbols)
            .order("created_at", desc=True)
            .execute()
        ).data or []
        for row in rows:
            sym = row.get("symbol")
            if sym and sym not in latest_scores:
                latest_scores[sym] = row.get("score")
    except Exception as e:
        logger.warning(f"thesis_tracker batch latest-score query failed: {e}")

    # Route every THESIS_INVALIDATED close through the shared helper so
    # wallet settlement + learning loop fire consistently. Direct UPDATEs
    # from here (the old path) silently bypassed the wallet — a
    # wallet-LONG closed via THESIS_INVALIDATED would leak its full
    # position size because the proceeds never got credited back.
    from app.services.virtual_portfolio import close_virtual_trade

    closed = 0
    for ctx in invalid_ctxs:
        pos = ctx["position"]
        sym = pos["symbol"]
        live_price = ctx["live_price"]
        entry_price = float(pos.get("entry_price") or 0)
        if not live_price or not entry_price:
            logger.warning(f"Cannot exit {sym} via thesis_invalidated: no price")
            continue
        pnl_pct = ctx["pnl_pct"]
        is_win = pnl_pct > 0
        exit_score = latest_scores.get(sym)

        try:
            close_res = close_virtual_trade(
                pos, float(live_price), "THESIS_INVALIDATED", exit_score,
            )
        except Exception as e:
            logger.warning(f"Failed to close {sym} via thesis_invalidated: {e}")
            continue

        # Skip the event log + Telegram alert if another path already
        # closed this row — don't double-announce a close we didn't do.
        if close_res.get("skipped"):
            logger.info(
                f"thesis_invalidated for {sym} skipped — row already closed by "
                f"another path; no audit event or notification sent."
            )
            continue

        closed += 1
        emoji = "✅" if is_win else "❌"
        result = ctx.get("result") or {}
        thesis_reason = (result.get("reason") or "")[:200]
        logger.info(
            f"Virtual THESIS_INVALIDATED [brain]: {emoji} {sym} @ ${live_price:.2f} "
            f"(entry ${entry_price:.2f}, P&L {pnl_pct:+.1f}%, reason: {thesis_reason})"
        )

        log_event(
            EVENT_THESIS_INVALIDATED_EXIT,
            triggered_by="thesis_tracker",
            trade_id=pos["id"],
            payload={
                "symbol": sym,
                "entry_price": entry_price,
                "exit_price": float(live_price),
                "pnl_pct": round(pnl_pct, 2),
                "is_win": is_win,
                "thesis_reason": thesis_reason,
                "claude_provider": result.get("_provider"),
                "claude_confidence": result.get("confidence"),
            },
            reason=(
                f"Closed {sym} via THESIS_INVALIDATED at {pnl_pct:+.2f}%. "
                f"Claude (confidence {result.get('confidence')}): {thesis_reason}"
            ),
        )

        if notifications is not None:
            verdict = (
                f"{emoji} {'Win' if is_win else 'Loss'} — thesis invalidated. "
                f"The reason for owning is gone."
            )
            notifications.append(("brain_sell", {
                "symbol": sym,
                "price": f"{live_price:.2f}",
                "pnl": f"{pnl_pct:+.1f}",
                "reason": f"Thesis invalidated: {thesis_reason[:100]}",
                "entry_score": str(pos.get("entry_score", 0)),
                "exit_score": str(exit_score or 0),
                "verdict": verdict,
            }))

    if closed:
        logger.info(f"thesis_tracker closed {closed} positions via THESIS_INVALIDATED")
    return closed
