"""Scan orchestrator — runs the full Signa data pipeline end-to-end.

============================================================
WHAT THIS MODULE IS
============================================================

This is the main entry point for every scan. The brain doesn't run on
its own — it runs as the final phase of a scan, on the signals this
module produces. Without scan_service, there are no signals and the
brain has nothing to act on.

A "scan" is the act of analyzing the entire ticker universe and
producing a fresh set of signals. Scans run on a schedule (4x/day:
PRE_MARKET, MORNING, PRE_CLOSE, AFTER_CLOSE) and can also be triggered
manually via /api/v1/scans/trigger.

This module is INTENTIONALLY large — every step of the pipeline lives
here so you can read top-to-bottom and understand the full flow without
hopping between files. The downside is the file is long; the upside is
the data flow is explicit at every step.

============================================================
THE 8-PHASE PIPELINE
============================================================

Every scan runs these phases in order. Progress percentages are
reported to the scans table for the frontend's progress bar.

  PHASE 1 — Universe loading & pre-filter  (0-15%)
  -------------------------------------------------
    • Load ~270 hardcoded tickers from `universe.get_all_tickers()`.
    • Add brain-discovered tickers from the DB (positions the brain
      bought that aren't in the core universe).
    • Add discovered trending tickers via `universe.discover_tickers()`
      (Yahoo Finance screeners — most active, day gainers, etc.)
      ONLY for PRE_MARKET / MANUAL scans (rate limit).
    • Bulk-fetch screening data via `market_scanner.get_bulk_screening`
      (price, volume, day_change for all tickers in one call).
    • Filter to top 50 candidates via `prefilter_candidates` based on
      volume >= 200K, price >= $1, |day_change| >= 1%. Crypto gets
      5 reserved slots so equities don't crowd them out.

  PHASE 2 — Macro snapshot  (15-20%)
  -----------------------------------
    • `macro_scanner.get_macro_snapshot()` runs ONCE per scan and is
      shared across all candidates. Includes Fed funds, CPI, VIX,
      Fear & Greed, intermarket signals.
    • Optional `get_macro_pulse()` for trending news topics
      (PRE_MARKET / MANUAL scans only).
    • Classifies the regime as TRENDING / VOLATILE / CRISIS.

  PHASE 3 — Previous signals + brain knowledge  (20%)
  ----------------------------------------------------
    • Load the most recent signal for each candidate ticker from the DB
      (used by `determine_status` to compute CONFIRMED/WEAKENING/etc).
    • Load the brain knowledge block — score ranges, GEM conditions,
      blocker rules, regime detection, calibration notes — once per
      scan, injected into AI prompts.

  PHASE 4a — PASS 1 pre-scoring  (20-45%)
  ----------------------------------------
    For every candidate (parallel, semaphore=3 to avoid DNS exhaustion):
      • Fetch 1-year price history via yfinance
      • Compute technical indicators (RSI, MACD, SMA, volume z-score, ATR)
      • Fetch fundamentals (P/E, EPS, dividend yield, market cap)
      • Quick score using technicals + fundamentals + macro ONLY
        (no AI yet — this is the cheap pre-score)
      • Skip HIGH_RISK candidates entirely if regime == "CRISIS"
    Output: list of (ticker, pre_score, bucket, technical_data, fundamental_data)

  PHASE 4b — Top-N AI candidate selection
  ----------------------------------------
    • Sort by pre-score descending.
    • Reserve at least 5 slots for HIGH_RISK (so sentiment is used).
    • Pick the top `ai_candidate_limit` (default 15).
    • PREPEND AI retry queue tickers (failed AI from previous scans).
    • FORCE-INCLUDE tickers with open brain positions (even if low
      pre-score) so we don't lose AI analysis on what the brain holds.
    • Everything else goes to `skip_candidates` (tech-only signals).

  PHASE 4c — PASS 2 full AI synthesis  (45-80%)
  ---------------------------------------------
    For every AI candidate (parallel):
      • Fetch sentiment via Grok / Gemini fallback (HIGH_RISK only —
        SAFE_INCOME hardcodes neutral to save cost).
      • Fetch Barchart options flow (free, all candidates).
      • Run AI synthesis via `provider.synthesize_signal` (Claude Local
        → Claude API → Gemini fallback chain).
      • Classify ai_status: validated / low_confidence / failed.
      • Update AI retry queue (clear on success, add on failure).
      • Compute final score with all components.
      • Run blockers check.
      • Detect contrarian signal style.
      • Determine action (BUY/HOLD/SELL/AVOID), with low-confidence /
        failed-AI BUY auto-downgraded to HOLD.
      • Check GEM conditions.
      • Determine status vs previous signal.
      • Build the signal_data dict.

    After Pass 2: check the AI failure rate. If > 50% of AI candidates
    failed synthesis, send an immediate Telegram alert.

  PHASE 5 — Persist  (85-90%)
  ----------------------------
    Batch insert all signal_data rows into the `signals` table.

  PHASE 6 — Alerts  (90-95%)
  ---------------------------
    • GEM alerts (one Telegram message per GEM).
    • Watchlist SELL/AVOID alerts (immediate ping for held positions).
    • Scan digest (PRE_MARKET and AFTER_CLOSE only).

  PHASE 7 — Brain (virtual portfolio)  (95%)
  -------------------------------------------
    This is where the brain runs. The order is critical:
      1. `new_notification_queue()` — fresh per-scan queue
      2. `process_pending_reviews(signals, queue)` — handle flagged positions
         from previous pre-market scans
      3. `process_virtual_trades(signals, watchlist, queue)` — main
         buy/sell loop, including the tiered trust model
      4. `check_virtual_exits(queue)` — stop/target/profit-take/age exits
      5. `await flush_brain_notifications(queue)` — drain the queue

  PHASE 8 — Position monitoring  (95-100%)
  -----------------------------------------
    Compares fresh signals against the user's REAL tracked positions
    (different from virtual brain positions) and sends alerts for stop
    hits, target hits, status changes, P&L milestones.

============================================================
DATA FLOW SUMMARY
============================================================

  scan_id created in scans table
       ↓
  Universe → pre-filter → candidates
       ↓
  Pre-score (PASS 1) → top N selection → AI candidates + skip candidates
       ↓
  Full AI analysis (PASS 2) → signal_data dicts
       ↓                              ↓
  Tech-only signals built              Failed-AI queued for retry
       ↓                              ↓
  signals table insert
       ↓
  GEM / watchlist SELL alerts
       ↓
  Brain (virtual portfolio): pending reviews → buys/sells → exits → flush
       ↓
  Position monitor (real user positions)
       ↓
  scan_id marked COMPLETE
"""

import asyncio
import time
from datetime import datetime, timezone

from loguru import logger

from app.ai import provider as ai_provider
from app.ai.signal_engine import (
    check_blockers,
    check_gem,
    compute_factor_labels,
    compute_probability_vs_spy,
    compute_score,
    determine_status,
    score_to_action,
)
from app.core.config import settings
from app.db import queries
from app.notifications.telegram_bot import send_gem_alert, send_scan_digest, send_watchlist_sell_alert
from app.scanners import barchart_scanner, indicators, macro_scanner, market_scanner
from app.scanners.prefilter import prefilter_candidates

# Ticker universe — hardcoded for now, could move to DB
from app.scanners.universe import get_all_tickers, get_asset_class, get_exchange


async def run_scan(scan_type: str, scan_id: str | None = None) -> str:
    """Execute a complete 8-phase scan cycle from universe load to brain action.

    This is the main entry point for every scan. See the file header for the
    full phase-by-phase breakdown. The function progresses through each phase
    sequentially, updating the `scans` table with progress and current_ticker
    so the frontend's progress bar can poll it.

    Each phase is gated by `if valid_signals:` or similar guards so partial
    failures don't crash the rest of the scan. Errors during AI synthesis
    for individual tickers are caught and counted in `errors_count`; if more
    than half of the AI candidates fail, the AI failure rate alert fires.

    The brain (virtual portfolio) runs in Phase 7. Even though the scan can
    complete successfully without the brain (e.g. if AI fails for everything),
    the brain still gets called with an empty queue — it just won't act.

    Args:
        scan_type: One of PRE_MARKET, MORNING, PRE_CLOSE, AFTER_CLOSE,
            MANUAL. The type affects:
              • PRE_MARKET / MANUAL: discovery scan + macro pulse fetch
              • PRE_MARKET / AFTER_CLOSE: scan digest Telegram alert
              • PRE_MARKET specifically: outside market hours, so the
                brain flags equities for review instead of executing.
        scan_id: Optional pre-created scan row ID (from `/scans/trigger`).
            If None, a new row is inserted at the start of the scan.

    Returns:
        The scan_id (existing or newly-created), even on failure.

    Side effects:
        • DB inserts/updates: scans, signals, virtual_trades, ai_retry_queue,
          ai_usage, watchdog_events, alerts.
        • Telegram alerts: GEM, watchlist SELL, scan digest, brain BUY/SELL,
          brain pending review, brain review cleared, AI failure rate,
          budget threshold.
        • Brain notification queue (created fresh per scan, drained at end).
    """
    start_time = time.time()
    logger.info(f"Starting {scan_type} scan...")

    # Load bucket cache once for the entire scan (avoids N individual DB queries)
    global _bucket_cache
    try:
        all_tickers = queries.get_active_tickers()
        _bucket_cache = {t["symbol"]: t["bucket"] for t in all_tickers if t.get("bucket")}
    except Exception:
        _bucket_cache = {}

    # Use pre-created scan or create new one
    if scan_id:
        queries.update_scan(scan_id, status="RUNNING", progress_pct=0, phase="loading")
    else:
        scan = queries.insert_scan({
            "scan_type": scan_type,
            "status": "RUNNING",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "progress_pct": 0,
            "phase": "loading",
        })
        scan_id = scan.get("id")

    def _update_progress(pct: int, phase: str, current_ticker: str = ""):
        """Update scan progress in DB for frontend polling."""
        queries.update_scan(scan_id, progress_pct=pct, phase=phase, current_ticker=current_ticker)

    try:
        # Phase 1: Load tickers + discovery and pre-filter (0-15%)
        _update_progress(5, "screening", "Loading universe...")
        all_tickers = get_all_tickers()

        # Add tickers from DB that brain previously discovered and picked
        core_set = set(all_tickers)
        db_tickers = queries.get_active_tickers()
        db_additions = [t["symbol"] for t in db_tickers if t["symbol"] not in core_set]
        if db_additions:
            all_tickers = all_tickers + db_additions

        # Discovery: find trending/active tickers not in the universe
        from app.scanners.universe import discover_tickers
        try:
            full_set = set(all_tickers)
            discovered = await asyncio.to_thread(discover_tickers)
            discovered = [d for d in discovered if d not in full_set]
            if discovered:
                all_tickers = all_tickers + discovered
        except Exception as e:
            logger.debug(f"Discovery failed: {e}")
            discovered = []

        discovered_set = set(discovered)
        logger.info(
            f"Universe: {len(all_tickers)} tickers "
            f"({len(core_set)} core + {len(db_additions)} brain-added + {len(discovered)} discovered)"
        )

        screening_data = await market_scanner.get_bulk_screening(all_tickers)
        _update_progress(10, "filtering")
        watchlist_symbols = queries.get_all_watchlist_symbols()
        candidates = prefilter_candidates(screening_data, watchlist_symbols)
        logger.info(f"Candidates after pre-filter: {len(candidates)}")

        queries.update_scan(scan_id, candidates=len(candidates), tickers_scanned=len(all_tickers))
        _update_progress(15, "macro", "Fetching macro data...")

        # Phase 2: Macro snapshot (15-20%)
        macro_data = await macro_scanner.get_macro_snapshot()

        # Macro news pulse -- only on first scan of the day to save Grok tokens
        if scan_type in ("PRE_MARKET", "MANUAL"):
            try:
                from app.ai.macro_pulse import get_macro_pulse
                pulse = await get_macro_pulse()
                macro_data["macro_pulse"] = pulse
            except Exception as e:
                logger.debug(f"Macro pulse skipped: {e}")

        # Layer 0 — Market regime (runs ONCE per scan, not per ticker)
        from app.signals.regime import get_market_regime
        market_regime = get_market_regime(macro_data)
        logger.info(f"Market regime: {market_regime}")
        queries.update_scan(scan_id, market_regime=market_regime)

        _update_progress(20, "analyzing")

        # Phase 3: Get previous signals + brain knowledge
        previous_signals = queries.get_latest_signals_map()

        # Load brain knowledge block ONCE per scan (not per ticker)
        from app.services.knowledge_service import KnowledgeService
        _ks = KnowledgeService()
        _knowledge_block = await _ks.get_knowledge_block([
            "signa_is_short_term_only",
            "score_ranges_and_actions",
            "backtest_key_findings",
            "gem_conditions",
            "signal_blockers",
            "market_regime_detection",
            "grok_sentiment_calibration",
            "supply_deficit_asymmetry",
            "contrarian_sentiment_in_commodities",
            "bubble_detection_framework",
        ])
        if _knowledge_block:
            logger.info(f"Brain knowledge loaded: {len(_knowledge_block)} chars")

        # Bust the per-scan pattern_stats dedupe cache so each scan
        # re-reads closed history + live open positions fresh.
        from app.services import pattern_stats
        pattern_stats.invalidate_cache()

        # ══════════════════════════════════════════════════════
        # TWO-PASS SCANNING — saves ~70% AI tokens
        # Pass 1: Quick pre-score (FREE — technicals + fundamentals only)
        # Pass 2: Full AI analysis (PAID — only top candidates)
        # ══════════════════════════════════════════════════════

        AI_CANDIDATE_LIMIT = settings.ai_candidate_limit
        semaphore = asyncio.Semaphore(3)  # Strict limit to prevent DNS thread exhaustion
        total_candidates = len(candidates)

        # ── PASS 1: Pre-score all candidates (no AI tokens) ──
        _update_progress(20, "prescoring", "Pre-scoring candidates...")
        pre_scores: list[tuple[str, int, str, dict, dict]] = []  # (ticker, score, bucket, tech, fund)

        async def _prescore(ticker: str, idx: int) -> tuple[str, int, str, dict, dict] | None:
            _update_progress(
                20 + int((idx / total_candidates) * 25),
                "prescoring",
                ticker,
            )
            try:
                bucket = _classify_bucket(ticker, screening_data.get(ticker, {}))
                if market_regime == "CRISIS" and bucket == "HIGH_RISK":
                    return None

                async with semaphore:
                    price_df, fundamental_data = await asyncio.gather(
                        market_scanner.get_price_history(ticker, "1y"),
                        market_scanner.get_fundamentals(ticker),
                    )

                technical_data = indicators.compute_indicators(price_df)
                # Quick score: technicals + fundamentals + macro only, no AI
                quick_score, _ = compute_score(
                    technical_data, fundamental_data or {}, macro_data,
                    {}, {}, bucket, market_regime,
                )
                return (ticker, quick_score, bucket, technical_data, fundamental_data or {})
            except Exception as e:
                logger.debug(f"Pre-score failed {ticker}: {e}")
                return None

        # Process in batches of 10 to avoid DNS thread exhaustion
        prescore_results = []
        batch_size = 10
        for batch_start in range(0, len(candidates), batch_size):
            batch = candidates[batch_start:batch_start + batch_size]
            batch_tasks = [_prescore(t, batch_start + i) for i, t in enumerate(batch)]
            batch_results = await asyncio.gather(*batch_tasks)
            prescore_results.extend(batch_results)
        pre_scores = [r for r in prescore_results if r is not None]

        # Sort by pre-score descending, pick top N for AI
        # Ensure a balanced mix: at least 5 HIGH_RISK slots so Grok sentiment gets used
        pre_scores.sort(key=lambda x: x[1], reverse=True)

        if settings.ai_enabled and AI_CANDIDATE_LIMIT > 0:
            safe_pool = [x for x in pre_scores if x[2] == "SAFE_INCOME"]
            risk_pool = [x for x in pre_scores if x[2] == "HIGH_RISK"]

            # Reserve at least 5 slots for HIGH_RISK (sentiment matters most there)
            min_risk_slots = min(5, len(risk_pool))
            safe_slots = AI_CANDIDATE_LIMIT - min_risk_slots

            ai_safe = safe_pool[:safe_slots]
            ai_risk = risk_pool[:min_risk_slots]

            # If one bucket didn't fill its slots, give extras to the other
            remaining = AI_CANDIDATE_LIMIT - len(ai_safe) - len(ai_risk)
            if remaining > 0:
                used = {(t[0]) for t in ai_safe + ai_risk}
                extras = [x for x in pre_scores if x[0] not in used][:remaining]
                ai_candidates = ai_safe + ai_risk + extras
            else:
                ai_candidates = ai_safe + ai_risk

            ai_tickers = {x[0] for x in ai_candidates}

            # AI retry queue: prepend tickers whose synthesis failed last scan.
            # Gives transient failures (CLI hiccup, API timeout) a second chance
            # without losing the signal entirely.
            from app.services.ai_retry_queue import cleanup_stale, get_retry_tickers
            # Drop entries older than RETRY_STALE_HOURS to keep the table small
            try:
                cleanup_stale()
            except Exception as e:
                logger.debug(f"AI retry queue cleanup failed: {e}")
            retry_rows = get_retry_tickers(limit=5)
            if retry_rows:
                pre_score_index = {r[0]: r for r in pre_scores}
                added = 0
                for retry_row in retry_rows:
                    rt_sym = retry_row["symbol"]
                    if rt_sym in ai_tickers:
                        continue  # Already in this scan's AI candidates
                    rt_pre = pre_score_index.get(rt_sym)
                    if rt_pre is None:
                        # Ticker not in this scan's pre-scored pool — skip it.
                        # Likely it dropped out of the pre-filter (low volume etc).
                        continue
                    ai_candidates.append(rt_pre)
                    ai_tickers.add(rt_sym)
                    added += 1
                    logger.info(
                        f"AI retry: re-attempting {rt_sym} "
                        f"(failure_count={retry_row.get('failure_count', '?')})"
                    )
                if added:
                    logger.info(f"AI retry queue: added {added} tickers to AI candidates")

            # Guard: force AI analysis on tickers with open brain positions
            # Prevents false AVOID/SELL from tech-only scoring on held positions
            from app.db.supabase import get_client as _get_db
            _db = _get_db()
            open_brain_result = _db.table("virtual_trades") \
                .select("symbol") \
                .eq("status", "OPEN") \
                .eq("source", "brain") \
                .execute()
            open_brain_symbols = {r["symbol"] for r in (open_brain_result.data or [])}

            for ps in pre_scores:
                if ps[0] in open_brain_symbols and ps[0] not in ai_tickers:
                    ai_candidates.append(ps)
                    ai_tickers.add(ps[0])
                    logger.info(f"Forced AI analysis for {ps[0]} (open brain position)")

            skip_candidates = [x for x in pre_scores if x[0] not in ai_tickers]
        else:
            # AI disabled — all candidates get tech-only scoring (zero AI cost)
            ai_candidates = []
            skip_candidates = pre_scores

        logger.info(
            f"Two-pass: {len(pre_scores)} pre-scored → "
            f"{len(ai_candidates)} get AI, {len(skip_candidates)} tech-only"
            f"{' (AI disabled)' if not settings.ai_enabled else ''}"
        )

        # ── PASS 2: Full AI analysis for top candidates ──
        _update_progress(45, "analyzing", "AI analysis on top candidates...")
        valid_signals = []
        errors_count = 0

        async def _process_ai(item: tuple, idx: int) -> dict | None:
            nonlocal errors_count
            ticker, _, _, _, _ = item
            _update_progress(
                45 + int((idx / max(len(ai_candidates), 1)) * 35),
                "analyzing",
                ticker,
            )
            try:
                result = await _process_candidate(
                    ticker, macro_data, screening_data, previous_signals,
                    scan_id, semaphore, market_regime, _knowledge_block,
                    discovered_set,
                )
                return result
            except Exception as e:
                errors_count += 1
                logger.debug(f"AI processing failed {ticker}: {e}")
                return None

        ai_tasks = [_process_ai(item, i) for i, item in enumerate(ai_candidates)]
        ai_results = await asyncio.gather(*ai_tasks)
        valid_signals.extend(s for s in ai_results if isinstance(s, dict))

        # AI failure rate guard: alert if >50% of AI candidates failed synthesis.
        # This catches systemic issues (CLI dead, API key revoked, all providers
        # over budget) before the brain operates blind for hours.
        ai_total = len(ai_candidates)
        ai_failed = sum(
            1 for s in ai_results
            if isinstance(s, dict) and s.get("ai_status") == "failed"
        ) + errors_count  # exception-thrown candidates also count as failures
        if ai_total > 0 and ai_failed / ai_total > 0.5:
            failure_pct = int((ai_failed / ai_total) * 100)
            logger.error(
                f"AI failure rate critical: {ai_failed}/{ai_total} ({failure_pct}%) "
                f"failed synthesis this scan"
            )
            # Best-effort Telegram alert (don't break the scan if it fails)
            try:
                from app.notifications.messages import msg
                from app.notifications.telegram_bot import send_message
                # Build a brief error breakdown from failed signals
                error_samples = []
                for s in ai_results:
                    if isinstance(s, dict) and s.get("ai_status") == "failed":
                        reason = (s.get("reasoning") or "")[:60]
                        if reason and reason not in error_samples:
                            error_samples.append(reason)
                        if len(error_samples) >= 2:
                            break
                errors_text = "; ".join(error_samples) if error_samples else "see logs"
                await send_message(
                    settings.telegram_chat_id,
                    msg(
                        "ai_failure_rate",
                        scan_type=scan_type,
                        failed=str(ai_failed),
                        total=str(ai_total),
                        pct=str(failure_pct),
                        errors=errors_text[:200],
                    ),
                )
            except Exception as e:
                logger.warning(f"Failed to send AI failure rate alert: {e}")

        # ── Generate tech-only signals for skipped candidates ──
        _update_progress(80, "saving", "Building tech-only signals...")
        for ticker, quick_score, bucket, technical_data, fundamental_data in skip_candidates:
            from app.scanners.universe import get_exchange
            exchange = get_exchange(ticker)
            action = score_to_action(quick_score, bucket)
            prev = previous_signals.get(ticker)
            status = determine_status(action, quick_score, prev)

            signal_data = {
                "scan_id": scan_id,
                "symbol": ticker,
                "asset_type": get_asset_class(ticker),
                "exchange": exchange,
                "action": action,
                "status": status,
                "score": quick_score,
                "confidence": 0,
                "ai_status": "skipped",
                "is_gem": False,
                "bucket": bucket,
                "price_at_signal": technical_data.get("current_price"),
                "target_price": None,
                "stop_loss": None,
                "risk_reward": None,
                "catalyst": None,
                "sentiment_score": 50,
                "reasoning": "Technical + fundamental analysis only (AI skipped — below pre-score threshold)",
                "technical_data": technical_data,
                "fundamental_data": fundamental_data,
                "macro_data": macro_data,
                "grok_data": {},
                "market_regime": market_regime,
                "catalyst_type": None,
                "account_recommendation": _recommend_account(bucket, exchange),
                "company_name": fundamental_data.get("company_name") if fundamental_data else None,
                "is_discovered": ticker in (discovered_set or set()),
            }
            valid_signals.append(signal_data)

        if errors_count:
            logger.warning(f"{errors_count} candidates failed AI processing")

        # Phase 5: Persist signals (85-90%)
        _update_progress(85, "saving", "Persisting signals...")
        if valid_signals:
            queries.insert_signals_batch(valid_signals)

        gems = [s for s in valid_signals if s.get("is_gem")]
        gems_count = len(gems)

        # Phase 6: Send alerts (90-95%)
        _update_progress(90, "alerting", "Sending alerts...")
        for gem_signal in gems:
            sent = await send_gem_alert(gem_signal)
            queries.insert_alert({
                "alert_type": "GEM",
                "message": gem_signal.get("symbol", ""),
                "status": "SENT" if sent else "FAILED",
                "sent_at": datetime.now(timezone.utc).isoformat(),
            })

        # Check watchlist for SELL/AVOID signals -- alert immediately
        for sig in valid_signals:
            sym = sig.get("symbol")
            action = sig.get("action")
            if sym in watchlist_symbols and action in ("SELL", "AVOID"):
                sent = await send_watchlist_sell_alert(sig)
                queries.insert_alert({
                    "alert_type": "WATCHLIST_SELL",
                    "message": sym,
                    "status": "SENT" if sent else "FAILED",
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                })
                logger.info(f"Watchlist SELL alert sent for {sym}")

        if scan_type in ("PRE_MARKET", "AFTER_CLOSE") and valid_signals:
            sent = await send_scan_digest(scan_type, valid_signals)
            queries.insert_alert({
                "alert_type": "SCAN_DIGEST",
                "message": f"{scan_type}: {len(valid_signals)} signals",
                "status": "SENT" if sent else "FAILED",
                "sent_at": datetime.now(timezone.utc).isoformat(),
            })

        # Phase 7: Virtual portfolio tracking
        if valid_signals:
            from app.services.virtual_portfolio import (
                check_virtual_exits,
                flush_brain_notifications,
                new_notification_queue,
                process_pending_reviews,
                process_virtual_trades,
            )

            # Create a scan-local brain notification queue. All virtual_portfolio
            # functions in this scan append into this queue, and flush drains it
            # at the end. This is per-scan state — concurrent scans get
            # independent queues, so notifications can never be mixed between
            # scans, lost, or duplicated across runs.
            brain_notifications = new_notification_queue()

            # First: process any positions flagged for review during prior
            # pre-market scans. If their fresh signal is still SELL/AVOID, the
            # flag is cleared so the SELL flow below can execute. If recovered,
            # the flag is cleared and a "review cleared" notification is queued.
            review_result = process_pending_reviews(valid_signals, brain_notifications)
            if review_result["cleared"] or review_result["confirmed"]:
                logger.info(
                    f"Pending reviews: {review_result['cleared']} cleared, "
                    f"{review_result['confirmed']} confirmed for sell"
                )

            vt_result = process_virtual_trades(valid_signals, watchlist_symbols, brain_notifications)
            if vt_result["buys"] or vt_result["sells"]:
                logger.info(f"Virtual portfolio: {vt_result['buys']} buys, {vt_result['sells']} sells")

            # Stage 6: Thesis re-evaluation + invalidation exits.
            # Runs BETWEEN process_virtual_trades (which handles SIGNAL/AVOID
            # closes + new entries) and check_virtual_exits (which handles
            # price-based stops/targets/profit-takes/time). This ordering
            # matters: thesis_invalidated closes set status='CLOSED' so the
            # subsequent stop/target sweep skips them via the OPEN guard.
            #
            # The thesis re-eval also persists thesis_last_status on every
            # OPEN row, which check_virtual_exits then reads via
            # _exit_is_thesis_protected to suppress noise exits when the
            # thesis is still valid (catastrophic carve-out at hard_stop_pct).
            try:
                from app.services import thesis_tracker
                thesis_results = await thesis_tracker.reevaluate_open_theses(valid_signals)
                if thesis_results:
                    invalidated = thesis_tracker.execute_thesis_invalidation_exits(
                        thesis_results, brain_notifications,
                    )
                    if invalidated:
                        logger.info(
                            f"Thesis tracker: {invalidated} positions closed via THESIS_INVALIDATED"
                        )
            except Exception as e:
                logger.warning(f"Thesis tracker failed (scan continues): {e}")

            # Check stop/target/time exits on all open virtual trades.
            # These now read pos.thesis_last_status (set above) and
            # suppress themselves when the thesis is still valid, except
            # for the catastrophic stop carve-out at hard_stop_pct.
            vt_exits = check_virtual_exits(brain_notifications)
            if any(vt_exits.values()):
                logger.info(f"Virtual exits: {vt_exits}")

            # Send all queued brain Telegram notifications for this scan
            sent_count = await flush_brain_notifications(brain_notifications)
            if sent_count:
                logger.info(f"Brain: sent {sent_count} Telegram notifications")

        # Phase 8: Monitor positions (95-100%)
        _update_progress(95, "monitoring", "Checking positions...")
        if valid_signals:
            from app.services.position_service import monitor_positions
            position_alerts = await monitor_positions(valid_signals)
            if position_alerts:
                logger.info(f"Position monitor: {position_alerts} alerts sent")

        # Done
        duration = round(time.time() - start_time, 2)
        queries.update_scan(
            scan_id,
            status="COMPLETE",
            completed_at=datetime.now(timezone.utc),
            tickers_scanned=len(all_tickers),
            signals_found=len(valid_signals),
            gems_found=gems_count,
            progress_pct=100,
            phase="complete",
            current_ticker="",
        )

        logger.info(
            f"{scan_type} scan complete: {len(valid_signals)} signals, "
            f"{gems_count} GEMs, {duration}s"
        )

        return scan_id

    except Exception as e:
        logger.error(f"Scan failed: {e}")
        if scan_id:
            queries.update_scan(
                scan_id,
                status="FAILED",
                completed_at=datetime.now(timezone.utc),
                error_message=str(e)[:200],
                progress_pct=0,
                phase="failed",
                current_ticker="",
            )
        raise


async def _process_candidate(
    ticker: str,
    macro_data: dict,
    screening_data: dict,
    previous_signals: dict,
    scan_id: str,
    semaphore: asyncio.Semaphore,
    market_regime: str = "TRENDING",
    knowledge_block: str = "",
    discovered_set: set | None = None,
) -> dict:
    """Run the FULL Pass-2 pipeline for a single AI candidate ticker.

    This is what fires for every ticker that made the top-15 cut for AI
    analysis. Tech-only signals (the 35 below the cut) take a much
    cheaper path inline in `run_scan` — they don't go through this
    function and skip AI synthesis, blockers check, and contrarian
    detection entirely.

    Steps inside this function:

      1. Classify bucket (SAFE_INCOME or HIGH_RISK)
      2. Fetch in parallel:
           - 1y price history (yfinance)
           - Fundamentals (yfinance .info)
           - Sentiment (Grok / Gemini fallback) — HIGH_RISK only
           - Barchart options flow (free, all candidates)
      3. Compute technical indicators from the price data
      4. Inject regime context + brain knowledge into grok_data so the
         AI prompt has the full context
      5. AI synthesis via the provider fallback chain
      6. Classify ai_status (validated / low_confidence / failed)
      7. Update the AI retry queue (clear on success, record on failure)
      8. Compute the final composite score
      9. Run blockers check
     10. Detect contrarian signal style
     11. Determine action (with low-conf / failed-AI BUY → HOLD downgrade)
     12. Check GEM conditions (only if not blocked)
     13. Determine status vs previous signal
     14. Build signal_data dict with all fields the DB and brain need
     15. Compute Kelly position sizing (only for action == BUY)

    Args:
        ticker: The symbol to analyze.
        macro_data: Shared macro snapshot (same across all candidates).
        screening_data: Bulk screening data (price, volume, day_change).
        previous_signals: Map of symbol → previous signal record (used by
            `determine_status` to compute CONFIRMED/WEAKENING/etc).
        scan_id: The current scan ID to attribute the signal to.
        semaphore: Concurrency limit (default 3) to avoid DNS exhaustion
            from yfinance's threaded fetcher.
        market_regime: TRENDING / VOLATILE / CRISIS — drives the regime
            multiplier in `compute_score` and the contextual hint in the
            AI synthesis prompt.
        knowledge_block: Brain knowledge text (score ranges, GEM rules,
            calibration notes) injected into the AI prompt.
        discovered_set: Symbols that came from `discover_tickers` rather
            than the core universe — used to set `is_discovered` on the
            signal record so the UI can flag them.

    Returns:
        A signal_data dict ready for `queries.insert_signals_batch`.
        The dict matches the `signals` table schema.
    """
    async with semaphore:
        logger.debug(f"Processing {ticker}...")

        bucket = _classify_bucket(ticker, screening_data.get(ticker, {}))

        # Fetch data in parallel
        # Skip sentiment for SAFE_INCOME (only 10% weight — not worth the AI cost)
        # Barchart options flow fetched for HIGH_RISK US equities (free, no API cost)
        if bucket == "SAFE_INCOME":
            price_df, fundamental_data, options_flow = await asyncio.gather(
                market_scanner.get_price_history(ticker, "1y"),
                market_scanner.get_fundamentals(ticker),
                barchart_scanner.get_options_flow(ticker),
            )
            grok_data = {"score": 50, "label": "neutral", "confidence": 0, "top_themes": [], "summary": "Sentiment skipped for Safe Income (10% weight)"}
        else:
            price_df, fundamental_data, grok_data, options_flow = await asyncio.gather(
                market_scanner.get_price_history(ticker, "1y"),
                market_scanner.get_fundamentals(ticker),
                ai_provider.analyze_sentiment(ticker),
                barchart_scanner.get_options_flow(ticker),
            )

        # Compute technicals (CPU-only, no I/O)
        technical_data = indicators.compute_indicators(price_df)

        # Inject regime context + brain knowledge into grok_data for AI prompt
        if isinstance(grok_data, dict):
            grok_data["_market_regime"] = market_regime
            grok_data["_catalyst_context"] = "No specific catalyst detected"
            if market_regime != "TRENDING":
                grok_data["_regime_note"] = f"Market is in {market_regime} mode — adjust signal accordingly"
            else:
                grok_data["_regime_note"] = ""
            if knowledge_block:
                grok_data["_knowledge_block"] = knowledge_block
            if options_flow:
                grok_data["_options_flow"] = options_flow

            # Append per-ticker pattern stats — the brain's live track record
            # on similar setups (closed trades + currently-open positions
            # combined). Surfaces a warning when the brain has been losing
            # this kind of pattern, or a green light when it's been winning.
            # See app/services/pattern_stats.py for the math + thresholds.
            try:
                from app.services.pattern_stats import get_pattern_warning
                pattern_warning = get_pattern_warning({
                    "bucket": bucket,
                    "market_regime": market_regime,
                })
                if pattern_warning:
                    existing_kb = grok_data.get("_knowledge_block", "") or ""
                    grok_data["_knowledge_block"] = existing_kb + "\n\n" + pattern_warning
            except Exception as e:
                # Unexpected failure in the stats query — surface as warning
                # so it shows up in logs, but never block the synthesis.
                logger.warning(f"pattern_stats injection failed for {ticker}: {e}")

        # AI synthesis with provider fallback chain
        synthesis = await ai_provider.synthesize_signal(
            ticker, technical_data, fundamental_data, macro_data, grok_data,
        )

        # Classify AI status — honest data instead of inferring from confidence==0
        # validated     = AI ran, confidence >= 50
        # low_confidence = AI ran, confidence < 50 (but > 0)
        # failed        = AI tried, all providers errored or over budget
        synthesis_confidence = synthesis.get("confidence", 0) or 0
        if synthesis.get("error"):
            ai_status = "failed"
        elif synthesis_confidence >= 50:
            ai_status = "validated"
        else:
            ai_status = "low_confidence"

        # Update AI retry queue based on synthesis result
        from app.services import ai_retry_queue
        if ai_status == "failed":
            ai_retry_queue.record_failure(ticker, error=str(synthesis.get("error", "")))
        else:
            # AI ran (any confidence) — clear from retry queue if it was there
            ai_retry_queue.clear_success(ticker)

        # Score (with regime context)
        asset_class = get_asset_class(ticker)
        score, breakdown = compute_score(
            technical_data, fundamental_data, macro_data,
            grok_data, synthesis, bucket, market_regime, asset_class,
        )

        # Check blockers
        is_blocked, block_reasons = check_blockers(
            grok_data, fundamental_data, macro_data, technical_data,
        )

        # Contrarian detection
        from app.signals.contrarian import detect_contrarian
        contrarian = detect_contrarian(technical_data, bucket)
        signal_style = contrarian["signal_style"]

        # Determine action — contrarian signals can generate BUY even at lower scores
        confidence = synthesis.get("confidence", 0) or 0
        if is_blocked:
            action = "AVOID"
        elif contrarian["is_contrarian"] and contrarian["contrarian_score"] >= 60:
            action = "BUY" if score >= 55 else "HOLD"
        else:
            action = score_to_action(score, bucket)

        # AI quality guard: downgrade BUY to HOLD when AI is unreliable
        if action == "BUY":
            if ai_status == "failed":
                logger.warning(f"{ticker}: BUY downgraded to HOLD (AI synthesis failed — all providers errored)")
                action = "HOLD"
            elif ai_status == "low_confidence":
                logger.info(f"{ticker}: BUY downgraded to HOLD (low AI confidence {confidence}%)")
                action = "HOLD"

        # Check GEM (blocked signals can't be GEMs)
        is_gem, gem_conditions = check_gem(score, grok_data, synthesis)
        if is_blocked:
            is_gem = False

        # Determine status vs previous signal
        prev = previous_signals.get(ticker)
        status = determine_status(action, score, prev)

        current_price = technical_data.get("current_price")

        # Build signal record
        from app.scanners.universe import get_exchange
        exchange = get_exchange(ticker)
        signal_data = {
            "scan_id": scan_id,
            "symbol": ticker,
            "asset_type": get_asset_class(ticker),
            "exchange": exchange,
            "action": action,
            "status": status,
            "score": score,
            "confidence": synthesis.get("confidence", 0),
            "ai_status": ai_status,
            "is_gem": is_gem,
            "bucket": bucket,
            "price_at_signal": current_price,
            "target_price": synthesis.get("target_price"),
            "stop_loss": synthesis.get("stop_loss"),
            "risk_reward": synthesis.get("risk_reward_ratio"),
            "catalyst": synthesis.get("catalyst"),
            "sentiment_score": int(grok_data.get("score", 50)),
            "reasoning": synthesis.get("reasoning", ""),
            "technical_data": technical_data,
            "fundamental_data": fundamental_data,
            "macro_data": macro_data,
            "grok_data": grok_data,
            "market_regime": market_regime,
            "catalyst_type": breakdown.get("catalyst_type"),
            "account_recommendation": _recommend_account(bucket, exchange),
            "signal_style": signal_style,
            "contrarian_score": contrarian["contrarian_score"] if contrarian["is_contrarian"] else None,
            "company_name": fundamental_data.get("company_name") if fundamental_data else None,
            "is_discovered": ticker in (discovered_set or set()),
            "probability_vs_spy": compute_probability_vs_spy(score, bucket, has_ai=bool(synthesis.get("reasoning"))),
            "factor_labels": compute_factor_labels(breakdown, bucket, asset_class),
        }

        # Kelly position sizing (if actionable)
        rr = synthesis.get("risk_reward_ratio")
        if action == "BUY" and rr and float(rr) > 0:
            from app.signals.kelly import calculate_kelly
            kelly = calculate_kelly(risk_reward=float(rr), score=score, regime=market_regime)
            signal_data["kelly_recommendation"] = kelly

        logger.info(
            f"{ticker}: {action} (score={score}, gem={is_gem}, "
            f"blocked={is_blocked}, status={status}, regime={market_regime})"
        )

        return signal_data


def _classify_bucket(ticker: str, screening: dict) -> str:
    """Classify a ticker into SAFE_INCOME or HIGH_RISK.

    Priority: 1) stored bucket from tickers table (stable across scans),
    2) hardcoded lists, 3) heuristic fallback.
    """
    # 1. Check cached bucket map first (loaded once per scan, not per ticker)
    if ticker in _bucket_cache:
        return _bucket_cache[ticker]

    # 2. Hardcoded classifications
    if ticker.endswith("-USD"):
        return "HIGH_RISK"

    safe_suffixes = ["-UN.TO", "-B.TO", "-A.TO"]
    from app.scanners.universe import _ETF_TICKERS
    safe_etfs = _ETF_TICKERS | {"O", "PLD", "AMT", "SPY"}

    if ticker in safe_etfs or any(ticker.endswith(s) for s in safe_suffixes):
        return "SAFE_INCOME"

    energy_tickers = {"CNQ.TO", "SU.TO", "CVE.TO", "ARX.TO", "IMO.TO", "BTE.TO",
                      "WCP.TO", "TVE.TO", "ERF.TO",
                      "XOM", "COP", "EOG", "SLB", "MPC", "OXY"}
    mining_tickers = {"ABX.TO", "FNV.TO", "WPM.TO", "NTR.TO", "K.TO",
                      "TECK.TO", "FM.TO", "LUN.TO", "IVN.TO",
                      "ABX", "FNV", "WPM", "NTR", "K", "NEM", "FCX"}
    high_risk_tickers = {"WEED.TO", "ACB.TO", "TLRY.TO", "CRON.TO", "OGI.TO",
                         "RIVN", "LCID", "PLTR", "RKLB", "IONQ", "SMCI",
                         "MSTR", "SOUN", "HIMS", "COIN", "SOFI", "AFRM",
                         "HOOD", "MRNA"}
    high_risk_tickers |= energy_tickers | mining_tickers

    if ticker in high_risk_tickers:
        return "HIGH_RISK"

    # 3. Heuristic fallback (sector-based only, NOT day_change)
    sector = (screening.get("sector") or "").lower()
    if sector in ("energy", "basic materials", "materials"):
        bucket = "HIGH_RISK"
    else:
        bucket = "SAFE_INCOME"

    # Persist bucket so it's stable across scans
    try:
        from app.scanners.universe import get_exchange
        queries.upsert_ticker(ticker, exchange=get_exchange(ticker), bucket=bucket)
    except Exception:
        pass

    _bucket_cache[ticker] = bucket
    return bucket


# Module-level bucket cache, loaded once per scan
_bucket_cache: dict[str, str] = {}


def _recommend_account(bucket: str, exchange: str) -> str:
    """Recommend a Canadian account type based on bucket and asset type.

    - SAFE_INCOME → TFSA (tax-free dividends & gains)
    - HIGH_RISK → RRSP (shields active trading from CRA business income rules)
    - CRYPTO → TAXABLE (crypto gains are always taxable in Canada)
    """
    if exchange == "CRYPTO":
        return "TAXABLE"
    if bucket == "HIGH_RISK":
        return "RRSP"
    return "TFSA"
