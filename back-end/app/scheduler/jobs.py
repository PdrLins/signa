"""Scheduled scan jobs — 4 daily scans on market days + maintenance."""

from loguru import logger


async def pre_market_scan():
    """6:00 AM ET — Pre-market scan."""
    logger.info("⏰ Pre-market scan triggered (6:00 AM ET)")
    from app.services.scan_service import run_scan
    await run_scan("PRE_MARKET")


async def morning_scan():
    """10:00 AM ET — Morning confirmation."""
    logger.info("⏰ Morning scan triggered (10:00 AM ET)")
    from app.services.scan_service import run_scan
    await run_scan("MORNING")


async def pre_close_scan():
    """3:00 PM ET — Pre-close check."""
    logger.info("⏰ Pre-close scan triggered (3:00 PM ET)")
    from app.services.scan_service import run_scan
    await run_scan("PRE_CLOSE")


async def midday_scan():
    """12:00 PM ET — Midday scan."""
    logger.info("Midday scan triggered (12:00 PM ET)")
    from app.services.scan_service import run_scan
    await run_scan("MIDDAY")


async def after_close_scan():
    """4:30 PM ET — After-close full scan."""
    logger.info("⏰ After-close scan triggered (4:30 PM ET)")
    from app.services.scan_service import run_scan
    await run_scan("AFTER_CLOSE")


async def cleanup_expired_tokens():
    """Daily cleanup — remove expired blacklisted tokens and used OTPs.

    Runs at 2:00 AM ET to keep tables lean.
    """
    from datetime import datetime, timezone
    from app.db.supabase import get_client

    try:
        db = get_client()
        now = datetime.now(timezone.utc).isoformat()

        # Delete expired blacklisted tokens
        bl_result = db.table("token_blacklist").delete().lt("expires_at", now).execute()
        bl_count = len(bl_result.data) if bl_result.data else 0

        # Delete OTPs that are either used or expired (safe — never deletes valid unexpired ones)
        otp_used = db.table("otp_codes").delete().not_.is_("used_at", "null").execute()
        otp_expired = db.table("otp_codes").delete().lt("expires_at", now).execute()
        otp_count = (len(otp_used.data) if otp_used.data else 0) + (len(otp_expired.data) if otp_expired.data else 0)

        # Delete expired brain sessions
        bs_result = db.table("brain_sessions").delete().lt("expires_at", now).execute()
        bs_count = len(bs_result.data) if bs_result.data else 0

        if bl_count or otp_count or bs_count:
            logger.info(
                f"DB cleanup: {bl_count} expired tokens, "
                f"{otp_count} old OTPs, {bs_count} brain sessions removed"
            )
        # Purge expired entries from in-memory caches
        from app.core.cache import blacklist_cache, stats_cache, price_cache
        blacklist_cache.cleanup()
        stats_cache.cleanup()
        price_cache.cleanup()

    except Exception as e:
        logger.warning(f"DB cleanup failed: {e}")


async def virtual_portfolio_snapshot():
    """5:00 PM ET — Daily snapshot of virtual portfolio for equity curve."""
    import asyncio
    from app.services.virtual_portfolio import snapshot_virtual_portfolio

    try:
        result = await asyncio.to_thread(snapshot_virtual_portfolio)
        logger.info(f"📊 Virtual portfolio snapshot: brain_cum={result.get('brain_cumulative_pnl', 0):+.1f}%")
    except Exception as e:
        logger.warning(f"Virtual portfolio snapshot failed: {e}")


async def catch_up_missed_scans():
    """Run on startup -- check which scheduled scans were missed today and run them."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")
    now_et = datetime.now(et)

    # Only on weekdays
    if now_et.weekday() >= 5:
        return

    from app.core.scan_schedule import SCAN_SCHEDULE
    from app.db import queries

    # Get today's completed scans (exclude manual)
    today_start = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
    recent_scans = queries.get_scans(limit=20)
    completed_types = set()
    for s in recent_scans:
        started = s.get("started_at", "")
        if started and started >= today_start.isoformat():
            if s.get("triggered_by", "scheduler") != "manual" and s.get("status") == "COMPLETE":
                completed_types.add(s.get("scan_type"))

    # Find missed scans (scheduled time has passed but no completed scan)
    missed = []
    for slot in SCAN_SCHEDULE:
        scheduled_time = now_et.replace(hour=slot.hour, minute=slot.minute, second=0, microsecond=0)
        if now_et > scheduled_time and slot.scan_type not in completed_types:
            missed.append(slot.scan_type)

    if not missed:
        logger.info("Startup catch-up: no missed scans")
        return

    logger.info(f"Startup catch-up: running {len(missed)} missed scan(s): {missed}")
    from app.services.scan_service import run_scan
    for scan_type in missed:
        try:
            logger.info(f"Catch-up: running missed {scan_type} scan")
            await run_scan(scan_type)
        except Exception as e:
            logger.error(f"Catch-up scan {scan_type} failed: {e}")


async def candidate_outcome_tracking():
    """5:15 PM ET — seed + fill counterfactual candidate outcomes.

    Runs after the AFTER_CLOSE scan (so today's signals get seeded) and
    before the 5:30 PM daily learning loop (which reads the filled rows).
    Seeds one candidate_outcomes row per new signal, then fills every
    5/10/20 trading-day horizon that has elapsed with forward returns vs
    SPY. Idempotent; see app/services/decision_outcomes.py.
    """
    import asyncio
    from app.core.config import settings

    if not settings.outcomes_enabled:
        return
    try:
        from app.services.decision_outcomes import run_outcome_tracking
        result = await asyncio.to_thread(run_outcome_tracking)
        logger.info(f"Candidate outcomes: {result}")
    except Exception as e:
        logger.error(f"Candidate outcome tracking failed: {e}")


async def daily_learning_loop():
    """5:30 PM ET — Autonomous Daily Learning Loop.

    Runs after the AFTER_CLOSE scan (16:30 ET) and virtual_portfolio_snapshot
    (17:00 ET) have completed for the day. Produces a daily MD report at
    docs/daily-reports/YYYY-MM-DD.md, a Telegram digest (heartbeat — fires
    every market day including zero-finding days), brain_suggestions
    INVESTIGATE rows for actionable findings, and auto-creates / auto-
    graduates / auto-rejects signal_thinking hypotheses based on
    observed cohort drift and explicit pattern matchers.

    See `app/services/daily_learning/` for the full design.
    """
    logger.info("⏰ Daily Learning Loop triggered (5:30 PM ET)")
    try:
        from app.services.daily_learning import run_daily_learning
        result = await run_daily_learning()
        logger.info(
            f"📋 Daily Learning complete: {result.get('status')} "
            f"findings={result.get('findings_count', 0)} "
            f"created={result.get('hypotheses_created', 0)} "
            f"graduated={result.get('hypotheses_graduated', 0)}"
        )
    except Exception as e:
        logger.error(f"Daily Learning Loop failed: {e}")


async def brain_watchdog():
    """Every 15 min during market hours -- monitor open brain positions.

    When concerned about any position, schedules a follow-up check in 5 min
    for faster sentiment confirmation.
    """
    from app.services.watchdog_service import run_watchdog

    try:
        result = await run_watchdog()
        if result.get("concerned"):
            logger.info(f"Watchdog: {result}")
            try:
                from app.scheduler.runner import get_scheduler
                from datetime import datetime, timedelta, timezone as tz
                from apscheduler.triggers.date import DateTrigger
                sched = get_scheduler()
                if sched and sched.running:
                    run_at = datetime.now(tz.utc) + timedelta(minutes=5)
                    sched.add_job(
                        brain_watchdog,
                        DateTrigger(run_date=run_at),
                        id="watchdog_followup",
                        name="Watchdog follow-up (5 min, one-shot)",
                        replace_existing=True,
                    )
                    logger.info("Watchdog: scheduled 5-min follow-up due to concerned positions")
            except Exception as e:
                logger.debug(f"Watchdog follow-up scheduling failed: {e}")
    except Exception as e:
        logger.error(f"Brain watchdog failed: {e}")


async def holdings_monitor():
    """5:45 PM ET weekdays — watch the owner's REAL long-term holdings.

    Trend / drawdown / earnings / cited red flags (stocks only, free AI
    path, <= 1 AI call per holding per day) / concentration. Telegram only
    on state changes. See app/services/holdings_monitor.py.
    """
    from app.core.config import settings

    if not settings.holdings_monitor_enabled:
        return
    try:
        from app.services.holdings_monitor import run_holdings_monitor
        result = await run_holdings_monitor()
        logger.info(f"Holdings monitor: {result}")
    except Exception as e:
        logger.error(f"Holdings monitor failed: {e}")


async def quotes_refresh(force: bool = False):
    """Every 60s in the 09:30-16:00 ET session (force=True after the close):
    refresh the shared `quotes` table for every followed symbol (one batched
    yfinance call; nothing per user). See app/services/quotes.py."""
    import asyncio

    from app.core.config import settings

    if not settings.quotes_refresh_enabled:
        return
    try:
        from app.services.quotes import refresh_followed_quotes
        result = await asyncio.to_thread(refresh_followed_quotes, force)
        if result.get("status") != "closed":
            logger.debug(f"Quotes refresh: {result}")
    except Exception as e:
        logger.error(f"Quotes refresh failed: {e}")


async def quotes_refresh_after_close():
    """16:05 ET weekdays — one last refresh so quotes hold the closing prices."""
    await quotes_refresh(force=True)


async def portfolio_snapshots():
    """16:30 ET weekdays — per-user / per-account value, cash and cost basis
    in the user's home currency (app/services/portfolio_snapshots.py)."""
    import asyncio

    from app.core.config import settings

    if not settings.portfolio_snapshots_enabled:
        return
    try:
        from app.services.portfolio_snapshots import run_snapshots
        result = await asyncio.to_thread(run_snapshots)
        logger.info(f"Portfolio snapshots: {result}")
    except Exception as e:
        logger.error(f"Portfolio snapshots failed: {e}")


async def income_forecast_snapshots():
    """18:00 ET weekdays — per-user forward dividend income forecast
    (migration 014), the history "why your income changed" diffs against
    (app/services/income_forecast.py). No AI."""
    import asyncio

    from app.core.config import settings

    if not settings.portfolio_insights_jobs_enabled:
        return
    try:
        from app.services.income_forecast import run_income_snapshots
        result = await run_income_snapshots()
        logger.info(f"Income forecast snapshots: {result}")
    except Exception as e:
        logger.error(f"Income forecast snapshots failed: {e}")


async def check_status_snapshots():
    """18:15 ET weekdays — the five Signa checks per followed symbol
    (migration 014), diffed by /events/upcoming (app/services/check_status.py).
    Shared per symbol, no AI."""
    from app.core.config import settings

    if not settings.portfolio_insights_jobs_enabled:
        return
    try:
        from app.services.check_status import run_check_snapshots
        result = await run_check_snapshots()
        logger.info(f"Check status snapshots: {result}")
    except Exception as e:
        logger.error(f"Check status snapshots failed: {e}")


async def telegram_notifications(mode: str = "events"):
    """Per-user Telegram notifications for Premium (migration 016,
    app/services/telegram_notify.py): "events" digest 08:30 ET daily + 18:30 ET
    weekdays; "live" (price alerts, big moves) every 5 min in the session."""
    from app.core.config import settings

    if not settings.telegram_notifications_enabled:
        return
    try:
        from app.services.telegram_notify import run_delivery
        result = await run_delivery(mode)
        if result.get("lines"):
            logger.info(f"Telegram notifications ({mode}): {result}")
    except Exception as e:
        logger.error(f"Telegram notifications ({mode}) failed: {e}")


async def telegram_notifications_live():
    await telegram_notifications("live")


async def usage_flush():
    """Every 5 minutes — write the buffered data-usage counters (migration 014)."""
    import asyncio

    try:
        from app.services.usage_metrics import flush
        result = await asyncio.to_thread(flush)
        if result.get("rows"):
            logger.debug(f"Usage flush: {result}")
    except Exception as e:
        logger.error(f"Usage flush failed: {e}")
