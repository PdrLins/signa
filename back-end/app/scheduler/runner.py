"""APScheduler setup -- scan jobs, cleanup, snapshot, and watchdog."""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from app.core.config import settings
from app.core.scan_schedule import SCAN_SCHEDULE
from app.scheduler.jobs import (
    after_close_scan,
    brain_watchdog,
    candidate_outcome_tracking,
    cleanup_expired_tokens,
    daily_learning_loop,
    holdings_monitor,
    midday_scan,
    morning_scan,
    pre_close_scan,
    pre_market_scan,
    virtual_portfolio_snapshot,
)

# Map scan_type to the async job handler. This preserves the existing
# per-job handler pattern while letting us drive registration from the
# canonical SCAN_SCHEDULE list in core/scan_schedule.py.
_SCAN_HANDLERS = {
    "PRE_MARKET": pre_market_scan,
    "MORNING": morning_scan,
    "MIDDAY": midday_scan,
    "PRE_CLOSE": pre_close_scan,
    "AFTER_CLOSE": after_close_scan,
}

# APScheduler's default misfire grace is 1 second: if the event loop is busy
# (a scan running) when a job is due, the job is silently skipped. Allow 15
# minutes late, and run a job that missed several times only once.
scheduler = AsyncIOScheduler(
    timezone=settings.timezone,
    job_defaults={"misfire_grace_time": 15 * 60, "coalesce": True, "max_instances": 1},
)


def get_scheduler() -> AsyncIOScheduler:
    """Get the scheduler instance."""
    return scheduler


def init_scheduler() -> AsyncIOScheduler:
    """Configure and return the scheduler with all jobs.

    All scans run Monday-Friday only (day_of_week='mon-fri').
    Times are in Eastern Time.
    """
    # Register all scan jobs from the canonical schedule. Adding a new
    # scan means adding it to core/scan_schedule.py — NOT here.
    for slot in SCAN_SCHEDULE:
        handler = _SCAN_HANDLERS.get(slot.scan_type)
        if handler is None:
            logger.warning(f"No handler registered for scan_type={slot.scan_type}, skipping")
            continue
        job_id = slot.scan_type.lower() + "_scan"
        scheduler.add_job(
            handler,
            CronTrigger(hour=slot.hour, minute=slot.minute, day_of_week="mon-fri", timezone=settings.timezone),
            id=job_id,
            name=f"{slot.label} ({slot.hhmm} ET)",
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

    # 5:15 PM ET — Counterfactual candidate outcomes (seed + fill forward
    # returns). Before the 5:30 learning loop, which reads them.
    if settings.outcomes_enabled:
        scheduler.add_job(
            candidate_outcome_tracking,
            CronTrigger(hour=17, minute=15, day_of_week="mon-fri", timezone=settings.timezone),
            id="candidate_outcome_tracking",
            name="Candidate Outcome Tracking (5:15 PM ET)",
            replace_existing=True,
        )

    # 5:30 PM ET — Daily Learning Loop. Must run AFTER virtual_portfolio_snapshot
    # (5:00 PM) and the AFTER_CLOSE scan (4:30 PM) so the analysis sees the
    # day's full close-out. See app/services/daily_learning/ for design.
    scheduler.add_job(
        daily_learning_loop,
        CronTrigger(hour=17, minute=30, day_of_week="mon-fri", timezone=settings.timezone),
        id="daily_learning_loop",
        name="Daily Learning Loop (5:30 PM ET)",
        replace_existing=True,
    )

    # 5:45 PM ET — My holdings monitor (the owner's REAL positions): after
    # the close so daily bars are complete; alerts only on state changes.
    if settings.holdings_monitor_enabled:
        scheduler.add_job(
            holdings_monitor,
            CronTrigger(hour=17, minute=45, day_of_week="mon-fri", timezone=settings.timezone),
            id="holdings_monitor",
            name="My Holdings Monitor (5:45 PM ET)",
            replace_existing=True,
        )

    # Every 15 min during market hours (9 AM - 5 PM ET, Mon-Fri)
    if settings.watchdog_enabled:
        scheduler.add_job(
            brain_watchdog,
            CronTrigger(minute="*/15", hour="9-17", day_of_week="mon-fri", timezone=settings.timezone),
            id="brain_watchdog",
            name="Brain Watchdog (every 15 min, 9AM-5PM Mon-Fri)",
            replace_existing=True,
        )

        # Crypto trades 24/7: cover every hour outside the weekday job
        # (weeknights + weekends) every 15 min. run_watchdog only touches
        # positions that can fill, so off-hours this is crypto-only.
        if settings.watchdog_weekend_crypto:
            scheduler.add_job(
                brain_watchdog,
                CronTrigger(minute="*/15", hour="0-8,18-23", day_of_week="mon-fri", timezone=settings.timezone),
                id="brain_watchdog_weeknight",
                name="Brain Watchdog weeknights (every 15 min, crypto only)",
                replace_existing=True,
            )
            scheduler.add_job(
                brain_watchdog,
                CronTrigger(minute="*/15", day_of_week="sat,sun", timezone=settings.timezone),
                id="brain_watchdog_weekend",
                name="Brain Watchdog weekend (every 15 min, crypto only)",
                replace_existing=True,
            )

    watchdog_status = "enabled" if settings.watchdog_enabled else "disabled"
    logger.info(
        f"Scheduler configured: {len(SCAN_SCHEDULE)} scans + cleanup + snapshot "
        f"+ outcomes + daily-learning + holdings + watchdog ({watchdog_status}) "
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
