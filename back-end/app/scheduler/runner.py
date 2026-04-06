"""APScheduler setup -- scan jobs, cleanup, snapshot, and watchdog."""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from app.core.config import settings
from app.scheduler.jobs import (
    after_close_scan,
    brain_watchdog,
    cleanup_expired_tokens,
    midday_scan,
    morning_scan,
    pre_close_scan,
    pre_market_scan,
    virtual_portfolio_snapshot,
)

scheduler = AsyncIOScheduler(timezone=settings.timezone)


def init_scheduler() -> AsyncIOScheduler:
    """Configure and return the scheduler with all jobs.

    All scans run Monday-Friday only (day_of_week='mon-fri').
    Times are in Eastern Time.
    """
    # 6:00 AM ET — Pre-market scan
    scheduler.add_job(
        pre_market_scan,
        CronTrigger(hour=6, minute=0, day_of_week="mon-fri", timezone=settings.timezone),
        id="pre_market_scan",
        name="Pre-Market Scan (6:00 AM ET)",
        replace_existing=True,
    )

    # 10:00 AM ET — Morning confirmation
    scheduler.add_job(
        morning_scan,
        CronTrigger(hour=10, minute=0, day_of_week="mon-fri", timezone=settings.timezone),
        id="morning_scan",
        name="Morning Scan (10:00 AM ET)",
        replace_existing=True,
    )

    # 12:00 PM ET — Midday scan (covers the 10 AM - 3 PM gap)
    scheduler.add_job(
        midday_scan,
        CronTrigger(hour=12, minute=0, day_of_week="mon-fri", timezone=settings.timezone),
        id="midday_scan",
        name="Midday Scan (12:00 PM ET)",
        replace_existing=True,
    )

    # 3:00 PM ET — Pre-close check
    scheduler.add_job(
        pre_close_scan,
        CronTrigger(hour=15, minute=0, day_of_week="mon-fri", timezone=settings.timezone),
        id="pre_close_scan",
        name="Pre-Close Scan (3:00 PM ET)",
        replace_existing=True,
    )

    # 4:30 PM ET — After-close full scan
    scheduler.add_job(
        after_close_scan,
        CronTrigger(hour=16, minute=30, day_of_week="mon-fri", timezone=settings.timezone),
        id="after_close_scan",
        name="After-Close Scan (4:30 PM ET)",
        replace_existing=True,
    )

    # 2:00 AM ET — Daily cleanup of expired tokens, OTPs, brain sessions
    scheduler.add_job(
        cleanup_expired_tokens,
        CronTrigger(hour=2, minute=0, timezone=settings.timezone),
        id="cleanup_expired_tokens",
        name="DB Cleanup (2:00 AM ET)",
        replace_existing=True,
    )

    # 5:00 PM ET — Daily virtual portfolio snapshot (after last scan with prices)
    scheduler.add_job(
        virtual_portfolio_snapshot,
        CronTrigger(hour=17, minute=0, day_of_week="mon-fri", timezone=settings.timezone),
        id="virtual_portfolio_snapshot",
        name="Virtual Portfolio Snapshot (5:00 PM ET)",
        replace_existing=True,
    )

    # Every 15 min during market hours — brain watchdog monitors open positions
    if settings.watchdog_enabled:
        scheduler.add_job(
            brain_watchdog,
            CronTrigger(minute="*/15", hour="9-16", day_of_week="mon-fri", timezone=settings.timezone),
            id="brain_watchdog",
            name="Brain Watchdog (every 15 min)",
            replace_existing=True,
        )

    watchdog_status = "enabled" if settings.watchdog_enabled else "disabled"
    logger.info(
        f"Scheduler configured: 4 scans + cleanup + snapshot + watchdog ({watchdog_status}) "
        f"(timezone: {settings.timezone})"
    )

    return scheduler


def start_scheduler():
    """Start the scheduler."""
    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started")


def stop_scheduler():
    """Gracefully shut down the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
