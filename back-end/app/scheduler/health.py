"""Scheduled-job health (migration 030 job_runs): last start, success and
error per job, an alert to the owner after repeated failures, and catching up
daily runs missed while the server was down or the Mac was asleep.

  tracked(job_id)      decorator for a job coroutine. A job that catches its
                       own errors reports them with fail(job_id, error).
  GET /admin/jobs      owner report (app/api/v1/admin_usage.py)
  catch_up()           startup: runs a daily job whose last scheduled time
                       passed without a success (same New York day for the
                       market-close jobs; the monthly recap within 7 days).

Minute-level jobs are kept in memory only; daily jobs are also written to
job_runs so the history survives restarts. Before migration 030 everything
stays in memory.
"""

from __future__ import annotations

import functools
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from loguru import logger

ET = ZoneInfo("America/New_York")
ALERT_AFTER_FAILURES = 2
# daily jobs worth catching up: job_id -> (hour, minute, weekdays only?, same-day only?)
DAILY = {
    "cleanup_expired_tokens": (2, 0, False, False),
    "suggestions_nightly": (3, 0, False, False),
    "portfolio_snapshots": (16, 30, True, True),
    "holding_status_refresh": (17, 45, True, True),
    "income_forecast_snapshots": (18, 0, True, True),
    "check_status_snapshots": (18, 15, True, True),
}
MONTHLY = {"monthly_recap_push": (1, 9, 5)}   # day, hour, minute
_state: dict[str, dict] = {}
_pending_error: dict[str, str] = {}


def fail(job_id: str, error: BaseException | str) -> None:
    """A job that handles its own exception reports it here (the run counts as failed)."""
    _pending_error[job_id] = (f"{type(error).__name__}: {error}" if isinstance(error, BaseException)
                              else str(error))[:500]


def tracked(job_id: str):
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            started = datetime.now(timezone.utc)
            _pending_error.pop(job_id, None)
            try:
                result = await fn(*args, **kwargs)
            except Exception as e:   # jobs normally catch their own; this is the safety net
                logger.exception(f"Job {job_id} crashed")
                fail(job_id, e)
                result = None
            await _record(job_id, started, _pending_error.pop(job_id, None))
            return result
        wrapper.job_id = job_id
        return wrapper
    return deco


async def _record(job_id: str, started: datetime, error: str | None) -> None:
    from app.core.executors import in_job_pool
    s = _state.setdefault(job_id, {"job_id": job_id, "failures": 0})
    s["last_started_at"] = started.isoformat()
    now = datetime.now(timezone.utc).isoformat()
    if error:
        s.update(last_error=error, last_error_at=now, failures=s.get("failures", 0) + 1)
        if s["failures"] == ALERT_AFTER_FAILURES:
            await _alert_owner(job_id, error)
    else:
        s.update(last_success_at=now, failures=0)
    if job_id in DAILY or job_id in MONTHLY or error:
        try:
            await in_job_pool(_save, dict(s))
        except Exception as e:
            logger.debug(f"job_runs not written ({type(e).__name__})")


def _save(row: dict) -> None:
    from app.db.supabase import get_client
    get_client().table("job_runs").upsert(row, on_conflict="job_id").execute()


async def _alert_owner(job_id: str, error: str) -> None:
    """Telegram (and push) to the owner. Never raises."""
    text = f"Signa: job {job_id} failed {ALERT_AFTER_FAILURES} times in a row. Last error: {error[:200]}"
    logger.error(text)
    try:
        from app.core.executors import in_job_pool
        from app.db.supabase import get_client
        owners = await in_job_pool(lambda: get_client().table("users").select("id, telegram_chat_id")
                                   .eq("access_level", "owner").execute().data or [])
        from app.notifications.telegram_bot import enqueue
        from app.services import push
        for o in owners:
            if o.get("telegram_chat_id"):
                enqueue(str(o["telegram_chat_id"]), text, parse_mode="", urgent=True)
            await push.notify_user(str(o["id"]), "Signa server", f"Job {job_id} is failing", {"kind": "job_alert"})
    except Exception as e:
        logger.warning(f"job alert not sent ({type(e).__name__})")


def report() -> list[dict]:
    """GET /admin/jobs: the database rows merged with this process's memory."""
    rows: dict[str, dict] = {}
    try:
        from app.db.supabase import get_client
        rows = {r["job_id"]: r for r in get_client().table("job_runs").select("*").execute().data or []}
    except Exception:
        pass
    for k, v in _state.items():
        rows[k] = {**rows.get(k, {}), **v}
    return sorted(rows.values(), key=lambda r: (-(r.get("failures") or 0), r["job_id"]))


# ---------------------------------------------------------------- catch-up

def last_due(job_id: str, now: datetime) -> datetime | None:
    """The most recent scheduled time at or before `now` (New York). Pure."""
    local = now.astimezone(ET)
    if job_id in DAILY:
        h, m, weekdays, _same = DAILY[job_id]
        for back in range(0, 8):
            d = local.date() - timedelta(days=back)
            if weekdays and d.weekday() >= 5:
                continue
            due = datetime.combine(d, time(h, m), tzinfo=ET)
            if due <= local:
                return due
        return None
    if job_id in MONTHLY:
        day, h, m = MONTHLY[job_id]
        due = datetime(local.year, local.month, day, h, m, tzinfo=ET)
        if due > local:
            prev = (date(local.year, local.month, 1) - timedelta(days=1))
            due = datetime(prev.year, prev.month, day, h, m, tzinfo=ET)
        return due
    return None


def overdue(job_id: str, last_success: datetime | None, now: datetime) -> bool:
    """Missed its last scheduled run and still worth running now. Pure."""
    due = last_due(job_id, now)
    if due is None or (last_success and last_success >= due):
        return False
    if job_id in DAILY:
        same_day = DAILY[job_id][3]
        if same_day:   # a market-close snapshot is only right on its own day
            return due.date() == now.astimezone(ET).date()
        return now - due < timedelta(hours=24)
    return now - due < timedelta(days=7)   # monthly recap: within the first week


async def catch_up(jobs: dict, now: datetime | None = None) -> list[str]:
    """Run overdue daily/monthly jobs once at startup. `jobs`: job_id -> coroutine function."""
    from app.core.executors import in_job_pool
    now = now or datetime.now(timezone.utc)
    try:
        from app.db.supabase import get_client
        rows = await in_job_pool(lambda: get_client().table("job_runs").select("job_id, last_success_at")
                                 .execute().data or [])
    except Exception:
        return []   # before migration 030: no history to compare with
    last = {r["job_id"]: r.get("last_success_at") for r in rows}
    ran = []
    for job_id, fn in jobs.items():
        ls = last.get(job_id)
        try:
            ls_dt = datetime.fromisoformat(str(ls).replace("Z", "+00:00")) if ls else None
        except ValueError:
            ls_dt = None
        if ls_dt is None and job_id not in last:
            continue   # never ran on this database yet: nothing to catch up
        if overdue(job_id, ls_dt, now):
            logger.info(f"Catching up missed job {job_id}")
            await fn()
            ran.append(job_id)
    return ran
