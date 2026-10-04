"""My holdings — the owner's REAL long-term positions (not the paper brain).

This module is pure logic + yfinance lookups; persistence lives in
app/db/queries.py (holdings table, migration 010) and the daily monitor in
services/holdings_monitor.py.

  parse_holdings_text   one-per-line / CSV / tab / "@" import text -> rows
  resolve_rows          rows -> candidate listings (TSX preferred, ambiguity
                        flagged: ENS -> ENS.TO "E Split Corp" vs ENS "EnerSys")
  portfolio_math        value / weight / unrealized gain per holding, totals
                        in CAD (USD converted with CAD=X)
  review_summary        long_term_check result -> compact `last_review`
  allocate_ideas        "where could new cash go?" — ranked considerations,
                        never amounts or buy instructions
  overlap_notes         fund overlap / covered-call / leverage information

Every feature works without shares or average cost.
"""

from __future__ import annotations

import asyncio
import csv
import io
import math
import re
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from app.core.cache import TTLCache
from app.core.config import settings
from app.core.utils import validate_ticker

MAX_IMPORT_LINES = 100
MAX_IMPORT_CHARS = 20_000
RESOLVE_CONCURRENCY = 6

ACCOUNTS = ("TFSA", "RRSP", "FHSA", "NON_REGISTERED", "OTHER")
_ACCOUNT_ALIASES = {
    "TFSA": "TFSA", "CELI": "TFSA",
    "RRSP": "RRSP", "REER": "RRSP",
    "FHSA": "FHSA", "CELIAPP": "FHSA",
    "NON_REGISTERED": "NON_REGISTERED", "NONREGISTERED": "NON_REGISTERED", "NON-REGISTERED": "NON_REGISTERED",
    "NON REGISTERED": "NON_REGISTERED", "TAXABLE": "NON_REGISTERED", "OTHER": "OTHER",
}

# Words that can appear in free text but are not tickers.
_STOPWORDS = {"SHARES", "SHARE", "UNITS", "UNIT", "QTY", "@"}

_HEADER_ALIASES = {
    "symbol": ("symbol", "ticker", "stock", "security", "code"),
    "shares": ("shares", "quantity", "qty", "units", "amount"),
    "avg_cost": ("avg_cost", "avg cost", "average cost", "avg price", "average price", "avgcost",
                 "cost", "price paid", "book cost per share", "cost per share", "acb"),
    "account": ("account", "account type", "acct"),
}

_NUM_RE = re.compile(r"^(?:C\$|US\$|\$)?\d+(?:\.\d+)?$", re.IGNORECASE)


def _clean_num(tok: str) -> float | None:
    t = tok.strip().upper().replace("C$", "").replace("US$", "").replace("$", "").replace("_", "")
    if not t or not re.fullmatch(r"\d+(?:\.\d+)?", t):
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    return v if math.isfinite(v) and v > 0 else None


def _is_num(tok: str) -> bool:
    return bool(_NUM_RE.match(tok.strip()))


def normalize_account(raw: str | None) -> str | None:
    if not raw:
        return None
    k = str(raw).strip().upper()
    return _ACCOUNT_ALIASES.get(k) or _ACCOUNT_ALIASES.get(re.sub(r"[\s_\-]+", " ", k))


def _norm_symbol(tok: str) -> str | None:
    s = tok.strip().upper().lstrip("$").strip()
    if not s or s in _STOPWORDS or not re.search(r"[A-Z]", s):
        return None
    return s


# ============================================================
# Parsing
# ============================================================

def _header_map(cells: list[str]) -> dict[str, int] | None:
    lowered = [c.strip().lower() for c in cells]
    out: dict[str, int] = {}
    for key, aliases in _HEADER_ALIASES.items():
        for i, c in enumerate(lowered):
            if c in aliases and i not in out.values():
                out[key] = i
                break
    return out if "symbol" in out else None


def _row(line: int, raw: str, sym: str, shares=None, avg_cost=None, account=None, error=None) -> dict:
    return {"line": line, "raw": raw[:200], "input": sym, "shares": shares, "avg_cost": avg_cost,
            "account": account, "error": error}


def _parse_free_line(line_no: int, raw: str) -> list[dict]:
    """Free-form line: tickers, each optionally followed by shares and an
    average cost ("NVDA 17.99", "RY.TO 4.1 @ 145.20", "XEQT, COST, NVDA")."""
    text = raw.replace("@", " @ ")
    tokens = [t for t in re.split(r"[,\t;|]+|\s+", text) if t.strip()]
    rows: list[dict] = []
    cur: dict | None = None
    expect_cost = False
    for tok in tokens:
        if tok == "@" or tok.upper() == "AT":
            expect_cost = True
            continue
        acct = normalize_account(tok)
        if acct and cur is not None and not _is_num(tok):
            cur["account"] = acct
            continue
        if _is_num(tok):
            v = _clean_num(tok)
            if cur is None or v is None:
                continue
            if expect_cost or cur["shares"] is not None:
                if cur["avg_cost"] is None:
                    cur["avg_cost"] = v
            else:
                cur["shares"] = v
            expect_cost = False
            continue
        sym = _norm_symbol(tok)
        if sym is None:
            continue
        cur = _row(line_no, raw, sym)
        rows.append(cur)
        expect_cost = False
    return rows


def parse_holdings_text(text: str) -> list[dict]:
    """Parse pasted import text into rows:
        {"line", "raw", "input", "shares", "avg_cost", "account", "error"}

    Accepts one holding per line ("XEQT", "NVDA 17.99", "RY.TO 4.1 @ 145.20"),
    comma / tab / semicolon separated values, several bare tickers on one
    line, and CSV with a header row (symbol/ticker, shares/quantity,
    avg_cost/average cost, account). Blank lines and '#' comments are
    skipped. Duplicate symbols are merged (shares summed; average cost
    weighted when every part has one).
    """
    text = (text or "")[:MAX_IMPORT_CHARS]
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    rows: list[dict] = []
    header: dict[str, int] | None = None
    delim = ","
    for idx, raw in enumerate(lines[: MAX_IMPORT_LINES * 2], start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if header is None and not rows:
            d = "\t" if "\t" in stripped else (";" if ";" in stripped else ",")
            cells = next(csv.reader(io.StringIO(stripped), delimiter=d), [])
            hm = _header_map(cells) if len(cells) > 1 else None
            if hm:
                header, delim = hm, d
                continue
        if header is not None:
            cells = next(csv.reader(io.StringIO(stripped), delimiter=delim), [])
            get = lambda k: cells[header[k]].strip() if k in header and header[k] < len(cells) else ""  # noqa: E731
            sym = _norm_symbol(get("symbol"))
            if not sym:
                continue
            shares = _clean_num(get("shares").replace(",", "")) if get("shares") else None
            cost = _clean_num(get("avg_cost").replace(",", "")) if get("avg_cost") else None
            rows.append(_row(idx, stripped, sym, shares, cost, normalize_account(get("account"))))
        else:
            rows.extend(_parse_free_line(idx, stripped))
        if len(rows) >= MAX_IMPORT_LINES:
            break

    # validate + merge duplicates
    merged: dict[str, dict] = {}
    out: list[dict] = []
    for r in rows[:MAX_IMPORT_LINES]:
        if len(r["input"]) > 20 or not validate_ticker(r["input"]):
            r["error"] = "invalid_ticker"
            out.append(r)
            continue
        prev = merged.get(r["input"])
        if prev is None:
            merged[r["input"]] = r
            out.append(r)
            continue
        prev["merged"] = int(prev.get("merged") or 1) + 1
        if prev["shares"] is not None and r["shares"] is not None:
            total = prev["shares"] + r["shares"]
            if prev["avg_cost"] is not None and r["avg_cost"] is not None:
                prev["avg_cost"] = round((prev["shares"] * prev["avg_cost"] + r["shares"] * r["avg_cost"]) / total, 6)
            else:
                prev["avg_cost"] = None
            prev["shares"] = round(total, 8)
        elif r["shares"] is not None or prev["shares"] is not None:
            # one part has shares, the other does not: keep the known part only
            prev["shares"] = prev["shares"] if prev["shares"] is not None else r["shares"]
            prev["avg_cost"] = prev["avg_cost"] if prev["avg_cost"] is not None else r["avg_cost"]
        prev["account"] = prev["account"] or r["account"]
    return out


# ============================================================
# Resolution
# ============================================================

_lookup_cache = TTLCache(max_size=1000, default_ttl=24 * 3600)

_EXCHANGE_CODES = {
    "TOR": "TSX", "TSX": "TSX", "VAN": "TSXV", "CVE": "TSXV", "NEO": "NEO", "CNQ": "CSE",
    "NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ", "NAS": "NASDAQ", "NASDAQ": "NASDAQ",
    "NYQ": "NYSE", "NYS": "NYSE", "NYSE": "NYSE", "ASE": "NYSE American", "PCX": "NYSE Arca",
    "BTS": "Cboe", "BATS": "Cboe", "CCC": "CRYPTO", "CCY": "CRYPTO",
}


def _exchange_label(symbol: str, info: dict) -> str:
    code = str((info or {}).get("exchange") or "").upper()
    if code in _EXCHANGE_CODES:
        return _EXCHANGE_CODES[code]
    from app.market.symbols import exchange_for
    return exchange_for(symbol)


def _lookup_listing(symbol: str) -> dict | None:
    """Recent price + identity for one exact Yahoo symbol (blocking, cached 24h).
    None when it has not traded in the last ~10 days."""
    cached = _lookup_cache.get(symbol)
    if cached is not None:
        return cached or None
    from app.market import funds
    from app.market.symbols import recent_price

    price = recent_price(symbol)
    if not price:
        _lookup_cache.set(symbol, False, ttl=1800)
        return None
    info: dict = {}
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).info or {}
    except Exception as e:
        logger.debug(f"holdings: info({symbol}) failed: {e}")
    out = {
        "symbol": symbol,
        "name": info.get("longName") or info.get("shortName"),
        "exchange": _exchange_label(symbol, info),
        "currency": funds.currency_of(symbol, info),
        "asset_type": funds.asset_type_for(symbol, info) if info else _guess_asset_type(symbol),
        "price": round(float(price), 4),
    }
    _lookup_cache.set(symbol, out)
    return out


def _guess_asset_type(symbol: str) -> str:
    from app.market.universe import get_asset_class
    return get_asset_class(symbol)


async def resolve_input(sym: str) -> dict:
    """All listings for one typed symbol, TSX first (Canadian owner).

    Returns {"status": ok|ambiguous|not_found, "selected", "alternatives",
    "note"}. The bare symbol and SYMBOL.TO are both looked up; when both
    trade, the TSX listing is selected and the result is flagged
    "ambiguous" so the owner confirms (ENS.TO E Split Corp vs ENS EnerSys).
    A universe crypto (BTC -> BTC-USD) is preferred; SYMBOL-USD is only
    tried when neither stock listing exists.
    """
    from app.market.symbols import candidate_symbols

    cands = candidate_symbols(sym, prefer_tsx=True)
    if len(cands) == 1:
        found = await asyncio.to_thread(_lookup_listing, cands[0])
        return {"status": "ok" if found else "not_found", "selected": found,
                "alternatives": [found] if found else [], "note": None}

    crypto = f"{sym}-USD"
    stock_cands = [c for c in cands if c != crypto]
    # A universe-known symbol (e.g. BTC -> BTC-USD) comes first in cands.
    first_known = cands[0] if cands[0] == crypto else None
    lookups = await asyncio.gather(*(asyncio.to_thread(_lookup_listing, c) for c in stock_cands))
    found = [f for f in lookups if f]
    if first_known or not found:
        c = await asyncio.to_thread(_lookup_listing, crypto)
        if c:
            found = [c] + found if first_known else found + [c]
    if not found:
        return {"status": "not_found", "selected": None, "alternatives": [], "note": None}
    # candidate order already encodes the preference (universe-known, then TSX)
    order = {c: i for i, c in enumerate(cands)}
    found.sort(key=lambda f: order.get(f["symbol"], 99))
    if len(found) == 1:
        return {"status": "ok", "selected": found[0], "alternatives": found, "note": None}
    tsx = next((f for f in found if f["symbol"].endswith(".TO")), None)
    us = next((f for f in found if f["symbol"] == sym), None)
    if tsx and us and is_cdr_of(tsx, us):
        # Yahoo lists Canadian Depositary Receipts as SYMBOL.TO under the US
        # company's name (NVDA.TO "NVIDIA Corporation"): the plain ticker most
        # likely means the US share — still flagged so the owner confirms.
        found = [us] + [f for f in found if f is not us]
        return {"status": "ambiguous", "selected": us, "alternatives": found, "note": "cdr"}
    tsx_first = found[0]["symbol"].endswith(".TO")
    return {"status": "ambiguous", "selected": found[0], "alternatives": found,
            "note": "prefer_tsx" if tsx_first else "prefer_known"}


_NAME_NOISE = re.compile(
    r"\b(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|holdings|class [a-z]|cdr|"
    r"cad hedged|canadian depositary receipts?)\b|[^a-z0-9 ]")


def _norm_name(name: str | None) -> str:
    return re.sub(r"\s+", " ", _NAME_NOISE.sub(" ", (name or "").lower())).strip()


def is_cdr_of(tsx: dict, us: dict) -> bool:
    """True when the TSX listing is a CDR of the US company (same name, or
    'CDR' in its name)."""
    tn, un = _norm_name(tsx.get("name")), _norm_name(us.get("name"))
    if "cdr" in (tsx.get("name") or "").lower():
        return True
    return bool(tn and un and (tn == un or tn.startswith(un) or un.startswith(tn)))


async def resolve_rows(rows: list[dict], existing_symbols: set[str] | None = None) -> list[dict]:
    """Resolve parsed rows concurrently (bounded)."""
    sem = asyncio.Semaphore(RESOLVE_CONCURRENCY)
    existing = existing_symbols or set()

    async def one(r: dict) -> dict:
        if r.get("error"):
            return {**r, "status": "invalid", "selected": None, "alternatives": [], "note": None,
                    "existing": False}
        async with sem:
            try:
                res = await resolve_input(r["input"])
            except Exception as e:
                logger.warning(f"holdings: resolve {r['input']} failed: {e}")
                res = {"status": "not_found", "selected": None, "alternatives": [], "note": None}
        sel = res.get("selected")
        return {**r, **res, "existing": bool(sel and sel["symbol"] in existing)}

    return list(await asyncio.gather(*(one(r) for r in rows)))


# ============================================================
# Portfolio math (currency-aware, totals in CAD)
# ============================================================

def _num(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def to_cad(amount: float | None, currency: str | None, usdcad: float | None) -> float | None:
    """Native amount -> CAD. USD needs the CAD=X rate (CAD per 1 USD)."""
    if amount is None:
        return None
    ccy = (currency or "").upper()
    if ccy == "CAD":
        return amount
    if ccy == "USD":
        return amount * usdcad if usdcad else None
    return None


def holding_currency(h: dict) -> str:
    c = str(h.get("currency") or "").upper()
    if c:
        return c
    sym = str(h.get("symbol") or "")
    return "CAD" if sym.endswith((".TO", ".V", ".NE", ".CN")) else "USD"


def holding_price(h: dict) -> float | None:
    return _num((h.get("holding_status") or {}).get("price"))


def _ytd_base(st: dict) -> float | None:
    """Previous year's last close from the monitor's status: stored
    `ytd_base`, else derived from price / (1 + ytd_pct/100)."""
    base = _num(st.get("ytd_base"))
    if base:
        return base
    price, ytd = _num(st.get("price")), _num(st.get("ytd_pct"))
    if price and ytd is not None and ytd > -100:
        return price / (1 + ytd / 100)
    return None


def holding_quote(h: dict, quotes: dict[str, dict] | None) -> dict | None:
    """The price a holding is valued at: the shared live quote (`quotes`
    table, same source as /portfolio/summary) when there is one, else the
    monitor's last close (holding_status). Pure.

    {"price", "prev_close", "change_pct" (PERCENT, today), "change" (native
    currency, price - prev_close), "as_of" (ISO), "live" (bool),
    "price_source": "quote" | "last_close", "ytd_pct_live" (PERCENT)}
    or None when nothing prices it. With price_source "last_close" the
    day change is unknown: change / change_pct are null (the monitor's
    prev_close would show yesterday's move as today's). ytd_pct_live =
    price vs the previous year's last close (holding_status ytd base; null
    when unknown or when the quote is from a later year than the status)."""
    sym = str(h.get("symbol") or "").upper()
    q = (quotes or {}).get(sym) or {}
    st = h.get("holding_status") or {}
    price = _num(q.get("price"))
    if price is not None:
        prev, as_of, live = _num(q.get("prev_close")), q.get("as_of"), True
    else:
        price, prev, as_of, live = _num(st.get("price")), None, st.get("as_of"), False
    if price is None:
        return None
    base = _ytd_base(st)
    same_year = not (as_of and st.get("as_of")) or str(as_of)[:4] == str(st.get("as_of"))[:4]
    return {
        "price": price,
        "prev_close": prev,
        "change_pct": _r((price / prev - 1) * 100, 4) if prev else None,
        "change": _r(price - prev, 4) if prev else None,
        "as_of": as_of,
        "live": live,
        "price_source": "quote" if live else "last_close",
        "ytd_pct_live": _r((price / base - 1) * 100) if base and same_year else None,
    }


def portfolio_math(holdings: list[dict], usdcad: float | None,
                   max_weight_pct: float | None = None,
                   quotes: dict[str, dict] | None = None) -> tuple[dict[str, dict], dict]:
    """Per-holding position figures + portfolio totals.

    Only holdings with shares AND a price have a value; weights are shares
    of the total value of those holdings (labelled as such in the UI). A
    gain needs avg_cost too. Everything is in the holding's own currency
    plus a CAD figure (USD x CAD=X); totals are CAD only.

    `quotes` ({SYMBOL: quote row}, quotes.get_quotes): when given, a holding
    is priced with its live quote (falling back to holding_status.price) —
    the same price /portfolio/summary uses, so totals match its market value.
    Without it the monitor's last close is used (unchanged behaviour).

    weight_pct = this ROW's share (one account's lot); symbol_weight_pct =
    the symbol's share across all its rows (accounts) — `overweight` uses
    symbol_weight_pct, so a stock split over TFSA + RRSP is judged as one.
    Totals carry "as_of" (the oldest quote time among priced rows, when
    `quotes` is given; else null).
    """
    max_w = settings.holdings_max_weight_pct if max_weight_pct is None else max_weight_pct
    per: dict[str, dict] = {}
    total_cad = 0.0
    cost_cad = 0.0
    gain_cad = 0.0
    fx_missing = False
    with_shares = 0
    as_ofs: list[str] = []
    for h in holdings:
        hid = str(h.get("id") or h.get("symbol"))
        shares = _num(h.get("shares"))
        cost = _num(h.get("avg_cost"))
        if quotes is None:
            ccy = holding_currency(h)
            price = holding_price(h)
        else:
            q = quotes.get(str(h.get("symbol") or "").upper()) or {}
            ccy = str(q.get("currency") or holding_currency(h)).upper()   # as value_positions
            hq = holding_quote(h, quotes) or {}
            price = hq.get("price")
            if price is not None and hq.get("as_of"):
                as_ofs.append(str(hq["as_of"]))
        value = shares * price if shares and price else None
        value_cad = to_cad(value, ccy, usdcad)
        book = shares * cost if shares and cost else None
        gain = value - book if value is not None and book is not None else None
        gain_pct = (value / book - 1) * 100 if value is not None and book else None
        if shares:
            with_shares += 1
        if value is not None and value_cad is None:
            fx_missing = True
        if value_cad is not None:
            total_cad += value_cad
            book_cad = to_cad(book, ccy, usdcad)
            if book_cad is not None and gain is not None:
                cost_cad += book_cad
                gain_cad += value_cad - book_cad
        per[hid] = {
            "currency": ccy, "value": _r(value), "value_cad": _r(value_cad), "book_value": _r(book),
            "unrealized": _r(gain), "unrealized_pct": _r(gain_pct), "weight_pct": None,
            "symbol_weight_pct": None, "overweight": False, "_symbol": str(h.get("symbol") or "").upper(),
        }
    sym_cad: dict[str, float] = {}
    for hid, p in per.items():
        if p["value_cad"] is not None:
            sym_cad[p["_symbol"]] = sym_cad.get(p["_symbol"], 0.0) + p["value_cad"]
    for hid, p in per.items():
        sym = p.pop("_symbol")
        if p["value_cad"] is not None and total_cad > 0:
            w = p["value_cad"] / total_cad * 100
            sw = sym_cad[sym] / total_cad * 100
            p["weight_pct"] = round(w, 2)
            p["symbol_weight_pct"] = round(sw, 2)
            p["overweight"] = sw > max_w
    totals = {
        "currency": "CAD",
        "value_cad": _r(total_cad) if total_cad > 0 else None,
        "book_value_cad": _r(cost_cad) if cost_cad > 0 else None,
        "unrealized_cad": _r(gain_cad) if cost_cad > 0 else None,
        "unrealized_pct": _r((gain_cad / cost_cad) * 100) if cost_cad > 0 else None,
        "count": len(holdings),
        "count_with_shares": with_shares,
        "usdcad": usdcad,
        "fx_missing": fx_missing,
        "max_weight_pct": max_w,
        "as_of": min(as_ofs) if as_ofs else None,
    }
    return per, totals


def _r(v: float | None, nd: int = 2) -> float | None:
    return round(v, nd) if v is not None and math.isfinite(v) else None


# ============================================================
# Long-term review summary
# ============================================================

def review_summary(result: dict) -> dict:
    """Compact `last_review` from a long_term_check.run_long_check result."""
    ai = result.get("ai_assessment") or {}
    scorecard = [{"key": s.get("key"), "rating": s.get("rating")} for s in (result.get("scorecard") or [])]
    concern = None
    code = None
    if ai.get("concerns"):
        concern, code = str(ai["concerns"][0])[:300], "ai"
    elif result.get("red_flags"):
        concern, code = str(result["red_flags"][0].get("text") or "")[:300], "red_flag"
    else:
        poor = [s for s in (result.get("scorecard") or []) if s.get("rating") == "poor"]
        if poor:
            concern, code = str(poor[0].get("reason") or poor[0].get("key"))[:300], f"poor:{poor[0].get('key')}"
    return {
        "verdict": result.get("verdict"),
        "verdict_source": result.get("verdict_source"),
        "summary": (str(ai.get("summary"))[:500] if ai.get("summary") else None),
        "confidence": ai.get("confidence"),
        "scorecard": scorecard,
        "key_concern": concern,
        "key_concern_source": code,
        "red_flags": len(result.get("red_flags") or []),
        "asset_type": result.get("asset_type"),
        "reviewed_at": result.get("checked_at") or datetime.now(timezone.utc).isoformat(),
    }


def review_all_allowed(last_at: str | datetime | None, now: datetime | None = None,
                       days: int | None = None) -> tuple[bool, str | None]:
    """(allowed, next_allowed_at_iso) for the weekly "review all"."""
    days = settings.holdings_review_all_days if days is None else days
    if not last_at or days <= 0:
        return True, None
    now = now or datetime.now(timezone.utc)
    try:
        at = last_at if isinstance(last_at, datetime) else datetime.fromisoformat(str(last_at).replace("Z", "+00:00"))
    except ValueError:
        return True, None
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    from datetime import timedelta
    nxt = at + timedelta(days=days)
    return (now >= nxt), nxt.isoformat()


# ============================================================
# Overlap / fund-structure notes (informational)
# ============================================================

def base_symbol(symbol: str) -> str:
    s = (symbol or "").upper()
    for suf in (".TO", ".V", ".NE", ".CN"):
        if s.endswith(suf):
            return s[: -len(suf)]
    return s


# Funds whose top holdings are US large-cap tech (Nasdaq-100 / S&P 500 heavy).
US_LARGE_TECH_FUNDS = {"XEQT", "VEQT", "VFV", "VOO", "SPY", "IVV", "XUS", "ZSP", "XSP", "QQQ", "QQQM",
                       "TQQQ", "QQCL", "QQC", "QYLD", "ZQQ", "XQQ", "ZWT", "TEC", "XIT", "VGT", "XLK"}
US_MEGA_CAPS = {"NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "GOOG", "META", "AVGO", "TSLA", "AMD", "COST", "NFLX"}
COVERED_CALL_FUNDS = {"QYLD", "QQCL", "ZWT", "HDIV", "XYLD", "RYLD", "JEPI", "JEPQ", "ZWC", "ZWB", "ZWU",
                      "ZWH", "ZWE", "ZWG", "ZWK", "ZWS", "HYLD", "QQCC", "UMAX", "HMAX", "EMAX", "CNCC"}
LEVERAGED_FUNDS = {"TQQQ", "SQQQ", "SOXL", "SOXS", "UPRO", "SPXL", "SPXU", "TNA", "TZA", "HQU", "HQD",
                   "HSU", "HSD", "QLD", "SSO", "FNGU", "LABU", "TECL", "BITX", "NVDL", "TSLL"}
CASH_LIKE_FUNDS = {"CBIL", "ZMMK", "CASH", "PSA", "HISA", "CSAV", "MNY", "ZST", "UBIL", "BIL", "SGOV"}
OVERLAP_GROUPS: dict[str, set[str]] = {
    "bitcoin": {"BTCQ", "FBTC", "BTCC", "BTCX", "EBIT", "IBIT", "BITO", "BTC-USD", "GBTC"},
    "canadian_banks": {"RY", "TD", "BMO", "BNS", "CM", "NA", "ZEB"},
    "enbridge": {"ENB", "ENS"},
    "precious_metals": {"XGD", "SVR", "CGL", "ZGD", "GLD", "SLV", "PHYS", "PSLV"},
    "cash_like": CASH_LIKE_FUNDS,
}


def fund_flags(symbol: str) -> dict:
    b = base_symbol(symbol)
    from app.market.universe import is_leveraged_or_inverse
    return {
        "covered_call": b in COVERED_CALL_FUNDS,
        "leveraged": b in LEVERAGED_FUNDS or is_leveraged_or_inverse(symbol),
        "cash_like": b in CASH_LIKE_FUNDS,
        "us_large_tech_fund": b in US_LARGE_TECH_FUNDS,
    }


def overlap_notes(holdings: list[dict]) -> list[dict]:
    """Informational notes: overlapping funds, doubly-held mega caps,
    covered-call caps, leverage decay, same-issuer / same-theme groups."""
    syms = [str(h.get("symbol") or "") for h in holdings]
    bases = {base_symbol(s): s for s in syms}
    notes: list[dict] = []
    tech_funds = sorted(bases[b] for b in bases if b in US_LARGE_TECH_FUNDS)
    if len(tech_funds) >= 2:
        notes.append({"code": "overlap_us_large_tech", "symbols": tech_funds, "text":
                      f"{', '.join(tech_funds)} all hold the same US large-cap tech names "
                      "(Apple, Microsoft, Nvidia...), so adding to any of them adds to the same exposure."})
    megas = sorted(bases[b] for b in bases if b in US_MEGA_CAPS)
    if tech_funds and megas:
        notes.append({"code": "overlap_mega_caps", "symbols": megas, "text":
                      f"{', '.join(megas)} are also top holdings inside {', '.join(tech_funds[:3])} — "
                      "you own them twice."})
    cc = sorted(bases[b] for b in bases if b in COVERED_CALL_FUNDS)
    if cc:
        notes.append({"code": "covered_call", "symbols": cc, "text":
                      f"{', '.join(cc)} sell call options for income: the yield is high but the upside "
                      "in strong markets is capped and the price tends to lag the index over time."})
    lev = sorted(bases[b] for b in bases if fund_flags(bases[b])["leveraged"])
    if lev:
        notes.append({"code": "leveraged", "symbols": lev, "text":
                      f"{', '.join(lev)} is leveraged (resets daily): it can lose value in choppy markets "
                      "even when the index ends flat — usually sized as a small satellite, not a core holding."})
    for group, members in OVERLAP_GROUPS.items():
        present = sorted(bases[b] for b in bases if b in members)
        if len(present) >= 2:
            notes.append({"code": f"group_{group}", "symbols": present, "text": {
                "bitcoin": f"{', '.join(present)} all track bitcoin — the same exposure twice.",
                "canadian_banks": f"{', '.join(present)} are all Canadian banks (XEQT holds them too).",
                "enbridge": f"{', '.join(present)}: E Split Corp's return depends on Enbridge — overlapping exposure.",
                "precious_metals": f"{', '.join(present)} are both precious-metals exposure.",
                "cash_like": f"{', '.join(present)} are cash-like (T-bills / savings): a place to park cash, not growth.",
            }[group]})
    return notes


# ============================================================
# "Where could new cash go?" — ranked considerations, never advice
# ============================================================

VERDICT_POINTS = {"SOLID": 3.0, "REASONABLE_WITH_CAVEATS": 1.5, "NOT_A_GOOD_FIT": -3.0}

ALLOCATE_CAVEAT = (
    "Not financial advice. These are considerations ranked from Signa's own data (long-term review, "
    "trend, discount from the 52-week high, concentration) — not buy instructions or amounts. "
    "You decide; your goals, taxes and account room matter more than any score."
)


def allocate_score(h: dict, weight: dict | None) -> tuple[float, list[dict]]:
    """(score, factors). Factors are {code, params, points} ordered by
    |points| so the first one or two explain the rank."""
    st = h.get("holding_status") or {}
    rv = h.get("last_review") or {}
    flags = fund_flags(str(h.get("symbol") or ""))
    factors: list[dict] = []

    def add(code: str, pts: float, **params):
        factors.append({"code": code, "points": pts, "params": params})

    verdict = rv.get("verdict")
    if verdict in VERDICT_POINTS:
        add(f"verdict_{verdict.lower()}", VERDICT_POINTS[verdict])
    else:
        add("not_reviewed", 0.0)

    dd = _num(st.get("drawdown_pct"))           # negative %, from the 52-week high
    vs200 = _num(st.get("pct_vs_sma200"))      # % above (+) / below (-) the 200-day average
    if st.get("trend_break"):
        add("trend_break", -2.0, pct_vs_sma200=vs200)
        if st.get("death_cross"):
            add("death_cross", -0.5)
    else:
        if dd is not None:
            off = -dd
            if off < 3:
                add("near_high", 0.0, drawdown_pct=dd)
            elif off <= 15:
                add("modest_discount", 1.5, drawdown_pct=dd)
            elif off <= 30:
                add("deeper_discount", 0.5, drawdown_pct=dd)
            else:
                add("steep_fall", -0.5, drawdown_pct=dd)
        if vs200 is not None and vs200 > 25:
            add("stretched", -1.0, pct_vs_sma200=vs200)
        elif vs200 is not None and 0 <= vs200 <= 10:
            add("near_trend", 0.5, pct_vs_sma200=vs200)

    w = (weight or {}).get("symbol_weight_pct")   # the symbol across accounts
    if w is None:
        w = (weight or {}).get("weight_pct")
    max_w = settings.holdings_max_weight_pct
    if (weight or {}).get("overweight"):
        add("overweight", -4.0, weight_pct=w, max_pct=max_w)
    elif w is not None and w > max_w * 0.66:
        add("heavy", -1.0, weight_pct=w, max_pct=max_w)

    if st.get("red_flags"):
        add("red_flag", -3.0, count=len(st["red_flags"]))
    if flags["leveraged"]:
        add("leveraged", -1.0)
    if flags["covered_call"]:
        add("covered_call", -0.5)
    if flags["cash_like"]:
        add("cash_like", -1.0)
    ed = st.get("earnings") or {}
    if ed.get("days") is not None and 0 <= int(ed["days"]) <= 7:
        add("earnings_soon", -0.25, days=ed["days"], date=ed.get("date"))
    if not st or (st.get("error") and st.get("price") is None):
        add("no_data", -0.5)

    score = round(sum(f["points"] for f in factors), 2)
    factors.sort(key=lambda f: -abs(f["points"]))
    return score, factors


_FACTOR_TEXT = {
    "verdict_solid": "long-term review: solid",
    "verdict_reasonable_with_caveats": "long-term review: reasonable, with caveats",
    "verdict_not_a_good_fit": "long-term review: not a good fit",
    "not_reviewed": "not reviewed yet",
    "trend_break": "below its 200-day average (trend break)",
    "death_cross": "50-day average below the 200-day",
    "near_high": "trading near its 52-week high",
    "modest_discount": "a modest discount from its 52-week high ({drawdown_pct:.0f}%)",
    "deeper_discount": "well below its 52-week high ({drawdown_pct:.0f}%)",
    "steep_fall": "a steep fall from its 52-week high ({drawdown_pct:.0f}%) — worth understanding why",
    "stretched": "stretched: {pct_vs_sma200:.0f}% above its 200-day average",
    "near_trend": "close to its 200-day average",
    "overweight": "already {weight_pct:.0f}% of your holdings (over {max_pct:.0f}%)",
    "heavy": "already a large position ({weight_pct:.0f}%)",
    "red_flag": "a cited red flag in recent news",
    "leveraged": "leveraged fund (daily reset)",
    "covered_call": "covered-call fund: capped upside",
    "cash_like": "cash-like fund",
    "earnings_soon": "earnings in {days} days",
    "no_data": "no monitor data yet",
}


def factor_text(f: dict) -> str:
    tpl = _FACTOR_TEXT.get(f["code"], f["code"])
    try:
        return tpl.format(**{k: v for k, v in (f.get("params") or {}).items() if v is not None})
    except (KeyError, ValueError, TypeError):
        return tpl.split(" (")[0].split(":")[0]


def allocate_ideas(holdings: list[dict], weights: dict[str, dict], extra: list[dict] | None = None) -> dict:
    """Rank holdings (+ optional watchlist rows) as considerations for new cash."""
    ranked = []
    for h in list(holdings) + list(extra or []):
        hid = str(h.get("id") or h.get("symbol"))
        score, factors = allocate_score(h, weights.get(hid))
        top = [f for f in factors if f["points"] != 0][:2] or factors[:1]
        tier = "consider" if score >= 2.5 else ("caution" if score < 0 else "neutral")
        ranked.append({
            "id": h.get("id"), "symbol": h.get("symbol"), "name": h.get("name"),
            "source": h.get("_source") or "holding",
            "score": score, "tier": tier, "factors": factors,
            "reason": "; ".join(factor_text(f) for f in top).capitalize() if top else "",
            "verdict": (h.get("last_review") or {}).get("verdict"),
            "weight_pct": (weights.get(hid) or {}).get("weight_pct"),
        })
    ranked.sort(key=lambda r: (-r["score"], r["symbol"] or ""))
    for i, r in enumerate(ranked, start=1):
        r["rank"] = i
    return {
        "ideas": ranked,
        "notes": overlap_notes(holdings),
        "caveat": ALLOCATE_CAVEAT,
        "max_weight_pct": settings.holdings_max_weight_pct,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def public_holding(h: dict, weight: dict | None, quote: dict | None = None,
                   with_quote: bool = False) -> dict[str, Any]:
    """API shape of one holding (alert_state is internal). with_quote adds
    "quote" (holding_quote shape or None)."""
    out = {k: v for k, v in h.items() if k not in ("alert_state", "user_id")}
    out["position"] = weight
    out["flags"] = fund_flags(str(h.get("symbol") or ""))
    if with_quote:
        out["quote"] = quote
    return out


def merge_by_symbol(holdings: list[dict]) -> list[dict]:
    """One row per symbol (the same stock can sit in several accounts since
    migration 013): shares added, avg_cost weighted when every lot has one,
    account/account_id kept only when all lots agree. Order = first seen."""
    out: dict[str, dict] = {}
    for h in holdings or []:
        sym = str(h.get("symbol") or "").upper()
        if sym not in out:
            out[sym] = dict(h)
            continue
        m = out[sym]
        a, b = _num(m.get("shares")), _num(h.get("shares"))
        ca, cb = _num(m.get("avg_cost")), _num(h.get("avg_cost"))
        shares = (a or 0) + (b or 0) if (a or b) else None
        m["avg_cost"] = (a * ca + b * cb) / shares if a and b and ca and cb and shares else (
            None if (a and b) else ca or cb)
        m["shares"] = shares
        for k in ("account", "account_id"):
            if m.get(k) != h.get(k):
                m[k] = None
    return list(out.values())
