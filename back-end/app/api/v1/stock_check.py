"""Check a stock — on-demand live analysis of ONE symbol (no trade, no DB rows).

  POST /api/v1/check           {ticker, force?} -> {job_id, status, ...}
  GET  /api/v1/check/{job_id}  -> progress; `result` when status == "done"

Jobs run as asyncio background tasks in an in-memory registry (single
worker, like the scan progress state) and expire after
settings.stock_check_job_ttl_minutes. Results are cached per RESOLVED
symbol for settings.stock_check_cache_minutes; a repeat check returns the
cached result immediately (`cached: true`) unless force=true.

Limits: settings.stock_check_daily_limit non-cached runs per US-Eastern day
and settings.stock_check_max_concurrent runs at once. The POST is on the
STRICT rate-limit tier (app/middleware/rate_limit.py); polling the job is
exempt, like scan progress polling.

Protected (JWT via AuthMiddleware + get_current_user). Response shape:
front-end/src/types/check.ts.
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.services import stock_check

router = APIRouter(prefix="/check", tags=["Check"])

ET = ZoneInfo("America/New_York")
_JOB_ID = re.compile(r"^[a-f0-9]{32}$")


class CheckRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=24)
    force: bool = False


@dataclass
class Job:
    id: str
    input: str
    force: bool
    status: str = "running"          # running | done | failed
    phase: str = "resolving"
    pct: int = 0
    symbol: str | None = None
    result: dict | None = None
    error: dict | None = None
    counted: bool = False            # consumed one of today's non-cached runs
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    task: asyncio.Task | None = None

    def progress(self, phase: str, pct: int) -> None:
        self.phase = phase
        self.pct = max(self.pct, min(100, int(pct)))
        self.updated = time.time()

    def public(self) -> dict:
        out = {
            "job_id": self.id,
            "input": self.input,
            "symbol": self.symbol,
            "status": self.status,
            "phase": self.phase,
            "pct": self.pct,
            "started_at": datetime.fromtimestamp(self.created, timezone.utc).isoformat(),
        }
        if self.status == "done":
            out["result"] = self.result
            out["cached"] = bool((self.result or {}).get("cached"))
        if self.status == "failed":
            out["error"] = self.error
        return out


# ── In-memory state (single-process) ──
_jobs: dict[str, Job] = {}
_results: dict[str, tuple[float, dict]] = {}   # resolved symbol -> (stored_at, result)
_alias: dict[str, str] = {}                     # normalized input -> resolved symbol
_daily: dict[str, object] = {"date": None, "count": 0}


def _reset_state() -> None:
    """Test helper: drop every job, cached result and counter."""
    for j in _jobs.values():
        if j.task and not j.task.done():
            j.task.cancel()
    _jobs.clear()
    _results.clear()
    _alias.clear()
    _daily.update({"date": None, "count": 0})


def _et_today() -> str:
    return datetime.now(ET).date().isoformat()


def _daily_count() -> int:
    today = _et_today()
    if _daily["date"] != today:
        _daily.update({"date": today, "count": 0})
    return int(_daily["count"])  # type: ignore[arg-type]


def _consume() -> None:
    _daily_count()
    _daily["count"] = int(_daily["count"]) + 1  # type: ignore[arg-type]


def _refund(job: Job) -> None:
    if job.counted:
        job.counted = False
        _daily["count"] = max(0, int(_daily["count"]) - 1)  # type: ignore[arg-type]


def _next_reset_iso() -> str:
    now = datetime.now(ET)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return tomorrow.isoformat()


def _purge() -> None:
    ttl = settings.stock_check_job_ttl_minutes * 60
    cutoff = time.time() - ttl
    for jid in [j.id for j in _jobs.values() if j.created < cutoff]:
        job = _jobs.pop(jid)
        if job.task and not job.task.done():
            job.task.cancel()
    cache_ttl = settings.stock_check_cache_minutes * 60
    for sym in [s for s, (at, _) in _results.items() if time.time() - at > cache_ttl]:
        _results.pop(sym, None)


def _cached_result(symbol: str | None) -> dict | None:
    if not symbol or settings.stock_check_cache_minutes <= 0:
        return None
    entry = _results.get(symbol)
    if not entry:
        return None
    at, result = entry
    if time.time() - at > settings.stock_check_cache_minutes * 60:
        _results.pop(symbol, None)
        return None
    return {**result, "cached": True}


def _running() -> int:
    return sum(1 for j in _jobs.values() if j.status == "running")


def _err(code: str, message: str, http: int, **extra) -> HTTPException:
    return HTTPException(status_code=http, detail={"code": code, "message": message, **extra})


async def _run(job: Job) -> None:
    try:
        job.progress("resolving", 3)
        resolved = await stock_check.resolve_symbol(job.input)
        job.symbol = resolved["symbol"]
        _alias[job.input] = resolved["symbol"]
        if not job.force:
            cached = _cached_result(job.symbol)
            if cached is not None:
                _refund(job)
                job.result = cached
                job.status = "done"
                job.progress("done", 100)
                return
        job.progress("market_data", 6)
        result = await stock_check.run_check(resolved, progress=job.progress)
        result = {**result, "cached": False}
        _results[job.symbol] = (time.time(), result)
        job.result = result
        job.status = "done"
        job.progress("done", 100)
    except asyncio.CancelledError:
        job.status = "failed"
        job.error = {"code": "cancelled", "message": "The check was cancelled.", "status": 499}
        raise
    except stock_check.StockCheckError as e:
        if e.code in ("not_found", "invalid_ticker"):
            _refund(job)   # nothing was analysed — doesn't count
        job.status = "failed"
        job.error = e.to_dict()
        job.updated = time.time()
    except Exception:
        logger.exception(f"Stock check failed for {job.input}")
        job.status = "failed"
        job.error = {"code": "internal", "message": "The check failed — please try again.", "status": 500}
        job.updated = time.time()


@router.post("")
async def start_check(body: CheckRequest, user: dict = Depends(get_current_user)):
    _purge()
    try:
        sym = stock_check.normalize_input(body.ticker)
    except stock_check.StockCheckError as e:
        raise _err(e.code, e.message, status.HTTP_400_BAD_REQUEST)

    # Cache hit (by a previously resolved alias) — instant, never counted.
    if not body.force:
        cached = _cached_result(_alias.get(sym) or sym)
        if cached is not None:
            job = Job(id=uuid.uuid4().hex, input=sym, force=False, status="done",
                      phase="done", pct=100, symbol=cached.get("symbol"), result=cached)
            _jobs[job.id] = job
            return job.public()

    if _running() >= settings.stock_check_max_concurrent:
        raise _err("busy", f"{settings.stock_check_max_concurrent} checks are already running — "
                           "wait for one to finish.", status.HTTP_429_TOO_MANY_REQUESTS,
                   max_concurrent=settings.stock_check_max_concurrent)
    limit = settings.stock_check_daily_limit
    if _daily_count() >= limit:
        raise _err("daily_limit", f"Daily limit of {limit} checks reached — resets at midnight ET.",
                   status.HTTP_429_TOO_MANY_REQUESTS, limit=limit, resets_at=_next_reset_iso())

    job = Job(id=uuid.uuid4().hex, input=sym, force=body.force, counted=True)
    _consume()
    _jobs[job.id] = job
    job.task = asyncio.create_task(_run(job))
    return {**job.public(), "remaining_today": max(0, limit - _daily_count())}


@router.get("/{job_id}")
async def get_check(job_id: str, user: dict = Depends(get_current_user)):
    _purge()
    job = _jobs.get(job_id) if _JOB_ID.match(job_id or "") else None
    if job is None:
        raise _err("job_not_found", "This check expired or does not exist — start a new one.",
                   status.HTTP_404_NOT_FOUND)
    return job.public()
