"""Check a stock — on-demand live analysis of ONE symbol (no trade, no DB rows).

  POST /api/v1/check           {ticker, force?, mode?} -> {job_id, status, ...}
  GET  /api/v1/check/{job_id}  -> progress; `result` when status == "done"
  POST /api/v1/check/compare   {tickers: [2..3], mode?, force?} -> {compare_id, ...}
  GET  /api/v1/check/compare/{compare_id}
                               -> per-symbol progress; results + comparison
                                  + summary when status == "done"

Compare: every ticker is resolved up front (unknown / duplicate after
resolution -> 4xx before anything runs). Each symbol then runs as a normal
check through the same per-symbol result cache: a cached result counts
nothing, every non-cached run counts one toward the shared daily limit
(checked for the whole set before starting). Runs queue inside the compare
job so the total never exceeds settings.stock_check_max_concurrent. When all
finish: services/stock_compare.py builds the comparison block and one AI
summary (deterministic ranking if the AI is unavailable).

Jobs run as asyncio background tasks in an in-memory registry (single
worker, like the scan progress state) and expire after
settings.stock_check_job_ttl_minutes. Results are cached per RESOLVED
symbol AND mode for settings.stock_check_cache_minutes (mode "short") or
settings.stock_check_long_cache_hours (mode "long"); a repeat check returns
the cached result immediately (`cached: true`) unless force=true.

mode: "short" (default) = is the next days/weeks a good swing entry
(services/stock_check.py); "long" = is this a sound long-term holding
(services/long_term_check.py). Both share the daily limit.

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
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.services import long_term_check, stock_check, stock_compare

router = APIRouter(prefix="/check", tags=["Check"])

ET = ZoneInfo("America/New_York")
_JOB_ID = re.compile(r"^[a-f0-9]{32}$")


class CompareRequest(BaseModel):
    tickers: list[str] = Field(..., max_length=10)
    force: bool = False
    mode: Literal["short", "long"] = "short"


class CheckRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=24)
    force: bool = False
    mode: Literal["short", "long"] = "short"


@dataclass
class Job:
    id: str
    input: str
    force: bool
    mode: str = "short"
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
            "mode": self.mode,
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
_results: dict[str, tuple[float, dict]] = {}   # cache key (symbol[|long]) -> (stored_at, result)
_alias: dict[str, str] = {}                     # normalized input -> resolved symbol
_daily: dict[str, object] = {"date": None, "count": 0}
_compares: dict[str, "CompareJob"] = {}


def _reset_state() -> None:
    """Test helper: drop every job, cached result and counter."""
    for j in _jobs.values():
        if j.task and not j.task.done():
            j.task.cancel()
    _jobs.clear()
    for c in _compares.values():
        if c.task and not c.task.done():
            c.task.cancel()
    _compares.clear()
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


def _cache_key(symbol: str, mode: str = "short") -> str:
    """Short-mode results keep the bare symbol key; long mode is suffixed."""
    return symbol if mode == "short" else f"{symbol}|{mode}"


def _cache_ttl_s(key: str) -> float:
    if key.endswith("|long"):
        return settings.stock_check_long_cache_hours * 3600
    return settings.stock_check_cache_minutes * 60


def _purge() -> None:
    ttl = settings.stock_check_job_ttl_minutes * 60
    cutoff = time.time() - ttl
    for jid in [j.id for j in _jobs.values() if j.created < cutoff]:
        job = _jobs.pop(jid)
        if job.task and not job.task.done():
            job.task.cancel()
    for cid in [c.id for c in _compares.values() if c.created < cutoff]:
        comp = _compares.pop(cid)
        if comp.task and not comp.task.done():
            comp.task.cancel()
    for key in [k for k, (at, _) in _results.items() if time.time() - at > _cache_ttl_s(k)]:
        _results.pop(key, None)


def _cached_result(symbol: str | None, mode: str = "short") -> dict | None:
    if not symbol:
        return None
    key = _cache_key(symbol, mode)
    ttl = _cache_ttl_s(key)
    if ttl <= 0:
        return None
    entry = _results.get(key)
    if not entry:
        return None
    at, result = entry
    if time.time() - at > ttl:
        _results.pop(key, None)
        return None
    return {**result, "cached": True}


def _running() -> int:
    """Checks running now: single jobs + compare items holding a slot."""
    return (sum(1 for j in _jobs.values() if j.status == "running")
            + sum(1 for c in _compares.values() for it in c.items if it.status == "running"))


def _err(code: str, message: str, http: int, **extra) -> HTTPException:
    return HTTPException(status_code=http, detail={"code": code, "message": message, **extra})


async def _run(job: Job) -> None:
    try:
        job.progress("resolving", 3)
        resolved = await stock_check.resolve_symbol(job.input)
        job.symbol = resolved["symbol"]
        _alias[job.input] = resolved["symbol"]
        if not job.force:
            cached = _cached_result(job.symbol, job.mode)
            if cached is not None:
                _refund(job)
                job.result = cached
                job.status = "done"
                job.progress("done", 100)
                return
        if job.mode == "long":
            job.progress("history", 6)
            result = await long_term_check.run_long_check(resolved, progress=job.progress)
        else:
            job.progress("market_data", 6)
            result = await stock_check.run_check(resolved, progress=job.progress)
        result = {**result, "cached": False}
        _results[_cache_key(job.symbol, job.mode)] = (time.time(), result)
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
        cached = _cached_result(_alias.get(sym) or sym, body.mode)
        if cached is not None:
            job = Job(id=uuid.uuid4().hex, input=sym, force=False, mode=body.mode, status="done",
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

    job = Job(id=uuid.uuid4().hex, input=sym, force=body.force, mode=body.mode, counted=True)
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


# ============================================================
# Compare 2-3 symbols
# ============================================================

COMPARE_MIN, COMPARE_MAX = 2, 3
_QUEUE_POLL_S = 0.2


@dataclass
class CompareJob:
    id: str
    mode: str
    force: bool
    items: list[Job]
    status: str = "running"          # running | done
    phase: str = "checking"          # checking | summarizing | done
    comparison: dict | None = None
    summary: dict | None = None
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    task: asyncio.Task | None = None

    def pct(self) -> int:
        if self.status == "done":
            return 100
        if self.phase == "summarizing":
            return 95
        return int(sum(it.pct for it in self.items) / max(1, len(self.items)) * 0.9)

    def public(self) -> dict:
        items = []
        for it in self.items:
            items.append({
                "input": it.input,
                "symbol": it.symbol,
                "status": it.status,          # queued | running | done | failed
                "phase": it.phase,
                "pct": it.pct,
                "cached": bool((it.result or {}).get("cached")) if it.status == "done" else None,
                "error": it.error if it.status == "failed" else None,
            })
        out = {
            "compare_id": self.id,
            "mode": self.mode,
            "status": self.status,
            "phase": self.phase,
            "pct": self.pct(),
            "symbols": [it.symbol for it in self.items],
            "items": items,
            "started_at": datetime.fromtimestamp(self.created, timezone.utc).isoformat(),
        }
        if self.status == "done":
            out["results"] = {it.symbol: it.result for it in self.items if it.status == "done" and it.result}
            out["comparison"] = self.comparison
            out["summary"] = self.summary
        return out


async def _run_compare_item(item: Job) -> None:
    """Wait for a free check slot (queue inside the compare), then run the
    normal single-check pipeline (cache, refund, errors all shared)."""
    cap = max(1, settings.stock_check_max_concurrent)
    while _running() >= cap:
        await asyncio.sleep(_QUEUE_POLL_S)
    item.status = "running"            # no await since the check: slot taken atomically
    item.progress("resolving", 3)
    await _run(item)


async def _run_compare(comp: CompareJob) -> None:
    try:
        await asyncio.gather(*(_run_compare_item(it) for it in comp.items if it.status == "queued"))
        comp.phase = "summarizing"
        comp.updated = time.time()
        ok = [it.result for it in comp.items if it.status == "done" and it.result]
        comp.comparison = stock_compare.build_comparison(comp.mode, ok)
        if len(ok) >= COMPARE_MIN:
            comp.summary = await stock_compare.summarize(comp.comparison)
        else:
            comp.summary = stock_compare.fallback_summary(comp.comparison, "not_enough_results")
    except asyncio.CancelledError:
        for it in comp.items:
            if it.status in ("queued", "running"):
                _refund(it)
                it.status = "failed"
                it.error = {"code": "cancelled", "message": "The check was cancelled.", "status": 499}
        raise
    except Exception:
        logger.exception(f"Compare {comp.id} failed")
        if comp.comparison is not None and comp.summary is None:
            comp.summary = stock_compare.fallback_summary(comp.comparison)
    finally:
        comp.status = "done"
        comp.phase = "done"
        comp.updated = time.time()


@router.post("/compare")
async def start_compare(body: CompareRequest, user: dict = Depends(get_current_user)):
    _purge()
    n = len(body.tickers)
    if n < COMPARE_MIN or n > COMPARE_MAX:
        raise _err("compare_count", f"Compare {COMPARE_MIN} or {COMPARE_MAX} tickers.",
                   status.HTTP_400_BAD_REQUEST, min=COMPARE_MIN, max=COMPARE_MAX)
    inputs: list[str] = []
    for raw in body.tickers:
        try:
            inputs.append(stock_check.normalize_input(raw))
        except stock_check.StockCheckError as e:
            raise _err(e.code, e.message, status.HTTP_400_BAD_REQUEST, input=str(raw)[:24])
    if len(set(inputs)) != len(inputs):
        raise _err("compare_duplicate", "Each ticker can appear only once.", status.HTTP_400_BAD_REQUEST,
                   symbols=sorted({s for s in inputs if inputs.count(s) > 1}))

    resolved = await asyncio.gather(*(stock_check.resolve_symbol(s) for s in inputs), return_exceptions=True)
    unknown = [inputs[i] for i, r in enumerate(resolved)
               if isinstance(r, stock_check.StockCheckError) and r.code in ("not_found", "invalid_ticker")]
    if unknown:
        raise _err("compare_unknown", f"No recent price data for {', '.join(unknown)}.",
                   status.HTTP_404_NOT_FOUND, inputs=unknown)
    for r in resolved:
        if isinstance(r, BaseException):
            logger.warning(f"compare: resolve failed: {r}")
            raise _err("resolve_failed", "Could not look up one of the tickers — please try again.",
                       status.HTTP_502_BAD_GATEWAY)
    symbols = [r["symbol"] for r in resolved]  # type: ignore[index]
    if len(set(symbols)) != len(symbols):
        dup = sorted({s for s in symbols if symbols.count(s) > 1})
        raise _err("compare_duplicate", f"These tickers are the same listing: {', '.join(dup)}.",
                   status.HTTP_400_BAD_REQUEST, symbols=dup,
                   inputs=[i for i, s in zip(inputs, symbols) if s in dup])

    items: list[Job] = []
    for inp, sym in zip(inputs, symbols):
        _alias[inp] = sym
        cached = None if body.force else _cached_result(sym, body.mode)
        if cached is not None:
            items.append(Job(id=uuid.uuid4().hex, input=inp, force=False, mode=body.mode, status="done",
                             phase="done", pct=100, symbol=sym, result=cached))
        else:
            items.append(Job(id=uuid.uuid4().hex, input=inp, force=body.force, mode=body.mode,
                             status="queued", phase="queued", pct=0, symbol=sym))

    needed = sum(1 for it in items if it.status == "queued")
    limit = settings.stock_check_daily_limit
    used = _daily_count()
    if needed and used + needed > limit:
        raise _err("daily_limit",
                   f"This comparison needs {needed} new check(s) but only {max(0, limit - used)} remain today "
                   f"(limit {limit}) — resets at midnight ET.",
                   status.HTTP_429_TOO_MANY_REQUESTS, limit=limit, needed=needed,
                   remaining=max(0, limit - used), resets_at=_next_reset_iso())
    for it in items:
        if it.status == "queued":
            it.counted = True
            _consume()

    comp = CompareJob(id=uuid.uuid4().hex, mode=body.mode, force=body.force, items=items)
    _compares[comp.id] = comp
    comp.task = asyncio.create_task(_run_compare(comp))
    return {**comp.public(), "remaining_today": max(0, limit - _daily_count())}


@router.get("/compare/{compare_id}")
async def get_compare(compare_id: str, user: dict = Depends(get_current_user)):
    _purge()
    comp = _compares.get(compare_id) if _JOB_ID.match(compare_id or "") else None
    if comp is None:
        raise _err("compare_not_found", "This comparison expired or does not exist — start a new one.",
                   status.HTTP_404_NOT_FOUND)
    return comp.public()
