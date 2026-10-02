"""Following — the stocks a user follows, priced, in one call. No AI.

Feeds the Following tab (web) and the iOS equivalent: the watchlist with
today's price and a 1-month sparkline, the held symbols (they count as
followed, see app.services.slots), the slot meter and a few suggestions to
follow. Prices come from the shared `quotes` table (quotes.get_quotes, which
fetches live only what is missing) and sparklines from the cached daily
closes (price_cache.fetch_daily_closes, one batched download, 6h cache), so
opening the page costs no per-user provider calls in the steady state.

build_following() is pure; load_following() does the IO.
"""

from __future__ import annotations

import math
from typing import Iterable

SPARK_POINTS = 22          # ~1 month of daily closes
SUGGESTION_LIMIT = 6
SUGGESTION_QUOTE_TTL = 900  # suggestion prices: shared row if this fresh, else one batched fetch cached this long

# Curated, display-ready names (symbol_search.KNOWN_NAMES carries search
# keywords, not display names). Groups are shown in this order; symbols the
# user already follows are dropped.
SUGGESTIONS: dict[str, list[tuple[str, str]]] = {
    "popular_ca": [
        ("XEQT.TO", "iShares Core Equity ETF Portfolio"), ("VFV.TO", "Vanguard S&P 500 Index ETF"),
        ("RY.TO", "Royal Bank of Canada"), ("SHOP.TO", "Shopify"), ("ENB.TO", "Enbridge"),
        ("TD.TO", "Toronto-Dominion Bank"), ("CNR.TO", "Canadian National Railway"), ("BN.TO", "Brookfield"),
    ],
    "popular_us": [
        ("VOO", "Vanguard S&P 500 ETF"), ("AAPL", "Apple"), ("MSFT", "Microsoft"), ("NVDA", "Nvidia"),
        ("AMZN", "Amazon"), ("GOOGL", "Alphabet"), ("META", "Meta Platforms"), ("COST", "Costco"),
    ],
    "monthly_income": [
        ("O", "Realty Income"), ("ZWC.TO", "BMO Canadian High Dividend Covered Call ETF"),
        ("CDZ.TO", "iShares S&P/TSX Canadian Dividend Aristocrats ETF"), ("ZRE.TO", "BMO Equal Weight REITs ETF"),
        ("XEI.TO", "iShares S&P/TSX Composite High Dividend ETF"), ("MAIN", "Main Street Capital"),
    ],
    "dividend_growers": [
        ("FTS.TO", "Fortis"), ("JNJ", "Johnson & Johnson"), ("PG", "Procter & Gamble"), ("KO", "Coca-Cola"),
        ("CNR.TO", "Canadian National Railway"), ("ATD.TO", "Alimentation Couche-Tard"),
    ],
}


def _f(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def suggestion_groups(country: str | None) -> list[str]:
    """Group keys in display order: the home market's popular list first."""
    popular = ["popular_ca", "popular_us"] if (country or "").upper() == "CA" else ["popular_us", "popular_ca"]
    return [popular[0], "monthly_income", "dividend_growers", popular[1]]


def build_suggestions(country: str | None, followed: Iterable[str], limit: int = SUGGESTION_LIMIT) -> list[dict]:
    """[{key, items: [{symbol, name}]}] without symbols already followed; empty groups dropped. Pure."""
    seen = {s.upper() for s in followed}
    out = []
    for key in suggestion_groups(country):
        items = []
        for sym, name in SUGGESTIONS[key]:
            if sym in seen:
                continue
            seen.add(sym)   # a symbol appears in one group only
            items.append({"symbol": sym, "name": name})
            if len(items) >= limit:
                break
        if items:
            out.append({"key": key, "items": items})
    return out


def _spark(series) -> list[float]:
    if series is None:
        return []
    try:
        vals = [_f(v) for v in list(series.values)[-SPARK_POINTS:]]
    except Exception:
        return []
    return [round(v, 4) for v in vals if v is not None]


def _row(symbol: str, name: str | None, quote: dict | None, closes, extra: dict) -> dict:
    q = quote or {}
    spark = _spark(closes)
    price = _f(q.get("price"))
    change_1m = None
    if price is not None and len(spark) >= 2 and spark[0] > 0:
        change_1m = round((price / spark[0] - 1) * 100, 2)
    return {
        "symbol": symbol,
        "name": name,
        "price": price,
        "change_pct": _f(q.get("change_pct")),
        "change_1m_pct": change_1m,
        "currency": q.get("currency"),
        "as_of": q.get("as_of"),
        "spark": spark,
        **extra,
    }


def build_following(watch_rows: list[dict], holding_rows: list[dict], quotes: dict[str, dict],
                    closes: dict, names: dict[str, str], country: str | None, slots: dict | None) -> dict:
    """The GET /watchlist/overview body. Pure.

    watched: watchlist symbols (newest first, as stored), flagged in_holdings
    when also held. held: holding symbols not on the watchlist, one row per
    symbol even when held in several accounts, ordered by name/symbol."""
    held_names: dict[str, str | None] = {}
    for h in holding_rows or []:
        sym = str(h.get("symbol") or "").upper()
        if sym and (sym not in held_names or not held_names[sym]):
            held_names[sym] = h.get("name")

    watched, seen = [], set()
    for w in watch_rows or []:
        sym = str(w.get("symbol") or "").upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        watched.append(_row(sym, held_names.get(sym) or names.get(sym), quotes.get(sym), closes.get(sym), {
            "added_at": w.get("added_at"), "in_holdings": sym in held_names,
        }))

    held = [
        _row(sym, held_names[sym] or names.get(sym), quotes.get(sym), closes.get(sym), {"in_holdings": True})
        for sym in sorted(held_names, key=lambda s: ((held_names[s] or s).lower(), s))
        if sym not in seen
    ]

    as_ofs = sorted(r["as_of"] for r in watched + held if r.get("as_of"))
    return {
        "as_of": as_ofs[0] if as_ofs else None,
        "delayed_minutes": 15,
        "watched": watched,
        "held": held,
        "slots": slots,
        "suggestions": build_suggestions(country, list(seen) + list(held_names)),
    }


_suggestion_quotes: dict[str, tuple[float, dict | None]] = {}   # SYMBOL -> (fetched at, quote | None)


def _fresh(row: dict, now_ts: float, ttl: int) -> bool:
    from datetime import datetime
    try:
        t = datetime.fromisoformat(str(row.get("updated_at")).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return False
    return now_ts - t <= ttl


def suggestion_quotes(symbols: list[str], now_ts: float | None = None) -> dict[str, dict]:
    """Quotes for suggestion symbols (nobody follows them, so the quotes job
    doesn't refresh their rows): a shared `quotes` row updated within
    SUGGESTION_QUOTE_TTL, else ONE batched live download (quotes.fetch_quotes,
    not stored) cached in process for SUGGESTION_QUOTE_TTL. Never raises."""
    import time

    from app.services import quotes as quotes_service

    now_ts = time.time() if now_ts is None else now_ts
    syms = [s.upper() for s in symbols if s]
    out: dict[str, dict] = {}
    need = []
    for s in syms:
        hit = _suggestion_quotes.get(s)
        if hit and now_ts - hit[0] <= SUGGESTION_QUOTE_TTL:
            if hit[1]:
                out[s] = hit[1]
        else:
            need.append(s)
    if not need:
        return out
    try:
        stored = quotes_service.get_stored_quotes(need)
    except Exception:
        stored = {}
    fetch = []
    for s in need:
        row = stored.get(s)
        if row and _fresh(row, now_ts, SUGGESTION_QUOTE_TTL):
            out[s] = row
        else:
            fetch.append(s)
    if fetch:
        try:
            live = quotes_service.fetch_quotes(fetch)
        except Exception:
            live = {}
        for s in fetch:
            q = live.get(s) or stored.get(s)   # an old shared row beats nothing
            _suggestion_quotes[s] = (now_ts, q)
            if q:
                out[s] = q
    return out


def price_suggestions(groups: list[dict], quotes: dict[str, dict]) -> list[dict]:
    """Adds "price", "change_pct" (PERCENT, today) and "currency" (each
    nullable) to every suggestion item. Pure."""
    for g in groups:
        for it in g["items"]:
            q = quotes.get(it["symbol"]) or {}
            it["price"] = _f(q.get("price"))
            it["change_pct"] = _f(q.get("change_pct"))
            it["currency"] = q.get("currency")
    return groups


def _display_names(symbols: list[str]) -> dict[str, str]:
    """Names Signa already stores (tickers table / holdings), else the curated suggestion names."""
    from app.services import symbol_search

    curated = {s: n for group in SUGGESTIONS.values() for s, n in group}
    out: dict[str, str] = {}
    try:
        stored = {c["symbol"]: c.get("name") for c in symbol_search.local_candidates()}
    except Exception:
        stored = {}
    for s in symbols:
        name = curated.get(s) or stored.get(s)
        if name:
            out[s] = name
    return out


def load_following(user: dict) -> dict:
    """IO wrapper (blocking; call via asyncio.to_thread / run_db)."""
    from app.db import queries
    from app.services import price_cache, profile_service, quotes as quotes_service, slots as slots_service

    uid = user["user_id"]
    watch_rows = queries.get_watchlist(uid)
    try:
        holding_rows = queries.get_holdings(uid)
    except Exception:
        holding_rows = []
    symbols = list(dict.fromkeys(
        [str(r.get("symbol") or "").upper() for r in watch_rows + holding_rows if r.get("symbol")]))
    quotes = quotes_service.get_quotes(symbols) if symbols else {}
    # "1y" shares the cache entries portfolio risk / performance already fill
    closes = price_cache.fetch_daily_closes(symbols, period="1y") if symbols else {}
    try:
        country, _ = profile_service.get_country_and_currency(uid)
    except Exception:
        country = None
    try:
        slots = slots_service.slot_summary(user)
    except Exception:
        slots = None
    out = build_following(watch_rows, holding_rows, quotes, closes, _display_names(symbols), country, slots)
    sugg_syms = [it["symbol"] for g in out["suggestions"] for it in g["items"]]
    try:
        sugg_quotes = suggestion_quotes(sugg_syms) if sugg_syms else {}
    except Exception:
        sugg_quotes = {}
    price_suggestions(out["suggestions"], sugg_quotes)
    # pre-market / after-hours (Premium, migration 021): per row "extended" + "extended_locked"
    from app.core.access import can
    level = user.get("access_level") or "free"
    ext = quotes_service.get_extended(symbols) if can(level, "feature.extended_hours") else {}
    for row in out["watched"] + out["held"]:
        view = quotes_service.extended_view(quotes.get(row["symbol"]), ext.get(row["symbol"]))
        row.update(quotes_service.extended_payload(level, row["symbol"], view))
    return out
