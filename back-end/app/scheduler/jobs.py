"""Scheduled jobs: quotes, portfolio snapshots, insights history,
Telegram notifications and maintenance. No AI."""

from loguru import logger


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

        if bl_count or otp_count:
            logger.info(f"DB cleanup: {bl_count} expired tokens, {otp_count} old OTPs removed")
        # Purge expired entries from in-memory caches
        from app.core.cache import blacklist_cache, stats_cache, price_cache
        blacklist_cache.cleanup()
        stats_cache.cleanup()
        price_cache.cleanup()

    except Exception as e:
        logger.warning(f"DB cleanup failed: {e}")


async def holding_status_refresh():
    """17:45 ET weekdays — daily price snapshot on every holding (price
    fallback and YTD base; app/services/holding_status.py). No AI."""
    from app.core.config import settings

    if not settings.holdings_monitor_enabled:
        return
    try:
        from app.services.holding_status import refresh
        result = await refresh()
        logger.info(f"Holding status: {result}")
    except Exception as e:
        logger.error(f"Holding status refresh failed: {e}")


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


async def quotes_offhours():
    """Every minute, any day: crypto 24/7 and US pre/after-hours prices for
    Premium followers, outside the regular session (app/services/quotes.py
    refresh_offhours). Skips itself during the session."""
    import asyncio

    from app.core.config import settings

    if not (settings.quotes_refresh_enabled and settings.quotes_offhours_enabled):
        return
    try:
        from app.services.quotes import refresh_offhours
        result = await asyncio.to_thread(refresh_offhours)
        if result.get("crypto") or result.get("extended"):
            logger.debug(f"Quotes off-hours: {result}")
    except Exception as e:
        logger.error(f"Quotes off-hours refresh failed: {e}")


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


async def push_notifications(mode: str = "events"):
    """iOS push (migration 025, app/services/push.py), same schedule as Telegram:
    "events" 08:30 ET daily + 18:30 ET weekdays; "live" every 5 min in the session."""
    try:
        from app.services.push import run_delivery
        result = await run_delivery(mode)
        if result.get("lines"):
            logger.info(f"Push notifications ({mode}): {result}")
    except Exception as e:
        logger.error(f"Push notifications ({mode}) failed: {e}")


async def monthly_recap_push():
    """1st of the month 09:05 ET: last month's recap as a push (app/services/recap.py)."""
    try:
        from app.services.recap import run_monthly_push
        logger.info(f"Monthly recap: {await run_monthly_push()}")
    except Exception as e:
        logger.error(f"Monthly recap failed: {e}")


async def push_notifications_live():
    await push_notifications("live")


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
