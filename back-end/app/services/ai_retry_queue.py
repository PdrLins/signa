"""AI retry queue — gives transient AI failures a second chance.

============================================================
WHAT THIS MODULE IS
============================================================

When the AI synthesis pipeline fails for a ticker, that ticker's signal
gets `ai_status = "failed"` and the brain refuses to act on it (per the
tier model in `virtual_portfolio.py`). The brain will only consider
auto-buying this ticker after AI has successfully run.

But what if the failure was transient — a CLI timeout, a brief API
outage, all providers having a bad minute? Without this module, that
ticker's good signal is LOST until the next scheduled scan, which
might be hours away. By then the entry might be gone.

This module is a tiny persistence layer that remembers failed-AI
tickers between scans and asks the next scan to retry them. It's
the difference between "one bad minute kills the day's signals"
and "one bad minute delays the signals by 90 minutes".

============================================================
HOW IT WORKS
============================================================

  1. PASS 2 in `scan_service` runs AI synthesis for each candidate.
     If the result has `error` set (all providers failed), it calls
     `record_failure(ticker, error)`.

  2. `record_failure` either inserts a new row (failure_count=1) or
     increments an existing row's failure_count by 1. When
     failure_count reaches MAX_FAILURE_COUNT (5), the row is DELETED
     — at that point we give up, this ticker is probably permanently
     broken (delisted, ticker change, etc.).

  3. On the NEXT scan, `scan_service` calls `get_retry_tickers(limit=5)`
     BEFORE building the AI candidate list. The returned tickers are
     PREPENDED to the candidates, jumping the queue ahead of the
     normal top-15 selection.

  4. If the retry succeeds (any ai_status other than "failed"),
     `clear_success(ticker)` removes the row from the queue.

  5. Stale entries (older than RETRY_STALE_HOURS = 24) are cleaned
     up at the start of each scan via `cleanup_stale()`.

============================================================
CONCURRENCY SAFETY
============================================================

`record_failure` does SELECT-then-UPDATE/INSERT, which is not atomic.
Two concurrent failures for the same ticker could race. The DB has a
UNIQUE constraint on `symbol`, so the second INSERT would fail with
a constraint violation; we catch that and retry as an UPDATE. In
practice scans are serial so this almost never happens, but the
guard exists for safety.

============================================================
WHAT THIS DOES NOT DO
============================================================

This is NOT a general-purpose job queue. It's purpose-built for the
AI failure case:
  • No priorities (just oldest-first ordering)
  • No backoff timing (the next scan is the next attempt)
  • No worker pools (the scan service is the only consumer)
  • Auto-drops after 5 attempts (no exponential expiry curves)

If you need anything more sophisticated, build a separate module
rather than extending this one.
"""

from datetime import datetime, timedelta, timezone

from loguru import logger

from app.db.supabase import get_client


# After this many consecutive failures, drop the ticker from retries.
# It's likely a permanent issue (delisted, ticker change, broken data) — not
# something a retry will fix.
MAX_FAILURE_COUNT = 5

# Don't retry tickers older than this many hours. Stale retries waste budget.
RETRY_STALE_HOURS = 24


def record_failure(symbol: str, error: str = "") -> None:
    """Mark a ticker for retry on the next scan.

    If the ticker is already in the queue, increments failure_count.
    If failure_count exceeds MAX_FAILURE_COUNT, the row is deleted (give up).

    Concurrency: SELECT-then-UPDATE/INSERT is not atomic. Two concurrent
    failures for the same symbol could race. The UNIQUE constraint on `symbol`
    ensures at most one row exists; the second INSERT fails with constraint
    violation which we catch and retry as an UPDATE. Failures are rare enough
    in practice that this is acceptable without a full UPSERT.
    """
    if not symbol:
        return
    db = get_client()
    now_iso = datetime.now(timezone.utc).isoformat()
    truncated_error = (error or "")[:500]

    try:
        existing = (
            db.table("ai_retry_queue")
            .select("id, failure_count")
            .eq("symbol", symbol)
            .limit(1)
            .execute()
        )
        rows = existing.data or []
        if rows:
            current_count = rows[0].get("failure_count", 0) or 0
            new_count = current_count + 1
            if new_count >= MAX_FAILURE_COUNT:
                # Give up — too many failures
                db.table("ai_retry_queue").delete().eq("id", rows[0]["id"]).execute()
                logger.warning(
                    f"AI retry queue: dropping {symbol} after {new_count} failures "
                    f"(likely permanent issue)"
                )
                return
            db.table("ai_retry_queue").update({
                "failure_count": new_count,
                "last_failed_at": now_iso,
                "last_error": truncated_error,
            }).eq("id", rows[0]["id"]).execute()
            logger.info(f"AI retry queue: {symbol} failure_count={new_count}")
            return

        # Not in queue yet — try INSERT
        try:
            db.table("ai_retry_queue").insert({
                "symbol": symbol,
                "failure_count": 1,
                "last_failed_at": now_iso,
                "last_error": truncated_error,
            }).execute()
            logger.info(f"AI retry queue: added {symbol}")
        except Exception as insert_err:
            # Race: another worker inserted between our SELECT and INSERT.
            # Treat as UPDATE — fetch fresh row and increment.
            err_str = str(insert_err).lower()
            if "duplicate" in err_str or "unique" in err_str or "23505" in err_str:
                logger.debug(f"AI retry queue: race on {symbol}, retrying as update")
                fresh = (
                    db.table("ai_retry_queue")
                    .select("id, failure_count")
                    .eq("symbol", symbol)
                    .limit(1)
                    .execute()
                )
                fresh_rows = fresh.data or []
                if fresh_rows:
                    db.table("ai_retry_queue").update({
                        "failure_count": (fresh_rows[0].get("failure_count", 0) or 0) + 1,
                        "last_failed_at": now_iso,
                        "last_error": truncated_error,
                    }).eq("id", fresh_rows[0]["id"]).execute()
            else:
                raise
    except Exception as e:
        logger.warning(f"AI retry queue: failed to record {symbol}: {e}")


def get_retry_tickers(limit: int = 5) -> list[dict]:
    """Get tickers due for AI retry, ordered by oldest failure first.

    Returns up to `limit` tickers. Stale entries (> RETRY_STALE_HOURS) are
    excluded. Returns dicts with symbol, failure_count, last_failed_at.
    """
    db = get_client()
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=RETRY_STALE_HOURS)).isoformat()
        result = (
            db.table("ai_retry_queue")
            .select("symbol, failure_count, last_failed_at, last_error")
            .gte("last_failed_at", cutoff)
            .order("last_failed_at", desc=False)  # oldest first
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.warning(f"AI retry queue: failed to fetch retries: {e}")
        return []


def clear_success(symbol: str) -> None:
    """Remove a ticker from the retry queue after successful AI synthesis."""
    if not symbol:
        return
    db = get_client()
    try:
        db.table("ai_retry_queue").delete().eq("symbol", symbol).execute()
    except Exception as e:
        logger.debug(f"AI retry queue: failed to clear {symbol}: {e}")


def cleanup_stale() -> int:
    """Delete entries older than RETRY_STALE_HOURS. Returns count deleted."""
    db = get_client()
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=RETRY_STALE_HOURS)).isoformat()
        result = db.table("ai_retry_queue").delete().lt("last_failed_at", cutoff).execute()
        deleted = len(result.data or [])
        if deleted:
            logger.info(f"AI retry queue: cleaned up {deleted} stale entries")
        return deleted
    except Exception as e:
        logger.debug(f"AI retry queue: cleanup failed: {e}")
        return 0
