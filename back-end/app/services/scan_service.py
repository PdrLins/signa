"""Scan orchestrator — runs the full data pipeline for a scan cycle."""

import asyncio
import time
from datetime import datetime, timezone

from loguru import logger

from app.ai import claude_client, grok_client
from app.ai.signal_engine import (
    check_blockers,
    check_gem,
    compute_score,
    determine_status,
    score_to_action,
)
from app.core.config import settings
from app.db import queries
from app.notifications.telegram_bot import send_gem_alert, send_scan_digest
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
        _update_progress(20, "analyzing")

        # Phase 3: Get previous signals
        previous_signals = queries.get_latest_signals_map()

        # Phase 4: Process candidates with progress tracking (20-85%)
        semaphore = asyncio.Semaphore(settings.max_concurrent_api_calls)
        valid_signals = []
        errors_count = 0
        total_candidates = len(candidates)

        async def _process_with_progress(ticker: str, index: int) -> dict | None:
            nonlocal errors_count
            _update_progress(
                20 + int((index / total_candidates) * 65),
                "analyzing",
                ticker,
            )
            try:
                result = await _process_candidate(
                    ticker, macro_data, screening_data, previous_signals,
                    scan_id, semaphore,
                )
                return result
            except Exception as e:
                errors_count += 1
                logger.debug(f"Failed {ticker}: {e}")
                return None

        # Process with semaphore concurrency but track each completion
        tasks = [
            _process_with_progress(ticker, i)
            for i, ticker in enumerate(candidates)
        ]
        results = await asyncio.gather(*tasks)
        valid_signals = [s for s in results if isinstance(s, dict)]

        if errors_count:
            logger.warning(f"{errors_count} candidates failed processing")

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
                error_message=str(e),
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
) -> dict:
    """Process a single candidate ticker through the full pipeline.

    Returns a signal dict ready for DB insertion.
    """
    async with semaphore:
        logger.debug(f"Processing {ticker}...")

        bucket = _classify_bucket(ticker, screening_data.get(ticker, {}))

        # Fetch data in parallel (price + fundamentals + Grok sentiment)
        price_df, fundamental_data, grok_data = await asyncio.gather(
            market_scanner.get_price_history(ticker, "3mo"),
            market_scanner.get_fundamentals(ticker),
            grok_client.analyze_sentiment(ticker),
        )

        # Compute technicals (CPU-only, no I/O)
        technical_data = indicators.compute_indicators(price_df)

        # Call Claude ONCE with all real data (including Grok)
        synthesis = await claude_client.synthesize_signal(
            ticker, technical_data, fundamental_data, macro_data, grok_data,
        )

        # Score
        score, breakdown = compute_score(
            technical_data, fundamental_data, macro_data,
            grok_data, synthesis, bucket,
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
        }

        logger.info(
            f"{ticker}: {action} (score={score}, gem={is_gem}, "
            f"blocked={is_blocked}, status={status})"
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
