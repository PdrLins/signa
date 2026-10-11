"""Import any broker's or bank's CSV: inspect the file, suggest which column is
which, turn rows into Signa's template fields with a mapping, save mappings.
No AI: header aliases and word lists in English, French and Portuguese, and
a few generic description patterns (for cash-ledger exports that keep the
symbol and quantity inside a text column).

Flow: POST /transactions/import/inspect (file kept FILE_TTL_S, `file_id`) ->
the app confirms the mapping -> POST /transactions/import {file_id, mapping}
(dry run, then the real import: transactions_service.finish_rows /
import_parsed, the same validation, preview and Undo as the template).

Rows without a type: a symbol + quantity makes a trade (negative quantity or, with
signed amounts, money in = sell; else buy); otherwise, with signed amounts, money in =
deposit and money out = withdrawal. Rows whose type value is mapped use that type;
an unmapped value is an unknown_type error (or the description's type when it has one).

Mapping = {"fields": {field: column index}, "date_format": "auto" | "YYYY-MM-DD" |
           "DD/MM/YYYY" | "MM/DD/YYYY", "decimal": "." | ",", "amount_sign": "signed" |
           "positive", "type_values": {file value: Signa type}, "skip_type_values": [...],
           "extract_from_description": bool, "default_currency": "CAD" | null,
           "account": {"column": index | null, "fixed_account_id": id | null,
                       "names": {file name: account id}}}
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import secrets
import time
import unicodedata
from collections import Counter
from typing import Any

from app.core.api_errors import api_error
from app.core.cache import TTLCache

FIELDS = ("date", "type", "symbol", "quantity", "price", "amount", "currency", "fee", "account", "note")
FILE_TTL_S = 30 * 60
MAX_HEADER_SCAN = 20
MAX_TYPE_VALUES = 50
MAX_SAMPLES = 3
MAX_MAPPINGS = 20
DATE_FORMATS = {"auto": None, "YYYY-MM-DD": "dmy", "DD/MM/YYYY": "dmy", "MM/DD/YYYY": "mdy"}
SIGNA_TYPES = ("buy", "sell", "dividend", "deposit", "withdrawal", "split", "fee")

# header aliases, accent-free lowercase, best match first within each field
HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("trade date", "transaction date", "date", "data do pregao", "data da operacao", "data",
             "date de transaction", "date d'operation", "date de l'operation", "date de negociation",
             "process date", "settlement date", "settle date", "data de liquidacao", "date de reglement",
             "posted date", "value date"),
    "type": ("transaction type", "activity type", "type", "transaction", "action", "activity", "tipo de operacao",
             "tipo de movimentacao", "tipo", "operacao", "movimentacao", "type de transaction", "operation",
             "nature"),
    "symbol": ("symbol", "ticker", "ticker symbol", "codigo de negociacao", "codigo", "ativo", "papel",
               "security", "symbole", "titre", "produto", "instrument"),
    "quantity": ("quantity", "qty", "shares", "units", "quantidade", "qtd", "qtde", "quantite", "nombre de parts",
                 "nombre"),
    "price": ("price", "unit price", "price per share", "preco", "preco unitario", "prix", "prix unitaire",
              "cours"),
    "amount": ("net amount", "amount", "total", "total amount", "value", "valor da operacao", "valor liquido",
               "valor", "montant net", "montant", "net", "gross amount"),
    "currency": ("currency", "ccy", "currency code", "moeda", "devise"),
    "fee": ("commission", "commissions", "fee", "fees", "taxa", "taxas", "corretagem", "emolumentos", "frais"),
    "account": ("account", "account name", "account number", "account type", "conta", "compte"),
    "note": ("description", "details", "memo", "note", "notes", "descricao", "historico", "detalhes",
             "libelle", "libelle de l'operation"),
}

# type words (accent-free lowercase): exact values first, then words/phrases inside the value
TYPE_EXACT = {"b": "buy", "c": "buy", "s": "sell", "v": "sell", "cont": "deposit", "div": "dividend",
              "dep": "deposit", "wd": "withdrawal", "jcp": "dividend"}
TYPE_WORDS: tuple[tuple[str, str | None], ...] = (
    ("juros sobre capital", "dividend"), ("stock split", "split"), ("reverse split", "split"),
    ("buy", "buy"), ("bought", "buy"), ("purchase", "buy"), ("achat", "buy"), ("compra", "buy"),
    ("sell", "sell"), ("sold", "sell"), ("sale", "sell"), ("vente", "sell"), ("venda", "sell"),
    ("dividend", "dividend"), ("dividende", "dividend"), ("dividendo", "dividend"), ("rendimento", "dividend"),
    ("distribution", "dividend"), ("distribuicao", "dividend"), ("provento", "dividend"),
    ("deposit", "deposit"), ("contribution", "deposit"), ("depot", "deposit"), ("deposito", "deposit"),
    ("aporte", "deposit"), ("cotisation", "deposit"),
    ("withdrawal", "withdrawal"), ("withdraw", "withdrawal"), ("retrait", "withdrawal"), ("saque", "withdrawal"),
    ("retirada", "withdrawal"),
    ("fee", "fee"), ("frais", "fee"), ("taxa", "fee"), ("tarifa", "fee"), ("commission", "fee"),
    ("custodia", "fee"),
    ("split", "split"), ("desdobramento", "split"), ("grupamento", "split"), ("fractionnement", "split"),
    # no Signa type: the user decides (often deposit) or skips them
    ("interest", None), ("interet", None), ("juros", None),
)

_TICKER = r"[A-Z][A-Z0-9]{0,6}(?:[.\-][A-Z0-9]{1,4})?"
# generic description patterns (cash-ledger exports keep the trade in a text column)
_DESC_SYMBOL_PREFIX = re.compile(rf"^\s*(?P<sym>{_TICKER})\s*[:\-–]\s+")
_DESC_TRADE = re.compile(
    r"(?P<verb>bought|sold|buy|sell|purchased?|achat(?: de)?|vente(?: de)?|achete|vendu|compra(?: de)?|venda(?: de)?"
    r"|comprou|vendeu)\s+(?P<qty>\d[\d.,]*)\s*(?:shares?|units?|actions?|acoes|acao|cotas?|parts?|titres?)?"
    rf"(?:\s+(?:of|de|du|da|do)\s+(?P<sym>{_TICKER}))?"
    r"(?:\s+(?:at|@|à|a|por|au prix de|à preço de|a preço de|a preco de)\s*(?:US\$|C\$|R\$|\$|€)?\s*(?P<price>\d[\d.,]*))?", re.I)
_DESC_DIVIDEND = re.compile(r"\b(dividend|dividende|dividendo|distribution|rendimento|jcp|provento)", re.I)
_DESC_SYMBOL_ANY = re.compile(rf"\b(?:of|de|du|on|sur|em)\s+(?P<sym>{_TICKER})\b")
_CCY_HINT = re.compile(r"(?i)\b(USD|CAD|BRL|EUR|GBP)\b|US\$|C\$|R\$|€|£")

_files = TTLCache(max_size=200, default_ttl=FILE_TTL_S)


def _plain(s: Any) -> str:
    """Lowercase, trimmed, accents removed, inner spaces collapsed."""
    t = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return " ".join(t.lower().replace("_", " ").split()).strip(" :")


# ============================================================
# Reading the file (pure)
# ============================================================

def decode(content: bytes) -> tuple[str, str]:
    """(text, "utf-8" | "latin-1")."""
    try:
        return content.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        return content.decode("cp1252", errors="replace"), "latin-1"


def detect_delimiter(lines: list[str]) -> str:
    best, score = ",", -1.0
    for d in (",", ";", "\t", "|"):
        counts = [ln.count(d) for ln in lines[:40] if ln.strip()]
        counts = [c for c in counts if c]
        if not counts:
            continue
        common = Counter(counts).most_common(1)[0]
        s = common[1] * (1 + min(common[0], 10) / 100)   # most lines agreeing, more columns break ties
        if s > score:
            best, score = d, s
    return best


def _cells(row: list[str]) -> list[str]:
    out = [c.strip() for c in row]
    while out and not out[-1]:
        out.pop()
    return out


def _is_value(c: str) -> bool:
    return bool(re.fullmatch(r"[-+()$€£R\d\s.,/:%A-Z]*\d[-+()$€£\d\s.,/:%]*", c or ""))


def find_header(rows: list[list[str]]) -> int:
    """Index of the header row among the first MAX_HEADER_SCAN rows: the row
    with the most known header names (then the first with the file's usual
    width and mostly text cells)."""
    widths = Counter(len(_cells(r)) for r in rows[:200] if len(_cells(r)) >= 2)
    width = widths.most_common(1)[0][0] if widths else 0
    best, best_score = 0, -1
    for i, r in enumerate(rows[:MAX_HEADER_SCAN]):
        cells = _cells(r)
        if len(cells) < 2:
            continue
        texts = [c for c in cells if c and not _is_value(c)]
        if len(texts) < max(2, len(cells) // 2):
            continue
        hits = sum(1 for c in cells if any(_plain(c) in al for al in HEADER_ALIASES.values()))
        score = hits * 10 + (5 if len(cells) >= width - 1 else 0)
        if score > best_score:
            best, best_score = i, score
    return best


def detect_decimal(values: list[str], delimiter: str) -> str:
    comma = dot = 0
    for v in values:
        t = re.sub(r"[^\d.,]", "", v or "")
        if re.search(r"\d,\d{1,2}$", t) and ("." not in t or t.rfind(".") < t.rfind(",")):
            comma += 1
        elif re.search(r"\d\.\d{1,2}$", t) or re.search(r"\d,\d{3}\.\d", t):
            dot += 1
    if comma > dot:
        return ","
    return "," if (delimiter == ";" and not dot) else "."


def signature(headers: list[str]) -> str:
    norm = "|".join(" ".join(str(h or "").strip().lower().split()) for h in headers)
    return hashlib.sha256(norm.encode()).hexdigest()[:24]


def read(content: bytes) -> dict:
    """{"text", "encoding", "delimiter", "header_index", "headers", "body" (rows after the header,
    blank rows dropped)}. Raises empty_file / invalid_file."""
    from app.services.transactions_service import MAX_IMPORT_BYTES
    if len(content) > MAX_IMPORT_BYTES:
        raise api_error("file_too_large", f"The file is larger than {MAX_IMPORT_BYTES // (1024 * 1024)} MB.",
                        413, max_bytes=MAX_IMPORT_BYTES)
    text, enc = decode(content)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise api_error("empty_file", "The file is empty.", 422)
    delim = detect_delimiter(lines)
    rows = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delim))
    h = find_header(rows)
    headers = [c.strip().lstrip("﻿") for c in rows[h]]
    body = [r for r in rows[h + 1:] if any(c.strip() for c in r)]
    return {"encoding": enc, "delimiter": delim, "header_index": h, "headers": headers, "body": body}


# ============================================================
# Suggestions (pure)
# ============================================================

def suggest_fields(headers: list[str]) -> dict[str, int]:
    plain = [_plain(h) for h in headers]
    out: dict[str, int] = {}
    used: set[int] = set()
    for field, aliases in HEADER_ALIASES.items():
        for alias in aliases:   # best alias first
            idx = next((i for i, p in enumerate(plain) if p == alias and i not in used), None)
            if idx is not None:
                out[field] = idx
                used.add(idx)
                break
    return out


def suggest_type(value: str) -> str | None:
    p = _plain(value)
    if p in TYPE_EXACT:
        return TYPE_EXACT[p]
    for word, typ in TYPE_WORDS:
        if re.search(rf"(?<![a-z]){re.escape(word)}", p):
            return typ
    return None


def extract(text: str) -> dict:
    """{"type"?, "symbol"?, "quantity"? (str), "price"? (str)} read from a description. Pure."""
    t = str(text or "")
    out: dict = {}
    m = _DESC_SYMBOL_PREFIX.match(t)
    if m:
        out["symbol"] = m.group("sym")
    tm = _DESC_TRADE.search(t)
    if tm:
        verb = _plain(tm.group("verb"))
        out["type"] = "sell" if verb.startswith(("sell", "sold", "vent", "vend")) else "buy"
        out["quantity"] = tm.group("qty")
        if tm.group("price"):
            out["price"] = tm.group("price")
        if tm.group("sym"):
            out.setdefault("symbol", tm.group("sym"))
    elif _DESC_DIVIDEND.search(t):
        out["type"] = "dividend"
    if "symbol" not in out and out.get("type"):
        sm = _DESC_SYMBOL_ANY.search(t)
        if sm:
            out["symbol"] = sm.group("sym")
    return out


def _column(body: list[list[str]], i: int | None) -> list[str]:
    if i is None:
        return []
    return [r[i].strip() for r in body if i < len(r)]


def inspect(content: bytes, country: str | None = None) -> dict:
    """The inspect answer without file_id / saved_mapping / account names lookups. Pure."""
    from app.services.transactions_service import MAX_IMPORT_ROWS, infer_date_order
    f = read(content)
    headers, body = f["headers"], f["body"]
    fields = suggest_fields(headers)
    columns = []
    for i, h in enumerate(headers):
        samples = [v for v in _column(body, i) if v][:MAX_SAMPLES]
        columns.append({"index": i, "header": h, "samples": samples})
    numeric = [v for k in ("amount", "price", "quantity", "fee") for v in _column(body, fields.get(k))[:200]]
    decimal = detect_decimal(numeric, f["delimiter"])
    warnings = []
    dates = [v for v in _column(body, fields.get("date")) if v]
    date_format = "auto"
    if "date" not in fields:
        warnings.append("no_date_column")
    else:
        order = infer_date_order(dates)
        iso = sum(1 for d in dates[:200] if re.match(r"^\d{4}[-/.]", d))
        if order == "conflict":
            warnings.append("ambiguous_dates")
        elif iso and iso >= len(dates[:200]) / 2:
            date_format = "YYYY-MM-DD"
        elif order:
            date_format = "DD/MM/YYYY" if order == "dmy" else "MM/DD/YYYY"
        elif any(re.match(r"^\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}$", d) for d in dates):
            date_format = "MM/DD/YYYY" if (country or "").upper() == "US" else "DD/MM/YYYY"
    amounts = _column(body, fields.get("amount"))
    if "amount" not in fields and not ("quantity" in fields and "price" in fields):
        warnings.append("no_amount_column")
    if "symbol" not in fields:
        warnings.append("no_symbol_column")
    if "currency" not in fields and len({m.group(0).upper().replace("US$", "USD").replace("C$", "CAD")
                                         .replace("R$", "BRL").replace("€", "EUR").replace("£", "GBP")
                                         for v in amounts for m in _CCY_HINT.finditer(v)}) > 1:
        warnings.append("mixed_currencies_no_column")
    if len(body) > MAX_IMPORT_ROWS:
        warnings.append("too_many_rows")
    amount_sign = "signed" if any(re.match(r"^\s*(-|\()", a) for a in amounts) else "positive"
    type_values = []
    if "type" in fields:
        counts = Counter(v for v in _column(body, fields["type"]) if v)
        type_values = [{"value": v, "count": n, "suggested": suggest_type(v)}
                       for v, n in counts.most_common(MAX_TYPE_VALUES)]
    extract_desc = False
    if "symbol" not in fields or "quantity" not in fields:
        best = 0.0
        for i, h in enumerate(headers):
            if i in fields.values() and i != fields.get("note"):
                continue
            col = [v for v in _column(body, i) if v]
            if col:
                hit = sum(1 for v in col if extract(v).get("symbol") or extract(v).get("quantity")) / len(col)
                if hit > best:
                    best, best_i = hit, i
        if best >= 0.2:
            extract_desc = True
            fields.setdefault("note", best_i)
    accounts = sorted({v for v in _column(body, fields.get("account")) if v})[:100] if "account" in fields else []
    return {
        "delimiter": f["delimiter"], "encoding": f["encoding"], "decimal": decimal,
        "header_row": f["header_index"] + 1, "rows": len(body), "columns": columns,
        "signature": signature(headers),
        "suggested": {"fields": fields, "date_format": date_format, "amount_sign": amount_sign,
                      "type_values": type_values, "extract_from_description": extract_desc},
        "account_names": accounts, "warnings": warnings,
    }


# ============================================================
# Applying a mapping (pure)
# ============================================================

def validate_mapping(m: Any, width: int) -> dict:
    """The mapping, cleaned; 422 invalid_mapping with "field"."""
    def bad(field: str, msg: str):
        return api_error("invalid_mapping", msg, 422, field=field)
    if not isinstance(m, dict) or not isinstance(m.get("fields"), dict):
        raise bad("fields", "mapping.fields is required.")
    fields: dict[str, int] = {}
    for k, v in m["fields"].items():
        if v is None:
            continue
        if k not in FIELDS:
            raise bad(f"fields.{k}", f"Unknown field '{k}'.")
        if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v < width:
            raise bad(f"fields.{k}", f"Column {v} doesn't exist in this file.")
        fields[k] = v
    if "date" not in fields:
        raise bad("fields.date", "Pick the column with the date.")
    extract_desc = bool(m.get("extract_from_description"))
    if "amount" not in fields and not ("quantity" in fields and "price" in fields) and not extract_desc:
        raise bad("fields.amount", "Pick the amount column, or quantity and price.")
    fmt = m.get("date_format") or "auto"
    if fmt not in DATE_FORMATS:
        raise bad("date_format", f"date_format must be one of {', '.join(DATE_FORMATS)}.")
    dec = m.get("decimal") or "."
    if dec not in (".", ","):
        raise bad("decimal", "decimal must be '.' or ','.")
    sign = m.get("amount_sign") or "positive"
    if sign not in ("signed", "positive"):
        raise bad("amount_sign", "amount_sign must be 'signed' or 'positive'.")
    tv = m.get("type_values") or {}
    if not isinstance(tv, dict) or any(v not in SIGNA_TYPES for v in tv.values()):
        raise bad("type_values", f"type_values must map to one of {', '.join(SIGNA_TYPES)}.")
    skip = m.get("skip_type_values") or []
    if not isinstance(skip, list):
        raise bad("skip_type_values", "skip_type_values must be a list.")
    ccy = m.get("default_currency")
    if ccy is not None and not re.fullmatch(r"[A-Z]{3}", str(ccy).upper()):
        raise bad("default_currency", "default_currency must be a 3-letter code.")
    acct = m.get("account") or {}
    if not isinstance(acct, dict):
        raise bad("account", "account must be an object.")
    col = acct.get("column", fields.get("account"))
    if col is not None and (not isinstance(col, int) or not 0 <= col < width):
        raise bad("account.column", f"Column {col} doesn't exist in this file.")
    names = acct.get("names") or {}
    if not isinstance(names, dict):
        raise bad("account.names", "account.names must map names to account ids.")
    return {"fields": fields, "date_format": fmt, "decimal": dec, "amount_sign": sign,
            "type_values": {str(k).strip(): v for k, v in tv.items()},
            "skip_type_values": [str(s).strip() for s in skip],
            "extract_from_description": extract_desc,
            "default_currency": str(ccy).upper() if ccy else None,
            "account": {"column": col, "fixed_account_id": acct.get("fixed_account_id"),
                        "names": {" ".join(str(k).split()).casefold(): str(v) for k, v in names.items()}}}


def _ticker(raw: str) -> str:
    """A symbol cell: "SGN-B", "SGNB3 - SIGNA PN" -> "SGNB3", "$SGN" -> "SGN"."""
    t = (raw or "").strip().lstrip("$")
    t = re.split(r"\s+-\s+|\s{2,}|\s*\(", t)[0].strip()
    return t.split()[0] if t else ""


def to_records(body: list[list[str]], mapping: dict, *, order: str, accounts: list[dict]) -> tuple[list[dict], int]:
    """Rows -> finish_rows records (typed template fields), and how many rows the
    mapping skipped on purpose (skip_type_values). Lines are counted from the
    header (header = line 1). Pure."""
    from app.services.transactions_service import _err, parse_date, parse_number

    f = mapping["fields"]
    comma = mapping["decimal"] == ","
    signed = mapping["amount_sign"] == "signed"
    tv = {k.casefold(): v for k, v in mapping["type_values"].items()}
    skip = {s.casefold() for s in mapping["skip_type_values"]}
    acct = mapping["account"]
    mine = {str(a["id"]) for a in accounts}
    out, skipped = [], 0

    def cell(row: list[str], key: str) -> str:
        i = f.get(key)
        return row[i].strip() if i is not None and i < len(row) else ""

    for n, row in enumerate(body, start=2):
        errors: list[dict] = []
        tval = cell(row, "type")
        if tval and tval.casefold() in skip:
            skipped += 1
            continue
        if not cell(row, "date") and not cell(row, "amount"):
            skipped += 1   # blank / summary line
            continue
        raw: dict[str, Any] = {}
        try:
            raw["trade_date"] = parse_date(cell(row, "date"), order)
        except (ValueError, TypeError):
            raw["trade_date"] = None
            errors.append(_err("date", "invalid_date", f"Unrecognised date '{cell(row, 'date')}'."))
        nums: dict[str, float | None] = {}
        for k in ("quantity", "price", "amount", "fee"):
            try:
                nums[k] = parse_number(cell(row, k), comma)
            except ValueError:
                nums[k] = None
                errors.append(_err(k, "invalid_number", f"'{cell(row, k)}' is not a number."))
        found = extract(cell(row, "note")) if mapping["extract_from_description"] else {}
        typ = None
        if "type" in f:
            if tval.casefold() in tv:
                typ = tv[tval.casefold()]
            elif tval and found.get("type"):
                typ = found["type"]
            else:
                errors.append(_err("type", "unknown_type", f"No Signa type chosen for '{tval}'."))
        else:
            typ = found.get("type")
        amt = nums["amount"]
        qty_cell = nums["quantity"]
        if typ is None and not errors:
            if (cell(row, "symbol") or found.get("symbol")) and (qty_cell or found.get("quantity")):
                # a trade without a type column: a negative quantity (or money in) is a sale
                typ = "sell" if (qty_cell or 0) < 0 or (signed and (amt or 0) > 0) else "buy"
            elif amt is None or not signed:
                errors.append(_err("type", "unknown_type", "This row has no type."))
            else:
                typ = "deposit" if amt >= 0 else "withdrawal"
        raw["type"] = typ or ""
        sym = _ticker(cell(row, "symbol")) or found.get("symbol") or ""
        raw["symbol"] = sym if typ not in ("deposit", "withdrawal") else ""
        for k in ("quantity", "price"):
            v = nums[k]
            if v is None and found.get(k):
                try:
                    v = parse_number(found[k], comma)
                except ValueError:
                    v = None
            raw[k] = abs(v) if v is not None else None
        raw["amount"] = abs(amt) if amt is not None else None
        raw["fee"] = abs(nums["fee"]) if nums["fee"] is not None else None
        raw["currency"] = (cell(row, "currency").upper() or mapping["default_currency"] or None)
        raw["note"] = cell(row, "note")[:500] or None
        rec = {"line": n, "raw": raw, "errors": errors}
        if acct["fixed_account_id"]:
            rec["account_id"] = str(acct["fixed_account_id"])
            if rec["account_id"] not in mine:
                errors.append(_err("account", "unknown_account", "Account not found."))
        elif acct["column"] is not None:
            name = row[acct["column"]].strip() if acct["column"] < len(row) else ""
            target = acct["names"].get(" ".join(name.split()).casefold())
            if target:
                rec["account_id"] = target
                if target not in mine:
                    errors.append(_err("account", "unknown_account", "Account not found."))
            else:
                rec["account_name"] = name
        out.append(rec)
    return out, skipped


# ============================================================
# Stored files (in memory, per user, FILE_TTL_S)
# ============================================================

def keep_file(user_id: str, content: bytes) -> str:
    file_id = "imp_" + secrets.token_urlsafe(16)
    _files.set(file_id, {"user_id": str(user_id), "content": content, "at": time.time()})
    return file_id


def get_file(user_id: str, file_id: str) -> bytes:
    hit = _files.get(str(file_id or ""))
    if not hit or hit["user_id"] != str(user_id):
        raise api_error("import_file_expired", "That upload expired. Choose the file again.", 404)
    return hit["content"]


def drop_file(file_id: str) -> None:
    _files.delete(str(file_id or ""))


# ============================================================
# Saved mappings (blocking; migration 035)
# ============================================================

MIGRATION = "035_import_mappings.sql"
MAPPING_COLUMNS = "id, name, signature, headers, updated_at"


def _db():
    from app.db.supabase import get_client
    return get_client()


def saved_for(user_id: str, sig: str) -> dict | None:
    """The saved mapping for this signature, or None (also before migration 035)."""
    try:
        rows = (_db().table("import_mappings").select("mapping").eq("user_id", user_id).eq("signature", sig)
                .limit(1).execute().data or [])
    except Exception:
        return None
    return rows[0]["mapping"] if rows else None


def list_mappings(user_id: str) -> dict:
    rows = (_db().table("import_mappings").select(MAPPING_COLUMNS).eq("user_id", user_id)
            .order("updated_at", desc=True).execute().data or [])
    return {"items": rows}


def save(user_id: str, sig: str, headers: list[str], name: str, mapping: dict) -> None:
    """Upsert by (user, signature); past MAX_MAPPINGS the oldest goes. Never raises."""
    from datetime import datetime, timezone

    from loguru import logger
    try:
        db = _db()
        now = datetime.now(timezone.utc).isoformat()
        db.table("import_mappings").upsert({
            "user_id": user_id, "signature": sig, "name": (name or "My import").strip()[:60] or "My import",
            "headers": headers, "mapping": mapping, "updated_at": now,
        }, on_conflict="user_id,signature").execute()
        rows = (db.table("import_mappings").select("id").eq("user_id", user_id)
                .order("updated_at", desc=True).execute().data or [])
        for r in rows[MAX_MAPPINGS:]:
            db.table("import_mappings").delete().eq("id", r["id"]).eq("user_id", user_id).execute()
    except Exception as e:
        logger.warning(f"import mapping not saved: {type(e).__name__}")


def rename(user_id: str, mapping_id: str, name: Any) -> dict:
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 60:
        raise api_error("invalid_name", "name must be text up to 60 characters.", 422, field="name")
    res = (_db().table("import_mappings").update({"name": name.strip()}).eq("id", mapping_id)
           .eq("user_id", user_id).execute())
    if not res.data:
        raise api_error("mapping_not_found", "Saved import not found.", 404)
    r = res.data[0]
    return {k: r.get(k) for k in ("id", "name", "signature", "headers", "updated_at")}


def delete(user_id: str, mapping_id: str) -> dict:
    res = _db().table("import_mappings").delete().eq("id", mapping_id).eq("user_id", user_id).execute()
    if not res.data:
        raise api_error("mapping_not_found", "Saved import not found.", 404)
    return {"deleted": True, "id": mapping_id}


# ============================================================
# The two calls (blocking: run with run_db)
# ============================================================

def inspect_upload(user_id: str, content: bytes) -> dict:
    from app.services import profile_service
    country, _home = profile_service.get_country_and_currency(user_id)
    out = inspect(content, country)
    return {"file_id": keep_file(user_id, content), **out, "saved_mapping": saved_for(user_id, out["signature"])}


def import_with_mapping(user_id: str, body: dict) -> dict:
    """POST /transactions/import with {"file_id", "mapping", ...}: the file's rows through
    the mapping, then the template's validation, duplicates, dry run / import."""
    from app.db import queries
    from app.services import profile_service
    from app.services import transactions_service as ts

    content = get_file(user_id, body.get("file_id"))
    f = read(content)
    mapping = validate_mapping(body.get("mapping"), len(f["headers"]))
    if len(f["body"]) > ts.MAX_IMPORT_ROWS:
        raise api_error("too_many_rows", f"Up to {ts.MAX_IMPORT_ROWS} rows per import (this file has "
                        f"{len(f['body'])}).", 422, max_rows=ts.MAX_IMPORT_ROWS, rows=len(f["body"]))
    accounts = queries.get_accounts(user_id)
    country, home = profile_service.get_country_and_currency(user_id)
    order = DATE_FORMATS[mapping["date_format"]]
    if order is None:
        di = mapping["fields"]["date"]
        inferred = ts.infer_date_order([r[di].strip() for r in f["body"] if di < len(r)])
        if inferred == "conflict":
            raise api_error("ambiguous_dates", "Dates mix day/month and month/day — choose the date format.", 422)
        order = inferred or ("mdy" if (country or "").upper() == "US" else "dmy")
    records, skipped = to_records(f["body"], mapping, order=order, accounts=accounts)
    if not records:
        raise api_error("nothing_to_import", "No rows to import with this matching.", 422)
    parsed = ts.finish_rows(records, accounts=accounts,
                            create_missing_accounts=bool(body.get("create_missing_accounts")),
                            home_currency=home,
                            extra={"date_format": order, "delimiter": f["delimiter"], "ignored_columns": [],
                                   "skipped_by_mapping": skipped})
    dry_run = body.get("dry_run", True) is not False
    result = ts.import_parsed(user_id, parsed, dry_run=dry_run, skip_errors=bool(body.get("skip_errors")))
    if not dry_run:
        drop_file(body.get("file_id"))
        sm = body.get("save_mapping")
        if isinstance(sm, dict):
            save(user_id, signature(f["headers"]), f["headers"], str(sm.get("name") or ""), body["mapping"])
    return result
