"""Signal service — CRUD operations and status management."""

from typing import Optional

from app.core.cache import TTLCache
from app.db import queries
from app.services.price_cache import enrich_signals
from app.services.signal_breakdown import compute_signal_breakdown

_track_record_cache = TTLCache(max_size=1, default_ttl=900)


def invalidate_track_record_cache() -> None:
    """Bust the track record cache. Called whenever a brain/watchlist trade
    closes so the dashboard reflects the new state immediately instead of
    waiting up to 15 minutes for the TTL to expire.

    Without this, a brain trade closing at 13:06 ET would not appear in the
    Track Record by Score table until ~14:06 ET (the cache TTL), which is
    confusing because the dashboard's Brain Performance card already shows
    the new total. The two displays drift out of sync until cache expiry.
    """
    _track_record_cache.clear()


def get_signals(
    bucket: Optional[str] = None,
    action: Optional[str] = None,
    status: Optional[str] = None,
    period: Optional[str] = None,
    min_score: int = 0,
    limit: int = 50,
    gems_only: bool = False,
) -> list[dict]:
    """Get latest signals with optional filters."""
    signals = queries.get_signals(
        bucket=bucket,
        action=action,
        status=status,
        period=period,
        min_score=min_score,
        limit=limit,
        gems_only=gems_only,
    )
    return enrich_signals(signals)


def get_signals_by_ticker(symbol: str, limit: int = 20) -> list[dict]:
    """Get signal history for a specific ticker.

    The detail page consumes this. Each signal is enriched with a
    `breakdown` field — a list of plain-English rule rows derived from
    the signal's technical_data, fundamental_data, and grok_data. See
    `signal_breakdown.compute_signal_breakdown` for the rule set.
    Pure derivation, no extra DB queries, no AI cost.
    """
    signals = queries.get_signals_by_ticker(symbol, limit)
    enriched = enrich_signals(signals)
    for sig in enriched:
        sig["breakdown"] = compute_signal_breakdown(sig)
    return enriched


def get_gem_signals(limit: int = 20) -> list[dict]:
    """Get only GEM alerts."""
    signals = queries.get_signals(gems_only=True, limit=limit)
    return enrich_signals(signals)


def get_track_record() -> dict:
    """Historical signal track record — win rates by score range, segmented by source.

    Computed from virtual_trades (closed positions with known outcomes).
    Cached for 1 hour since closed trades rarely change.
    """
    cached = _track_record_cache.get("track_record")
    if cached is not None:
        return cached

    from app.db.supabase import get_client
    db = get_client()

    closed = (
        db.table("virtual_trades")
        .select("entry_score, bucket, pnl_pct, is_win, source")
        .eq("status", "CLOSED")
        .limit(5000)
        .execute()
    )
    trades = closed.data or []

    if not trades:
        return {"ranges": [], "by_source": {}, "total_trades": 0, "overall_win_rate": 0}

    score_ranges = [
        {"label": "75+", "min": 75, "max": 101},
        {"label": "70-74", "min": 70, "max": 75},
        {"label": "65-69", "min": 65, "max": 70},
        {"label": "60-64", "min": 60, "max": 65},
        {"label": "<60", "min": 0, "max": 60},
    ]

    def _compute_ranges(trade_list: list[dict]) -> list[dict]:
        results = []
        for r in score_ranges:
            matched = [
                t for t in trade_list
                if r["min"] <= (t.get("entry_score") or 0) < r["max"]
            ]
            count = len(matched)
            if not count:
                results.append({"score_range": r["label"], "trades": 0, "win_rate": 0, "avg_return_pct": 0})
                continue
            wins = sum(1 for t in matched if t.get("is_win"))
            avg_ret = sum(t.get("pnl_pct", 0) for t in matched) / count
            results.append({
                "score_range": r["label"],
                "trades": count,
                "win_rate": round(wins / count * 100, 1),
                "avg_return_pct": round(avg_ret, 2),
            })
        return results

    total_wins = sum(1 for t in trades if t.get("is_win"))

    # Segment by source (brain vs watchlist)
    brain_trades = [t for t in trades if t.get("source") == "brain"]
    watchlist_trades = [t for t in trades if t.get("source") == "watchlist"]

    result = {
        "ranges": _compute_ranges(trades),
        "by_source": {
            "brain": {
                "ranges": _compute_ranges(brain_trades),
                "total_trades": len(brain_trades),
                "win_rate": round(sum(1 for t in brain_trades if t.get("is_win")) / len(brain_trades) * 100, 1) if brain_trades else 0,
            },
            "watchlist": {
                "ranges": _compute_ranges(watchlist_trades),
                "total_trades": len(watchlist_trades),
                "win_rate": round(sum(1 for t in watchlist_trades if t.get("is_win")) / len(watchlist_trades) * 100, 1) if watchlist_trades else 0,
            },
        },
        "total_trades": len(trades),
        "overall_win_rate": round(total_wins / len(trades) * 100, 1),
    }

    _track_record_cache.set("track_record", result)
    return result


def get_scans(limit: int = 20) -> list[dict]:
    """Get recent scan history."""
    return queries.get_scans(limit)
