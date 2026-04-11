"""Stats service — computes daily aggregated statistics with caching."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from loguru import logger

from app.core.cache import stats_cache
from app.db.supabase import get_client, with_retry


# Scan schedule (ET times) — used to compute next_scan_time
_SCHEDULE = [
    ("PRE_MARKET", "06:00"),
    ("MORNING", "10:00"),
    ("PRE_CLOSE", "15:00"),
    ("AFTER_CLOSE", "16:30"),
]


@with_retry
def get_daily_stats() -> dict:
    """Compute aggregated daily stats. Cached for 120s."""
    cached = stats_cache.get("daily_stats")
    if cached is not None:
        return cached

    # Use ET date for "today" — after 8pm ET the UTC date rolls to
    # tomorrow, which would zero out all of today's stats.
    from zoneinfo import ZoneInfo
    now_et = datetime.now(ZoneInfo("America/New_York"))
    today_et = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start = today_et.astimezone(timezone.utc)
    yesterday_start = today_start - timedelta(days=1)

    try:
        db = get_client()

        # Query only today's signals (not 500 then filter in Python)
        today_result = (
            db.table("signals")
            .select("is_gem, is_discovered")
            .gte("created_at", today_start.isoformat())
            .execute()
        )
        today_signals = today_result.data or []
        gems_today = sum(1 for s in today_signals if s.get("is_gem"))
        discovered_today = sum(1 for s in today_signals if s.get("is_discovered"))

        # Query yesterday's gems
        yesterday_result = (
            db.table("signals")
            .select("is_gem")
            .gte("created_at", yesterday_start.isoformat())
            .lt("created_at", today_start.isoformat())
            .eq("is_gem", True)
            .execute()
        )
        gems_yesterday = len(yesterday_result.data or [])

        # Query today's scans for tickers_scanned
        scans_result = (
            db.table("scans")
            .select("tickers_scanned")
            .gte("started_at", today_start.isoformat())
            .execute()
        )
        tickers_scanned = sum(s.get("tickers_scanned", 0) for s in scans_result.data or [])

        # Next scan time (pure computation, no DB)
        next_scan = _compute_next_scan_time()

        # Run the two remaining DB-bound helpers in parallel
        with ThreadPoolExecutor(max_workers=2) as pool:
            win_rate_future = pool.submit(_get_virtual_win_rate)
            ai_cost_future = pool.submit(_get_ai_cost_today)
            win_rate = win_rate_future.result()
            ai_cost = ai_cost_future.result()

        # Macro data from latest signal (no extra API call needed)
        fear_greed = None
        intermarket = None
        vix_term = None
        yield_curve = None
        credit_spread = None
        try:
            fg_result = (
                db.table("signals")
                .select("macro_data")
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if fg_result.data:
                macro = fg_result.data[0].get("macro_data") or {}
                fg = macro.get("fear_greed")
                if fg and isinstance(fg, dict):
                    fear_greed = fg
                im = macro.get("intermarket")
                if im and isinstance(im, dict):
                    intermarket = im
                vt = macro.get("vix_term_structure")
                if vt and isinstance(vt, dict):
                    vix_term = vt
                if macro.get("yield_curve_10y2y") is not None:
                    yield_curve = macro["yield_curve_10y2y"]
                if macro.get("credit_spread_bbb") is not None:
                    credit_spread = macro["credit_spread_bbb"]
        except Exception:
            pass

        result = {
            "gems_today": gems_today,
            "gems_yesterday": gems_yesterday,
            "win_rate_30d": win_rate,
            "tickers_scanned": tickers_scanned,
            "discovered_today": discovered_today,
            "next_scan_time": next_scan,
            "ai_cost_today": ai_cost,
            "claude_cost": 0.0,
            "grok_cost": 0.0,
            "fear_greed": fear_greed,
            "intermarket": intermarket,
            "vix_term": vix_term,
            "yield_curve": yield_curve,
            "credit_spread": credit_spread,
        }
        stats_cache.set("daily_stats", result, ttl=120)
        return result
    except Exception:
        logger.exception("Failed to compute daily stats")
        return {
            "gems_today": 0,
            "gems_yesterday": 0,
            "win_rate_30d": 0.0,
            "tickers_scanned": 0,
            "discovered_today": 0,
            "next_scan_time": None,
            "ai_cost_today": 0.0,
            "claude_cost": 0.0,
            "grok_cost": 0.0,
            "fear_greed": None,
        }


def _get_virtual_win_rate() -> float:
    """Get win rate from virtual portfolio. Cached for 5 min."""
    cached = stats_cache.get("virtual_win_rate")
    if cached is not None:
        return cached

    try:
        db = get_client()
        # Only count recent trades (last 90 days) to keep it relevant
        cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        result = (
            db.table("virtual_trades")
            .select("is_win")
            .eq("status", "CLOSED")
            .gte("created_at", cutoff)
            .limit(500)
            .execute()
        )
        trades = result.data or []
        if not trades:
            return 0.0
        wins = sum(1 for t in trades if t.get("is_win"))
        rate = round(wins / len(trades), 4)
        stats_cache.set("virtual_win_rate", rate, ttl=300)
        return rate
    except Exception:
        return 0.0


def _get_ai_cost_today() -> float:
    """Get today's total AI spend from ai_usage table."""
    try:
        db = get_client()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        result = (
            db.table("ai_usage")
            .select("estimated_cost")
            .gte("created_at", f"{today}T00:00:00Z")
            .execute()
        )
        return round(sum(float(r.get("estimated_cost", 0)) for r in result.data or []), 4)
    except Exception:
        return 0.0


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
