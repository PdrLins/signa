"""My holdings — the owner's REAL long-term positions (migration 010).

  GET    /api/v1/holdings                   list + position math (CAD totals)
  POST   /api/v1/holdings/resolve           {text} -> parsed lines + candidate listings
  POST   /api/v1/holdings                   {items:[...]} bulk upsert (confirmed rows)
  PATCH  /api/v1/holdings/{id}              shares / avg_cost / account / notes
  DELETE /api/v1/holdings/{id}
  POST   /api/v1/holdings/refresh           run the monitor now for this user
  POST   /api/v1/holdings/review            {ids:[...]} | {all:true} -> background review job
  GET    /api/v1/holdings/review/current    the latest review job (or null)
  GET    /api/v1/holdings/review/{job_id}   review progress
  GET    /api/v1/holdings/allocate-ideas    ranked considerations for new cash

All routes are JWT-protected (AuthMiddleware + get_current_user) and scoped
to the caller's user_id. Tickers are validated (app.core.utils.validate_ticker);
no user input reaches a file path. Reviews reuse services/long_term_check.py
and the /check long-mode result cache, do NOT consume the /check daily
limit, and "review all" is allowed once per settings.holdings_review_all_days.
Before migration 010 is applied every route answers 503 holdings_unavailable.
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from pydantic import BaseModel, Field, field_validator

from app.core.access import require_feature
from app.services import slots
from app.core.config import settings
from app.core.dependencies import get_current_user
from app.core.utils import validate_ticker
from app.db import queries
from app.services import holdings_monitor as hm
from app.services import holdings_service as hs

router = APIRouter(prefix="/holdings", tags=["Holdings"])

_JOB_ID = re.compile(r"^[a-f0-9]{32}$")
JOB_TTL_S = 6 * 3600
Account = Literal["TFSA", "RRSP", "FHSA", "NON_REGISTERED", "OTHER"]
AssetType = Literal["STOCK", "ETF", "CRYPTO", "OTHER"]


# ============================================================
# Models
# ============================================================

def _ticker(v: str) -> str:
    s = (v or "").strip().upper()
    if not s or len(s) > 24 or not validate_ticker(s):
        raise ValueError("invalid ticker symbol")
    return s


class ResolveRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=hs.MAX_IMPORT_CHARS)


class HoldingIn(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=24)
    input_symbol: Optional[str] = Field(None, max_length=24)
    name: Optional[str] = Field(None, max_length=200)
    exchange: Optional[str] = Field(None, max_length=24)
    currency: Optional[str] = Field(None, pattern=r"^[A-Z]{3}$")
    asset_type: Optional[AssetType] = None
    shares: Optional[float] = Field(None, gt=0, lt=1e9)
    avg_cost: Optional[float] = Field(None, gt=0, lt=1e7)
    account: Optional[Account] = None
    notes: Optional[str] = Field(None, max_length=500)

    @field_validator("symbol")
    @classmethod
    def _v_symbol(cls, v: str) -> str:
        return _ticker(v)

    @field_validator("input_symbol")
    @classmethod
    def _v_input(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        s = v.strip().upper().lstrip("$")
        if not re.fullmatch(r"[A-Z0-9.\-]{1,24}", s):
            raise ValueError("invalid input symbol")
        return s


class UpsertRequest(BaseModel):
    items: list[HoldingIn] = Field(..., min_length=1, max_length=hs.MAX_IMPORT_LINES)


class HoldingPatch(BaseModel):
    shares: Optional[float] = Field(None, gt=0, lt=1e9)
    avg_cost: Optional[float] = Field(None, gt=0, lt=1e7)
    account: Optional[Account] = None
    notes: Optional[str] = Field(None, max_length=500)


class ReviewRequest(BaseModel):
    ids: Optional[list[UUID]] = Field(None, max_length=100)
    all: bool = False


# ============================================================
# Helpers
# ============================================================

def _err(code: str, message: str, http: int, **extra) -> HTTPException:
    return HTTPException(status_code=http, detail={"code": code, "message": message, **extra})


async def _db(fn, *args):
    """Run a blocking query; a missing table (migration 010) -> 503."""
    try:
        return await asyncio.to_thread(fn, *args)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"holdings: DB call {getattr(fn, '__name__', fn)} failed: {e}")
        raise _err("holdings_unavailable",
                   "Holdings storage is unavailable — apply migration 010_holdings.sql.",
                   status.HTTP_503_SERVICE_UNAVAILABLE)


async def _usdcad() -> float | None:
    from app.services.price_cache import get_usdcad_rate
    try:
        return await asyncio.to_thread(get_usdcad_rate)
    except Exception:
        return None


def _kick_refresh(user_id: str) -> bool:
    """Start a background monitor run for this user (no-op when one runs)."""
    if hm.is_running():
        return False
    asyncio.create_task(hm.run_holdings_monitor(user_id))
    return True


_review_all_mem: dict[str, str] = {}   # user_id -> iso (fallback when the column is missing)


async def _review_all_last(user_id: str) -> str | None:
    try:
        at = await asyncio.to_thread(queries.get_holdings_review_all_at, user_id)
    except Exception as e:
        logger.debug(f"holdings: review_all_at unavailable ({e})")
        at = None
    mem = _review_all_mem.get(user_id)
    if at and mem:
        return max(str(at), mem)
    return at or mem


async def _set_review_all(user_id: str, at_iso: str | None) -> None:
    if at_iso is None:
        _review_all_mem.pop(user_id, None)
    else:
        _review_all_mem[user_id] = at_iso
    try:
        await asyncio.to_thread(queries.set_holdings_review_all_at, user_id, at_iso)
    except Exception as e:
        logger.debug(f"holdings: could not persist review_all_at ({e})")


def _review_all_info(last_at: str | None) -> dict:
    allowed, nxt = hs.review_all_allowed(last_at)
    return {"last_at": last_at, "next_allowed_at": nxt, "allowed": allowed,
            "days": settings.holdings_review_all_days}


# ============================================================
# List / resolve / upsert / patch / delete
# ============================================================

@router.get("", dependencies=[Depends(require_feature("area.holdings"))])
async def list_holdings(user: dict = Depends(get_current_user)):
    rows = await _db(queries.get_holdings, user["user_id"])
    usdcad = await _usdcad()
    per, totals = hs.portfolio_math(rows, usdcad)
    items = [hs.public_holding(h, per.get(str(h.get("id")))) for h in rows]
    last_all = await _review_all_last(user["user_id"])
    return {
        "items": items,
        "count": len(items),
        "totals": totals,
        "monitor_running": hm.is_running(),
        "review_running": _active_job(user["user_id"]) is not None,
        "review_all": _review_all_info(last_all),
        "settings": {
            "max_weight_pct": settings.holdings_max_weight_pct,
            "alerts_enabled": settings.holdings_alerts_enabled,
            "review_max_ids": settings.holdings_review_max_ids,
        },
    }


@router.post("/resolve", dependencies=[Depends(require_feature("action.holdings.edit"))])
async def resolve_holdings(body: ResolveRequest, user: dict = Depends(get_current_user)):
    rows = hs.parse_holdings_text(body.text)
    if not rows:
        raise _err("nothing_to_import", "No tickers found in the text.", status.HTTP_400_BAD_REQUEST)
    try:
        existing = {h["symbol"] for h in await asyncio.to_thread(queries.get_holdings, user["user_id"])}
    except Exception:
        existing = set()
    lines = await hs.resolve_rows(rows, existing)
    counts = {k: sum(1 for x in lines if x["status"] == k) for k in ("ok", "ambiguous", "not_found", "invalid")}
    return {"lines": lines, "count": len(lines), "counts": counts}


@router.post("", dependencies=[Depends(require_feature("action.holdings.edit"))], status_code=status.HTTP_201_CREATED)
async def upsert_holdings(body: UpsertRequest, user: dict = Depends(get_current_user)):
    uid = user["user_id"]
    await slots.check_new_symbols_async(user, [it.symbol for it in body.items])
    existing = {h["symbol"]: h for h in await _db(queries.get_holdings, uid)}
    merged: dict[str, dict] = {}
    for it in body.items:
        prev = existing.get(it.symbol) or merged.get(it.symbol) or {}
        pick = lambda k, v: v if v is not None else prev.get(k)  # noqa: E731 — never wipe known values
        merged[it.symbol] = {
            "symbol": it.symbol,
            "input_symbol": pick("input_symbol", it.input_symbol),
            "name": pick("name", it.name),
            "exchange": pick("exchange", it.exchange),
            "currency": it.currency or prev.get("currency") or hs.holding_currency({"symbol": it.symbol}),
            "asset_type": pick("asset_type", it.asset_type),
            "shares": pick("shares", it.shares),
            "avg_cost": pick("avg_cost", it.avg_cost),
            "account": pick("account", it.account),
            "notes": pick("notes", it.notes),
        }
    saved = await _db(queries.upsert_holdings, uid, list(merged.values()))
    created = sum(1 for s in merged if s not in existing)
    refreshing = _kick_refresh(uid)
    return {"items": [hs.public_holding(h, None) for h in saved], "count": len(saved),
            "created": created, "updated": len(merged) - created, "refreshing": refreshing}


@router.patch("/{holding_id}", dependencies=[Depends(require_feature("action.holdings.edit"))])
async def patch_holding(holding_id: UUID, body: HoldingPatch, user: dict = Depends(get_current_user)):
    data = {k: getattr(body, k) for k in body.model_fields_set}
    if not data:
        raise _err("nothing_to_update", "No fields to update.", status.HTTP_400_BAD_REQUEST)
    item = await _db(queries.update_holding, str(holding_id), user["user_id"], data)
    if not item:
        raise _err("not_found", "Holding not found.", status.HTTP_404_NOT_FOUND)
    return hs.public_holding(item, None)


@router.delete("/{holding_id}", dependencies=[Depends(require_feature("action.holdings.edit"))])
async def delete_holding(holding_id: UUID, user: dict = Depends(get_current_user)):
    ok = await _db(queries.delete_holding, str(holding_id), user["user_id"])
    if not ok:
        raise _err("not_found", "Holding not found.", status.HTTP_404_NOT_FOUND)
    return {"message": "Holding deleted"}


@router.post("/refresh", dependencies=[Depends(require_feature("action.holdings.refresh"))], status_code=status.HTTP_202_ACCEPTED)
async def refresh_holdings(user: dict = Depends(get_current_user)):
    started = _kick_refresh(user["user_id"])
    return {"status": "started" if started else "running"}


# ============================================================
# Long-term reviews (background, sequential)
# ============================================================

@dataclass
class ReviewJob:
    id: str
    user_id: str
    mode: str                         # "all" | "selected"
    holding_ids: list[str]
    status: str = "running"           # running | done | failed
    total: int = 0
    done: int = 0
    current: str | None = None
    results: list[dict] = field(default_factory=list)
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    prev_review_all_at: str | None = None
    task: asyncio.Task | None = None

    def public(self) -> dict:
        return {
            "job_id": self.id, "mode": self.mode, "status": self.status, "total": self.total,
            "done": self.done, "current": self.current,
            "pct": int(self.done / self.total * 100) if self.total else 100,
            "results": self.results,
            "started_at": datetime.fromtimestamp(self.created, timezone.utc).isoformat(),
        }


_jobs: dict[str, ReviewJob] = {}


def _reset_state() -> None:
    """Test helper."""
    for j in _jobs.values():
        if j.task and not j.task.done():
            j.task.cancel()
    _jobs.clear()
    _review_all_mem.clear()


def _purge() -> None:
    cutoff = time.time() - JOB_TTL_S
    for jid in [j.id for j in _jobs.values() if j.created < cutoff and j.status != "running"]:
        _jobs.pop(jid, None)


def _active_job(user_id: str | None = None) -> ReviewJob | None:
    for j in _jobs.values():
        if j.status == "running" and (user_id is None or j.user_id == user_id):
            return j
    return None


async def _review_one(h: dict) -> dict:
    """Long-term check for one holding, reusing /check's long-mode cache."""
    from app.api.v1 import stock_check as check_api
    from app.services import long_term_check

    sym = h["symbol"]
    cached = check_api._cached_result(sym, "long")
    if cached is not None:
        return cached
    resolved = {"input": h.get("input_symbol") or sym, "symbol": sym, "exchange": h.get("exchange"),
                "price": (h.get("holding_status") or {}).get("price")}
    result = await long_term_check.run_long_check(resolved)
    check_api._results[check_api._cache_key(sym, "long")] = (time.time(), {**result, "cached": False})
    return result


async def _run_review(job: ReviewJob, holdings: list[dict]) -> None:
    from app.services.stock_check import StockCheckError

    ok = 0
    try:
        for h in holdings:
            job.current = h["symbol"]
            job.updated = time.time()
            entry: dict = {"id": str(h["id"]), "symbol": h["symbol"]}
            try:
                result = await _review_one(h)
                summary = hs.review_summary(result)
                now_iso = datetime.now(timezone.utc).isoformat()
                await asyncio.to_thread(queries.update_holding, str(h["id"]), job.user_id,
                                        {"last_review": summary, "last_reviewed_at": now_iso})
                entry.update({"verdict": summary.get("verdict"), "cached": bool(result.get("cached"))})
                ok += 1
            except StockCheckError as e:
                entry["error"] = e.code
            except Exception as e:
                logger.warning(f"holdings review: {h['symbol']} failed: {e}")
                entry["error"] = "internal"
            job.results.append(entry)
            job.done += 1
            job.updated = time.time()
        job.status = "done"
    except asyncio.CancelledError:
        job.status = "failed"
        raise
    finally:
        job.current = None
        if job.mode == "all" and ok == 0:
            await _set_review_all(job.user_id, job.prev_review_all_at)   # nothing reviewed: don't count


@router.post("/review", dependencies=[Depends(require_feature("action.holdings.review"))], status_code=status.HTTP_202_ACCEPTED)
async def start_review(body: ReviewRequest, user: dict = Depends(get_current_user)):
    _purge()
    uid = user["user_id"]
    if _active_job() is not None:
        raise _err("busy", "A review is already running — wait for it to finish.", status.HTTP_409_CONFLICT)
    rows = await _db(queries.get_holdings, uid)
    prev_all = None
    if body.all:
        prev_all = await _review_all_last(uid)
        allowed, nxt = hs.review_all_allowed(prev_all)
        if not allowed:
            raise _err("review_all_limit",
                       f"Review all is available once every {settings.holdings_review_all_days} days.",
                       status.HTTP_429_TOO_MANY_REQUESTS, next_allowed_at=nxt,
                       days=settings.holdings_review_all_days)
        targets = rows
    else:
        ids = [str(i) for i in (body.ids or [])]
        if not ids:
            raise _err("nothing_to_review", "Choose at least one holding.", status.HTTP_400_BAD_REQUEST)
        if len(ids) > settings.holdings_review_max_ids:
            raise _err("too_many", f"Review at most {settings.holdings_review_max_ids} holdings at once "
                                   "(or use Review all).", status.HTTP_400_BAD_REQUEST,
                       max=settings.holdings_review_max_ids)
        wanted = set(ids)
        targets = [h for h in rows if str(h.get("id")) in wanted]
        if not targets:
            raise _err("not_found", "Holding not found.", status.HTTP_404_NOT_FOUND)
    if not targets:
        raise _err("nothing_to_review", "You have no holdings yet.", status.HTTP_400_BAD_REQUEST)

    job = ReviewJob(id=uuid.uuid4().hex, user_id=uid, mode="all" if body.all else "selected",
                    holding_ids=[str(h["id"]) for h in targets], total=len(targets),
                    prev_review_all_at=prev_all)
    if body.all:
        await _set_review_all(uid, datetime.now(timezone.utc).isoformat())
    _jobs[job.id] = job
    job.task = asyncio.create_task(_run_review(job, targets))
    return job.public()


@router.get("/review/current", dependencies=[Depends(require_feature("action.holdings.review"))])
async def current_review(user: dict = Depends(get_current_user)):
    _purge()
    mine = [j for j in _jobs.values() if j.user_id == user["user_id"]]
    if not mine:
        return {"job": None}
    return {"job": max(mine, key=lambda j: j.created).public()}


@router.get("/review/{job_id}", dependencies=[Depends(require_feature("action.holdings.review"))])
async def get_review(job_id: str, user: dict = Depends(get_current_user)):
    job = _jobs.get(job_id) if _JOB_ID.match(job_id or "") else None
    if job is None or job.user_id != user["user_id"]:
        raise _err("job_not_found", "This review expired or does not exist.", status.HTTP_404_NOT_FOUND)
    return job.public()


# ============================================================
# "Where could new cash go?"
# ============================================================

@router.get("/allocate-ideas", dependencies=[Depends(require_feature("action.holdings.allocate"))])
async def allocate_ideas(
    include_watchlist: bool = Query(False),
    user: dict = Depends(get_current_user),
):
    uid = user["user_id"]
    rows = await _db(queries.get_holdings, uid)
    usdcad = await _usdcad()
    per, _totals = hs.portfolio_math(rows, usdcad)
    extra: list[dict] = []
    if include_watchlist:
        extra = await _watchlist_rows(uid, {h["symbol"] for h in rows})
    out = hs.allocate_ideas(rows, per, extra)
    out["count_with_shares"] = _totals["count_with_shares"]
    return out


async def _watchlist_rows(user_id: str, held: set[str]) -> list[dict]:
    from app.api.v1 import stock_check as check_api

    try:
        wl = await asyncio.to_thread(queries.get_watchlist, user_id)
    except Exception:
        return []
    syms = [str(w.get("symbol") or "").upper() for w in wl]
    syms = [s for s in dict.fromkeys(syms) if s and validate_ticker(s) and s not in held][:15]
    if not syms:
        return []
    closes = await asyncio.to_thread(hm.fetch_closes, syms)
    rows = []
    for s in syms:
        cached = check_api._cached_result(s, "long")
        rows.append({
            "id": None, "symbol": s, "name": (cached or {}).get("name"), "_source": "watchlist",
            "holding_status": hm.compute_price_status(closes.get(s)) if closes.get(s) is not None else {},
            "last_review": hs.review_summary(cached) if cached else None,
        })
    return rows
