"""Shared scope loader + position valuation for the tracker's insight endpoints.

Every Phase-2 endpoint (/portfolio/summary, /history, /performance,
/allocation, /dividends/summary, /events/upcoming) answers for a SCOPE:

  * the whole portfolio (no filter)
  * ?account_id=<uuid>   one of the user's accounts   (else 404 account_not_found)
  * ?person_id=<uuid>    the accounts of one person    (else 404 person_not_found)
  * both                 the account must belong to the person (else 422 invalid_scope)

Holdings without an account ("no account") belong only to the whole
portfolio. Transactions follow the same account filter.

  load_scope(user, account_id, person_id, ...)   sync (run it with run_db)
  scope_filter(...)                              pure
  value_positions(holdings, quotes, home, usdcad)  pure
  price_meta(positions)                          pure: as_of / delayed_minutes

Prices are free, delayed data (Yahoo, ~15 min): every response carries
`as_of` (the OLDEST quote time among the priced positions — conservative)
and `delayed_minutes` (quotes.DELAYED_MINUTES). A position with no quote
falls back to the monitor's last close (holding_status.price) and is
marked price_source="last_close" (estimated). Money is converted to the
user's home currency with USD/CAD only (portfolio_snapshots.convert);
anything else is left out of totals and listed as unconverted.
No AI.
"""

from __future__ import annotations

import math
from typing import Any

from fastapi import status

from app.core.api_errors import api_error
from app.services.holdings_service import holding_currency
from app.services.portfolio_snapshots import convert
from app.services.quotes import DELAYED_MINUTES


def _f(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def r2(v: float | None, nd: int = 2) -> float | None:
    return round(v, nd) if v is not None and math.isfinite(v) else None


def to_home(amount: float | None, ccy: str | None, home: str, usdcad: float | None) -> float | None:
    """Native amount -> home currency (USD/CAD only; None = can't convert)."""
    return convert(amount, (ccy or home), home, usdcad)


# ============================================================
# Scope (pure)
# ============================================================

def scope_filter(accounts: list[dict], holdings: list[dict], transactions: list[dict] | None,
                 account_id: str | None, person_id: str | None) -> dict:
    """{"accounts", "holdings", "transactions", "account_ids"} for the scope.
    account_ids None = whole portfolio. Raises structured 404/422. Pure."""
    by_id = {str(a.get("id")): a for a in accounts or []}
    if account_id is not None and account_id not in by_id:
        raise api_error("account_not_found", "Account not found.", status.HTTP_404_NOT_FOUND, field="account_id")
    # an unknown person_id is checked by load_scope (a person with no accounts is valid: empty scope)
    ids: set[str] | None = None
    if account_id is not None:
        ids = {account_id}
        if person_id is not None and str(by_id[account_id].get("person_id") or "") != person_id:
            raise api_error("invalid_scope", "That account does not belong to that person.",
                            422, field="account_id")
    elif person_id is not None:
        ids = {aid for aid, a in by_id.items() if str(a.get("person_id") or "") == person_id}
    if ids is None:
        return {"accounts": list(accounts or []), "holdings": list(holdings or []),
                "transactions": list(transactions or []), "account_ids": None}
    return {
        "accounts": [a for a in accounts or [] if str(a.get("id")) in ids],
        "holdings": [h for h in holdings or [] if str(h.get("account_id") or "") in ids],
        "transactions": [t for t in transactions or [] if str(t.get("account_id") or "") in ids],
        "account_ids": sorted(ids),
    }


# ============================================================
# Load (sync, DB + shared quotes)
# ============================================================

def load_scope(user: dict, account_id: str | None = None, person_id: str | None = None,
               with_transactions: bool = True, with_quotes: bool = True) -> dict:
    """Everything an insight endpoint needs, for the scope. Sync — call via run_db.

    Returns {
      "user_id", "level", "country", "home_currency", "tax_view" (effective),
      "tax_eligible" (feature.tax_view + CA/US), "compare_index" (stored, may be None),
      "all_accounts", "accounts", "account_ids" (None = whole portfolio),
      "holdings" (scope, one row per account+symbol), "transactions" (scope, oldest first),
      "quotes" {SYMBOL: quote}, "usdcad"
    }"""
    from app.db import queries
    from app.services import profile_service
    from app.services.price_cache import get_usdcad_rate

    uid = user["user_id"]
    level = user.get("access_level") or "free"
    settings_row = profile_service.merged_settings(queries.get_profile_settings(uid))
    accounts = queries.get_accounts(uid)
    if person_id is not None and not any(str(p.get("id")) == person_id for p in queries.get_people(uid)):
        raise api_error("person_not_found", "Person not found.", status.HTTP_404_NOT_FOUND, field="person_id")
    holdings = queries.get_holdings(uid)
    txs = queries.get_all_transactions(uid) if with_transactions else []
    scope = scope_filter(accounts, holdings, txs, account_id, person_id)
    country = settings_row.get("country")
    stored_tax = settings_row.get("dividend_tax_view")
    quotes_map: dict[str, dict] = {}
    ext_map: dict[str, dict] = {}
    if with_quotes:
        from app.core.access import can
        from app.services.quotes import get_extended, get_quotes
        held_syms = {str(h.get("symbol") or "").upper() for h in scope["holdings"] if h.get("symbol")}
        quotes_map = get_quotes(held_syms)
        if can(level, "feature.extended_hours"):   # pre/after-hours prices (migration 021)
            ext_map = get_extended(held_syms)
    try:
        usdcad = get_usdcad_rate()
    except Exception:
        usdcad = None
    return {
        "user_id": uid,
        "level": level,
        "country": country,
        "home_currency": (settings_row.get("home_currency") or "CAD").upper(),
        "tax_view": profile_service.effective_tax_view(stored_tax, level, country),
        "tax_eligible": profile_service.tax_view_allowed(level, country),
        "compare_index": settings_row.get("compare_index"),
        "all_accounts": accounts,
        "accounts": scope["accounts"],
        "account_ids": scope["account_ids"],
        "holdings": scope["holdings"],
        "transactions": scope["transactions"],
        "quotes": quotes_map,
        "quotes_ext": ext_map,
        "usdcad": usdcad,
    }


# ============================================================
# Valuation (pure)
# ============================================================

def value_positions(holdings: list[dict], quotes: dict[str, dict], home: str,
                    usdcad: float | None) -> list[dict]:
    """One row per holding (account + symbol). Pure.

    {symbol, account_id, name, asset_type, currency, shares, avg_cost,
     price, prev_close, change_pct, price_source "quote"|"last_close"|None,
     as_of, value (native), value_home, prev_value_home, day_change_home,
     cost_home, gain_home, gain_pct, converted (bool)}
    Holdings without shares or a price have value None (still listed)."""
    home = (home or "CAD").upper()
    out = []
    for h in holdings or []:
        sym = str(h.get("symbol") or "").upper()
        q = quotes.get(sym) or {}
        status_ = h.get("holding_status") or {}
        price, source = _f(q.get("price")), "quote"
        prev = _f(q.get("prev_close"))
        as_of = q.get("as_of")
        if price is None:
            price, source = _f(status_.get("price")), "last_close"
            prev = _f(status_.get("prev_close"))
            as_of = status_.get("as_of")
        if price is None:
            source = None
        ccy = str(q.get("currency") or holding_currency(h)).upper()
        shares = _f(h.get("shares"))
        cost = _f(h.get("avg_cost"))
        value = shares * price if shares and price else None
        value_home = to_home(value, ccy, home, usdcad)
        prev_value_home = to_home(shares * prev, ccy, home, usdcad) if shares and prev else None
        cost_home = to_home(shares * cost, ccy, home, usdcad) if shares and cost else None
        gain_home = value_home - cost_home if value_home is not None and cost_home is not None else None
        out.append({
            "symbol": sym,
            "account_id": h.get("account_id"),
            "name": h.get("name"),
            "asset_type": h.get("asset_type"),
            "currency": ccy,
            "shares": shares,
            "avg_cost": cost,
            "price": price,
            "prev_close": prev,
            "change_pct": r2((price / prev - 1) * 100, 4) if price and prev else None,
            "price_source": source,
            "as_of": as_of,
            "value": value,
            "value_home": value_home,
            "prev_value_home": prev_value_home,
            "day_change_home": (value_home - prev_value_home)
            if value_home is not None and prev_value_home is not None else None,
            "cost_home": cost_home,
            "gain_home": gain_home,
            "gain_pct": r2((gain_home / cost_home) * 100) if gain_home is not None and cost_home else None,
            "converted": value is None or value_home is not None,
        })
    return out


def merge_positions_by_symbol(positions: list[dict]) -> list[dict]:
    """value_positions rows summed per symbol (a stock held in two accounts
    counts once): shares/values/costs added. Pure."""
    out: dict[str, dict] = {}
    add_keys = ("shares", "value", "value_home", "prev_value_home", "day_change_home", "cost_home", "gain_home")
    for p in positions or []:
        m = out.get(p["symbol"])
        if m is None:
            out[p["symbol"]] = {**p, "account_ids": [p.get("account_id")]}
            continue
        m["account_ids"].append(p.get("account_id"))
        for k in add_keys:
            a, b = m.get(k), p.get(k)
            m[k] = (a or 0) + (b or 0) if (a is not None or b is not None) else None
        m["converted"] = m["converted"] and p["converted"]
        m["account_id"] = None
    for m in out.values():
        m["gain_pct"] = r2(m["gain_home"] / m["cost_home"] * 100) if m.get("gain_home") is not None \
            and m.get("cost_home") else None
        m["avg_cost"] = None if len(m["account_ids"]) > 1 else m.get("avg_cost")
    return list(out.values())


def price_meta(positions: list[dict]) -> dict:
    """{"as_of", "delayed_minutes", "estimated_prices": [symbols]}. as_of =
    the oldest price time among priced positions (None when none). Pure."""
    times = sorted(str(p["as_of"]) for p in positions or [] if p.get("price") is not None and p.get("as_of"))
    est = sorted({p["symbol"] for p in positions or [] if p.get("price_source") == "last_close"})
    return {"as_of": times[0] if times else None, "delayed_minutes": DELAYED_MINUTES,
            "estimated_prices": est}
