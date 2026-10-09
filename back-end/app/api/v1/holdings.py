"""My holdings — the owner's REAL long-term positions (migration 010).

  GET    /api/v1/holdings                   list + position math (CAD totals)
                                            ?account_id=<uuid> | ?person_id=<uuid> filter
  GET    /api/v1/holdings/changes?range=1W  each holding's change over a chart range (same
                                            ranges, plan checks and scope params as
                                            /portfolio/performance)
  POST   /api/v1/holdings/resolve           {text} -> parsed lines + candidate listings
  POST   /api/v1/holdings                   {items:[...]} bulk upsert (confirmed rows)
  PATCH  /api/v1/holdings/{id}              shares / avg_cost / notes / account_id (move)
  DELETE /api/v1/holdings/{id}

All routes are JWT-protected (AuthMiddleware + get_current_user) and scoped
to the caller's user_id. Tickers are validated (app.core.utils.validate_ticker);
no user input reaches a file path. The AI review / refresh / allocate-ideas
routes moved to Signa Advisor; the list keeps "monitor_running",
"review_running" and "review_all" (always idle) for older clients.
Before migration 010 is applied every route answers 503 holdings_unavailable.

Accounts (migration 013): a holding belongs to one of the user's accounts
(account_id, null = no account) and the same symbol can be held in several
accounts; upserts are keyed on (account_id, symbol). Every item carries
"account_id" and "account_name" (null before 013). The legacy `account`
field (TFSA/RRSP/...) is still accepted for old clients but is deprecated
and no longer written. Slots count distinct symbols across all accounts +
the watchlist, so a second account holding the same stock needs no slot.
Using account_id before 013 -> 503 migration_required; an account that
isn't the user's -> 422 invalid_account; moving a holding into an account
that already holds that symbol -> 409 duplicate_holding.
"""

from __future__ import annotations

import asyncio
import re
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from pydantic import BaseModel, Field, field_validator

from app.core.access import require_feature
from app.core.api_errors import MigrationRequired, migration_required
from app.services import slots
from app.core.config import settings
from app.core.dependencies import get_current_user
from app.core.utils import validate_ticker
from app.core import user_cache
from app.db import queries
from app.services import holding_status
from app.services import holdings_service as hs

router = APIRouter(prefix="/holdings", tags=["Holdings"])

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
    account: Optional[Account] = None   # deprecated (013): accepted, not written
    account_id: Optional[UUID] = None
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
    account: Optional[Account] = None   # deprecated (013): accepted, not written
    account_id: Optional[UUID] = None
    notes: Optional[str] = Field(None, max_length=500)


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
    except MigrationRequired:
        raise migration_required()
    except Exception as e:
        logger.warning(f"holdings: DB call {getattr(fn, '__name__', fn)} failed: {e}")
        raise _err("holdings_unavailable",
                   "Holdings storage is unavailable — apply migration 010_holdings.sql.",
                   status.HTTP_503_SERVICE_UNAVAILABLE)


async def _accounts(user_id: str) -> list[dict] | None:
    """The user's accounts; None before migration 013 (no accounts table)."""
    try:
        return await asyncio.to_thread(user_cache.get, user_id, "accounts", lambda: queries.get_accounts(user_id))
    except Exception as e:
        logger.debug(f"holdings: accounts unavailable ({e})")
        return None


async def _check_account_ids(user_id: str, ids: set[str]) -> list[dict] | None:
    accounts = await _accounts(user_id)
    if ids and accounts is None:
        raise migration_required()
    known = {str(a["id"]) for a in accounts or []}
    bad = ids - known
    if bad:
        raise _err("invalid_account", "Account not found.", 422,
                   account_id=sorted(bad)[0])
    return accounts


def _with_account(item: dict, accounts: list[dict] | None) -> dict:
    aid = item.get("account_id")
    acct = next((a for a in accounts or [] if str(a.get("id")) == str(aid)), None) if aid else None
    return {**item, "account_id": str(aid) if aid else None, "account_name": (acct or {}).get("name"),
            "person_id": (acct or {}).get("person_id")}


async def _home_currency(user_id: str) -> str:
    try:
        from app.services import profile_service
        row = await asyncio.to_thread(user_cache.get, user_id, "settings",
                                      lambda: queries.get_profile_settings(user_id))
        return str(profile_service.merged_settings(row).get("home_currency") or "CAD").upper()
    except Exception as e:
        logger.debug(f"holdings: home currency unavailable ({e})")
        return "CAD"


async def _usdcad() -> float | None:
    from app.services.price_cache import get_usdcad_rate
    try:
        return await asyncio.to_thread(get_usdcad_rate)
    except Exception:
        return None


async def _live_quotes(rows: list[dict]) -> dict[str, dict]:
    """Shared live quotes for the holdings (quotes.get_quotes — the source of
    /portfolio/summary). Fails soft to {} (rows then use holding_status)."""
    from app.services import quotes as quotes_service
    syms = {str(h.get("symbol") or "").upper() for h in rows if h.get("symbol")}
    if not syms:
        return {}
    try:
        return await asyncio.to_thread(quotes_service.get_quotes, syms) or {}
    except Exception as e:
        logger.debug(f"holdings: live quotes unavailable ({e})")
        return {}


def _add_dividends(items: list[dict]) -> None:
    """item["dividend"] = {"yield_pct", "next_pay_date"} | None from the CACHED
    dividend profiles only (the list never waits on Yahoo); symbols not cached
    yet are fetched in the background and show on the next load."""
    from app.core.executors import spawn
    from app.services import dividends
    from app.services.dividend_calendar import _d, fetch_profiles, holding_dividend

    today = dividends.today_et()
    missing = []
    for it in items:
        sym = str(it.get("symbol") or "").upper()
        prof = dividends.cached_profile(sym)
        if prof is None and sym:
            missing.append(sym)
        it["dividend"] = holding_dividend(prof, _d(str(it.get("created_at") or "")[:10]), today)
    try:
        asyncio.get_running_loop()
    except RuntimeError:   # no running loop (tests calling the helper directly)
        return
    if missing:
        spawn(fetch_profiles(dict.fromkeys(missing)))


# ============================================================
# List / resolve / upsert / patch / delete
# ============================================================

@router.get("", dependencies=[Depends(require_feature("area.holdings"))])
async def list_holdings(
    account_id: Optional[UUID] = Query(None),
    person_id: Optional[UUID] = Query(None),
    user: dict = Depends(get_current_user),
):
    """Response: {"items": [Holding + "account_id", "account_name", "person_id", "quote"], "count",
    "totals", "monitor_running", "review_running", "review_all", "settings",
    (totals and position carry the user's home currency: totals.home_currency, value_home,
    book_value_home, unrealized_home, unrealized_pct_home; position.value_home; weights use
    home values. The *_cad fields stay for older clients.)
    "filter": {"account_id", "person_id"}}. Totals/weights cover the filtered items.

    Prices: each holding is valued at its shared live quote (quotes table,
    delayed ~15 min — the same price as /portfolio/summary, so totals.value_cad
    equals its market_value for the same scope when home currency is CAD),
    falling back to the monitor's last close (holding_status.price, still
    written by the monitor for its checks). Per item:
        "quote": {"price", "prev_close" | null, "change_pct" | null (PERCENT, today),
                "change" | null (native currency, price - prev_close), "as_of" (ISO),
                "live" (bool), "price_source": "quote" | "last_close",
                "ytd_pct_live" | null (PERCENT, price vs previous year's last close)}
               | null (unpriced)
      e.g. {"price": 32.1, "prev_close": 31.8, "change_pct": 0.9434, "change": 0.3,
            "as_of": "2026-10-02T14:45:00+00:00", "live": true, "price_source": "quote",
            "ytd_pct_live": 12.4}
    price_source "last_close" (no live quote): change / change_pct / prev_close
    are null — the day move is unknown, never yesterday's move shown as today's.
    position.value / value_cad / unrealized / weight_pct use quote.price;
    position.currency follows the quote's currency when there is one.
    position.weight_pct = this row (one account's lot); position.symbol_weight_pct
    = the symbol across all accounts in the filter; position.overweight uses
    symbol_weight_pct. totals.as_of = the oldest price time among priced rows."""
    uid = user["user_id"]
    # Independent reads at once; the rows come from the per-user cache Home also uses.
    rows, accounts, usdcad, home = await asyncio.gather(
        _db(user_cache.get, uid, "holdings", lambda: queries.get_holdings(uid)),
        _accounts(uid), _usdcad(), _home_currency(uid))
    if (account_id or person_id) and accounts is None:
        raise migration_required()
    if account_id:
        rows = [h for h in rows if str(h.get("account_id")) == str(account_id)]
    if person_id:
        mine = {str(a["id"]) for a in accounts or [] if str(a.get("person_id")) == str(person_id)}
        rows = [h for h in rows if str(h.get("account_id")) in mine]
    quotes = await _live_quotes(rows)
    per, totals = await asyncio.to_thread(hs.portfolio_math, rows, usdcad, quotes=quotes, home=home)
    items = [_with_account(hs.public_holding(h, per.get(str(h.get("id"))), hs.holding_quote(h, quotes),
                                             with_quote=True), accounts) for h in rows]
    _add_dividends(items)
    return {
        "items": items,
        "count": len(items),
        "totals": totals,
        "monitor_running": holding_status.is_running(),
        "review_running": False,
        "review_all": {"last_at": None, "next_allowed_at": None, "allowed": False,
                       "days": settings.holdings_review_all_days},
        "settings": {
            "max_weight_pct": settings.holdings_max_weight_pct,
            "alerts_enabled": settings.holdings_alerts_enabled,
            "review_max_ids": settings.holdings_review_max_ids,
        },
        "filter": {"account_id": str(account_id) if account_id else None,
                   "person_id": str(person_id) if person_id else None},
    }


@router.get("/changes", dependencies=[Depends(require_feature("area.holdings"))])
async def holding_changes(
    range: str = Query("1W"),
    account_id: Optional[UUID] = Query(None),
    person_id: Optional[UUID] = Query(None),
    user: dict = Depends(get_current_user),
):
    """Each holding's change over a chart range (math: portfolio_performance.holding_changes_body).
    {
      "range": "1W", "currency": "CAD" (home), "start": "2026-10-02" | null, "end": "2026-10-09",
      "items": [{"holding_id", "symbol", "account_id" | null, "currency" (the holding's),
                 "pct": 2.31 | null, "abs": 41.2 | null (holding currency), "abs_home": 41.2 | null,
                 "basis": "range" | "purchase",       # purchase = first buy inside the range (ALL: avg cost)
                 "since": "2026-10-02" | null}],      # the start date used
      "as_of", "delayed_minutes"
    }
    pct / abs are null without a price or a start price. Range 1D..ALL; 5Y / ALL need
    feature.full_history (403 upgrade_required). 422 invalid_range · 404 account_not_found |
    person_not_found."""
    from app.api.v1.portfolio_home import _check_range
    from app.core.api_errors import run_db
    from app.services import portfolio_context
    from app.services import portfolio_performance as perf

    rng = _check_range(user, range)
    scope = await run_db(portfolio_context.load_scope, user, str(account_id) if account_id else None,
                         str(person_id) if person_id else None)
    return await run_db(perf.holding_changes_body, scope, rng)


@router.post("/resolve", dependencies=[Depends(require_feature("action.holdings.edit"))])
async def resolve_holdings(body: ResolveRequest, user: dict = Depends(get_current_user)):
    rows = hs.parse_holdings_text(body.text)
    if not rows:
        raise _err("nothing_to_import", "No tickers found in the text.", status.HTTP_400_BAD_REQUEST)
    try:
        existing = {h["symbol"] for h in await asyncio.to_thread(queries.get_holdings, user["user_id"])}
    except Exception:
        existing = set()
    try:
        country = ((await asyncio.to_thread(queries.get_profile_settings, user["user_id"])) or {}).get("country")
    except Exception:
        country = None
    lines = await hs.resolve_rows(rows, existing, country)
    counts = {k: sum(1 for x in lines if x["status"] == k) for k in ("ok", "ambiguous", "not_found", "invalid")}
    return {"lines": lines, "count": len(lines), "counts": counts}


@router.post("", dependencies=[Depends(require_feature("action.holdings.edit"))], status_code=status.HTTP_201_CREATED)
async def upsert_holdings(body: UpsertRequest, user: dict = Depends(get_current_user)):
    uid = user["user_id"]
    accounts = await _check_account_ids(uid, {str(it.account_id) for it in body.items if it.account_id})
    await slots.check_new_symbols_async(user, [it.symbol for it in body.items])
    existing = {(str(h.get("account_id") or ""), h["symbol"]): h for h in await _db(queries.get_holdings, uid)}
    merged: dict[tuple[str, str], dict] = {}
    for it in body.items:
        key = (str(it.account_id or ""), it.symbol)
        prev = existing.get(key) or merged.get(key) or {}
        pick = lambda k, v: v if v is not None else prev.get(k)  # noqa: E731 — never wipe known values
        merged[key] = {
            "symbol": it.symbol,
            "account_id": str(it.account_id) if it.account_id else None,
            "input_symbol": pick("input_symbol", it.input_symbol),
            "name": pick("name", it.name),
            "exchange": pick("exchange", it.exchange),
            "currency": it.currency or prev.get("currency") or hs.holding_currency({"symbol": it.symbol}),
            "asset_type": pick("asset_type", it.asset_type),
            "shares": pick("shares", it.shares),
            "avg_cost": pick("avg_cost", it.avg_cost),
            "notes": pick("notes", it.notes),
        }
    saved = await _db(queries.upsert_holdings, uid, list(merged.values()))
    created = sum(1 for s in merged if s not in existing)
    if saved:  # an invited user's first follow rewards their referrer (migration 019)
        from app.services import referrals
        await referrals.after_follow(uid)
    refreshing = holding_status.kick(uid)
    return {"items": [_with_account(hs.public_holding(h, None), accounts) for h in saved], "count": len(saved),
            "created": created, "updated": len(merged) - created, "refreshing": refreshing}


@router.patch("/{holding_id}", dependencies=[Depends(require_feature("action.holdings.edit"))])
async def patch_holding(holding_id: UUID, body: HoldingPatch, user: dict = Depends(get_current_user)):
    uid = user["user_id"]
    data = {k: getattr(body, k) for k in body.model_fields_set if k != "account"}
    if not data:
        raise _err("nothing_to_update", "No fields to update.", status.HTTP_400_BAD_REQUEST)
    accounts = None
    if "account_id" in data:
        target = str(data["account_id"]) if data["account_id"] else None
        accounts = await _check_account_ids(uid, {target} if target else set())
        if accounts is None:
            raise migration_required()
        rows = await _db(queries.get_holdings, uid)
        me = next((h for h in rows if str(h.get("id")) == str(holding_id)), None)
        if me is None:
            raise _err("not_found", "Holding not found.", status.HTTP_404_NOT_FOUND)
        if any(h.get("symbol") == me.get("symbol") and str(h.get("account_id") or "") == str(target or "")
               and str(h.get("id")) != str(holding_id) for h in rows):
            raise _err("duplicate_holding", f"That account already holds {me.get('symbol')} — edit that "
                       "holding instead.", status.HTTP_409_CONFLICT)
        data["account_id"] = target
    item = await _db(queries.update_holding, str(holding_id), uid, data)
    if not item:
        raise _err("not_found", "Holding not found.", status.HTTP_404_NOT_FOUND)
    if accounts is None:
        accounts = await _accounts(uid)
    return _with_account(hs.public_holding(item, None), accounts)


@router.delete("/{holding_id}", dependencies=[Depends(require_feature("action.holdings.edit"))])
async def delete_holding(holding_id: UUID, user: dict = Depends(get_current_user)):
    ok = await _db(queries.delete_holding, str(holding_id), user["user_id"])
    if not ok:
        raise _err("not_found", "Holding not found.", status.HTTP_404_NOT_FOUND)
    return {"message": "Holding deleted"}
