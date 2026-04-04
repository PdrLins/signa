"""Stats service — computes daily aggregated statistics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from loguru import logger

from app.db import queries


# Scan schedule (ET times) — used to compute next_scan_time
_SCHEDULE = [
    ("PRE_MARKET", "06:00"),
    ("MORNING", "10:00"),
    ("PRE_CLOSE", "15:00"),
    ("AFTER_CLOSE", "16:30"),
]


def get_daily_stats() -> dict:
    """Compute aggregated daily stats from existing tables."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)

    try:
        # Get today's signals
        all_signals = queries.get_signals(limit=500)
        today_signals = [
            s for s in all_signals
            if s.get("created_at") and s["created_at"] >= today_start.isoformat()
        ]
        gems_today = sum(1 for s in today_signals if s.get("is_gem"))

        # Get yesterday's gems
        yesterday_signals = [
            s for s in all_signals
            if s.get("created_at")
            and s["created_at"] >= yesterday_start.isoformat()
            and s["created_at"] < today_start.isoformat()
        ]
        gems_yesterday = sum(1 for s in yesterday_signals if s.get("is_gem"))

        # Get today's scans for tickers_scanned
        scans = queries.get_scans(limit=20)
        today_scans = [
            sc for sc in scans
            if sc.get("started_at") and sc["started_at"] >= today_start.isoformat()
        ]
        tickers_scanned = sum(sc.get("tickers_scanned", 0) for sc in today_scans)

        # Next scan time
        next_scan = _compute_next_scan_time()

        return {
            "gems_today": gems_today,
            "gems_yesterday": gems_yesterday,
            "win_rate_30d": 0.0,  # placeholder
            "tickers_scanned": tickers_scanned,
            "next_scan_time": next_scan,
            "ai_cost_today": 0.0,  # placeholder
            "claude_cost": 0.0,
            "grok_cost": 0.0,
        }
    except Exception:
        logger.exception("Failed to compute daily stats")
        return {
            "gems_today": 0,
            "gems_yesterday": 0,
            "win_rate_30d": 0.0,
            "tickers_scanned": 0,
            "next_scan_time": None,
            "ai_cost_today": 0.0,
            "claude_cost": 0.0,
            "grok_cost": 0.0,
        }


def _compute_next_scan_time() -> str | None:
    """Determine the next scheduled scan time (ET)."""
    try:
        from zoneinfo import ZoneInfo

        et = ZoneInfo("America/New_York")
        now_et = datetime.now(et)

        for _, time_str in _SCHEDULE:
            h, m = map(int, time_str.split(":"))
            scan_time = now_et.replace(hour=h, minute=m, second=0, microsecond=0)
            if scan_time > now_et:
                return scan_time.isoformat()

        # All scans done today — next is tomorrow's PRE_MARKET
        tomorrow = now_et + timedelta(days=1)
        h, m = map(int, _SCHEDULE[0][1].split(":"))
        return tomorrow.replace(hour=h, minute=m, second=0, microsecond=0).isoformat()
    except Exception:
        return None
