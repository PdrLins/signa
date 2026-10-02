"""People and accounts (migration 013). No AI.

Accounts are created and named by the user ("Wealthsimple", "Questrade",
"Ray WS"). Nothing is created by default. An account may belong to a person
(portfolio_people: me, spouse, kid ...) and may carry an optional tax type:

  CA: TFSA, RRSP, FHSA, RESP, NON_REGISTERED     US: ROTH_IRA, TRADITIONAL_IRA, 401K, TAXABLE
  both: OTHER

Setting a type needs action.accounts.type (free since migration 022) -> else 403
upgrade_required, and the user's country must be CA or US -> else 422
account_type_unavailable; the type must belong to that country -> else 422
invalid_account_type. Clearing it (null) is always allowed.

Deleting an account that still holds positions -> 409 account_has_holdings,
unless ?move_to=<account_id> (holdings and transactions move there; the same
symbol in both is merged: shares added, average cost weighted) or
?force=true (holdings become "no account", merged the same way).
"""

from __future__ import annotations

import math
import re
from typing import Any

from fastapi import status

from app.core.access import can, upgrade_required
from app.core.api_errors import api_error
from app.db import queries
from app.services import profile_service

CA_TYPES = ("TFSA", "RRSP", "FHSA", "RESP", "NON_REGISTERED", "OTHER")
US_TYPES = ("ROTH_IRA", "TRADITIONAL_IRA", "401K", "TAXABLE", "OTHER")
ACCOUNT_TYPES_BY_COUNTRY: dict[str, tuple[str, ...]] = {"CA": CA_TYPES, "US": US_TYPES}
ALL_ACCOUNT_TYPES: tuple[str, ...] = tuple(dict.fromkeys(CA_TYPES + US_TYPES))

MAX_ACCOUNTS = 50
MAX_PEOPLE = 20
MAX_CASH = 1e12
_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _422(code: str, message: str, field: str | None = None) -> Exception:
    extra = {"field": field} if field else {}
    return api_error(code, message, 422, **extra)


def _clean_name(v: Any, field: str = "name") -> str:
    if not isinstance(v, str):
        raise _422("invalid_name", "Name is required.", field)
    name = " ".join(v.split())
    if not name or len(name) > 60 or any(ord(c) < 32 for c in name):
        raise _422("invalid_name", "Name: 1 to 60 characters.", field)
    return name


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# ============================================================
# Account type rules (pure)
# ============================================================

def check_account_type(level: str, country: str | None, account_type: str | None) -> str | None:
    if account_type is None:
        return None
    t = str(account_type).strip().upper()
    if t not in ALL_ACCOUNT_TYPES:
        raise _422("invalid_account_type", f"Account type must be one of {', '.join(ALL_ACCOUNT_TYPES)}.",
                   "account_type")
    if not can(level, "action.accounts.type"):
        raise upgrade_required("action.accounts.type")
    c = (country or "").upper()
    if c not in ACCOUNT_TYPES_BY_COUNTRY:
        raise _422("account_type_unavailable",
                   "Account types are available for Canada and the United States — set your country in "
                   "your profile.", "account_type")
    if t not in ACCOUNT_TYPES_BY_COUNTRY[c]:
        raise _422("invalid_account_type",
                   f"For {c} the account type must be one of {', '.join(ACCOUNT_TYPES_BY_COUNTRY[c])}.",
                   "account_type")
    return t


def merge_holding(target: dict, src: dict) -> dict:
    """Fields to write on `target` when `src` (same symbol) is merged into it."""
    ts, ss = _num(target.get("shares")), _num(src.get("shares"))
    tc, sc = _num(target.get("avg_cost")), _num(src.get("avg_cost"))
    if ts and ss:
        shares = ts + ss
        avg = (ts * tc + ss * sc) / shares if tc and sc else None
    elif ts:
        shares, avg = ts, tc
    elif ss:
        shares, avg = ss, sc
    else:
        shares, avg = None, tc or sc
    return {"shares": round(shares, 8) if shares else None,
            "avg_cost": round(avg, 6) if avg else None,
            "notes": target.get("notes") or src.get("notes")}


# ============================================================
# People
# ============================================================

def public_person(p: dict, accounts: list[dict] | None = None) -> dict:
    return {"id": p.get("id"), "name": p.get("name"), "color": p.get("color"),
            "accounts_count": sum(1 for a in accounts or [] if a.get("person_id") == p.get("id")),
            "created_at": p.get("created_at")}


def _clean_color(v: Any) -> str | None:
    if v is None:
        return None
    if not isinstance(v, str) or not _COLOR.match(v.strip()):
        raise _422("invalid_color", "Color must look like #1A2B3C.", "color")
    return v.strip().upper()


def list_people(user_id: str) -> dict:
    people = queries.get_people(user_id)
    accounts = queries.get_accounts(user_id)
    items = [public_person(p, accounts) for p in people]
    return {"items": items, "count": len(items)}


def _dup(rows: list[dict], name: str, exclude_id: str | None = None) -> bool:
    return any(str(r.get("name", "")).casefold() == name.casefold() and str(r.get("id")) != str(exclude_id)
               for r in rows)


def create_person(user_id: str, data: dict) -> dict:
    name = _clean_name(data.get("name"))
    color = _clean_color(data.get("color"))
    people = queries.get_people(user_id)
    if len(people) >= MAX_PEOPLE:
        raise api_error("too_many_people", f"Up to {MAX_PEOPLE} people.", status.HTTP_409_CONFLICT)
    if _dup(people, name):
        raise api_error("duplicate_name", "There is already a person with this name.", status.HTTP_409_CONFLICT)
    return public_person(queries.insert_person(user_id, {"name": name, "color": color}))


def update_person(user_id: str, person_id: str, data: dict) -> dict:
    people = queries.get_people(user_id)
    if not any(str(p["id"]) == person_id for p in people):
        raise api_error("not_found", "Person not found.", status.HTTP_404_NOT_FOUND)
    clean: dict[str, Any] = {}
    if "name" in data:
        clean["name"] = _clean_name(data["name"])
        if _dup(people, clean["name"], person_id):
            raise api_error("duplicate_name", "There is already a person with this name.", status.HTTP_409_CONFLICT)
    if "color" in data:
        clean["color"] = _clean_color(data["color"])
    if not clean:
        raise api_error("nothing_to_update", "No fields to update.", status.HTTP_400_BAD_REQUEST)
    row = queries.update_person(person_id, user_id, clean)
    if not row:
        raise api_error("not_found", "Person not found.", status.HTTP_404_NOT_FOUND)
    return public_person(row, queries.get_accounts(user_id))


def delete_person(user_id: str, person_id: str) -> dict:
    if not queries.delete_person(person_id, user_id):
        raise api_error("not_found", "Person not found.", status.HTTP_404_NOT_FOUND)
    return {"deleted": True, "id": person_id}


# ============================================================
# Accounts
# ============================================================

def public_account(a: dict, people: list[dict] | None = None, holdings: list[dict] | None = None) -> dict:
    pid = a.get("person_id")
    person = next((p for p in people or [] if str(p.get("id")) == str(pid)), None) if pid else None
    return {
        "id": a.get("id"),
        "name": a.get("name"),
        "person_id": pid,
        "person_name": (person or {}).get("name"),
        "account_type": a.get("account_type"),
        "currency": a.get("currency"),
        "cash_balance": _num(a.get("cash_balance")) or 0.0,
        "holdings_count": sum(1 for h in holdings or [] if str(h.get("account_id")) == str(a.get("id"))),
        "created_at": a.get("created_at"),
        "updated_at": a.get("updated_at"),
    }


def list_accounts(user_id: str, person_id: str | None = None) -> dict:
    accounts = queries.get_accounts(user_id)
    people = queries.get_people(user_id)
    holdings = queries.get_holdings(user_id)
    if person_id:
        accounts = [a for a in accounts if str(a.get("person_id")) == person_id]
    items = [public_account(a, people, holdings) for a in accounts]
    return {"items": items, "count": len(items), "account_types": account_types_for_user_meta(user_id)}


def account_types_for_user_meta(user_id: str) -> dict:
    """Which types this user's country offers (clients build the picker)."""
    country, _ = profile_service.get_country_and_currency(user_id)
    return {"country": country, "types": list(ACCOUNT_TYPES_BY_COUNTRY.get((country or "").upper(), ()))}


def _clean_currency(v: Any) -> str:
    c = str(v or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", c):
        raise _422("invalid_currency", "Currency must be a 3-letter code (CAD, USD ...).", "currency")
    return c


def _clean_cash(v: Any) -> float:
    f = _num(v) if not isinstance(v, bool) else None
    if f is None or abs(f) >= MAX_CASH:
        raise _422("invalid_cash_balance", "Cash balance must be a number.", "cash_balance")
    return round(f, 2)


def _check_person(user_id: str, person_id: Any) -> str | None:
    if person_id is None:
        return None
    pid = str(person_id)
    if not any(str(p["id"]) == pid for p in queries.get_people(user_id)):
        raise _422("invalid_person", "Person not found.", "person_id")
    return pid


def create_account(user: dict, data: dict) -> dict:
    uid = user["user_id"]
    name = _clean_name(data.get("name"))
    accounts = queries.get_accounts(uid)
    if len(accounts) >= MAX_ACCOUNTS:
        raise api_error("too_many_accounts", f"Up to {MAX_ACCOUNTS} accounts.", status.HTTP_409_CONFLICT)
    if _dup(accounts, name):
        raise api_error("duplicate_name", "You already have an account with this name.", status.HTTP_409_CONFLICT)
    country, home = profile_service.get_country_and_currency(uid)
    row = {
        "name": name,
        "person_id": _check_person(uid, data.get("person_id")),
        "account_type": check_account_type(user.get("access_level") or "free", country, data.get("account_type")),
        "currency": _clean_currency(data["currency"]) if data.get("currency") is not None else home,
        "cash_balance": _clean_cash(data["cash_balance"]) if data.get("cash_balance") is not None else 0.0,
    }
    saved = queries.insert_accounts(uid, [row])
    return public_account(saved[0] if saved else row, queries.get_people(uid), [])


def update_account(user: dict, account_id: str, data: dict) -> dict:
    uid = user["user_id"]
    accounts = queries.get_accounts(uid)
    if not any(str(a["id"]) == account_id for a in accounts):
        raise api_error("not_found", "Account not found.", status.HTTP_404_NOT_FOUND)
    clean: dict[str, Any] = {}
    if "name" in data:
        clean["name"] = _clean_name(data["name"])
        if _dup(accounts, clean["name"], account_id):
            raise api_error("duplicate_name", "You already have an account with this name.",
                            status.HTTP_409_CONFLICT)
    if "person_id" in data:
        clean["person_id"] = _check_person(uid, data["person_id"])
    if "currency" in data:
        clean["currency"] = _clean_currency(data["currency"])
    if "cash_balance" in data:
        clean["cash_balance"] = _clean_cash(data["cash_balance"])
    if "account_type" in data:
        country, _ = profile_service.get_country_and_currency(uid)
        clean["account_type"] = check_account_type(user.get("access_level") or "free", country,
                                                   data["account_type"])
    if not clean:
        raise api_error("nothing_to_update", "No fields to update.", status.HTTP_400_BAD_REQUEST)
    row = queries.update_account(account_id, uid, clean)
    if not row:
        raise api_error("not_found", "Account not found.", status.HTTP_404_NOT_FOUND)
    return public_account(row, queries.get_people(uid), queries.get_holdings(uid))


def delete_account(user_id: str, account_id: str, move_to: str | None = None, force: bool = False) -> dict:
    accounts = queries.get_accounts(user_id)
    if not any(str(a["id"]) == account_id for a in accounts):
        raise api_error("not_found", "Account not found.", status.HTTP_404_NOT_FOUND)
    if move_to is not None:
        if move_to == account_id or not any(str(a["id"]) == move_to for a in accounts):
            raise _422("invalid_move_to", "move_to must be another of your accounts.", "move_to")
    holdings = queries.get_holdings(user_id)
    inside = [h for h in holdings if str(h.get("account_id")) == account_id]
    if inside and move_to is None and not force:
        raise api_error("account_has_holdings",
                        "This account still has holdings — move them to another account (move_to) "
                        "or remove them from any account (force=true).",
                        status.HTTP_409_CONFLICT, holdings=len(inside))
    target = move_to  # None = "no account"
    moved = merged = 0
    for h in inside:
        twin = next((x for x in holdings if x.get("symbol") == h.get("symbol")
                     and str(x.get("account_id") or "") == str(target or "") and x.get("id") != h.get("id")), None)
        if twin:
            queries.update_holding(str(twin["id"]), user_id, merge_holding(twin, h))
            queries.delete_holding(str(h["id"]), user_id)
            merged += 1
        else:
            queries.update_holding(str(h["id"]), user_id, {"account_id": target})
            moved += 1
    queries.move_account_transactions(user_id, account_id, target)
    if not queries.delete_account(account_id, user_id):
        raise api_error("not_found", "Account not found.", status.HTTP_404_NOT_FOUND)
    return {"deleted": True, "id": account_id, "moved_to": target,
            "moved_holdings": moved, "merged_holdings": merged}
