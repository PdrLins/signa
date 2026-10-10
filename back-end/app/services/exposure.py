"""What you really own (GET /portfolio/exposure, Premium feature.exposure): the
user's funds opened up and combined with their direct stocks. No AI.

Weights are shares of the scope's total (holdings at today's prices + cash +
fixed income), PERCENT, like /portfolio/summary.

  direct stock   100% to its company, its sector (symbol profile) and region
                 (profile country, else the listing)
  fund           companies = fund weight x each listed holding's weight;
                 sectors / regions = the fund's own breakdown on its stock part
                 (asset_classes "stock" share; all of it when unknown);
                 asset classes = the fund's asset_classes
  fund of funds  each underlying fund that can be opened adds its listed
                 holdings (weight in the fund x weight in the underlying);
                 the others add no companies. Breakdowns stay the fund's own.
  cash / fixed   asset classes "cash" / "bond"; no companies, sectors, regions
  crypto         asset class "other"

Same company twice (a direct stock and a fund holding, or a TSX and a US
listing): merged when the ticker without its exchange suffix AND the first
word of the name match (so T = AT&T and T.TO = TELUS stay apart), or when
it's the exact same listing and one side has no name.
coverage_pct = direct stocks + each fund's weight x its holdings_known_pct.
sectors / regions / asset_classes add up to 100 over the part that's known.
overlaps = pairs of held funds whose common companies sum (smaller weight
of the two) to >= MIN_OVERLAP_PCT.
"""

from __future__ import annotations

import math
import re
from typing import Any

from app.core.cache import TTLCache

MAX_COMPANIES = 25
MAX_COMMON = 10
MIN_OVERLAP_PCT = 10.0
MAX_UNDERLYING = 10       # underlying funds opened per fund of funds
MIN_UNDERLYING_WEIGHT = 1.0

SECTOR_KEYS = ("technology", "financial_services", "healthcare", "consumer_cyclical", "consumer_defensive",
               "industrials", "communication_services", "energy", "basic_materials", "realestate", "utilities")
_SECTOR_NAMES = {
    "technology": "technology", "information technology": "technology",
    "financial services": "financial_services", "financials": "financial_services", "financial": "financial_services",
    "healthcare": "healthcare", "health care": "healthcare",
    "consumer cyclical": "consumer_cyclical", "consumer discretionary": "consumer_cyclical",
    "consumer defensive": "consumer_defensive", "consumer staples": "consumer_defensive",
    "industrials": "industrials", "communication services": "communication_services",
    "energy": "energy", "basic materials": "basic_materials", "materials": "basic_materials",
    "real estate": "realestate", "realestate": "realestate", "utilities": "utilities",
}
ASSET_KEYS = {"stockPosition": "stock", "bondPosition": "bond", "cashPosition": "cash",
              "preferredPosition": "preferred", "convertiblePosition": "convertible", "otherPosition": "other"}
REGION_KEYS = ("us", "canada", "intl_developed", "emerging")
# MSCI emerging markets (by country name and by listing suffix)
_EMERGING_COUNTRIES = {"brazil", "china", "india", "mexico", "south africa", "taiwan", "south korea", "korea",
                       "indonesia", "thailand", "malaysia", "philippines", "chile", "peru", "colombia", "turkey",
                       "saudi arabia", "united arab emirates", "qatar", "kuwait", "poland", "hungary", "greece",
                       "czech republic", "egypt"}
_EMERGING_SUFFIXES = {"SA", "NS", "BO", "SS", "SZ", "MX", "JO", "TW", "TWO", "KS", "KQ", "JK", "BK", "KL", "SN",
                      "IS", "SR", "WA"}
_CANADA_SUFFIXES = {"TO", "V", "NE", "CN"}
_STOP_WORDS = {"the", "inc", "corp", "co", "ltd", "plc", "sa", "ag", "nv", "class", "cl"}


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _r(v: float | None, nd: int = 2) -> float | None:
    return round(v, nd) if v is not None else None


def sector_key(raw: str | None) -> str | None:
    """A profile sector ("Financial Services") or a fund key ("financial_services") -> app key."""
    if not raw:
        return None
    s = str(raw).strip().lower()
    if s in SECTOR_KEYS:
        return s
    return _SECTOR_NAMES.get(s.replace("_", " "))


def _suffix(symbol: str) -> str | None:
    s = (symbol or "").upper()
    return s.rsplit(".", 1)[1] if "." in s else None


def region_of(symbol: str, country: str | None = None) -> str | None:
    """us | canada | intl_developed | emerging for a single stock. Pure."""
    c = (country or "").strip().lower()
    if c:
        if c in ("united states", "usa", "us"):
            return "us"
        if c == "canada":
            return "canada"
        return "emerging" if c in _EMERGING_COUNTRIES else "intl_developed"
    suf = _suffix(symbol)
    if suf is None:
        return "us" if not (symbol or "").upper().endswith("-USD") else None
    if suf in _CANADA_SUFFIXES:
        return "canada"
    return "emerging" if suf in _EMERGING_SUFFIXES else "intl_developed"


def company_key(symbol: str, name: str | None) -> str:
    """Merge key for one company across listings (see the module docstring). Pure."""
    s = (symbol or "").upper()
    base = s.rsplit(".", 1)[0] if "." in s else s
    words = [w for w in re.findall(r"[a-z0-9]+", (name or "").lower()) if w not in _STOP_WORDS]
    return f"{base}|{words[0]}" if words else s


def _norm(d: dict[str, float]) -> dict[str, float]:
    tot = sum(v for v in d.values() if v and v > 0)
    return {k: v / tot * 100 for k, v in d.items() if v and v > 0} if tot > 0 else {}


def _sorted_list(d: dict[str, float]) -> list[dict]:
    """[{"key", "pct"}] over the known part (adds to 100), largest first."""
    return [{"key": k, "pct": _r(v)} for k, v in sorted(_norm(d).items(), key=lambda kv: -kv[1])]


def fund_asset_classes(raw: dict | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for k, v in (raw or {}).items():
        key = ASSET_KEYS.get(k) or (k if k in ASSET_KEYS.values() else "other")
        out[key] = out.get(key, 0.0) + (_f(v) or 0.0)
    return _norm(out)


def fund_companies(fund: dict) -> list[tuple[str, str | None, float]]:
    """[(symbol, name, weight PERCENT of the fund)] of a fund, looking through
    its underlying funds when it's a fund of funds and they were opened
    (fund["underlying"] = {listed symbol: [holdings]}). Pure."""
    from app.market.funds import looks_like_fund

    holdings = [h for h in fund.get("holdings") or [] if (_f(h.get("weight")) or 0) > 0]
    if not fund.get("fund_of_funds"):   # a fund listed among companies (XEF holds IEFA) isn't a company
        return [(str(h.get("symbol") or "").upper(), h.get("name"), _f(h["weight"])) for h in holdings
                if not looks_like_fund(h.get("name"))]
    out = []
    under = fund.get("underlying") or {}
    for h in holdings:
        inner = under.get(str(h.get("symbol") or "").upper())
        if not inner:
            continue   # not opened: no companies from this part
        for c in inner:
            wc = _f(c.get("weight"))
            if wc and wc > 0 and not looks_like_fund(c.get("name")):
                out.append((str(c.get("symbol") or "").upper(), c.get("name"), _f(h["weight"]) * wc / 100))
    return out


def build(items: list[dict], funds: dict[str, dict], cash: float, fixed: float, currency: str,
          as_of: str | None = None, estimated: bool = False) -> dict:
    """items: [{"symbol", "name", "value_home" | None, "kind": "stock" | "fund" | "crypto" | "other",
    "sector": key | None, "region": key | None}] (one per symbol); funds: symbol ->
    {"holdings", "sector_weights", "asset_classes", "regions", "fund_of_funds",
    "underlying"?} or missing when the fund's data couldn't be read. Pure."""
    priced = [i for i in items if (i.get("value_home") or 0) > 0]
    total = sum(i["value_home"] for i in priced) + max(cash, 0.0) + max(fixed, 0.0)
    est = estimated or any(i.get("value_home") is None for i in items)
    if total <= 0:
        return {"currency": currency, "as_of": as_of, "total": 0.0, "coverage_pct": None, "companies": [],
                "sectors": [], "regions": [], "asset_classes": [], "funds": [], "overlaps": [],
                "estimated": est}
    sectors: dict[str, float] = {}
    regions: dict[str, float] = {}
    assets: dict[str, float] = {}
    companies: dict[str, dict] = {}
    looked: dict[str, dict[str, float]] = {}   # fund -> company key -> weight in the fund
    funds_out = []
    covered = 0.0

    by_symbol: dict[str, str] = {}   # exact listing -> key (merges when a name is missing)

    def add_company(key: str, symbol: str, name: str | None, pct: float, via: str | None, direct: bool):
        if key not in companies and symbol in by_symbol:
            key = by_symbol[symbol]
        by_symbol.setdefault(symbol, key)
        c = companies.setdefault(key, {"symbol": symbol, "name": name, "pct": 0.0, "direct_pct": 0.0,
                                       "via": {}, "_best": 0.0})
        c["pct"] += pct
        if direct:
            c["direct_pct"] += pct
            c["symbol"], c["name"], c["_best"] = symbol, name or c["name"], math.inf   # the user's own listing
        else:
            c["via"][via] = c["via"].get(via, 0.0) + pct
            if pct > c["_best"]:
                c["symbol"], c["name"], c["_best"] = symbol, c["name"] or name, pct
            c["name"] = c["name"] or name

    for i in priced:
        w = i["value_home"] / total * 100
        kind = i.get("kind")
        if kind == "stock":
            assets["stock"] = assets.get("stock", 0.0) + w
            if i.get("sector"):
                sectors[i["sector"]] = sectors.get(i["sector"], 0.0) + w
            if i.get("region"):
                regions[i["region"]] = regions.get(i["region"], 0.0) + w
            add_company(company_key(i["symbol"], i.get("name")), i["symbol"], i.get("name"), w, None, True)
            covered += w
        elif kind == "fund":
            f = funds.get(i["symbol"])
            if not f:
                est = True
                funds_out.append({"symbol": i["symbol"], "name": i.get("name"), "pct": _r(w),
                                  "holdings_known_pct": None, "fund_of_funds": False})
                continue
            ac = fund_asset_classes(f.get("asset_classes"))
            for k, p in ac.items():
                assets[k] = assets.get(k, 0.0) + w * p / 100
            equity = ac.get("stock", 0.0) / 100 if ac else 1.0
            for k, p in _norm({sector_key(k) or "other": _f(v) or 0.0 for k, v in (f.get("sector_weights") or {}).items()}).items():
                sectors[k] = sectors.get(k, 0.0) + w * equity * p / 100
            for k, p in _norm({k: _f(v) or 0.0 for k, v in (f.get("regions") or {}).items()}).items():
                regions[k] = regions.get(k, 0.0) + w * equity * p / 100
            inside: dict[str, float] = {}
            for sym, name, wc in fund_companies(f):
                key = company_key(sym, name)
                key = key if key in companies or sym not in by_symbol else by_symbol[sym]
                inside[key] = inside.get(key, 0.0) + wc
                add_company(key, sym, name, w * wc / 100, i["symbol"], False)
            looked[i["symbol"]] = inside
            known = min(100.0, sum(inside.values()))
            covered += w * known / 100
            if not (f.get("holdings") or f.get("sector_weights") or ac):
                est = True
            funds_out.append({"symbol": i["symbol"], "name": i.get("name"), "pct": _r(w),
                              "holdings_known_pct": _r(known), "fund_of_funds": bool(f.get("fund_of_funds"))})
        else:   # crypto and anything else: no companies
            assets["other"] = assets.get("other", 0.0) + w
    if cash > 0:
        assets["cash"] = assets.get("cash", 0.0) + cash / total * 100
    if fixed > 0:
        assets["bond"] = assets.get("bond", 0.0) + fixed / total * 100

    top = sorted(companies.values(), key=lambda c: -c["pct"])[:MAX_COMPANIES]
    names = {k: c["symbol"] for k, c in companies.items()}
    overlaps = []
    held = sorted(looked)
    for x in range(len(held)):
        for y in range(x + 1, len(held)):
            a, b = looked[held[x]], looked[held[y]]
            common = [(k, a[k], b[k]) for k in a.keys() & b.keys()]
            ov = sum(min(wa, wb) for _, wa, wb in common)
            if ov >= MIN_OVERLAP_PCT:
                common.sort(key=lambda t: -min(t[1], t[2]))
                overlaps.append({"a": held[x], "b": held[y], "overlap_pct": _r(ov),
                                 "common": [{"symbol": names[k], "weight_a": _r(wa), "weight_b": _r(wb)}
                                            for k, wa, wb in common[:MAX_COMMON]]})
    overlaps.sort(key=lambda o: -o["overlap_pct"])
    return {
        "currency": currency, "as_of": as_of, "total": _r(total),
        "coverage_pct": _r(min(100.0, covered)),
        "companies": [{"symbol": c["symbol"], "name": c["name"], "pct": _r(c["pct"]),
                       "value_home": _r(c["pct"] * total / 100), "direct_pct": _r(c["direct_pct"]),
                       "via": [{"fund": f, "pct": _r(p)} for f, p in sorted(c["via"].items(), key=lambda kv: -kv[1])]}
                      for c in top],
        "sectors": _sorted_list(sectors),
        "regions": _sorted_list(regions),
        "asset_classes": _sorted_list(assets),
        "funds": sorted(funds_out, key=lambda f: -(f["pct"] or 0)),
        "overlaps": overlaps,
        "estimated": est,
    }


# ============================================================
# Loading (blocking: run with run_db)
# ============================================================

FETCH_TIMEOUT_S = 12.0    # all fund / profile reads together; what's late is left out (estimated)
CACHE_TTL_S = 300

_cache = TTLCache(max_size=2000, default_ttl=CACHE_TTL_S)


def _kind(symbol: str, asset_type: str | None, profile: dict | None) -> str:
    from app.market.currency import is_crypto
    if is_crypto(symbol):
        return "crypto"
    qt = str((profile or {}).get("quote_type") or "").upper()
    at = str(asset_type or "").upper()
    return "fund" if at in ("ETF", "MUTUALFUND") or qt in ("ETF", "MUTUALFUND") else "stock"


def _fund_data(symbol: str) -> dict | None:
    """The fund's cached data (the stock page's), its underlying funds opened when
    it's a fund of funds. None when nothing could be read. Blocking."""
    from app.market.funds import build_fund_info
    from app.services.fund_regions import regions_for
    from app.services.stock_page import _fetch_fund

    fd = _fetch_fund(symbol) or {}
    info = build_fund_info({}, fd)
    if not (fd.get("holdings") or fd.get("sector_weights") or fd.get("asset_classes")):
        return None
    out = {"holdings": fd.get("holdings") or [], "sector_weights": fd.get("sector_weights") or {},
           "asset_classes": fd.get("asset_classes") or {}, "fund_of_funds": info["fund_of_funds"],
           "regions": regions_for(symbol, info) or {}}
    if info["fund_of_funds"]:
        out["underlying"] = _open_underlying(symbol, out["holdings"], depth=1)
    return out


def _open_underlying(parent: str, holdings: list[dict], depth: int) -> dict[str, list]:
    """{listed symbol: its listed holdings (companies)} for the top underlying
    funds of a fund of funds. A wrapper fund (XTOT.TO holds ITOT) is opened
    one more level. Blocking."""
    from app.market.funds import build_fund_info
    from app.services.stock_page import _fetch_fund

    under: dict[str, list] = {}
    tops = sorted((h for h in holdings if (_f(h.get("weight")) or 0) >= MIN_UNDERLYING_WEIGHT),
                  key=lambda h: -_f(h["weight"]))[:MAX_UNDERLYING]
    for h in tops:
        listed = str(h.get("symbol") or "").upper()
        tries = [listed] + ([f"{listed}.TO"] if "." not in listed and parent.upper().endswith(".TO") else [])
        for cand in tries:
            inner = (_fetch_fund(cand) or {}).get("holdings") or []
            if not inner:
                continue
            if build_fund_info({}, {"holdings": inner})["fund_of_funds"]:
                if depth >= 2:
                    break   # too deep: leave its companies out
                nested = _open_underlying(cand, inner, depth + 1)
                inner = [{"symbol": c.get("symbol"), "name": c.get("name"),
                          "weight": (_f(n.get("weight")) or 0) * (_f(c.get("weight")) or 0) / 100}
                         for n in inner for c in nested.get(str(n.get("symbol") or "").upper(), [])]
            if inner:
                under[listed] = inner
            break
    return under


def body(scope: dict) -> dict:
    """GET /portfolio/exposure for a loaded scope, cached CACHE_TTL_S per user,
    scope and generation (any write by the user starts a new entry)."""
    from app.core import user_cache

    uid = scope.get("user_id")
    acc = scope.get("account_ids")
    key = "|".join(map(str, (uid, ",".join(sorted(map(str, acc))) if acc is not None else "*",
                             user_cache.generation(uid) if uid else 0)))
    hit = _cache.get(key) if uid else None
    if hit is not None:
        return hit
    out = _build_scope(scope)
    if uid:
        _cache.set(key, out)
    return out


def _build_scope(scope: dict) -> dict:
    from concurrent.futures import ThreadPoolExecutor, wait

    from app.services import fixed_income
    from app.services import portfolio_context as pc
    from app.services import portfolio_performance as perf
    from app.services import suggestions

    home, usdcad = scope["home_currency"], scope.get("usdcad")
    positions = pc.value_positions(scope["holdings"], scope["quotes"], home, usdcad)
    merged = pc.merge_positions_by_symbol(positions)
    cash, _ = perf.scope_cash(scope["accounts"], home, usdcad)
    fixed = fixed_income.scope_value(scope.get("fixed_income") or [], home, usdcad)["value"]
    try:
        pool = suggestions.load_pool()
    except Exception:
        pool = {}
    syms = [p["symbol"] for p in merged]
    asset_types = {str(h.get("symbol") or "").upper(): h.get("asset_type") for h in scope["holdings"]}
    profiles: dict[str, dict | None] = {s: pool.get(s) for s in syms}
    # late reads are left out (estimated); they keep running and fill the shared
    # caches for the next request (the pool doesn't wait for them)
    ex = ThreadPoolExecutor(max_workers=6)
    try:
        missing = {s: ex.submit(suggestions._profile_now, s, pool) for s in syms if profiles[s] is None}
        done, pending = wait(missing.values(), timeout=FETCH_TIMEOUT_S / 2)
        late = bool(pending)
        for s, fut in missing.items():
            profiles[s] = fut.result() if fut in done and not fut.exception() else None
        kinds = {s: _kind(s, asset_types.get(s), profiles[s]) for s in syms}
        jobs = {s: ex.submit(_fund_data, s) for s in syms if kinds[s] == "fund"}
        done, pending = wait(jobs.values(), timeout=FETCH_TIMEOUT_S)
        late = late or bool(pending)
        funds = {s: fut.result() for s, fut in jobs.items() if fut in done and not fut.exception() and fut.result()}
    finally:
        ex.shutdown(wait=False)
    items = []
    for p in merged:
        s, prof = p["symbol"], profiles.get(p["symbol"]) or {}
        items.append({"symbol": s, "name": p.get("name") or prof.get("name"), "value_home": p.get("value_home"),
                      "kind": kinds[s], "sector": sector_key(prof.get("sector")),
                      "region": region_of(s, prof.get("country"))})
    meta = pc.price_meta(positions)
    return build(items, funds, cash, fixed, home, meta["as_of"], estimated=late)
