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

    from app.db import queries

    scan_slots = [
        ("PRE_MARKET", 6, 0),
        ("MORNING", 10, 0),
        ("MIDDAY", 12, 0),
        ("PRE_CLOSE", 15, 0),
        ("AFTER_CLOSE", 16, 30),
    ]

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
    for scan_type, hour, minute in scan_slots:
        scheduled_time = now_et.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now_et > scheduled_time and scan_type not in completed_types:
            missed.append(scan_type)

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


async def brain_watchdog():
    """Every 15 min during market hours -- monitor open brain positions."""
    from app.services.watchdog_service import run_watchdog

    try:
        result = await run_watchdog()
        if result.get("concerned"):
            logger.info(f"Watchdog: {result}")
    except Exception as e:
        logger.error(f"Brain watchdog failed: {e}")
