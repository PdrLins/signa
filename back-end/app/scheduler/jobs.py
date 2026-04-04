"""Scheduled scan jobs — 4 daily scans on market days."""

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


async def after_close_scan():
    """4:30 PM ET — After-close full scan."""
    logger.info("⏰ After-close scan triggered (4:30 PM ET)")
    from app.services.scan_service import run_scan
    await run_scan("AFTER_CLOSE")
