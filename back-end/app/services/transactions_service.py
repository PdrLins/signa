"""Transactions: manual entry and CSV import with Signa's template (migration 013).

No broker integrations and no AI. A transaction is one of
buy | sell | dividend | deposit | withdrawal | split | fee.

Field rules (validate_transaction):
  type        required
  trade_date  required; not more than 1 day in the future; not before 1900
  symbol      required for buy/sell/dividend/split, optional for fee, must be
              empty for deposit/withdrawal. Yahoo-style symbol (XEQT.TO,
              NVDA, BTC-USD), checked with app.core.utils.validate_ticker.
  quantity    buy/sell: shares > 0. split: the RATIO > 0 and != 1
              (2 = 2-for-1, 0.1 = 1-for-10). dividend: optional (shares
              held). Ignored (stored null) for deposit/withdrawal/fee.
  price       buy/sell: > 0, or omitted when amount is given (price is then
              amount / quantity). Ignored for the other types.
  amount      ALWAYS a positive cash amount; the direction comes from type.
              buy/sell: gross (quantity x price) — defaults to that.
              dividend/deposit/withdrawal/fee: required > 0. split: null.
  currency    3 letters; defaults to the account's currency, else the
              symbol's listing currency (.TO -> CAD, else USD), else the
              user's home currency.
  fee         >= 0 (default 0)
  note        up to 500 characters
  account_id  optional; must be one of the user's accounts.

CSV template (header row required, any column order, extra columns ignored):
  date,type,symbol,quantity,price,amount,currency,fee,account,note
  * account = the account NAME (case-insensitive). Unknown names are a
    per-row error, or are created with create_missing_accounts=true.
  * dates: ISO (2026-09-30), 2026/09/30, 30/09/2026 or 09/30/2026 (the
    order is inferred from the whole file — a day > 12 decides; if nothing
    decides, US users get month/day, everyone else day/month; override with
    date_format=dmy|mdy), and "Sep 30, 2026" / "30 Sep 2026".
  * numbers: "1234.56", "1,234.56", "1.234,56", "12,5". A lone comma is a
    decimal comma unless followed by exactly 3 digits in a comma-delimited
    file (then thousands). Semicolon-delimited files use the decimal comma.
    Currency signs and spaces are ignored; signs are ignored (direction
    comes from type).
  * at most MAX_IMPORT_ROWS rows, MAX_IMPORT_BYTES bytes.
"""

from __future__ import annotations

import csv
import io
import math
import re
import uuid
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import status

from app.core.api_errors import api_error
from app.core.utils import validate_ticker
from app.db import queries
from app.services import profile_service
from app.services.price_cache import native_currency

TYPES: tuple[str, ...] = ("buy", "sell", "dividend", "deposit", "withdrawal", "split", "fee")
SYMBOL_REQUIRED = {"buy", "sell", "dividend", "split"}
SYMBOL_FORBIDDEN = {"deposit", "withdrawal"}
MAX_NUMBER = 1e12
MAX_NOTE = 500
MAX_IMPORT_ROWS = 5000
MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_ERRORS_RETURNED = 200

TEMPLATE_COLUMNS: tuple[str, ...] = ("date", "type", "symbol", "quantity", "price", "amount", "currency",
                                     "fee", "account", "note")
TEMPLATE_EXAMPLES: tuple[tuple[str, ...], ...] = (
    ("2026-01-15", "deposit", "", "", "", "5000", "CAD", "0", "Wealthsimple", "First deposit"),
    ("2026-01-16", "buy", "XEQT.TO", "100", "31.25", "3125", "CAD", "0", "Wealthsimple", ""),
    ("2026-03-31", "dividend", "XEQT.TO", "100", "", "18.40", "CAD", "0", "Wealthsimple", "Quarterly distribution"),
)
COLUMN_HELP: dict[str, str] = {
    "date": "Trade date: 2026-09-30 (also 30/09/2026, 09/30/2026, Sep 30 2026)",
    "type": "buy, sell, dividend, deposit, withdrawal, split or fee",
    "symbol": "Yahoo symbol (XEQT.TO, NVDA, BTC-USD); empty for deposit/withdrawal",
    "quantity": "Shares (buy/sell/dividend) or the split ratio (2 = 2-for-1)",
    "price": "Price per share (buy/sell)",
    "amount": "Cash amount, always positive (gross for buy/sell)",
    "currency": "CAD, USD ... (default: the account's currency)",
    "fee": "Commission, >= 0",
    "account": "Your account's name, e.g. Wealthsimple",
    "note": "Optional note",
}

_TYPE_ALIASES = {
    "buy": "buy", "bought": "buy", "purchase": "buy", "compra": "buy",
    "sell": "sell", "sold": "sell", "sale": "sell", "venda": "sell",
    "dividend": "dividend", "dividends": "dividend", "div": "dividend", "distribution": "dividend",
    "dividendo": "dividend", "dividendos": "dividend", "proventos": "dividend", "provento": "dividend",
    "jcp": "dividend", "juros sobre capital": "dividend", "juros sobre capital próprio": "dividend",
    "juros sobre capital proprio": "dividend", "rendimento": "dividend", "rendimentos": "dividend",
    "deposit": "deposit", "contribution": "deposit", "deposito": "deposit", "depósito": "deposit",
    "withdrawal": "withdrawal", "withdraw": "withdrawal", "saque": "withdrawal", "retirada": "withdrawal",
    "split": "split", "stock split": "split", "desdobramento": "split", "grupamento": "split",
    "fee": "fee", "fees": "fee", "commission": "fee", "taxa": "fee",
}
_HEADER_ALIASES = {
    "date": ("date", "trade_date", "trade date", "data"),
    "type": ("type", "action", "transaction type", "tipo"),
    "symbol": ("symbol", "ticker", "símbolo", "simbolo"),
    "quantity": ("quantity", "qty", "shares", "quantidade"),
    "price": ("price", "preço", "preco"),
    "amount": ("amount", "total", "valor"),
    "currency": ("currency", "ccy", "moeda"),
    "fee": ("fee", "fees", "commission", "taxa"),
    "account": ("account", "account name", "conta"),
    "note": ("note", "notes", "memo", "nota"),
}
_ET = ZoneInfo("America/New_York")


def _today() -> date:
    return datetime.now(_ET).date()


def _err(field: str, code: str, message: str) -> dict:
    return {"field": field, "code": code, "message": message}


def _num(v: Any) -> float | None:
    if v is None or v == "" or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# ============================================================
# Validation (shared by manual entry and CSV)
# ============================================================

def validate_transaction(raw: dict, *, accounts: dict[str, dict], home_currency: str = "CAD",
                         today: date | None = None) -> tuple[dict | None, list[dict]]:
    """-> (clean row ready to store, []) or (None, [errors]).

    `raw` values are already typed (numbers as numbers, trade_date as date or
    ISO string). `accounts` maps account_id -> account row (the user's).
    """
    today = today or _today()
    errors: list[dict] = []
    typ = str(raw.get("type") or "").strip().lower()
    if typ not in TYPES:
        return None, [_err("type", "invalid_type", f"Type must be one of {', '.join(TYPES)}.")]

    d = raw.get("trade_date")
    if isinstance(d, str):
        try:
            d = date.fromisoformat(d.strip()[:10])
        except ValueError:
            d = None
    if isinstance(d, datetime):
        d = d.date()
    if not isinstance(d, date):
        errors.append(_err("trade_date", "invalid_date", "Trade date is required (YYYY-MM-DD)."))
    elif d > today + timedelta(days=1):
        errors.append(_err("trade_date", "date_in_future", "Trade date can't be in the future."))
    elif d.year < 1900:
        errors.append(_err("trade_date", "invalid_date", "Trade date is too old."))

    sym = str(raw.get("symbol") or "").strip().upper().lstrip("$") or None
    if typ in SYMBOL_FORBIDDEN and sym:
        errors.append(_err("symbol", "symbol_not_allowed", f"A {typ} has no symbol."))
    elif typ in SYMBOL_REQUIRED and not sym:
        errors.append(_err("symbol", "symbol_required", f"A {typ} needs a symbol."))
    elif sym and (len(sym) > 24 or not validate_ticker(sym)):
        errors.append(_err("symbol", "invalid_symbol", f"'{sym}' is not a valid symbol (e.g. XEQT.TO, NVDA)."))
    if typ in SYMBOL_FORBIDDEN:
        sym = None

    def num(field: str) -> float | None:
        v = raw.get(field)
        if v is None or v == "":
            return None
        f = _num(v)
        if f is None or abs(f) >= MAX_NUMBER:
            errors.append(_err(field, "invalid_number", f"{field} must be a number."))
            return None
        return abs(f)

    qty, price, amount = num("quantity"), num("price"), num("amount")
    fee = num("fee")
    fee = fee if fee is not None else 0.0

    if typ in ("buy", "sell"):
        if not qty:
            errors.append(_err("quantity", "quantity_required", "Quantity must be greater than 0."))
        if not price and qty and amount:
            price = amount / qty
        if not price:
            errors.append(_err("price", "price_required", "Price (or amount) must be greater than 0."))
        if amount is None and qty and price:
            amount = qty * price
    elif typ == "split":
        if not qty or abs(qty - 1) < 1e-12:
            errors.append(_err("quantity", "invalid_split_ratio",
                               "For a split, quantity is the ratio (2 = 2-for-1, 0.1 = 1-for-10)."))
        price = amount = None
    else:  # dividend, deposit, withdrawal, fee
        if not amount:
            errors.append(_err("amount", "amount_required", "Amount must be greater than 0."))
        price = None
        if typ != "dividend":
            qty = None

    acct_id = raw.get("account_id")
    acct = None
    if acct_id:
        acct = accounts.get(str(acct_id))
        if acct is None:
            errors.append(_err("account_id", "unknown_account", "Account not found."))

    ccy = raw.get("currency")
    if ccy:
        ccy = str(ccy).strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", ccy):
            errors.append(_err("currency", "invalid_currency", "Currency must be a 3-letter code."))
    else:
        ccy = (acct or {}).get("currency") or (native_currency(sym) if sym else None) or home_currency

    note = raw.get("note")
    if note is not None:
        note = str(note).strip() or None
        if note and len(note) > MAX_NOTE:
            errors.append(_err("note", "note_too_long", f"Note: up to {MAX_NOTE} characters."))

    if errors:
        return None, errors
    r = lambda v, nd: round(v, nd) if v is not None else None  # noqa: E731
    return {
        "account_id": str(acct_id) if acct_id else None,
        "symbol": sym,
        "type": typ,
        "trade_date": d.isoformat(),
        "quantity": r(qty, 8),
        "price": r(price, 6),
        "amount": r(amount, 4),
        "currency": ccy,
        "fee": r(fee, 4),
        "note": note,
    }, []


def _raise_invalid(errors: list[dict]) -> None:
    first = errors[0]
    raise api_error(first["code"], first["message"], 422,
                    field=first["field"], errors=errors)


def public_tx(t: dict, accounts: dict[str, dict] | None = None) -> dict:
    out = {k: v for k, v in t.items() if k != "user_id"}
    for k in ("quantity", "price", "amount", "fee"):
        out[k] = _num(out.get(k))
    acct = (accounts or {}).get(str(t.get("account_id"))) if t.get("account_id") else None
    out["account_name"] = (acct or {}).get("name")
    out["estimated"] = t.get("source") == "auto"   # recorded by Signa (migration 032), not by the user
    return out


def _accounts_map(user_id: str) -> dict[str, dict]:
    from app.core import user_cache
    return {str(a["id"]): a for a in user_cache.get(user_id, "accounts", lambda: queries.get_accounts(user_id))}


# ============================================================
# CRUD (sync — run through app.core.api_errors.run_db)
# ============================================================

def list_transactions(user_id: str, filters: dict, limit: int, offset: int) -> dict:
    accounts = _accounts_map(user_id)
    rows, total = queries.list_transactions(user_id, filters, limit, offset)
    items = [public_tx(t, accounts) for t in rows]
    return {"items": items, "count": len(items), "total": total, "limit": limit, "offset": offset,
            "has_more": offset + len(items) < total}


MAX_TRANSACTIONS_PER_USER = 50_000   # a storage guard far above any real ledger


def _check_room(user_id: str, adding: int) -> None:
    have = queries.count_rows("transactions", user_id)
    if have + adding > MAX_TRANSACTIONS_PER_USER:
        raise api_error("transaction_limit",
                        f"An account can hold up to {MAX_TRANSACTIONS_PER_USER:,} transactions.", 422,
                        limit=MAX_TRANSACTIONS_PER_USER, current=have)


def create_transaction(user_id: str, raw: dict) -> dict:
    _check_room(user_id, 1)
    accounts = _accounts_map(user_id)
    _, home = profile_service.get_country_and_currency(user_id)
    clean, errors = validate_transaction(raw, accounts=accounts, home_currency=home)
    if errors:
        _raise_invalid(errors)
    saved = queries.insert_transactions(user_id, [{**clean, "source": "manual", "import_batch_id": None}])
    return public_tx(saved[0] if saved else clean, accounts)


def update_transaction(user_id: str, tx_id: str, patch: dict) -> dict:
    if not patch:
        raise api_error("nothing_to_update", "No fields to update.", status.HTTP_400_BAD_REQUEST)
    cur = queries.get_transaction(tx_id, user_id)
    if not cur:
        raise api_error("not_found", "Transaction not found.", status.HTTP_404_NOT_FOUND)
    accounts = _accounts_map(user_id)
    _, home = profile_service.get_country_and_currency(user_id)
    merged = {k: cur.get(k) for k in ("account_id", "symbol", "type", "trade_date", "quantity", "price",
                                      "amount", "currency", "fee", "note")}
    merged.update(patch)
    # a changed quantity/price on a buy/sell recomputes a gross amount the client didn't send
    if merged.get("type") in ("buy", "sell") and "amount" not in patch and ({"quantity", "price"} & set(patch)):
        merged["amount"] = None
    clean, errors = validate_transaction(merged, accounts=accounts, home_currency=home)
    if errors:
        _raise_invalid(errors)
    if cur.get("source") == "auto":   # the user checked it: now it's their record, no longer an estimate
        clean = {**clean, "source": "manual"}
        from app.services.auto_dividends import NOTES
        if clean.get("note") in NOTES:   # Signa's "estimated" note no longer applies
            clean["note"] = None
    row = queries.update_transaction(tx_id, user_id, clean)
    if not row:
        raise api_error("not_found", "Transaction not found.", status.HTTP_404_NOT_FOUND)
    return public_tx(row, accounts)


def delete_transaction(user_id: str, tx_id: str) -> dict:
    cur = queries.get_transaction(tx_id, user_id)
    if cur and cur.get("auto_ref"):   # an automatic dividend the user removed: never re-create it
        queries.add_dismissed_auto_ref(user_id, cur["auto_ref"])
    if not queries.delete_transaction(tx_id, user_id):
        raise api_error("not_found", "Transaction not found.", status.HTTP_404_NOT_FOUND)
    return {"deleted": True, "id": tx_id}


def undo_import(user_id: str, batch_id: str) -> dict:
    n = queries.delete_transaction_batch(user_id, batch_id)
    if not n:
        raise api_error("not_found", "No transactions from this import.", status.HTTP_404_NOT_FOUND)
    return {"deleted": n, "import_batch_id": batch_id}


# ============================================================
# CSV parsing (pure)
# ============================================================

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MONTHS.update({"fev": 2, "abr": 4, "mai": 5, "ago": 8, "set": 9, "out": 10, "dez": 12})   # Portuguese
_NUMERIC_DATE = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})$")
_THOUSANDS = re.compile(r"[1-9]\d{0,2} \d{3}")   # "1 234" after swapping the separator for a space
_ISO_DATE = re.compile(r"^(\d{4})[/.\-]?(\d{1,2})[/.\-]?(\d{1,2})(?:[T\s].*)?$")


def parse_number(s: Any, decimal_comma: bool = False) -> float | None:
    """'1,234.56' / '1.234,56' / '12,5' / '$1 000' -> float; '' -> None;
    garbage -> raises ValueError."""
    if s is None:
        return None
    t = str(s).strip()
    if not t:
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    t = re.sub(r"(?i)(US\$|C\$|CA\$|R\$|€|£|\$|CAD|USD|BRL|EUR)", "", t)
    t = t.replace(" ", "").replace(" ", "").replace("'", "").replace("_", "")
    if t.startswith(("+", "-")):
        neg = neg or t[0] == "-"
        t = t[1:]
    if not t or not re.fullmatch(r"[0-9.,]+", t) or not re.search(r"\d", t):
        raise ValueError("not a number")
    has_c, has_d = "," in t, "." in t
    if has_c and has_d:
        dec = "," if t.rfind(",") > t.rfind(".") else "."
        thou = "." if dec == "," else ","
        t = t.replace(thou, "").replace(dec, ".")
    elif has_c:
        if t.count(",") > 1:
            t = t.replace(",", "")
        else:
            thousands = not decimal_comma and _THOUSANDS.fullmatch(t.replace(",", " "))
            t = t.replace(",", "" if thousands else ".")
    elif has_d and t.count(".") > 1:
        t = t.replace(".", "")
    elif has_d and decimal_comma and _THOUSANDS.fullmatch(t.replace(".", " ")):
        t = t.replace(".", "")
    if t.count(".") > 1:
        raise ValueError("not a number")
    v = float(t)
    return -v if neg else v


def infer_date_order(values: list[str]) -> str | None:
    """'dmy' / 'mdy' when some numeric date proves it, 'conflict', or None."""
    dmy = mdy = False
    for v in values:
        m = _NUMERIC_DATE.match((v or "").strip())
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12 >= b:
            dmy = True
        elif b > 12 >= a:
            mdy = True
    if dmy and mdy:
        return "conflict"
    return "dmy" if dmy else "mdy" if mdy else None


def parse_date(s: Any, order: str = "dmy") -> date:
    """Raises ValueError on anything unparseable."""
    t = str(s or "").strip()
    if not t:
        raise ValueError("empty date")
    m = _ISO_DATE.match(t)
    if m and len(m.group(1)) == 4:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _NUMERIC_DATE.match(t)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        day, month = (a, b) if order == "dmy" else (b, a)
        return date(y, month, day)
    words = re.findall(r"[A-Za-z]+|\d+", t)
    mon = next((_MONTHS[w[:3].lower()] for w in words if w[:3].lower() in _MONTHS and not w.isdigit()), None)
    nums = [int(w) for w in words if w.isdigit()]
    if mon and len(nums) == 2:
        y = next((n for n in nums if n > 31), None)
        d = next((n for n in nums if n <= 31), None)
        if y and d:
            return date(y, mon, d)
    raise ValueError("unrecognised date")


def _header_map(header: list[str]) -> tuple[dict[str, int], list[str]]:
    cols = [str(h or "").strip().lower().lstrip("﻿") for h in header]
    mapping: dict[str, int] = {}
    for key, aliases in _HEADER_ALIASES.items():
        for i, c in enumerate(cols):
            if c in aliases and key not in mapping:
                mapping[key] = i
    ignored = [header[i] for i, _ in enumerate(cols) if i not in mapping.values() and header[i].strip()]
    return mapping, ignored


def decode_csv(content: bytes) -> str:
    if len(content) > MAX_IMPORT_BYTES:
        raise api_error("file_too_large", f"The file is larger than {MAX_IMPORT_BYTES // (1024 * 1024)} MB.",
                        413, max_bytes=MAX_IMPORT_BYTES)
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    raise api_error("invalid_file", "The file is not a text CSV.", 422)


def parse_csv(text: str, *, accounts: list[dict], create_missing_accounts: bool = False,
              date_format: str = "auto", country: str | None = None, home_currency: str = "CAD",
              today: date | None = None) -> dict:
    """Parse + validate every row. Pure (accounts come in). Returns
    {"rows": [...], "summary": {...}, "accounts_to_create": [...]}; raises
    structured 422s for file-level problems."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise api_error("empty_file", "The file is empty.", 422)
    head = lines[0]
    delim = ";" if head.count(";") > head.count(",") else "\t" if head.count("\t") > head.count(",") else ","
    reader = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delim))
    mapping, ignored = _header_map(reader[0])
    missing = [c for c in ("date", "type") if c not in mapping]
    if missing:
        raise api_error("invalid_header", f"Missing column(s): {', '.join(missing)}. Use Signa's template: "
                        + ",".join(TEMPLATE_COLUMNS), 422,
                        expected=list(TEMPLATE_COLUMNS))
    body = reader[1:]
    if len(body) > MAX_IMPORT_ROWS:
        raise api_error("too_many_rows", f"Up to {MAX_IMPORT_ROWS} rows per import (this file has {len(body)}).",
                        422, max_rows=MAX_IMPORT_ROWS, rows=len(body))
    if not body:
        raise api_error("nothing_to_import", "The file has a header but no rows.",
                        422)
    decimal_comma = delim == ";"

    def cell(row: list[str], key: str) -> str:
        i = mapping.get(key)
        return row[i].strip() if i is not None and i < len(row) else ""

    if date_format in ("dmy", "mdy"):
        order = date_format
    else:
        inferred = infer_date_order([cell(r, "date") for r in body])
        if inferred == "conflict":
            raise api_error("ambiguous_dates", "Dates mix day/month and month/day — pass date_format=dmy or mdy.",
                            422)
        order = inferred or ("mdy" if (country or "").upper() == "US" else "dmy")

    by_name = {str(a["name"]).casefold(): a for a in accounts}
    by_id = {str(a["id"]): a for a in accounts}
    to_create: dict[str, dict] = {}   # casefold -> {"name", "currency"}
    rows_out: list[dict] = []
    for n, row in enumerate(body, start=2):   # line 1 = header
        errors: list[dict] = []
        raw: dict[str, Any] = {}
        tval = cell(row, "type").lower()
        raw["type"] = _TYPE_ALIASES.get(tval, tval)
        try:
            raw["trade_date"] = parse_date(cell(row, "date"), order)
        except (ValueError, TypeError):
            raw["trade_date"] = None
            errors.append(_err("date", "invalid_date", f"Unrecognised date '{cell(row, 'date')}'."))
        raw["symbol"] = cell(row, "symbol")
        for f in ("quantity", "price", "amount", "fee"):
            try:
                raw[f] = parse_number(cell(row, f), decimal_comma)
            except ValueError:
                raw[f] = None
                errors.append(_err(f, "invalid_number", f"'{cell(row, f)}' is not a number."))
        raw["currency"] = cell(row, "currency") or None
        raw["note"] = cell(row, "note") or None

        acct_name = " ".join(cell(row, "account").split())
        new_account = None
        if acct_name:
            acct = by_name.get(acct_name.casefold())
            if acct:
                raw["account_id"] = str(acct["id"])
            elif create_missing_accounts and len(acct_name) <= 60:
                ccy = (raw["currency"] or home_currency).upper()
                new_account = to_create.setdefault(acct_name.casefold(), {
                    "name": acct_name, "currency": ccy if re.fullmatch(r"[A-Z]{3}", ccy) else home_currency,
                })
            else:
                errors.append(_err("account", "unknown_account",
                                   f"No account named '{acct_name}' — create it first or import with "
                                   "create_missing_accounts=true."))

        clean = None
        if not errors:
            acct_map = by_id
            if new_account is not None:   # validate against a stand-in for the account to be created
                raw["account_id"] = f"new:{new_account['name'].casefold()}"
                acct_map = {**by_id, raw["account_id"]: {"currency": new_account["currency"]}}
            clean, verrs = validate_transaction(raw, accounts=acct_map, home_currency=home_currency, today=today)
            errors.extend(verrs)
            if clean is not None:
                clean["account_name"] = new_account["name"] if new_account else (
                    by_id[raw["account_id"]]["name"] if raw.get("account_id") else None)
        rows_out.append({"line": n, "status": "error" if errors else "ok", "data": clean, "errors": errors})

    valid = [r for r in rows_out if r["status"] == "ok"]
    dates = sorted(r["data"]["trade_date"] for r in valid)
    by_type: dict[str, int] = {}
    for r in valid:
        by_type[r["data"]["type"]] = by_type.get(r["data"]["type"], 0) + 1
    used_new = {r["data"]["account_id"] for r in valid if str(r["data"]["account_id"] or "").startswith("new:")}
    creates = [v for k, v in to_create.items() if f"new:{k}" in used_new]
    summary = {
        "rows": len(rows_out), "valid": len(valid), "invalid": len(rows_out) - len(valid),
        "by_type": by_type, "symbols": len({r["data"]["symbol"] for r in valid if r["data"]["symbol"]}),
        "date_range": {"from": dates[0], "to": dates[-1]} if dates else None,
        "date_format": order, "delimiter": delim, "ignored_columns": ignored,
        "accounts_to_create": [c["name"] for c in creates],
    }
    return {"rows": rows_out, "summary": summary, "accounts_to_create": creates}


# ============================================================
# Import (sync — run through run_db)
# ============================================================

def import_csv(user_id: str, content: bytes, *, dry_run: bool, create_missing_accounts: bool = False,
               skip_errors: bool = False, date_format: str = "auto") -> dict:
    text = decode_csv(content)
    accounts = queries.get_accounts(user_id)
    country, home = profile_service.get_country_and_currency(user_id)
    parsed = parse_csv(text, accounts=accounts, create_missing_accounts=create_missing_accounts,
                       date_format=date_format, country=country, home_currency=home)
    summary = parsed["summary"]
    errors = [{"line": r["line"], "errors": r["errors"]} for r in parsed["rows"] if r["errors"]]
    if dry_run:
        return {"dry_run": True, "summary": summary, "rows": parsed["rows"],
                "errors": errors[:MAX_ERRORS_RETURNED]}
    if errors and not skip_errors:
        raise api_error("import_has_errors",
                        f"{len(errors)} row(s) have errors — fix them or import with skip_errors=true.",
                        422, summary=summary, errors=errors[:MAX_ERRORS_RETURNED])
    valid = [r["data"] for r in parsed["rows"] if r["status"] == "ok"]
    if not valid:
        raise api_error("nothing_to_import", "No valid rows to import.", 422,
                        summary=summary)
    _check_room(user_id, len(valid))

    created: list[dict] = []
    if parsed["accounts_to_create"]:
        created = queries.insert_accounts(user_id, [
            {"name": c["name"], "currency": c["currency"], "cash_balance": 0} for c in parsed["accounts_to_create"]
        ])
    new_ids = {f"new:{str(a['name']).casefold()}": str(a["id"]) for a in created}

    batch_id = str(uuid.uuid4())
    payload = []
    for d in valid:
        acct = d.get("account_id")
        if acct and str(acct).startswith("new:"):
            acct = new_ids.get(acct)
        payload.append({k: v for k, v in d.items() if k != "account_name"}
                       | {"account_id": acct, "source": "csv", "import_batch_id": batch_id})
    try:
        saved = queries.insert_transactions(user_id, payload)
    except Exception:
        try:   # all-or-nothing: drop any chunk that did land
            queries.delete_transaction_batch(user_id, batch_id)
        except Exception:
            pass
        raise
    return {"dry_run": False, "import_batch_id": batch_id, "imported": len(saved) or len(payload),
            "skipped": len(errors), "accounts_created": [{"id": a["id"], "name": a["name"]} for a in created],
            "summary": summary, "errors": errors[:MAX_ERRORS_RETURNED]}


def template_csv() -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(TEMPLATE_COLUMNS)
    for row in TEMPLATE_EXAMPLES:
        w.writerow(row)
    return buf.getvalue()
