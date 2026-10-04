"""Scheduled jobs: quotes, portfolio snapshots, insights history,
Telegram notifications and maintenance. No AI."""

from loguru import logger

from app.core.executors import in_job_pool
from app.scheduler.health import fail, tracked


# Days kept by the nightly cleanup. Delivery keys carry their event date, so
# a deleted key can't be sent again; check diffs only look a few days back.
RETENTION_DAYS = {"notification_deliveries": 45, "check_status_daily": 60, "audit_logs": 180,
                  "user_activity_days": 400, "feedback_reports": 365}
# Also removed nightly: used refresh tokens after 2 days, sessions ended 30 days
# ago, Telegram link codes a day after expiry, rejected push devices after 30 days,
# daily activity after 400 days, closed problem reports after a year, expired
# username holds, and accounts whose deletion grace ended.


def _cleanup_db(now=None) -> dict:
    """Blocking: expired tokens and OTPs, then old rows of the growing tables."""
    from datetime import datetime, timedelta, timezone

    from postgrest.types import CountMethod, ReturnMethod

    from app.db.supabase import get_client

    db = get_client()
    now = now or datetime.now(timezone.utc)

    def delete(q) -> int:
        return q.execute().count or 0

    def table(name):
        return db.table(name).delete(count=CountMethod.exact, returning=ReturnMethod.minimal)

    iso = now.isoformat()
    out = {"tokens": delete(table("token_blacklist").lt("expires_at", iso)),
           "otps": delete(table("otp_codes").not_.is_("used_at", "null"))
           + delete(table("otp_codes").lt("expires_at", iso))}
    cut = {t: now - timedelta(days=d) for t, d in RETENTION_DAYS.items()}
    day, month = (now - timedelta(days=1)).isoformat(), (now - timedelta(days=30)).isoformat()
    steps = [
        ("notification_deliveries", lambda: table("notification_deliveries").lt(
            "sent_at", cut["notification_deliveries"].isoformat())),
        ("check_status_daily", lambda: table("check_status_daily").lt(
            "check_date", cut["check_status_daily"].date().isoformat())),
        ("audit_logs", lambda: table("audit_logs").lt("created_at", cut["audit_logs"].isoformat())),
        # sign-in rows: used refresh tokens (rotation keeps the newest), sessions
        # ended 30+ days ago (their tokens go with them), old Telegram link codes,
        # devices Apple rejected a month ago
        ("auth_refresh_tokens", lambda: table("auth_refresh_tokens").lt("used_at", (now - timedelta(days=2)).isoformat())),
        ("auth_sessions", lambda: table("auth_sessions").lt("absolute_expires_at", month)),
        ("auth_sessions_revoked", lambda: db.table("auth_sessions").delete(
            count=CountMethod.exact, returning=ReturnMethod.minimal).lt("revoked_at", month)),
        ("telegram_link_codes", lambda: table("telegram_link_codes").lt("expires_at", day)),
        ("push_devices", lambda: table("push_devices").lt("disabled_at", month)),
        # usage history beyond what retention reports need; problem reports closed a year ago
        ("user_activity_days", lambda: table("user_activity_days").lt(
            "day", cut["user_activity_days"].date().isoformat())),
        ("feedback_reports", lambda: table("feedback_reports").in_("status", ["fixed", "wont_fix", "duplicate"])
         .lt("created_at", cut["feedback_reports"].isoformat())),
        ("reserved_usernames", lambda: table("reserved_usernames").lt("until", iso)),
    ]
    for name, build in steps:
        try:
            out[name] = delete(build())
        except Exception as e:   # one missing table must not stop the rest
            logger.warning(f"DB cleanup of {name} failed: {type(e).__name__}")
    # accounts whose 30-day deletion grace has ended (migration 030)
    try:
        from app.services import account
        out["accounts_deleted"] = account.purge_due(now)["deleted"]
    except Exception as e:
        logger.warning(f"DB cleanup of deleted accounts failed: {type(e).__name__}")
    return out


@tracked("cleanup_expired_tokens")
async def cleanup_expired_tokens():
    """Daily 2:00 AM ET: expired tokens and OTPs, old notification keys,
    check snapshots and audit rows (RETENTION_DAYS), in-memory caches."""
    try:
        result = await in_job_pool(_cleanup_db)
        try:   # referrals whose invited friend now counts as a real user
            from app.services import referrals
            paid = await in_job_pool(referrals.reward_due)
            for referrer in paid:
                await referrals.notify_referrer(referrer)
            result["referrals_rewarded"] = len(paid)
        except Exception as e:
            logger.warning(f"Referral rewards failed: {type(e).__name__}")
        if any(result.values()):
            logger.info(f"DB cleanup: {result}")
        from app.core.cache import blacklist_cache, stats_cache, price_cache
        blacklist_cache.cleanup()
        stats_cache.cleanup()
        price_cache.cleanup()
    except Exception as e:
        fail("cleanup_expired_tokens", e)
        logger.warning(f"DB cleanup failed: {e}")


@tracked("holding_status_refresh")
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
        fail("holding_status_refresh", e)
        logger.error(f"Holding status refresh failed: {e}")


@tracked("quotes_refresh")
async def quotes_refresh(force: bool = False):
    """Every 60s in the 09:30-16:00 ET session (force=True after the close):
    refresh the shared `quotes` table for every followed symbol (one batched
    yfinance call; nothing per user). See app/services/quotes.py."""
    from app.core.config import settings

    if not settings.quotes_refresh_enabled:
        return
    try:
        from app.services.quotes import refresh_followed_quotes
        result = await in_job_pool(refresh_followed_quotes, force)
        if result.get("status") != "closed":
            logger.debug(f"Quotes refresh: {result}")
    except Exception as e:
        fail("quotes_refresh", e)
        logger.error(f"Quotes refresh failed: {e}")


@tracked("quotes_refresh_after_close")
async def quotes_refresh_after_close():
    """16:05 ET weekdays — one last refresh so quotes hold the closing prices."""
    await quotes_refresh(force=True)


@tracked("quotes_offhours")
async def quotes_offhours():
    """Every minute, any day: crypto 24/7 and US pre/after-hours prices for
    Premium followers, outside the regular session (app/services/quotes.py
    refresh_offhours). Skips itself during the session."""
    from app.core.config import settings

    if not (settings.quotes_refresh_enabled and settings.quotes_offhours_enabled):
        return
    try:
        from app.services.quotes import refresh_offhours
        result = await in_job_pool(refresh_offhours)
        if result.get("crypto") or result.get("extended"):
            logger.debug(f"Quotes off-hours: {result}")
    except Exception as e:
        fail("quotes_offhours", e)
        logger.error(f"Quotes off-hours refresh failed: {e}")


@tracked("portfolio_snapshots")
async def portfolio_snapshots():
    """16:30 ET weekdays — per-user / per-account value, cash and cost basis
    in the user's home currency (app/services/portfolio_snapshots.py)."""
    from app.core.config import settings

    if not settings.portfolio_snapshots_enabled:
        return
    try:
        from app.services.portfolio_snapshots import run_snapshots
        result = await in_job_pool(run_snapshots)
        logger.info(f"Portfolio snapshots: {result}")
        if result.get("status") in ("failed", "unavailable"):
            fail("portfolio_snapshots", str(result))
    except Exception as e:
        fail("portfolio_snapshots", e)
        logger.error(f"Portfolio snapshots failed: {e}")


@tracked("income_forecast_snapshots")
async def income_forecast_snapshots():
    """18:00 ET weekdays — per-user forward dividend income forecast
    (migration 014), the history "why your income changed" diffs against
    (app/services/income_forecast.py). No AI."""
    from app.core.config import settings

    if not settings.portfolio_insights_jobs_enabled:
        return
    try:
        from app.services.income_forecast import run_income_snapshots
        result = await run_income_snapshots()
        logger.info(f"Income forecast snapshots: {result}")
    except Exception as e:
        fail("income_forecast_snapshots", e)
        logger.error(f"Income forecast snapshots failed: {e}")


@tracked("check_status_snapshots")
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
        fail("check_status_snapshots", e)
        logger.error(f"Check status snapshots failed: {e}")


@tracked("telegram_notifications")
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
        fail("telegram_notifications", e)
        logger.error(f"Telegram notifications ({mode}) failed: {e}")


@tracked("push_notifications")
async def push_notifications(mode: str = "events"):
    """iOS push (migration 025, app/services/push.py), same schedule as Telegram:
    "events" 08:30 ET daily + 18:30 ET weekdays; "live" every 5 min in the session."""
    try:
        from app.services.push import run_delivery
        result = await run_delivery(mode)
        if result.get("lines"):
            logger.info(f"Push notifications ({mode}): {result}")
    except Exception as e:
        fail("push_notifications", e)
        logger.error(f"Push notifications ({mode}) failed: {e}")


@tracked("monthly_recap_push")
async def monthly_recap_push():
    """1st of the month 09:05 ET: last month's recap as a push (app/services/recap.py)."""
    try:
        from app.services.recap import run_monthly_push
        logger.info(f"Monthly recap: {await run_monthly_push()}")
    except Exception as e:
        fail("monthly_recap_push", e)
        logger.error(f"Monthly recap failed: {e}")


_live_ran: dict[str, float] = {}


def _live_due(channel: str) -> bool:
    """Live alerts only when prices moved (or an alert fired) since the last run."""
    import time

    from app.services import quotes

    started = time.time()
    if not quotes.priced_since(_live_ran.get(channel, 0.0)):
        return False
    _live_ran[channel] = started
    return True


@tracked("push_notifications_live")
async def push_notifications_live():
    if _live_due("push"):
        await push_notifications("live")


@tracked("telegram_notifications_live")
async def telegram_notifications_live():
    if _live_due("telegram"):
        await telegram_notifications("live")


@tracked("usage_flush")
async def usage_flush():
    """Every 5 minutes — write the buffered data-usage counters (migration 014)."""

    try:
        from app.services.usage_metrics import flush
        result = await in_job_pool(flush)
        if result.get("rows"):
            logger.debug(f"Usage flush: {result}")
    except Exception as e:
        fail("usage_flush", e)
        logger.error(f"Usage flush failed: {e}")


@tracked("suggestions_nightly")
async def suggestions_nightly():
    """03:00 ET: co-follow counts and symbol profiles for suggestions (migration 028)."""
    try:
        from app.services.suggestions import run_nightly
        result = await in_job_pool(run_nightly)
        logger.info(f"Suggestions: {result}")
        if result.get("status") == "failed":
            fail("suggestions_nightly", str(result))
    except Exception as e:
        fail("suggestions_nightly", e)
        logger.error(f"Suggestions nightly failed: {e}")


@tracked("apple_search_ads_attribution")
async def apple_search_ads_attribution():
    """Every 10 min: resolve pending Apple Search Ads tokens (migration 029)."""
    try:
        from app.services.growth import resolve_asa
        result = await in_job_pool(resolve_asa)
        if result.get("pending"):
            logger.info(f"Apple Search Ads attribution: {result}")
    except Exception as e:
        from app.core.api_errors import is_missing_schema
        if is_missing_schema(e):
            return   # before migration 029
        logger.warning(f"Apple Search Ads attribution failed: {e}")


@tracked("weekly_digest")
async def weekly_digest():
    """Sunday 10:00 ET: "your week" push to every user with the app (app/services/weekly_digest.py)."""
    try:
        from app.services.weekly_digest import run
        result = await run()
        logger.info(f"Weekly digest: {result}")
        if result.get("status") == "failed":
            fail("weekly_digest", str(result))
    except Exception as e:
        fail("weekly_digest", e)
        logger.error(f"Weekly digest failed: {e}")


@tracked("auto_dividends")
async def auto_dividends():
    """19:30 ET daily: record dividends holdings paid (app/services/auto_dividends.py)."""
    try:
        from app.services.auto_dividends import run
        result = await run()
        logger.info(f"Auto dividends: {result}")
        if result.get("status") == "failed":
            fail("auto_dividends", str(result))
    except Exception as e:
        fail("auto_dividends", e)
        logger.error(f"Auto dividends failed: {e}")
