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
    • Add discovered tickers via `universe.discover_tickers()`
      (Yahoo screeners: undervalued_large_caps, growth_technology_stocks;
      most_actives only behind settings.discovery_include_most_actives;
      day_gainers removed — it chased moves).
    • Bulk-fetch screening data via `market_scanner.get_bulk_screening`
      (1y daily bars -> price, volume, trend features).
    • Filter to top 50 candidates via `prefilter_candidates`: volume
      >= 200K and price >= $1, ranked by TREND QUALITY (price vs
      SMA50/200, 3-month return ex-last-week, RSI) — not by today's
      move. Crypto gets 5 reserved slots.

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
    For every candidate (parallel, gated by yfinance_sem=3 to avoid DNS
    thread exhaustion):
      • Fetch 1-year price history via yfinance
      • Compute technical indicators (RSI, MACD, SMA, volume z-score, ATR)
      • Fetch fundamentals (P/E, EPS, dividend yield, market cap)
      • Quick score using technicals + fundamentals + macro ONLY
        (no AI yet — this is the cheap pre-score)
      • Skip HIGH_RISK candidates entirely if regime == "CRISIS"
      • Stash price_df + fundamentals + technicals in `prescore_cache`
        so PASS 2 reuses them instead of re-fetching from yfinance.
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
    For every AI candidate (parallel, gated by ai_sem=6 around the
    Claude CLI subprocess only — sentiment/options/scoring run unguarded):
      • Reuse price_df + fundamentals + technicals from `prescore_cache`
        (no yfinance refetch).
      • Fetch sentiment via Grok / Gemini fallback (HIGH_RISK only —
        SAFE_INCOME hardcodes neutral to save cost).
      • Fetch Barchart options flow (free, all candidates).
      • Run AI synthesis via `provider.synthesize_signal` (Claude Local
        → Claude API → Gemini fallback chain).
      • Classify ai_status: validated (AI said BUY, conf >= 60) /
        low_confidence / rejected (AI not BUY) / failed.
      • Update AI retry queue (clear on success, add on failure).
      • Compute final score with all components.
      • Run blockers check.
      • Detect contrarian signal style (descriptive only — no BUY bypass).
      • Determine action (BUY/HOLD/SELL/AVOID), with low-confidence /
        rejected / failed-AI BUY auto-downgraded to HOLD, and BUY ->
        HOLD inside the earnings blackout.
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
from zoneinfo import ZoneInfo

from loguru import logger

from app.ai import provider as ai_provider
from app.ai.signal_engine import (
    check_blockers,
    check_entry_blackout,
    check_gem,
    compute_factor_labels,
    compute_probability_vs_spy,
    compute_score,
    determine_status,
    score_to_action,
    technical_filter,
)
from app.core.config import settings
from app.db import queries
from app.notifications.telegram_bot import send_gem_alert, send_scan_digest, send_watchlist_sell_alert
from app.scanners import barchart_scanner, indicators, macro_scanner, market_scanner
from app.scanners.prefilter import prefilter_candidates, trend_quality_score
from app.signals.earnings import get_earnings_context

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
    # Datetime equivalent of start_time, used as the scan boundary for
    # stage-ordering guards (e.g. thesis_tracker must not re-evaluate
    # positions opened earlier in THIS scan — see Day 10 journal).
    scan_started_at = datetime.now(timezone.utc)
    logger.info(f"Starting {scan_type} scan...")

    # Bind scan_type to the async context so nested Telegram sends can
    # consult `settings.notify_scans_disabled` and suppress themselves for
    # scans the user has silenced (e.g. PRE_MARKET). Reset in finally below.
    from app.notifications.scan_context import set_current_scan_type, reset_current_scan_type
    _scan_ctx_token = set_current_scan_type(scan_type)

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

        import time as _time
        _scan_t0 = _time.perf_counter()

        # ── Phase 1 + Phase 2 + Phase 3 OVERLAP ──
        # Bulk screening (~100s on cold scans, ~5s on warm) is the long pole.
        # Macro snapshot, knowledge block, and macro pulse have NO dependency
        # on the screening output, so we kick them off as background tasks
        # alongside the screening and only await them at point of use.
        # Net savings: ~7-15s on every scan, more after Fix #3 lands.
        screening_task = asyncio.create_task(market_scanner.get_bulk_screening(all_tickers))
        macro_task = asyncio.create_task(macro_scanner.get_macro_snapshot())

        from app.services.knowledge_service import KnowledgeService
        _ks = KnowledgeService()
        knowledge_task = asyncio.create_task(_ks.get_knowledge_block([
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
        ]))

        # Macro pulse only on first scan of the day (Grok tokens).
        # Wrapped in try/except to match the original defensive behavior:
        # an import or task-creation failure must not crash the scan.
        pulse_task = None
        if scan_type in ("PRE_MARKET", "MANUAL"):
            try:
                from app.ai.macro_pulse import get_macro_pulse
                pulse_task = asyncio.create_task(get_macro_pulse())
            except Exception as e:
                logger.debug(f"Macro pulse setup skipped: {e}")

        # Block on screening (the long pole) before prefiltering
        screening_data = await screening_task
        _t_screening = _time.perf_counter()
        logger.info(f"⏱ Phase 1 (screening + macro + knowledge): {_t_screening - _scan_t0:.1f}s")
        _update_progress(10, "filtering")
        watchlist_symbols = queries.get_all_watchlist_symbols()
        # Always include held brain positions in the candidate list, even
        # if they don't meet day_change/volume thresholds. Without this,
        # quiet-day held positions get filtered out and the Stage 6 thesis
        # tracker can't re-evaluate them — they drift unsupervised until
        # the watchdog catches a price emergency. See journal Day 4
        # afternoon entry for the bug story.
        held_brain_symbols = queries.get_open_brain_symbols()
        candidates = prefilter_candidates(
            screening_data, watchlist_symbols, held_brain_symbols,
        )
        logger.info(f"Candidates after pre-filter: {len(candidates)}")

        queries.update_scan(scan_id, candidates=len(candidates), tickers_scanned=len(all_tickers))
        _update_progress(15, "macro", "Fetching macro data...")

        # Phase 2: Macro snapshot — already in flight, await result now.
        macro_data = await macro_task

        # Macro news pulse -- only on first scan of the day to save Grok tokens
        if pulse_task is not None:
            try:
                macro_data["macro_pulse"] = await pulse_task
            except Exception as e:
                logger.debug(f"Macro pulse skipped: {e}")

        # Layer 0 — Market regime (runs ONCE per scan, not per ticker)
        from app.signals.regime import get_market_regime
        market_regime = get_market_regime(macro_data)
        logger.info(f"Market regime: {market_regime}")
        queries.update_scan(scan_id, market_regime=market_regime)

        _update_progress(20, "analyzing")

        # Phase 3: Get previous signals + brain knowledge (knowledge already in flight)
        previous_signals = queries.get_latest_signals_map()
        try:
            _knowledge_block = await knowledge_task
        except Exception as e:
            logger.warning(f"Knowledge block load failed: {e}")
            _knowledge_block = ""
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

        # Two semaphores, two jobs:
        #   yfinance_sem — guards yfinance fetches against DNS thread exhaustion.
        #     Stays at 3 (the empirical safe ceiling).
        #   ai_sem — guards Claude Local CLI subprocess invocations. Each call
        #     is an independent Node process, so we can run more in parallel.
        #     Start at 6 — high enough to crush the 5-wave bottleneck on the
        #     top-15 AI candidates without spawning so many Node processes
        #     that the laptop swaps. Tune up to 10 if memory headroom allows.
        yfinance_sem = asyncio.Semaphore(3)
        ai_sem = asyncio.Semaphore(6)
        total_candidates = len(candidates)

        # ── PASS 1: Pre-score all candidates (no AI tokens) ──
        _t_prepass = _time.perf_counter()
        logger.info(f"⏱ Phase 2 (macro + regime + knowledge): {_t_prepass - _t_screening:.1f}s")
        _update_progress(20, "prescoring", "Pre-scoring candidates...")
        pre_scores: list[tuple[str, int, str, dict, dict]] = []  # (ticker, score, bucket, tech, fund)
        # Stash the raw price_df + fundamentals from PASS 1 so PASS 2 can
        # reuse them instead of re-fetching the same data from yfinance.
        # Saves ~30 yfinance round trips per scan (15 AI candidates × 2 calls).
        prescore_cache: dict[str, dict] = {}

        async def _prescore(ticker: str, idx: int) -> tuple[str, int, str, dict, dict] | None:
            _update_progress(
                20 + int((idx / total_candidates) * 25),
                "prescoring",
                ticker,
            )
            try:
                # Cheap early exit: names we already KNOW are HIGH_RISK
                # (crypto, leveraged ETFs, stored/hardcoded buckets) are
                # skipped in CRISIS before any fetch.
                known = _known_bucket(ticker)
                if market_regime == "CRISIS" and known == "HIGH_RISK":
                    return None

                exchange = get_exchange(ticker)
                fetch_earnings = get_asset_class(ticker) == "STOCK"
                async with yfinance_sem:
                    coros = [
                        market_scanner.get_price_history(ticker, "1y"),
                        market_scanner.get_fundamentals(ticker),
                    ]
                    if fetch_earnings:
                        coros.append(get_earnings_context(ticker))
                    fetched = await asyncio.gather(*coros)
                price_df, fundamental_data = fetched[0], fetched[1]
                earnings_ctx = fetched[2] if fetch_earnings else None

                # Copy: get_fundamentals returns the cached dict object.
                fundamental_data = dict(fundamental_data or {})
                # Bucket from REAL fundamentals (sector / dividend / mcap).
                bucket = _classify_bucket(ticker, fundamental_data)
                if market_regime == "CRISIS" and bucket == "HIGH_RISK":
                    return None
                asset_class = _asset_class(ticker, fundamental_data)
                if asset_class == "STOCK":
                    _merge_earnings(fundamental_data, earnings_ctx, exchange)

                # Indicators on COMPLETED bars only (drops today's
                # in-progress bar while the session is open).
                technical_data = indicators.compute_indicators(price_df, exchange=exchange)
                # Quick score: technicals + fundamentals + macro only, no AI
                quick_score, _ = compute_score(
                    technical_data, fundamental_data, macro_data,
                    {}, {}, bucket, market_regime, asset_class,
                )
                # Stash for PASS 2 reuse
                prescore_cache[ticker] = {
                    "price_df": price_df,
                    "fundamental_data": fundamental_data,
                    "technical_data": technical_data,
                    "bucket": bucket,
                    "asset_class": asset_class,
                }
                return (ticker, quick_score, bucket, technical_data, fundamental_data)
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

        # Stamp the brain's pass/fail technical filter on every candidate
        # (stored with the signal in technical_data["_tech_filter"]).
        _stamp_tech_filter(pre_scores, macro_data, prescore_cache)
        pre_scores.sort(key=lambda x: x[1], reverse=True)
        filter_mode = (settings.brain_entry_mode or "").lower() != "score"

        if settings.ai_enabled and AI_CANDIDATE_LIMIT > 0:
            # filter mode: filter-FAILING candidates get no AI call (the
            # brain could never buy them); passing ones ranked by trend
            # quality. Legacy score mode: top pre-score.
            ai_candidates = _select_ai_candidates(pre_scores, screening_data, AI_CANDIDATE_LIMIT)
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
                    if filter_mode and not _tech_filter_passed(rt_pre):
                        continue  # the brain can't buy it — don't pay for AI
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
        _t_pass1_done = _time.perf_counter()
        logger.info(f"⏱ PASS 1 (pre-score {len(pre_scores)} candidates): {_t_pass1_done - _t_prepass:.1f}s")
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
                    scan_id, yfinance_sem, ai_sem, market_regime, _knowledge_block,
                    discovered_set, prescore_cache.get(ticker),
                )
                return result
            except Exception as e:
                errors_count += 1
                logger.debug(f"AI processing failed {ticker}: {e}")
                return None

        ai_tasks = [_process_ai(item, i) for i, item in enumerate(ai_candidates)]
        ai_results = await asyncio.gather(*ai_tasks)
        _t_pass2_done = _time.perf_counter()
        logger.info(f"⏱ PASS 2 (AI synthesis {len(ai_candidates)} candidates): {_t_pass2_done - _t_pass1_done:.1f}s")
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
                from app.notifications.telegram_bot import enqueue
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
                enqueue(
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
            exchange = get_exchange(ticker)
            action, tech_block_reasons = _tech_only_action(
                quick_score, bucket, technical_data, fundamental_data, macro_data,
            )
            if tech_block_reasons:
                logger.info(f"{ticker} (tech-only): {action} — {'; '.join(tech_block_reasons)}")
            prev = previous_signals.get(ticker)
            status = determine_status(action, quick_score, prev)
            _cached = prescore_cache.get(ticker) or {}

            signal_data = {
                "scan_id": scan_id,
                "symbol": ticker,
                "asset_type": _cached.get("asset_class") or get_asset_class(ticker),
                "exchange": exchange,
                "action": action,
                "status": status,
                "score": quick_score,
                "confidence": 0,
                # Tech-only signals are NEVER "validated": AI never ran.
                # The brain must not auto-buy on "skipped".
                "ai_status": "skipped",
                "ai_signal": None,
                "ai_provider": None,
                "p_win": None,
                "routine_ai_signal": None,
                "decision_overturned": None,
                "sentiment_citations": 0,
                "is_gem": False,
                "bucket": bucket,
                "price_at_signal": technical_data.get("current_price"),
                "target_price": None,
                "stop_loss": None,
                "risk_reward": None,
                "catalyst": None,
                "sentiment_score": 50,
                "reasoning": (
                    "Technical + fundamental analysis only (AI skipped — "
                    + (
                        "technical filter failed: " + ", ".join(
                            (technical_data.get("_tech_filter") or {}).get("reasons") or [])
                        if filter_mode and not (technical_data.get("_tech_filter") or {}).get("passed", True)
                        else "not selected for AI analysis"
                    )
                    + ")"
                    + (f". {'; '.join(tech_block_reasons)}" if tech_block_reasons else "")
                ),
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
            _persist_signals(valid_signals)

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
        #
        # Exit checks (stop / target / time) must run on EVERY scan — they
        # used to sit inside `if valid_signals:`, so a scan that produced
        # no signals (AI outage, empty pre-filter) never checked stops.
        # Signal-driven steps (pending reviews, new trades, thesis re-eval)
        # still need signals and stay gated.
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

        if valid_signals:
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
            try:
                from app.services import thesis_tracker
                thesis_results = await thesis_tracker.reevaluate_open_theses(
                    valid_signals,
                    scan_started_at=scan_started_at,
                    scan_type=scan_type,
                )
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

        # Check stop/target/time exits on all open virtual trades — ALWAYS.
        try:
            vt_exits = check_virtual_exits(brain_notifications)
            if any(vt_exits.values()):
                logger.info(f"Virtual exits: {vt_exits}")
        except Exception as e:
            logger.error(f"check_virtual_exits failed (scan continues): {e}")

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

        _t_end = _time.perf_counter()
        logger.info(
            f"{scan_type} scan complete: {len(valid_signals)} signals, "
            f"{gems_count} GEMs, {duration}s"
        )
        logger.info(
            f"⏱ SCAN TIMING: screening={_t_screening - _scan_t0:.0f}s, "
            f"macro={_t_prepass - _t_screening:.0f}s, "
            f"pass1={_t_pass1_done - _t_prepass:.0f}s, "
            f"pass2={_t_pass2_done - _t_pass1_done:.0f}s, "
            f"tail={_t_end - _t_pass2_done:.0f}s, "
            f"total={_t_end - _scan_t0:.0f}s"
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
    finally:
        reset_current_scan_type(_scan_ctx_token)


async def _process_candidate(
    ticker: str,
    macro_data: dict,
    screening_data: dict,
    previous_signals: dict,
    scan_id: str,
    yfinance_sem: asyncio.Semaphore,
    ai_sem: asyncio.Semaphore,
    market_regime: str = "TRENDING",
    knowledge_block: str = "",
    discovered_set: set | None = None,
    prescore_data: dict | None = None,
) -> dict:
    """Run the FULL Pass-2 pipeline for a single AI candidate ticker.

    This is what fires for every ticker that made the top-15 cut for AI
    analysis. Tech-only signals (the 35 below the cut) take a much
    cheaper path inline in `run_scan` — they skip AI synthesis and
    contrarian detection, but DO run blockers + the earnings blackout
    (`_tech_only_action`) and are never ai_status="validated".

    Concurrency model:

      Two semaphores carve the function into three regions:
        1. yfinance_sem (default 3) — held only while fetching price history
           and fundamentals from yfinance. Protects against DNS thread
           exhaustion. SKIPPED ENTIRELY when `prescore_data` is supplied
           (the same data is reused from PASS 1).
        2. unguarded — sentiment, options flow, technicals, scoring, blockers,
           GEM checks, building the signal record. Each candidate runs these
           in full parallel because they don't share a contended resource.
        3. ai_sem (default 6) — held only while invoking Claude Local CLI
           for synthesis. Each call spawns an independent Node subprocess,
           so we can stack many in parallel — the cap is laptop RAM, not
           any shared lock.

      The previous design used a single Semaphore(3) wrapped around the
      entire function body, which serialized the 15 AI candidates into
      5 sequential waves of 3. That was the dominant cost in the scan.

    Steps inside this function:

      1. Classify bucket (SAFE_INCOME or HIGH_RISK)
      2. Fetch in parallel:
           - 1y price history (yfinance) — REUSED from PASS 1 if available
           - Fundamentals (yfinance .info) — REUSED from PASS 1 if available
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
        yfinance_sem: Concurrency cap on yfinance fetches (DNS protection).
        ai_sem: Concurrency cap on Claude Local CLI subprocess invocations.
        market_regime: TRENDING / VOLATILE / CRISIS — drives the regime
            multiplier in `compute_score` and the contextual hint in the
            AI synthesis prompt.
        knowledge_block: Brain knowledge text (score ranges, GEM rules,
            calibration notes) injected into the AI prompt.
        discovered_set: Symbols that came from `discover_tickers` rather
            than the core universe — used to set `is_discovered` on the
            signal record so the UI can flag them.
        prescore_data: Optional dict with `price_df`, `fundamental_data`,
            and `technical_data` from PASS 1. When supplied, skips the
            yfinance refetch entirely. Saves ~2 yfinance calls per AI
            candidate.

    Returns:
        A signal_data dict ready for `queries.insert_signals_batch`.
        The dict matches the `signals` table schema.
    """
    logger.debug(f"Processing {ticker}...")

    exchange = get_exchange(ticker)
    if prescore_data is not None and prescore_data.get("bucket"):
        bucket = prescore_data["bucket"]
    else:
        # Without PASS 1 data we need fundamentals before classifying.
        async with yfinance_sem:
            _fund = await market_scanner.get_fundamentals(ticker)
        bucket = _classify_bucket(ticker, dict(_fund or {}))

    # ── Fetch market data (yfinance, sentiment, options) ──
    # Reuse PASS 1's price/fundamentals when available — skips ~2 yfinance
    # round trips per AI candidate. PASS 1 ran moments ago so the data is
    # still fresh enough for synthesis.
    if prescore_data is not None:
        price_df = prescore_data["price_df"]
        fundamental_data = prescore_data["fundamental_data"]
        # Sentiment + options still need fetching (not in PASS 1)
        if bucket == "SAFE_INCOME":
            options_flow = await barchart_scanner.get_options_flow(ticker)
            grok_data = {"score": 50, "label": "neutral", "confidence": 0, "top_themes": [], "summary": "Sentiment skipped for Safe Income (10% weight)"}
        else:
            grok_data, options_flow = await asyncio.gather(
                ai_provider.analyze_sentiment(
                    ticker, market_cap=(fundamental_data or {}).get("market_cap"),
                ),
                barchart_scanner.get_options_flow(ticker),
            )
    else:
        # No PASS 1 data — fall back to fetching everything. yfinance calls
        # are gated by yfinance_sem; sentiment + options run unguarded.
        async with yfinance_sem:
            price_df, fundamental_data = await asyncio.gather(
                market_scanner.get_price_history(ticker, "1y"),
                market_scanner.get_fundamentals(ticker),
            )
        if bucket == "SAFE_INCOME":
            options_flow = await barchart_scanner.get_options_flow(ticker)
            grok_data = {"score": 50, "label": "neutral", "confidence": 0, "top_themes": [], "summary": "Sentiment skipped for Safe Income (10% weight)"}
        else:
            grok_data, options_flow = await asyncio.gather(
                ai_provider.analyze_sentiment(
                    ticker, market_cap=(fundamental_data or {}).get("market_cap"),
                ),
                barchart_scanner.get_options_flow(ticker),
            )
        fundamental_data = dict(fundamental_data or {})
        if _asset_class(ticker, fundamental_data) == "STOCK":
            _merge_earnings(fundamental_data, await get_earnings_context(ticker), exchange)

    # Compute technicals (CPU-only, no I/O). Reuse PASS 1's result if present.
    if prescore_data is not None:
        technical_data = prescore_data["technical_data"]
    else:
        technical_data = indicators.compute_indicators(price_df, exchange=exchange)

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

    # AI synthesis with provider fallback chain. ai_sem caps how many
    # Claude Local CLI subprocesses run concurrently — each is an
    # independent Node process, so the cap protects laptop RAM, not
    # any shared resource. With ai_sem=6, the 15 AI candidates land in
    # ~3 waves of ~30s each instead of the previous 5 waves at sem=3.
    async with ai_sem:
        synthesis = await ai_provider.synthesize_signal(
            ticker, technical_data, fundamental_data, macro_data, grok_data,
        )
        synthesis = await _confirm_buy_with_decision_model(
            ticker, synthesis, technical_data, fundamental_data, macro_data, grok_data,
        )

    # Classify AI status — see `_classify_ai_status` for the rules.
    # "validated" now REQUIRES Claude to have said BUY with enough
    # confidence; previously any confidence >= 50 counted, so a confident
    # HOLD/AVOID from Claude still validated a score-driven BUY.
    ai_status = _classify_ai_status(synthesis)

    # Update AI retry queue based on synthesis result
    from app.services import ai_retry_queue
    if ai_status == "failed":
        ai_retry_queue.record_failure(ticker, error=str(synthesis.get("error", "")))
    else:
        # AI ran (any confidence) — clear from retry queue if it was there
        ai_retry_queue.clear_success(ticker)

    # Score (with regime context)
    asset_class = (prescore_data or {}).get("asset_class") or _asset_class(ticker, fundamental_data)
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

    # Determine action. The old contrarian override turned any 3/4
    # contrarian setup into a BUY at score >= 55, bypassing the bucket
    # thresholds (62/65). Removed: contrarian is now descriptive
    # (signal_style / contrarian_score) and must pass the same thresholds
    # and AI validation as everything else.
    confidence = synthesis.get("confidence", 0) or 0
    if is_blocked:
        action = "AVOID"
    else:
        action = score_to_action(score, bucket)

    # AI quality guard: downgrade BUY to HOLD when AI is unreliable.
    #
    # ARCHITECTURE NOTE: score is the entry decider, Claude provides
    # the dossier (reasoning, target, stop, confidence). The principle
    # in `feedback_three_witness_consensus.md` is "AI is the decider"
    # but it applies to EXITS (Stage 6 thesis tracker) and to FEEDING
    # Claude a better dossier so future entries are calibrated. It does
    # NOT mean Claude has unilateral veto over score-derived BUYs at
    # entry — that would conflict with the explicit "do not build hard
    # vetoes that override the AI's view" guidance and Pedro's
    # "AI cannot win all the time" rule.
    #
    # What this guard CAN do: catch genuine self-contradictions where
    # Claude says BUY but its OWN structured self_check says the
    # reasoning doesn't support that BUY. That's not a math veto — it's
    # asking Claude "are you sure?" via a structured second pass that
    # Claude itself filled out.
    if action == "BUY":
        if ai_status == "failed":
            logger.warning(f"{ticker}: BUY downgraded to HOLD (AI synthesis failed — all providers errored)")
            action = "HOLD"
        elif ai_status == "rejected":
            logger.info(
                f"{ticker}: BUY downgraded to HOLD (AI said {synthesis.get('signal')!r}, "
                f"confidence {confidence}%)"
            )
            action = "HOLD"
        elif ai_status == "low_confidence":
            logger.info(f"{ticker}: BUY downgraded to HOLD (low AI confidence {confidence}%)")
            action = "HOLD"
        else:
            # Self-consistency safety net via structured self_check.
            # PRIMARY (added 2026-04-09): the synthesis prompt requires
            # Claude to return a `self_check` block answering yes/no
            # questions about its own reasoning. When Claude returns
            # signal=BUY but its self_check flags wait/bearish/inconsistent,
            # downgrade. Empirically structured self-questions are much
            # easier for an LLM to answer correctly than overall judgment.
            #
            # FALLBACK: substring regex on raw reasoning (only fires when
            # self_check is missing — older provider responses, malformed
            # JSON, error fallbacks). Defense in depth.
            _self_check = synthesis.get("self_check") or {}
            _downgrade_reason: str | None = None

            if _self_check.get("_present"):
                if _self_check.get("contains_wait_instruction"):
                    _downgrade_reason = "self_check.contains_wait_instruction=true"
                elif _self_check.get("contains_bearish_descriptors"):
                    _downgrade_reason = "self_check.contains_bearish_descriptors=true"
                elif not _self_check.get("reasoning_supports_signal"):
                    _downgrade_reason = "self_check.reasoning_supports_signal=false"
            else:
                _BEARISH_HEDGE_PHRASES = (
                    "falling knife", "falling-knife",
                    "structural downtrend", "structural weakness",
                    "severe downtrend", "confirmed downtrend",
                    "decisively bearish", "strongly bearish", "accelerating bearish",
                    "deeply negative macd", "deeply negative momentum",
                    "strongly negative macd",
                    "momentum has rolled over", "momentum rollover", "momentum collapse",
                    "bearish divergence pattern",
                    "technically stretched", "technically overextended",
                    "near overbought", "approaching overbought",
                    "internally contradictory",
                    "poor risk/reward", "poor risk reward",
                    "no fundamental margin of safety", "no margin of safety",
                    "bleed risk", "bleed within",
                    "wait for a pullback", "wait for macd", "wait for momentum",
                    "wait for confirmation", "wait for the",
                    "before considering entry", "before considering an entry",
                    "before commit", "for a better entry", "is premature",
                    "not an entry",
                )
                _reasoning = (synthesis.get("reasoning") or "").lower()
                _hit = next((p for p in _BEARISH_HEDGE_PHRASES if p in _reasoning), None)
                if _hit:
                    _downgrade_reason = f"legacy regex hit {_hit!r} (no self_check)"

            if _downgrade_reason:
                logger.warning(
                    f"{ticker}: BUY downgraded to HOLD — {_downgrade_reason} "
                    f"(notes: {_self_check.get('self_check_notes', '')!r})"
                )
                action = "HOLD"

    # Earnings blackout: no NEW BUY right before a scheduled report.
    # HOLD, not AVOID — held positions must not be sold because of it.
    # Evaluated for every candidate (not only score-BUYs): in filter mode the
    # brain enters on filter + AI BUY regardless of the score-based action, so
    # it reads the flag from grok_data["_earnings_blackout"] itself.
    blackout_reason = check_entry_blackout(fundamental_data)
    if isinstance(grok_data, dict):
        grok_data["_earnings_blackout"] = blackout_reason
    if blackout_reason and action == "BUY":
        logger.info(f"{ticker}: BUY downgraded to HOLD — {blackout_reason}")
        action = "HOLD"

    current_price = technical_data.get("current_price")

    # Trade levels: Claude's target/stop are validated upstream and may be
    # null. Fill missing ones from ATR and recompute R:R from the FINAL
    # levels so Kelly, GEM and the brain all see one consistent set.
    target_price, stop_loss, risk_reward, levels_source = _resolve_trade_levels(
        current_price, technical_data.get("atr"),
        synthesis.get("target_price"), synthesis.get("stop_loss"),
        synthesis.get("risk_reward_ratio"),
    )
    if isinstance(grok_data, dict):
        grok_data["_levels_source"] = levels_source

    # Check GEM (blocked signals can't be GEMs)
    is_gem, gem_conditions = check_gem(
        score, grok_data, {**synthesis, "risk_reward_ratio": risk_reward},
    )
    if is_blocked or blackout_reason or ai_status != "validated":
        is_gem = False

    # Determine status vs previous signal
    prev = previous_signals.get(ticker)
    status = determine_status(action, score, prev)

    # Persist Claude's raw signal + self_check alongside the rest of
    # grok_data so post-hoc audits can answer:
    #   1. "What did Claude actually say?" (`_ai_signal`) — distinct from
    #      `action`, which is derived by score_to_action and may differ.
    #   2. "Did Claude say its reasoning was consistent with that
    #      signal?" (`_self_check`).
    # Underscore-prefixed keys match the existing meta-field convention
    # (_market_regime, _knowledge_block, _options_flow, ...) and are
    # ignored by format_sentiment so they cannot leak into future prompts.
    if isinstance(grok_data, dict):
        _ai_signal = synthesis.get("signal")
        if _ai_signal:
            grok_data["_ai_signal"] = _ai_signal
        if synthesis.get("self_check"):
            grok_data["_self_check"] = synthesis["self_check"]
        # Decision-model escalation outcome ("confirmed" | "unavailable").
        if synthesis.get("_decision"):
            grok_data["_decision"] = synthesis["_decision"]

    # Build signal record
    signal_data = {
        "scan_id": scan_id,
        "symbol": ticker,
        "asset_type": asset_class,
        "exchange": exchange,
        "action": action,
        "status": status,
        "score": score,
        "confidence": synthesis.get("confidence", 0),
        "ai_status": ai_status,
        # Claude's own verdict + which provider produced it + its win
        # probability, as first-class columns (migration 005) so the
        # brain can gate on them without digging into grok_data.
        "ai_signal": (synthesis.get("signal") or None),
        "ai_provider": synthesis.get("_provider"),
        "p_win": _clean_p_win(synthesis.get("p_win")),
        # Routine-vs-decision model audit (migration 008): what the
        # screening model said and whether the decision model overturned it.
        **_decision_audit_fields(synthesis),
        "sentiment_citations": (
            len(grok_data.get("citations") or []) if isinstance(grok_data, dict) else 0
        ),
        "is_gem": is_gem,
        "bucket": bucket,
        "price_at_signal": current_price,
        "target_price": target_price,
        "stop_loss": stop_loss,
        "risk_reward": risk_reward,
        "catalyst": synthesis.get("catalyst"),
        "sentiment_score": int(grok_data.get("score", 50)),
        "reasoning": (
            (synthesis.get("reasoning") or "")
            + (f"\n[Earnings blackout] {blackout_reason}" if blackout_reason else "")
        ),
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

    # Kelly position sizing (if actionable) — uses the final R:R.
    rr = risk_reward
    if action == "BUY" and rr and float(rr) > 0:
        from app.signals.kelly import calculate_kelly
        kelly = calculate_kelly(risk_reward=float(rr), score=score, regime=market_regime)
        signal_data["kelly_recommendation"] = kelly

    logger.info(
        f"{ticker}: {action} (score={score}, gem={is_gem}, "
        f"blocked={is_blocked}, status={status}, regime={market_regime})"
    )

    return signal_data


async def _confirm_buy_with_decision_model(
    ticker: str,
    synthesis: dict,
    technical_data: dict,
    fundamental_data: dict,
    macro_data: dict,
    grok_data: dict,
) -> dict:
    """Escalate a would-be-validated routine BUY to the decision model.

    The routine model (Sonnet) screens every candidate cheaply; only its BUYs
    reach the decision model (Opus), whose answer replaces the routine one.
    If the decision call fails, the BUY is kept but capped to low_confidence
    so it can't auto-buy on an unconfirmed opinion.
    """
    if not settings.ai_decision_escalation or _classify_ai_status(synthesis) != "validated":
        return synthesis
    decision = await ai_provider.synthesize_signal(
        ticker, technical_data, fundamental_data, macro_data, grok_data, tier="decision",
    )
    if decision.get("error"):
        logger.warning(f"Decision model unavailable for {ticker}: {decision.get('error')} — BUY left unconfirmed")
        return {
            **synthesis,
            "confidence": min(
                float(synthesis.get("confidence") or 0),
                settings.ai_validated_min_confidence - 1,
            ),
            "_decision": "unavailable",
        }
    logger.info(
        f"Decision model [{ticker}]: routine BUY → {decision.get('signal')} "
        f"confidence={decision.get('confidence')}"
    )
    return {**decision, "_routine_signal": synthesis.get("signal"), "_decision": "confirmed"}


# Columns added by migration 008. If the migration hasn't been applied
# yet, PostgREST rejects the whole insert — retry without them rather
# than losing the scan's signals.
_OUTCOME_AUDIT_COLUMNS = ("routine_ai_signal", "decision_overturned")


def _decision_audit_fields(synthesis: dict) -> dict:
    """routine_ai_signal / decision_overturned for the signals row.

    - escalated + confirmed: routine = `_routine_signal`, overturned =
      decision signal != routine signal (e.g. Opus said HOLD to a Sonnet BUY)
    - escalated + unavailable: routine = the (kept) routine signal,
      overturned = None (no decision was made)
    - not escalated: routine = the synthesis signal (the routine model's
      own answer), overturned = None
    """
    signal = synthesis.get("signal") or None
    if synthesis.get("_decision") == "confirmed":
        routine = synthesis.get("_routine_signal") or None
        overturned = (
            None if routine is None
            else str(signal or "").upper() != str(routine).upper()
        )
        return {"routine_ai_signal": routine, "decision_overturned": overturned}
    return {"routine_ai_signal": signal, "decision_overturned": None}


def _persist_signals(signals: list[dict]) -> list[dict]:
    """Insert the scan's signals; tolerate a DB without migration 008."""
    try:
        return queries.insert_signals_batch(signals)
    except Exception as e:
        if not any(col in str(e) for col in _OUTCOME_AUDIT_COLUMNS):
            raise
        logger.warning(
            "signals insert rejected the migration-008 columns "
            f"({e}); retrying without them — apply 008_decision_outcomes.sql"
        )
        stripped = [
            {k: v for k, v in s.items() if k not in _OUTCOME_AUDIT_COLUMNS}
            for s in signals
        ]
        return queries.insert_signals_batch(stripped)


def _tech_filter_passed(item: tuple) -> bool:
    """Pre-score tuple (ticker, score, bucket, tech, fund) → stamped filter result."""
    tech = item[3] if len(item) > 3 and isinstance(item[3], dict) else {}
    return bool((tech.get("_tech_filter") or {}).get("passed"))


def _stamp_tech_filter(pre_scores: list[tuple], macro_data: dict | None,
                       prescore_cache: dict[str, dict] | None = None) -> None:
    """Run `technical_filter` (with the tech-level blockers) on every
    pre-scored candidate and store {"passed", "reasons"} in its
    technical_data["_tech_filter"] — persisted with the signal (JSONB), so
    no new column is needed."""
    for ticker, _score, _bucket, tech, fund in pre_scores:
        if not isinstance(tech, dict):
            continue
        ac = ((prescore_cache or {}).get(ticker) or {}).get("asset_class") or _asset_class(ticker, fund)
        try:
            _, blockers = check_blockers({}, fund or {}, macro_data or {}, tech)
        except Exception:
            blockers = []
        passed, reasons = technical_filter(tech, fund, ac, blockers)
        tech["_tech_filter"] = {"passed": passed, "reasons": reasons}


def _select_ai_candidates(pre_scores: list[tuple], screening_data: dict | None, limit: int,
                          entry_mode: str | None = None) -> list[tuple]:
    """Pick the PASS-2 (paid AI) candidates from the pre-scored pool.

    filter mode (default brain_entry_mode): only candidates whose stamped
    technical filter PASSED (see `_stamp_tech_filter`) — the brain can
    never buy a failing one, so its AI call would be wasted. Passing
    candidates are ranked by the prefilter's `trend_quality_score`
    (screening features), then pre-score. score mode (legacy): by pre-score.

    Either way at least 5 slots go to HIGH_RISK when available (sentiment
    matters most there) and unused slots spill over. Capped at `limit`.
    """
    mode = (entry_mode or settings.brain_entry_mode or "").lower()
    if mode == "score":
        pool = sorted(pre_scores, key=lambda x: x[1], reverse=True)
    else:
        def _key(x):
            feats = (screening_data or {}).get(x[0])
            tqs = trend_quality_score(feats) if feats else float("-inf")
            return (-tqs, -x[1])
        pool = sorted((x for x in pre_scores if _tech_filter_passed(x)), key=_key)

    safe_pool = [x for x in pool if x[2] == "SAFE_INCOME"]
    risk_pool = [x for x in pool if x[2] == "HIGH_RISK"]
    min_risk_slots = min(5, len(risk_pool), limit)
    ai = safe_pool[:limit - min_risk_slots] + risk_pool[:min_risk_slots]
    remaining = limit - len(ai)
    if remaining > 0:
        used = {t[0] for t in ai}
        ai += [x for x in pool if x[0] not in used][:remaining]
    return ai


def _classify_ai_status(synthesis: dict) -> str:
    """Classify the AI synthesis outcome for the brain's trust gate.

      failed         — provider error, or confidence <= 0 (the synthesis
                       layer defaults confidence to 0 on unparseable output)
      rejected       — AI ran fine but its signal is not BUY. A confident
                       HOLD/AVOID must never validate a score-driven BUY.
      low_confidence — AI said BUY but confidence < ai_validated_min_confidence
      validated      — AI said BUY with confidence >= ai_validated_min_confidence
    """
    synthesis = synthesis or {}
    if synthesis.get("error"):
        return "failed"
    try:
        confidence = float(synthesis.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence <= 0:
        return "failed"
    signal = str(synthesis.get("signal") or "").strip().upper()
    if signal != "BUY":
        return "rejected"
    if confidence < settings.ai_validated_min_confidence:
        return "low_confidence"
    return "validated"


ATR_STOP_MULTIPLE = 2.0
ATR_FALLBACK_RR = 2.0


def _resolve_trade_levels(price, atr, target, stop, ai_rr):
    """Final (target, stop, risk_reward, source) for a signal.

    Keeps Claude's validated levels when present. Missing ones are filled
    from ATR: stop = price - 2.0*ATR, target = price + 2*(price - stop).
    R:R is always recomputed from the final levels, so it can't disagree
    with them. Returns (None, None, None, "none") when unusable.
    """
    def _f(v):
        try:
            v = float(v)
            return v if v > 0 else None
        except (TypeError, ValueError):
            return None

    price, atr, target, stop = _f(price), _f(atr), _f(target), _f(stop)
    if price is None:
        return target, stop, _f(ai_rr), "ai" if (target and stop) else "none"
    # Discard levels on the wrong side of price.
    if stop is not None and stop >= price:
        stop = None
    if target is not None and target <= price:
        target = None
    source = "ai"
    if stop is None and atr is not None and price - ATR_STOP_MULTIPLE * atr > 0:
        stop = price - ATR_STOP_MULTIPLE * atr
        source = "atr_fallback"
    if target is None and stop is not None:
        target = price + ATR_FALLBACK_RR * (price - stop)
        source = "atr_fallback"
    if target is None or stop is None:
        return None, None, None, "none"
    rr = round((target - price) / (price - stop), 2)
    return round(target, 4), round(stop, 4), rr, source


def _clean_p_win(value) -> float | None:
    """p_win as a probability in [0, 1] (accepts 0-100 too), else None."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if 1.0 < v <= 100.0:
        v = v / 100.0
    if not (0.0 <= v <= 1.0):
        return None
    return round(v, 4)


def _tech_only_action(
    score: int,
    bucket: str,
    technical_data: dict,
    fundamental_data: dict,
    macro_data: dict,
) -> tuple[str, list[str]]:
    """Action for a tech-only (no AI) signal, with blockers applied.

    Tech-only signals used to skip `check_blockers` entirely yet could
    still be BUY. Now: blockers -> AVOID; earnings blackout -> BUY
    becomes HOLD. (ai_status stays "skipped" — never "validated".)
    """
    is_blocked, reasons = check_blockers({}, fundamental_data or {}, macro_data or {}, technical_data or {})
    if is_blocked:
        return "AVOID", reasons
    action = score_to_action(score, bucket)
    if action == "BUY":
        blackout = check_entry_blackout(fundamental_data or {})
        if blackout:
            return "HOLD", [blackout]
    return action, []


def _merge_earnings(
    fundamental_data: dict,
    ctx: dict | None,
    exchange: str,
    today=None,
) -> dict:
    """Write earnings context into fundamental_data (in place).

    Sets the keys `compute_score` (PEAD / PRE_EARNINGS) and
    `check_entry_blackout` read:
      next_earnings_date, earnings_date, days_to_next_earnings,
      trading_days_to_next_earnings, days_since_last_earnings,
      last_eps_surprise_pct (PERCENT), earnings_drift_signal.
    Falls back to the `.info`-derived `earnings_date` from
    get_fundamentals when the earnings context has no next date.
    """
    from datetime import date as _date
    from app.core.market_calendar import trading_days_until

    ctx = ctx or {}
    today = today or datetime.now(ZoneInfo("America/New_York")).date()
    next_iso = ctx.get("next_earnings_date") or fundamental_data.get("earnings_date")
    if next_iso:
        try:
            nd = _date.fromisoformat(str(next_iso)[:10])
        except ValueError:
            nd = None
        if nd is not None and nd >= today:
            fundamental_data["next_earnings_date"] = nd.isoformat()
            fundamental_data["earnings_date"] = nd.isoformat()
            fundamental_data["days_to_next_earnings"] = (nd - today).days
            fundamental_data["trading_days_to_next_earnings"] = trading_days_until(exchange, nd, today)
    if ctx.get("days_since_earnings") is not None:
        fundamental_data["days_since_last_earnings"] = ctx["days_since_earnings"]
    if ctx.get("earnings_surprise_pct") is not None:
        fundamental_data["last_eps_surprise_pct"] = ctx["earnings_surprise_pct"]
    if ctx.get("drift_signal"):
        fundamental_data["earnings_drift_signal"] = ctx["drift_signal"]
    return fundamental_data


def _asset_class(ticker: str, fundamentals: dict | None) -> str:
    """ETF / CRYPTO / STOCK — also recognises ETFs outside the hardcoded
    list (discovered tickers) via Yahoo's quoteType."""
    base = get_asset_class(ticker)
    if base == "STOCK" and ((fundamentals or {}).get("quote_type") or "").upper() == "ETF":
        return "ETF"
    return base


_ENERGY_TICKERS = {"CNQ.TO", "SU.TO", "CVE.TO", "ARX.TO", "IMO.TO", "BTE.TO",
                   "WCP.TO", "TVE.TO", "ERF.TO",
                   "XOM", "COP", "EOG", "SLB", "MPC", "OXY"}
_MINING_TICKERS = {"ABX.TO", "FNV.TO", "WPM.TO", "NTR.TO", "K.TO",
                   "TECK.TO", "FM.TO", "LUN.TO", "IVN.TO",
                   "ABX", "FNV", "WPM", "NTR", "K", "NEM", "FCX"}
_HIGH_RISK_TICKERS = {"WEED.TO", "ACB.TO", "TLRY.TO", "CRON.TO", "OGI.TO",
                      "RIVN", "LCID", "PLTR", "RKLB", "IONQ", "SMCI",
                      "MSTR", "SOUN", "HIMS", "COIN", "SOFI", "AFRM",
                      "HOOD", "MRNA"} | _ENERGY_TICKERS | _MINING_TICKERS


def _known_bucket(ticker: str) -> str | None:
    """Bucket decidable WITHOUT fundamentals, or None.

    Order: crypto / leveraged-inverse ETFs (hard overrides — a stale DB
    row can't make TQQQ "safe"), then the stored bucket, then the
    hardcoded lists.
    """
    from app.scanners.universe import _ETF_TICKERS, is_leveraged_or_inverse

    if ticker.endswith("-USD"):
        return "HIGH_RISK"
    if is_leveraged_or_inverse(ticker):
        return "HIGH_RISK"
    if ticker in _bucket_cache:
        return _bucket_cache[ticker]
    safe_suffixes = ["-UN.TO", "-B.TO", "-A.TO"]
    safe_etfs = _ETF_TICKERS | {"O", "PLD", "AMT", "SPY"}
    if ticker in safe_etfs or any(ticker.endswith(sfx) for sfx in safe_suffixes):
        return "SAFE_INCOME"
    if ticker in _HIGH_RISK_TICKERS:
        return "HIGH_RISK"
    return None


def _has_classifying_fundamentals(f: dict | None) -> bool:
    f = f or {}
    return bool(
        f.get("sector") or f.get("market_cap")
        or (f.get("quote_type") or "").upper() == "ETF"
    )


def _classify_bucket(ticker: str, fundamentals: dict | None) -> str:
    """Classify a ticker into SAFE_INCOME or HIGH_RISK.

    Priority: 1) `_known_bucket` (crypto / leveraged ETFs / stored /
    hardcoded), 2) heuristic on REAL fundamentals from
    `market_scanner.get_fundamentals` (sector, dividend_yield as a
    fraction, market_cap, quote_type).

    The old version read sector/dividend_yield/market_cap from the bulk
    screening row, which never contains them — every unknown ticker fell
    through to SAFE_INCOME and that guess was persisted permanently.

    If fundamentals are unavailable, return HIGH_RISK (the stricter BUY
    threshold, and sentiment is fetched) WITHOUT persisting or caching,
    so the next scan with real data classifies properly.
    """
    from app.scanners.universe import is_leveraged_or_inverse

    known = _known_bucket(ticker)
    if known is not None:
        return known
    if is_leveraged_or_inverse(ticker, fundamentals):
        bucket = "HIGH_RISK"
    elif not _has_classifying_fundamentals(fundamentals):
        logger.debug(f"{ticker}: no fundamentals — using HIGH_RISK for this scan (not persisted)")
        return "HIGH_RISK"
    else:
        bucket = _bucket_from_fundamentals(fundamentals)

    # Persist bucket so it's stable across scans
    try:
        queries.upsert_ticker(ticker, exchange=get_exchange(ticker), bucket=bucket)
    except Exception:
        pass

    _bucket_cache[ticker] = bucket
    return bucket


def _bucket_from_fundamentals(fundamentals: dict) -> str:
    """Heuristic bucket from real fundamentals.

    SAFE_INCOME weights `dividend_reliability` 35% and skips Grok, so a
    growth stock dumped there is mathematically capped near 60 and gets
    no sentiment signal. Rules, in order:
      1. Plain (non-leveraged) ETF → SAFE_INCOME (ETF weights)
      2. Energy / Materials → HIGH_RISK
      3. Tech / Comm / Consumer Cyclical → HIGH_RISK unless dividend
         yield >= 2% (T, BCE.TO belong with income; NVDA/AVGO don't)
      4. dividend yield >= 2% → SAFE_INCOME
      5. market cap < $50B → HIGH_RISK
      6. else → SAFE_INCOME
    dividend_yield is a FRACTION (0.02 = 2%) — see
    market_scanner._dividend_yield_fraction.
    """
    quote_type = (fundamentals.get("quote_type") or "").upper()
    sector_lower = (fundamentals.get("sector") or "").strip().lower()
    div_yield = fundamentals.get("dividend_yield") or 0
    mcap = fundamentals.get("market_cap") or 0

    high_risk_sectors_lower = {"technology", "communication services", "consumer cyclical"}
    energy_materials_lower = {"energy", "basic materials", "materials"}
    MEANINGFUL_DIV_THRESHOLD = 0.02

    if quote_type == "ETF":
        return "SAFE_INCOME"
    if sector_lower in energy_materials_lower:
        return "HIGH_RISK"
    if sector_lower in high_risk_sectors_lower and div_yield < MEANINGFUL_DIV_THRESHOLD:
        return "HIGH_RISK"
    if div_yield >= MEANINGFUL_DIV_THRESHOLD:
        return "SAFE_INCOME"
    if 0 < mcap < 50_000_000_000:
        return "HIGH_RISK"
    return "SAFE_INCOME"


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
