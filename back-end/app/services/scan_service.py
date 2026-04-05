"""Scan orchestrator — runs the full data pipeline for a scan cycle."""

import asyncio
import time
from datetime import datetime, timezone

from loguru import logger

from app.ai import provider as ai_provider
from app.ai.signal_engine import (
    check_blockers,
    check_gem,
    compute_score,
    determine_status,
    score_to_action,
)
from app.core.config import settings
from app.db import queries
from app.notifications.telegram_bot import send_gem_alert, send_scan_digest, send_watchlist_sell_alert
from app.scanners import indicators, macro_scanner, market_scanner
from app.scanners.prefilter import prefilter_candidates

# Ticker universe — hardcoded for now, could move to DB
from app.scanners.universe import get_all_tickers, get_exchange


async def run_scan(scan_type: str, scan_id: str | None = None) -> str:
    """Execute a full scan cycle.

    Steps:
    1. Load tickers → pre-filter to candidates
    2. Pull macro snapshot
    3. For each candidate: technicals, sentiment, synthesis, scoring
    4. Persist signals to Supabase
    5. Send GEM alerts + digest via Telegram

    Args:
        scan_type: PRE_MARKET, MORNING, PRE_CLOSE, AFTER_CLOSE
        scan_id: Pre-created scan ID (from /trigger endpoint). If None, creates one.

    Returns:
        The scan_id.
    """
    start_time = time.time()
    logger.info(f"Starting {scan_type} scan...")

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
        # Phase 1: Load tickers and pre-filter (0-15%)
        _update_progress(5, "screening", "Loading universe...")
        all_tickers = get_all_tickers()
        logger.info(f"Universe: {len(all_tickers)} tickers")

        screening_data = await market_scanner.get_bulk_screening(all_tickers)
        _update_progress(10, "filtering")
        candidates = prefilter_candidates(screening_data)
        logger.info(f"Candidates after pre-filter: {len(candidates)}")

        queries.update_scan(scan_id, candidates=len(candidates), tickers_scanned=len(all_tickers))
        _update_progress(15, "macro", "Fetching macro data...")

        # Phase 2: Macro snapshot (15-20%)
        macro_data = await macro_scanner.get_macro_snapshot()

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
        import asyncio as _aio
        _knowledge_block = await _aio.to_thread(
            lambda: _ks.get_knowledge_block([
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
        )
        if _knowledge_block:
            logger.info(f"Brain knowledge loaded: {len(_knowledge_block)} chars")

        # ══════════════════════════════════════════════════════
        # TWO-PASS SCANNING — saves ~70% AI tokens
        # Pass 1: Quick pre-score (FREE — technicals + fundamentals only)
        # Pass 2: Full AI analysis (PAID — only top candidates)
        # ══════════════════════════════════════════════════════

        AI_CANDIDATE_LIMIT = settings.ai_candidate_limit
        semaphore = asyncio.Semaphore(settings.max_concurrent_api_calls)
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
                        market_scanner.get_price_history(ticker, "3mo"),
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

        prescore_tasks = [_prescore(t, i) for i, t in enumerate(candidates)]
        prescore_results = await asyncio.gather(*prescore_tasks)
        pre_scores = [r for r in prescore_results if r is not None]

        # Sort by pre-score descending, pick top N for AI
        pre_scores.sort(key=lambda x: x[1], reverse=True)

        if settings.ai_enabled and AI_CANDIDATE_LIMIT > 0:
            ai_candidates = pre_scores[:AI_CANDIDATE_LIMIT]
            skip_candidates = pre_scores[AI_CANDIDATE_LIMIT:]
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
                )
                return result
            except Exception as e:
                errors_count += 1
                logger.debug(f"AI processing failed {ticker}: {e}")
                return None

        ai_tasks = [_process_ai(item, i) for i, item in enumerate(ai_candidates)]
        ai_results = await asyncio.gather(*ai_tasks)
        valid_signals.extend(s for s in ai_results if isinstance(s, dict))

        # ── Generate tech-only signals for skipped candidates ──
        _update_progress(80, "saving", "Building tech-only signals...")
        for ticker, quick_score, bucket, technical_data, fundamental_data in skip_candidates:
            from app.scanners.universe import get_exchange
            exchange = get_exchange(ticker)
            action = score_to_action(quick_score)
            prev = previous_signals.get(ticker)
            status = determine_status(action, quick_score, prev)

            signal_data = {
                "scan_id": scan_id,
                "symbol": ticker,
                "asset_type": "CRYPTO" if exchange == "CRYPTO" else "EQUITY",
                "exchange": exchange,
                "action": action,
                "status": status,
                "score": quick_score,
                "confidence": 0,
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
                "account_recommendation": "RRSP" if bucket == "HIGH_RISK" else "TFSA",
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
            await send_gem_alert(gem_signal)

        # Check watchlist for SELL/AVOID signals — alert immediately
        watchlist_items = queries.get_watchlist()
        watchlist_symbols = {item.get("symbol") for item in watchlist_items}
        for sig in valid_signals:
            sym = sig.get("symbol")
            action = sig.get("action")
            if sym in watchlist_symbols and action in ("SELL", "AVOID"):
                await send_watchlist_sell_alert(sig)
                logger.info(f"Watchlist SELL alert sent for {sym}")

        if scan_type in ("PRE_MARKET", "AFTER_CLOSE") and valid_signals:
            await send_scan_digest(scan_type, valid_signals)

        # Phase 7: Monitor positions (95-100%)
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
) -> dict:
    """Process a single candidate ticker through the full pipeline.

    Returns a signal dict ready for DB insertion.
    """
    async with semaphore:
        logger.debug(f"Processing {ticker}...")

        bucket = _classify_bucket(ticker, screening_data.get(ticker, {}))

        # Fetch data in parallel
        # Skip sentiment for SAFE_INCOME (only 10% weight — not worth the AI cost)
        if bucket == "SAFE_INCOME":
            price_df, fundamental_data = await asyncio.gather(
                market_scanner.get_price_history(ticker, "3mo"),
                market_scanner.get_fundamentals(ticker),
            )
            grok_data = {"score": 50, "label": "neutral", "confidence": 0, "top_themes": [], "summary": "Sentiment skipped for Safe Income (10% weight)"}
        else:
            price_df, fundamental_data, grok_data = await asyncio.gather(
                market_scanner.get_price_history(ticker, "3mo"),
                market_scanner.get_fundamentals(ticker),
                ai_provider.analyze_sentiment(ticker),
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

        # AI synthesis with provider fallback chain
        synthesis = await ai_provider.synthesize_signal(
            ticker, technical_data, fundamental_data, macro_data, grok_data,
        )

        # Score (with regime context)
        score, breakdown = compute_score(
            technical_data, fundamental_data, macro_data,
            grok_data, synthesis, bucket, market_regime,
        )

        # Check blockers
        is_blocked, block_reasons = check_blockers(
            grok_data, fundamental_data, macro_data, technical_data,
        )

        # Determine action (blockers override score)
        action = "AVOID" if is_blocked else score_to_action(score)

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
            "asset_type": "CRYPTO" if exchange == "CRYPTO" else "EQUITY",
            "exchange": exchange,
            "action": action,
            "status": status,
            "score": score,
            "confidence": synthesis.get("confidence", 0),
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
            "account_recommendation": "RRSP" if bucket == "HIGH_RISK" else "TFSA",
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
    """Simple heuristic to classify a ticker into SAFE_INCOME or HIGH_RISK.

    In production, this would come from the tickers table.
    """
    # All crypto → HIGH_RISK (no dividends, high volatility)
    if ticker.endswith("-USD"):
        return "HIGH_RISK"

    # ETFs and high-dividend stocks → SAFE_INCOME
    safe_suffixes = ["-UN.TO", "-B.TO", "-A.TO"]
    safe_etfs = {"XIU.TO", "XIC.TO", "VFV.TO", "ZDV.TO", "XEI.TO", "ZWC.TO",
                 "XDIV.TO", "VDY.TO", "QQQ", "SPY", "O", "PLD", "AMT"}

    if ticker in safe_etfs or any(ticker.endswith(s) for s in safe_suffixes):
        return "SAFE_INCOME"

    # High volatility or small cap → HIGH_RISK
    high_risk_tickers = {"WEED.TO", "ACB.TO", "TLRY.TO", "CRON.TO", "OGI.TO",
                         "RIVN", "LCID", "PLTR", "RKLB", "IONQ", "SMCI",
                         "MSTR", "SOUN", "HIMS", "COIN", "SOFI", "AFRM",
                         "HOOD", "MRNA"}

    if ticker in high_risk_tickers:
        return "HIGH_RISK"

    # Default based on day change
    day_change = abs(screening.get("day_change", 0))
    if day_change > 0.03:
        return "HIGH_RISK"

    return "SAFE_INCOME"
