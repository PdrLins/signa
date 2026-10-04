"""APScheduler setup: quotes, snapshots, notifications and maintenance (one
process only: two instances would run every job twice)."""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from app.core.config import settings
from app.scheduler.jobs import (
    check_status_snapshots,
    cleanup_expired_tokens,
    holding_status_refresh,
    income_forecast_snapshots,
    suggestions_nightly,
    portfolio_snapshots,
    monthly_recap_push,
    push_notifications,
    push_notifications_live,
    quotes_offhours,
    quotes_refresh,
    quotes_refresh_after_close,
    telegram_notifications,
    telegram_notifications_live,
    usage_flush,
)

# APScheduler's default misfire grace is 1 second: if the event loop is busy
# (a scan running) when a job is due, the job is silently skipped. Allow 15
# minutes late, and run a job that missed several times only once.
scheduler = AsyncIOScheduler(
    timezone=settings.timezone,
    job_defaults={"misfire_grace_time": 15 * 60, "coalesce": True, "max_instances": 1},
)


def init_scheduler() -> AsyncIOScheduler:
    """Configure and return the scheduler with all jobs (times in Eastern Time)."""
    # 2:00 AM ET — Daily cleanup of expired tokens and OTPs
    scheduler.add_job(
        cleanup_expired_tokens,
        CronTrigger(hour=2, minute=0, timezone=settings.timezone),
        id="cleanup_expired_tokens",
        name="DB Cleanup (2:00 AM ET)",
        replace_existing=True,
    )

    # 5:45 PM ET — daily price snapshot on every holding (after the close).
    if settings.holdings_monitor_enabled:
        scheduler.add_job(
            holding_status_refresh,
            CronTrigger(hour=17, minute=45, day_of_week="mon-fri", timezone=settings.timezone),
            id="holding_status_refresh",
            name="Holding status (5:45 PM ET)",
            replace_existing=True,
        )

    # Portfolio tracker (no AI, nothing per user): shared quotes every 60s
    # in the session (the job itself skips outside 09:30-16:00 ET and on
    # days both NYSE and TSX are closed), one refresh after the close, and
    # daily snapshots. A 60s job must not pile up: short grace, coalesced.
    if settings.quotes_refresh_enabled:
        scheduler.add_job(
            quotes_refresh,
            CronTrigger(minute="*", timezone=settings.timezone),
            id="quotes_refresh",
            name="Quotes refresh (every 60s, each exchange during its own session)",
            replace_existing=True,
            misfire_grace_time=30,
            coalesce=True,
            max_instances=1,
        )
        scheduler.add_job(
            quotes_refresh_after_close,
            CronTrigger(hour=16, minute=5, day_of_week="mon-fri", timezone=settings.timezone),
            id="quotes_refresh_after_close",
            name="Quotes refresh after close (4:05 PM ET)",
            replace_existing=True,
        )
        if settings.quotes_offhours_enabled:
            scheduler.add_job(
                quotes_offhours,
                CronTrigger(minute="*", timezone=settings.timezone),
                id="quotes_offhours",
                name="Quotes outside the session (crypto 24/7, US pre/after-hours)",
                replace_existing=True,
                misfire_grace_time=30,
                coalesce=True,
                max_instances=1,
            )
    if settings.portfolio_snapshots_enabled:
        scheduler.add_job(
            portfolio_snapshots,
            CronTrigger(hour=16, minute=30, day_of_week="mon-fri", timezone=settings.timezone),
            id="portfolio_snapshots",
            name="Portfolio snapshots (4:30 PM ET)",
            replace_existing=True,
        )

    # Portfolio insights history (migration 014, no AI): the forward income
    # forecast per user and the Signa check statuses per followed symbol.
    if settings.portfolio_insights_jobs_enabled:
        scheduler.add_job(
            income_forecast_snapshots,
            CronTrigger(hour=18, minute=0, day_of_week="mon-fri", timezone=settings.timezone),
            id="income_forecast_snapshots",
            name="Income forecast snapshots (6:00 PM ET)",
            replace_existing=True,
        )
        scheduler.add_job(
            check_status_snapshots,
            CronTrigger(hour=18, minute=15, day_of_week="mon-fri", timezone=settings.timezone),
            id="check_status_snapshots",
            name="Signa check status snapshots (6:15 PM ET)",
            replace_existing=True,
        )

    # Per-user Telegram notifications for Premium (migration 016, no AI).
    if settings.telegram_notifications_enabled:
        scheduler.add_job(
            telegram_notifications,
            CronTrigger(hour=8, minute=30, timezone=settings.timezone),
            id="telegram_notifications_morning",
            name="Telegram notifications digest (8:30 AM ET daily)",
            replace_existing=True,
        )
        scheduler.add_job(
            telegram_notifications,
            CronTrigger(hour=18, minute=30, day_of_week="mon-fri", timezone=settings.timezone),
            id="telegram_notifications_evening",
            name="Telegram notifications digest (6:30 PM ET weekdays)",
            replace_existing=True,
        )
        scheduler.add_job(
            telegram_notifications_live,
            CronTrigger(minute="*/5", timezone=settings.timezone),   # runs only after prices moved
            id="telegram_notifications_live",
            name="Telegram price alerts + big moves (every 5 min while any followed exchange trades)",
            replace_existing=True,
            max_instances=1,
        )

    # iOS push (migration 025): same times as Telegram, offset 1 minute.
    if settings.push_notifications_enabled:
        scheduler.add_job(push_notifications, CronTrigger(hour=8, minute=31, timezone=settings.timezone),
                          id="push_notifications_morning", name="Push digest (8:31 AM ET daily)",
                          replace_existing=True)
        scheduler.add_job(push_notifications,
                          CronTrigger(hour=18, minute=31, day_of_week="mon-fri", timezone=settings.timezone),
                          id="push_notifications_evening", name="Push digest (6:31 PM ET weekdays)",
                          replace_existing=True)
        scheduler.add_job(push_notifications_live,
                          CronTrigger(minute="1-59/5", timezone=settings.timezone),   # runs only after prices moved
                          id="push_notifications_live", name="Push price alerts + big moves (every 5 min)",
                          replace_existing=True, max_instances=1)
        scheduler.add_job(monthly_recap_push, CronTrigger(day=1, hour=9, minute=5, timezone=settings.timezone),
                          id="monthly_recap_push", name="Monthly recap push (1st, 9:05 AM ET)",
                          replace_existing=True)

    # Suggestions (migration 028): co-follow counts + symbol profiles, nightly.
    scheduler.add_job(suggestions_nightly, CronTrigger(hour=3, minute=0, timezone=settings.timezone),
                      id="suggestions_nightly", name="Suggestions data (3:00 AM ET)", replace_existing=True)

    # Data-usage counters (cost control, migration 014): flush every 5 minutes.
    scheduler.add_job(
        usage_flush,
        CronTrigger(minute="*/5", timezone=settings.timezone),
        id="usage_flush",
        name="Usage counters flush (every 5 min)",
        replace_existing=True,
    )

    logger.info(f"Scheduler configured: {len(scheduler.get_jobs())} jobs (timezone: {settings.timezone})")

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
