"""Stock suggestions without AI (migration 028). Ideas to look at, never advice.

Three sources, all plain rules and counts:

1. Similar to this one (stock page). Same curated fund group first
   (similar_funds.PEER_GROUPS), then a score over what the symbols are
   (symbol_profiles): stocks by industry (+4) or sector (+2), funds by Yahoo
   category (+3); then +1 same country, +1 similar size (market cap within 3x),
   +0.5 both pay dividends, +0.5 listed on the user's home exchange. Same kind
   only (a stock never suggests a fund); leveraged / inverse funds never.
2. People who follow X also follow Y. Anonymous counts of users following
   both symbols (symbol_cofollows), computed nightly from holdings and
   watchlists of real, returning accounts only (eligible_users: 30+ days
   old, back a week after sign-up); a pair is kept only when at least
   MIN_COFOLLOW_USERS share it, counts are rounded down to a multiple of 5 and
   the order uses the rounded counts. No user is ever named.
3. Gaps in your portfolio (Premium, feature.portfolio_gaps): one position over
   20% of the portfolio, one sector over 40% of the stocks, almost nothing
   outside the home country, no dividend payers. Each gap lists a few broad
   funds to look at, for the user's currency (GAP_IDEAS).

Free: FREE_LIMIT rows per list; Premium (feature.suggestions_all): FULL_LIMIT.
Symbols the user already follows are marked (`followed`), not hidden, on the
stock page, and left out of the portfolio lists.

symbol_profiles is written whenever a stock page is built (record_from_info,
the Yahoo info is already there) and refreshed nightly (run_nightly, 03:00 ET)
for followed symbols and the curated lists, NIGHTLY_PROFILE_MAX per night.
"""

from __future__ import annotations

import heapq
import threading
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from loguru import logger

from app.core.cache import TTLCache

MIGRATION = "028_suggestions.sql"
FEATURE_ALL = "feature.suggestions_all"
FEATURE_GAPS = "feature.portfolio_gaps"
FREE_LIMIT = 3
FULL_LIMIT = 10
MIN_COFOLLOW_USERS = 10          # raise later only if the user base is large
MIN_ACCOUNT_AGE_DAYS = 30
MAX_PAIRS_PER_SYMBOL = 20
MAX_SYMBOLS_PER_USER = 60         # a big portfolio counts its 60 most-followed stocks (pairs grow with the square)
MIN_SIMILAR_SCORE = 2.0
PROFILE_REFRESH_DAYS = 7
NIGHTLY_PROFILE_MAX = 400
POOL_TTL_S = 3600
SINGLE_HEAVY_PCT = 20.0
SECTOR_HEAVY_PCT = 40.0
HOME_ONLY_PCT = 90.0              # more than this in the home country = "home country only"
PAYER_MIN_YIELD = 0.01            # 1%: counts as a dividend payer
MIN_POSITIONS_FOR_GAPS = 3

# Broad funds to look at for each gap, by the user's home currency.
GAP_IDEAS: dict[str, dict[str, list[str]]] = {
    "global": {"CAD": ["XEQT.TO", "VEQT.TO", "XEF.TO"], "USD": ["VT", "VXUS", "VEA"],
               "BRL": ["IVVB11.SA", "WRLD11.SA"], "EUR": ["VWCE.DE", "IWDA.AS"], "GBP": ["VWRL.L", "SWDA.L"],
               "default": ["VT", "VXUS"]},
    "broad_home": {"CAD": ["XIC.TO", "VCN.TO", "ZCN.TO"], "USD": ["VTI", "VOO", "ITOT"],
                   "BRL": ["BOVA11.SA", "SMAL11.SA"], "EUR": ["VWCE.DE"], "GBP": ["VUKE.L"],
                   "default": ["VT", "VTI"]},
    "income": {"CAD": ["XEI.TO", "VDY.TO", "CDZ.TO"], "USD": ["SCHD", "VYM", "VIG"],
               "BRL": ["DIVO11.SA"], "EUR": ["VHYL.AS"], "GBP": ["VHYL.L"], "default": ["SCHD", "VYM"]},
}
# Funds whose holdings are mostly outside their listing country.
INTERNATIONAL_GROUPS = {"all_in_one_equity", "all_in_one_growth", "all_in_one_balanced", "sp500_cad",
                        "us_total", "nasdaq100", "intl_developed", "emerging", "covered_call_us"}
_INTL_WORDS = ("global", "world", "international", "foreign", "emerging", "eafe", "u.s.", "us equity",
               "developed", "asia", "europe", "s&p 500")

_pool = TTLCache(max_size=2, default_ttl=POOL_TTL_S)
_pool_lock = threading.Lock()


def _f(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def _kind(quote_type: str | None) -> str:
    q = str(quote_type or "").upper()
    if q in ("ETF", "MUTUALFUND"):
        return "fund"
    if q in ("CRYPTOCURRENCY", "CRYPTO"):
        return "crypto"
    return "stock" if q in ("EQUITY", "") else q.lower()


def _limit(level: str) -> int:
    from app.core.access import can
    return FULL_LIMIT if can(level, FEATURE_ALL) else FREE_LIMIT


def home_exchange(country: str | None) -> str | None:
    """User country -> exchange label of their market (BR -> B3, CA -> TSX, US -> US)."""
    from app.market.currency import exchange_for_suffix
    from app.market.symbols import COUNTRY_SUFFIX
    c = (country or "").upper()
    if c == "US":
        return "US"
    suf = COUNTRY_SUFFIX.get(c)
    return exchange_for_suffix("X" + suf) if suf else None


# ============================================================
# Profiles
# ============================================================

def dividend_yield_from_info(info: dict, price: float | None) -> float | None:
    """FRACTION. Stocks: dividendRate / price; funds: `yield` (a fraction).
    Yahoo's `dividendYield` is a PERCENT (3.0 = 3%) in yfinance 1.x; the
    trailing fields are often 0 for funds that do pay. Pure."""
    rate = _f(info.get("dividendRate")) or _f(info.get("trailingAnnualDividendRate"))
    if rate and price:
        return rate / price
    for v in (_f(info.get("yield")), (_f(info.get("dividendYield")) or 0) / 100 or None,
              _f(info.get("trailingAnnualDividendYield"))):
        if v:
            return v
    known = any(k in info for k in ("dividendRate", "yield", "dividendYield", "trailingAnnualDividendYield"))
    return 0.0 if known else None


def profile_from_info(symbol: str, info: dict | None) -> dict | None:
    """symbol_profiles row from a Yahoo info dict (already in the main currency,
    market/currency.normalize_info). None when info says nothing. Pure."""
    from app.market.currency import currency_for
    from app.market.sessions import label_for_symbol

    info = info or {}
    name = info.get("longName") or info.get("shortName")
    qt = info.get("quoteType")
    if not (name or qt):
        return None
    price = _f(info.get("regularMarketPrice")) or _f(info.get("currentPrice")) or _f(info.get("previousClose"))
    dy = dividend_yield_from_info(info, price)
    return {
        "symbol": symbol.upper(),
        "name": (str(name)[:200] if name else None),
        "quote_type": (str(qt).upper()[:16] if qt else None),
        "sector": (str(info["sector"])[:64] if info.get("sector") else None),
        "industry": (str(info["industry"])[:96] if info.get("industry") else None),
        "category": (str(info["category"])[:96] if info.get("category") else None),
        "country": (str(info["country"])[:64] if info.get("country") else None),
        "exchange": label_for_symbol(symbol)[:24],
        "currency": (str(info.get("currency") or currency_for(symbol)).upper()[:3]),
        "market_cap": _f(info.get("marketCap")),
        "dividend_yield": round(dy, 6) if dy is not None and 0 <= dy < 1 else None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


PROFILE_STALE_S = 24 * 3600   # a page rebuild re-saves the profile at most once a day


def record_from_info(symbol: str, info: dict | None) -> None:
    """Store a profile from info a caller already has (stock page). Only when
    it's missing or a day old, so page rebuilds (and crawlers) don't write on
    every build. Never raises."""
    sym = (symbol or "").upper()
    cur = (_pool.get("pool") or _pool.get("last") or {}).get(sym)
    if cur:
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(str(cur.get("updated_at")).replace("Z", "+00:00"))
            if age.total_seconds() < PROFILE_STALE_S:
                return
        except ValueError:
            pass
    row = profile_from_info(sym, info)
    if not row:
        return
    try:
        from app.db import queries
        queries.upsert_symbol_profiles([row])
    except Exception as e:
        logger.debug(f"suggestions: profile for {sym} not stored ({type(e).__name__})")
        return
    with _pool_lock:   # copy, never change in place: readers iterate the old dict safely
        pool = _pool.get("pool")
        if pool is not None:
            _pool.set("pool", {**pool, sym: row})


_pool_refreshing = threading.Event()


def _reload_pool() -> dict[str, dict]:
    from app.db import queries
    pool = {str(r["symbol"]).upper(): r for r in queries.get_symbol_profiles()}
    _pool.set("pool", pool)
    _pool.set("last", pool, ttl=24 * 3600)
    return pool


def load_pool() -> dict[str, dict]:
    """symbol -> profile for every stored symbol (read-only: never change it).
    Cached POOL_TTL_S; after that the old pool keeps answering while one
    background thread reloads it, so no request waits on the full table."""
    pool = _pool.get("pool")
    if pool is not None:
        return pool
    last = _pool.get("last")
    if last is not None:
        if not _pool_refreshing.is_set():
            _pool_refreshing.set()

            def run():
                try:
                    _reload_pool()
                except Exception as e:
                    logger.debug(f"suggestions: pool reload failed ({type(e).__name__})")
                finally:
                    _pool_refreshing.clear()
            threading.Thread(target=run, name="suggestions-pool", daemon=True).start()
        return last
    with _pool_lock:
        pool = _pool.get("pool")
        return pool if pool is not None else _reload_pool()


def clear_cache() -> None:
    _pool.clear()


# ============================================================
# 1. Similar (pure)
# ============================================================

def _leveraged(symbol: str, prof: dict) -> bool:
    from app.market.universe import is_leveraged_or_inverse
    try:
        return is_leveraged_or_inverse(symbol, {"quote_type": prof.get("quote_type"), "company_name": prof.get("name")})
    except Exception:
        return False


def similarity(a: dict, b: dict, home_exch: str | None = None) -> tuple[float, str | None]:
    """(score, reason) of b as a suggestion for a. Pure."""
    if _kind(a.get("quote_type")) != _kind(b.get("quote_type")):
        return 0.0, None
    score, reason = 0.0, None
    if _kind(a.get("quote_type")) == "fund":
        if a.get("category") and a.get("category") == b.get("category"):
            score, reason = 3.0, "same_category"
    elif a.get("industry") and a.get("industry") == b.get("industry"):
        score, reason = 4.0, "same_industry"
    elif a.get("sector") and a.get("sector") == b.get("sector"):
        score, reason = 2.0, "same_sector"
    if not reason:
        return 0.0, None
    if a.get("country") and a.get("country") == b.get("country"):
        score += 1.0
    ca, cb = _f(a.get("market_cap")), _f(b.get("market_cap"))
    if ca and cb and 1 / 3 <= cb / ca <= 3:
        score += 1.0
    ya, yb = _f(a.get("dividend_yield")) or 0, _f(b.get("dividend_yield")) or 0
    if ya >= PAYER_MIN_YIELD and yb >= PAYER_MIN_YIELD:
        score += 0.5
    if home_exch and b.get("exchange") == home_exch:
        score += 0.5
    return score, reason


def _row(symbol: str, prof: dict | None, reason: str, followed: set[str], **params) -> dict:
    from app.services.symbol_search import label_for
    prof = prof or {}
    return {"symbol": symbol, "name": prof.get("name"), "reason": reason, "params": params,
            "asset_type": {"fund": "etf", "crypto": "crypto"}.get(_kind(prof.get("quote_type")), "stock"),
            "exchange_label": label_for(symbol), "sector": prof.get("sector"),
            "dividend_yield": prof.get("dividend_yield"), "followed": symbol in followed}


def similar_to(symbol: str, pool: dict[str, dict], followed: set[str], home_exch: str | None,
               limit: int) -> list[dict]:
    """Rows for "similar to this one". Pure (the pool is passed in)."""
    from app.services.similar_funds import peers_for
    sym = symbol.upper()
    out: list[dict] = []
    seen = {sym}
    for peer, name in peers_for(sym):   # curated fund groups first
        if peer not in seen:
            seen.add(peer)
            out.append(_row(peer, pool.get(peer) or {"name": name, "quote_type": "ETF"}, "same_fund_group", followed))
    me = pool.get(sym)
    if me and len(out) < limit:
        scored = []
        for other, prof in pool.items():
            if other in seen:
                continue
            score, reason = similarity(me, prof, home_exch)
            if score >= MIN_SIMILAR_SCORE:
                scored.append((-score, -(_f(prof.get("market_cap")) or 0), other, reason))
        # rows (and the leveraged check) only for the best few, not every match
        for _s, _c, other, reason in heapq.nsmallest(limit * 3, scored):
            if len(out) >= limit:
                break
            if _leveraged(other, pool[other]):
                continue
            key = "industry" if reason == "same_industry" else "sector" if reason == "same_sector" else "category"
            out.append(_row(other, pool[other], reason, followed, **{key: me.get(key)}))
    return out[:limit]


# ============================================================
# 2. Co-follows
# ============================================================

def eligible_users(users: Iterable[dict], now: datetime) -> set[str]:
    """Accounts that count in "followed together": at least MIN_ACCOUNT_AGE_DAYS
    old and seen again a week or more after signing up. Fake accounts made to
    reveal a real user's holdings, or to push a ticker, have to live a month
    and keep coming back first. Pure."""
    out = set()
    for u in users:
        created = _ts(u.get("created_at"))
        seen = _ts(u.get("last_seen_at"))
        if not created or not seen:
            continue
        if (now - created).days >= MIN_ACCOUNT_AGE_DAYS and (seen - created).days >= 7:
            out.add(str(u["id"]))
    return out


def _ts(v: Any) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def compute_cofollows(follow_rows: Iterable[dict], min_users: int = MIN_COFOLLOW_USERS,
                      top: int = MAX_PAIRS_PER_SYMBOL, eligible: set[str] | None = None) -> list[dict]:
    """[{symbol, other, users}] from [{user_id, symbol}]: pairs shared by at
    least min_users users, the top `top` per symbol. Pure.

    Scales: a symbol with fewer than min_users followers can't be in any
    pair, so it is dropped before pairing; each user is cut to their
    MAX_SYMBOLS_PER_USER most-followed symbols (not the alphabetically first)."""
    by_user: dict[str, set[str]] = defaultdict(set)
    for r in follow_rows:
        uid, sym = r.get("user_id"), str(r.get("symbol") or "").upper()
        if uid and sym and (eligible is None or str(uid) in eligible):
            by_user[str(uid)].add(sym)
    followers: Counter = Counter(sym for syms in by_user.values() for sym in syms)
    popular = {sym for sym, n in followers.items() if n >= min_users}
    pairs: Counter = Counter()
    for syms in by_user.values():
        keep = sorted((x for x in syms if x in popular), key=lambda x: (-followers[x], x))[:MAX_SYMBOLS_PER_USER]
        keep.sort()
        for i, a in enumerate(keep):
            for b in keep[i + 1:]:
                pairs[(a, b)] += 1
    per: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for (a, b), n in pairs.items():
        if n >= min_users:
            per[a].append((n, b))
            per[b].append((n, a))
    out = []
    for sym, lst in per.items():
        for n, other in sorted(lst, key=lambda x: (-x[0], x[1]))[:top]:
            out.append({"symbol": sym, "other": other, "users": n})
    return out


def _rounded(n: int) -> int:
    return max(MIN_COFOLLOW_USERS, n - n % 5)


def also_followed(symbols: Iterable[str], rows: list[dict], exclude: set[str], followed: set[str],
                  pool: dict[str, dict], limit: int) -> list[dict]:
    """Symbols most often followed together with `symbols`, minus `exclude`. Pure."""
    wanted = {s.upper() for s in symbols}
    score: Counter = Counter()
    best: dict[str, tuple[int, str]] = {}
    for r in rows:
        if str(r.get("symbol")).upper() not in wanted:
            continue
        other, n = str(r.get("other")).upper(), _rounded(int(r.get("users") or 0))
        if other in exclude or other in wanted:
            continue
        score[other] += n   # rounded counts only: the order never reveals exact numbers
        if n > best.get(other, (0, ""))[0]:
            best[other] = (n, str(r["symbol"]).upper())
    out = []
    for other, _ in sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]:
        n, via = best[other]
        out.append(_row(other, pool.get(other), "also_followed", followed, users=_rounded(n), via=via))
    return out


# ============================================================
# 3. Gaps (pure)
# ============================================================

def _ideas(kind: str, home: str, held: set[str], pool: dict[str, dict]) -> list[dict]:
    lst = GAP_IDEAS[kind].get((home or "").upper()) or GAP_IDEAS[kind]["default"]
    return [{"symbol": s, "name": (pool.get(s) or {}).get("name")} for s in lst if s not in held]


def _international(p: dict, prof: dict | None, home_exch: str | None, user_country: str | None) -> bool:
    from app.services.similar_funds import group_of
    sym = p["symbol"]
    if group_of(sym) in INTERNATIONAL_GROUPS:
        return True
    prof = prof or {}
    if _kind(prof.get("quote_type")) == "fund":
        cat = str(prof.get("category") or "").lower()
        if any(w in cat for w in _INTL_WORDS):
            return True
    exch = prof.get("exchange")
    if exch and home_exch:
        return exch != home_exch
    country = prof.get("country")
    names = {"US": "United States", "CA": "Canada", "BR": "Brazil"}
    return bool(country and user_country and country != names.get(user_country.upper(), country))


def find_gaps(positions: list[dict], pool: dict[str, dict], home: str, user_country: str | None) -> list[dict]:
    """positions: merged by symbol, with value_home. Pure."""
    valued = [p for p in positions if (p.get("value_home") or 0) > 0]
    total = sum(p["value_home"] for p in valued)
    if len(valued) < MIN_POSITIONS_FOR_GAPS or total <= 0:
        return []
    held = {p["symbol"] for p in positions}
    home_exch = home_exchange(user_country)
    gaps: list[dict] = []

    big = max(valued, key=lambda p: p["value_home"])
    pct = big["value_home"] / total * 100
    from app.services.similar_funds import group_of
    if pct > SINGLE_HEAVY_PCT and _kind((pool.get(big["symbol"]) or {}).get("quote_type")) != "fund" \
            and not group_of(big["symbol"]):
        gaps.append({"code": "single_position_heavy", "params": {"symbol": big["symbol"], "pct": round(pct, 1)},
                     "ideas": _ideas("broad_home", home, held, pool)})

    stocks = [p for p in valued if _kind((pool.get(p["symbol"]) or {}).get("quote_type")) == "stock"
              and (pool.get(p["symbol"]) or {}).get("sector")]
    stock_total = sum(p["value_home"] for p in stocks)
    if stock_total > 0 and len(stocks) >= 2:
        by_sector: Counter = Counter()
        for p in stocks:
            by_sector[pool[p["symbol"]]["sector"]] += p["value_home"]
        sector, v = by_sector.most_common(1)[0]
        if v / stock_total * 100 > SECTOR_HEAVY_PCT:
            gaps.append({"code": "sector_heavy", "params": {"sector": sector, "pct": round(v / stock_total * 100, 1)},
                         "ideas": _ideas("broad_home", home, held, pool)})

    intl = sum(p["value_home"] for p in valued
               if _international(p, pool.get(p["symbol"]), home_exch, user_country))
    if (total - intl) / total * 100 > HOME_ONLY_PCT:
        gaps.append({"code": "home_country_only", "params": {"pct": round((total - intl) / total * 100, 1)},
                     "ideas": _ideas("global", home, held, pool)})

    known = [p for p in valued if p["symbol"] in pool]
    if len(known) >= MIN_POSITIONS_FOR_GAPS and not any(
            (_f(pool[p["symbol"]].get("dividend_yield")) or 0) >= PAYER_MIN_YIELD for p in known):
        gaps.append({"code": "no_dividend_payers", "params": {}, "ideas": _ideas("income", home, held, pool)})
    return gaps


# ============================================================
# Endpoints (blocking — run via run_db_for(MIGRATION, ...))
# ============================================================

def _followed(user: dict) -> set[str]:
    from app.services.slots import followed_symbols
    return followed_symbols(user["user_id"])


def _country(uid: str) -> str | None:
    from app.core import user_cache
    from app.db import queries
    try:
        return (user_cache.get(uid, "settings", lambda: queries.get_profile_settings(uid)) or {}).get("country")
    except Exception:
        return None


def _profile_now(sym: str, pool: dict[str, dict]) -> dict | None:
    """The symbol's profile even when the cached pool doesn't have it yet:
    the table (written moments ago by the stock page), else built from Yahoo
    info and stored (then it's in the pool for everyone). Blocking."""
    if sym in pool:
        return pool[sym]
    from app.db import queries
    try:
        row = queries.get_symbol_profile(sym)
    except Exception:
        row = None
    if row is None:
        info = _fetch_info(sym)
        row = profile_from_info(sym, info) if info else None
        if row:
            record_from_info(sym, info)
    if row:
        with _pool_lock:   # copy, never change in place
            cur = _pool.get("pool")
            if cur is not None and sym not in cur:
                _pool.set("pool", {**cur, sym: row})
    return row


def resolve_symbol(raw: str, pool: dict[str, dict]) -> str:
    """A bare ticker as the stock page resolves it (ZWC -> ZWC.TO, PETR4 ->
    PETR4.SA): the stock page's own answer when it has one, else the first
    candidate Signa knows, else the input. Pure except for the caches."""
    from app.market.symbols import candidate_symbols
    from app.services import stock_page
    sym = (raw or "").upper()
    known = stock_page._resolve_cache.get(sym)
    if known:
        return known
    if sym in pool:
        return sym
    from app.services.similar_funds import group_of
    for cand in candidate_symbols(sym):
        if cand in pool or group_of(cand):
            return cand
    return sym


def stock_body(symbol: str, user: dict) -> dict:
    """GET /stocks/{symbol}/similar."""
    from app.db import queries
    level = user.get("access_level") or "free"
    limit = _limit(level)
    pool = load_pool()
    sym = resolve_symbol(symbol, pool)
    me = _profile_now(sym, pool)
    if me is not None and sym not in pool:
        pool = {**pool, sym: me}
    followed = _followed(user)
    home_exch = home_exchange(_country(user["user_id"]))
    similar = similar_to(sym, pool, followed, home_exch, FULL_LIMIT)
    also = also_followed([sym], queries.get_cofollows([sym]), {sym}, followed, pool, FULL_LIMIT)
    return {"symbol": sym,
            "similar": similar[:limit], "also_followed": also[:limit],
            "more_locked": len(similar) > limit or len(also) > limit,
            "disclaimer": "ideas_not_advice"}


def portfolio_body(user: dict) -> dict:
    """GET /suggestions."""
    from app.core.access import can
    from app.db import queries
    from app.services import portfolio_context as pc

    level = user.get("access_level") or "free"
    limit = _limit(level)
    scope = pc.load_scope(user, None, None, False, True)
    positions = pc.merge_positions_by_symbol(
        pc.value_positions(scope["holdings"], scope.get("quotes") or {}, scope["home_currency"], scope.get("usdcad")))
    followed = _followed(user)
    held = sorted({p["symbol"] for p in positions})
    pool = load_pool()
    also = also_followed(held, queries.get_cofollows(held), followed, followed, pool, FULL_LIMIT) if held else []
    gaps_on = can(level, FEATURE_GAPS)
    gaps = find_gaps(positions, pool, scope["home_currency"], scope.get("country")) if gaps_on else []
    return {"also_followed": also[:limit], "more_locked": len(also) > limit,
            "gaps": gaps, "gaps_locked": not gaps_on,
            "home_currency": scope["home_currency"], "disclaimer": "ideas_not_advice"}


# ============================================================
# Nightly job (blocking; scheduler runs it in the job pool)
# ============================================================

def _fetch_info(symbol: str) -> dict | None:
    import yfinance as yf

    from app.market.currency import normalize_info
    try:
        info = yf.Ticker(symbol).info or {}
    except Exception as e:
        logger.debug(f"suggestions: info({symbol}) failed: {type(e).__name__}")
        return None
    return normalize_info(symbol, info)[0]


# Large, liquid B3 names (the static universe is North American), so Brazilian
# users get similar-stock suggestions from day one.
B3_SEED = ["PETR4.SA", "PETR3.SA", "VALE3.SA", "ITUB4.SA", "BBDC4.SA", "BBAS3.SA", "ABEV3.SA", "WEGE3.SA",
           "B3SA3.SA", "ITSA4.SA", "SUZB3.SA", "RENT3.SA", "GGBR4.SA", "RADL3.SA", "PRIO3.SA", "EQTL3.SA",
           "VIVT3.SA", "TAEE11.SA", "CMIG4.SA", "SBSP3.SA", "BBSE3.SA", "KLBN11.SA", "HYPE3.SA", "TOTS3.SA",
           "LREN3.SA", "CSAN3.SA", "EGIE3.SA", "SANB11.SA", "BPAC11.SA", "RAIL3.SA", "EMBR3.SA", "MGLU3.SA",
           "HGLG11.SA", "KNRI11.SA", "MXRF11.SA", "XPML11.SA", "BOVA11.SA", "SMAL11.SA", "IVVB11.SA", "DIVO11.SA"]


def _curated() -> set[str]:
    from app.market.universe import get_all_tickers
    from app.services.similar_funds import PEER_GROUPS
    out = {m for members in PEER_GROUPS.values() for m, _ in members}
    out.update(s for s in get_all_tickers() if not s.endswith("-USD"))
    out.update(B3_SEED)
    for by_ccy in GAP_IDEAS.values():
        for lst in by_ccy.values():
            out.update(lst)
    return out


def run_nightly(now: datetime | None = None) -> dict:
    """Co-follow counts, then profiles for followed + curated symbols that are
    missing or older than PROFILE_REFRESH_DAYS (NIGHTLY_PROFILE_MAX per run)."""
    from concurrent.futures import ThreadPoolExecutor

    from app.core.api_errors import is_missing_schema
    from app.db import queries

    now = now or datetime.now(timezone.utc)
    out: dict = {"status": "ok"}
    try:
        follows = queries.get_follow_rows()
        eligible = eligible_users(queries.get_users_age(), now) - queries.pending_deletion_ids()
        rows = compute_cofollows(follows, eligible=eligible)
        stamp = now.isoformat()
        out["pairs"] = queries.replace_cofollows([{**r, "updated_at": stamp} for r in rows], stamp)
    except Exception as e:
        if is_missing_schema(e):
            return {"status": "migration_required"}
        logger.warning(f"suggestions: co-follows failed: {type(e).__name__}: {e}")
        follows = []
        out["pairs"] = None

    try:
        existing = {str(r["symbol"]).upper(): r.get("updated_at") for r in queries.get_symbol_profiles()}
    except Exception as e:
        if is_missing_schema(e):
            return {"status": "migration_required"}
        logger.warning(f"suggestions: profiles unavailable: {type(e).__name__}")
        return {**out, "status": "failed"}
    wanted = {str(r.get("symbol") or "").upper() for r in follows if r.get("symbol")} | _curated()
    cutoff = (now - timedelta(days=PROFILE_REFRESH_DAYS)).isoformat()
    stale = sorted(s for s in wanted if s and (s not in existing or str(existing[s] or "") < cutoff))
    stale = sorted(stale, key=lambda s: (s in existing, str(existing.get(s) or "")))[:NIGHTLY_PROFILE_MAX]
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="suggest-info") as pool:
        infos = list(pool.map(_fetch_info, stale))
    profiles = [p for p in (profile_from_info(s, i) for s, i in zip(stale, infos)) if p]
    if profiles:
        queries.upsert_symbol_profiles(profiles)
        clear_cache()
    out.update({"profiles": len(profiles), "profiles_due": len(stale)})
    return out
