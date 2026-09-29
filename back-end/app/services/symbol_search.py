"""Symbol search — type a ticker OR a company name (typos tolerated).

    search("telas")      -> TSLA (Tesla, Inc.)
    search("dollarama")  -> DOL.TO
    search("royal bank") -> RY.TO + RY (dual listing, both labelled)

Two sources, merged and ranked:

1. Local ("signa"): symbols Signa already knows — the `tickers` table (with
   company names), the owner's holdings and watchlist, plus small built-in
   name tables (KNOWN_NAMES, CRYPTO_ALIASES: "bitcoin" -> BTC-USD). Loaded once, cached 6h in memory.
   Scored: exact symbol > symbol prefix > name prefix > fuzzy name word
   (difflib ratio >= FUZZY_MIN, so "telas" ~ "tesla").
2. Yahoo (`yfinance.Search`): handles names but not typos. Run in a thread
   with a timeout, cached per normalized query for 1h. When Yahoo finds
   nothing that matches what was typed (it answers "telas" with "Texas ...")
   and the local fuzzy step corrected a word ("telas" -> "tesla"), Yahoo is
   re-queried with the corrected text and those matches rank first.

Yahoo quotes are filtered to stocks / ETFs / crypto (USD pairs) on US and
Canadian (TSX / TSXV / NEO) exchanges; OTC (PNK) ranks last. Futures,
options, mutual funds and foreign listings (MUN, F, DE, ...) are dropped.

Response rows: {symbol, name, exchange, exchange_label, type, source}.
"""

from __future__ import annotations

import asyncio
import re
from difflib import SequenceMatcher

from loguru import logger

from app.core.cache import TTLCache

MAX_QUERY_LEN = 40
MAX_LIMIT = 20
FUZZY_MIN = 0.75
YAHOO_TIMEOUT_S = 6.0
LOCAL_TTL_S = 6 * 3600
YAHOO_TTL_S = 3600
YAHOO_EMPTY_TTL_S = 600

_local_cache = TTLCache(max_size=2, default_ttl=LOCAL_TTL_S)
_yahoo_cache = TTLCache(max_size=500, default_ttl=YAHOO_TTL_S)

# Yahoo exchange code -> display label. Anything not here is dropped.
EXCHANGE_LABELS = {
    "NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ", "NAS": "NASDAQ", "NASDAQ": "NASDAQ",
    "NYQ": "NYSE", "NYS": "NYSE", "NYSE": "NYSE",
    "ASE": "NYSE American", "PCX": "NYSE Arca", "ARCA": "NYSE Arca",
    "BTS": "Cboe", "BATS": "Cboe",
    "PNK": "OTC",
    "TOR": "TSX", "TSX": "TSX",
    "VAN": "TSXV", "CVE": "TSXV", "TSXV": "TSXV",
    "NEO": "NEO",
    "CCC": "Crypto", "CCY": "Crypto", "CRYPTO": "Crypto",
}
_QUOTE_TYPES = {"EQUITY": "stock", "ETF": "etf", "CRYPTOCURRENCY": "crypto"}
_SUFFIX_LABELS = ((".TO", "TSX"), (".V", "TSXV"), (".NE", "NEO"), ("-USD", "Crypto"))
_CAN_LABELS = {"TSX", "TSXV", "NEO"}

# Common crypto names -> Yahoo symbol (names are not in the tickers table).
CRYPTO_ALIASES = {
    "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum", "SOL-USD": "Solana", "BNB-USD": "BNB",
    "XRP-USD": "XRP", "ADA-USD": "Cardano", "AVAX-USD": "Avalanche", "DOT-USD": "Polkadot",
    "ATOM-USD": "Cosmos", "LINK-USD": "Chainlink", "AAVE-USD": "Aave", "MKR-USD": "Maker",
    "DOGE-USD": "Dogecoin", "SHIB-USD": "Shiba Inu", "LTC-USD": "Litecoin", "NEAR-USD": "NEAR Protocol",
}

# Well-known names for symbols the tickers table stores without one (most
# universe rows have no name). Lets typos resolve locally ("telas" -> Tesla)
# and seeds the corrected Yahoo re-query.
KNOWN_NAMES = {
    # US mega / large caps
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "Nvidia", "AMZN": "Amazon", "GOOGL": "Alphabet Google",
    "META": "Meta Platforms Facebook", "TSLA": "Tesla", "BRK-B": "Berkshire Hathaway", "AVGO": "Broadcom",
    "LLY": "Eli Lilly", "JPM": "JPMorgan Chase", "V": "Visa", "MA": "Mastercard", "UNH": "UnitedHealth",
    "XOM": "Exxon Mobil", "WMT": "Walmart", "COST": "Costco", "HD": "Home Depot", "PG": "Procter Gamble",
    "JNJ": "Johnson Johnson", "KO": "Coca-Cola", "PEP": "PepsiCo", "MCD": "McDonald's", "NFLX": "Netflix",
    "AMD": "Advanced Micro Devices AMD", "INTC": "Intel", "ORCL": "Oracle", "CRM": "Salesforce",
    "ADBE": "Adobe", "IBM": "IBM", "DIS": "Walt Disney", "NKE": "Nike", "SBUX": "Starbucks",
    "BA": "Boeing", "CAT": "Caterpillar", "GE": "General Electric", "GM": "General Motors", "F": "Ford Motor",
    "BAC": "Bank of America", "WFC": "Wells Fargo", "GS": "Goldman Sachs", "MS": "Morgan Stanley",
    "PFE": "Pfizer", "MRK": "Merck", "ABBV": "AbbVie", "CVX": "Chevron", "PLTR": "Palantir",
    "UBER": "Uber", "PYPL": "PayPal", "SHOP": "Shopify", "SNOW": "Snowflake", "CRWD": "CrowdStrike",
    "PANW": "Palo Alto Networks", "MU": "Micron", "QCOM": "Qualcomm", "TSM": "Taiwan Semiconductor TSMC",
    "ASML": "ASML", "COIN": "Coinbase", "HOOD": "Robinhood", "SPOT": "Spotify", "ABNB": "Airbnb",
    "T": "AT&T", "VZ": "Verizon", "TGT": "Target", "LOW": "Lowe's", "MSTR": "MicroStrategy Strategy",
    # Canada (TSX)
    "RY.TO": "Royal Bank of Canada", "TD.TO": "Toronto-Dominion Bank TD", "BNS.TO": "Bank of Nova Scotia Scotiabank",
    "BMO.TO": "Bank of Montreal BMO", "CM.TO": "Canadian Imperial Bank of Commerce CIBC",
    "NA.TO": "National Bank of Canada", "ENB.TO": "Enbridge", "CNR.TO": "Canadian National Railway",
    "CP.TO": "Canadian Pacific Kansas City", "SHOP.TO": "Shopify", "SU.TO": "Suncor Energy",
    "CNQ.TO": "Canadian Natural Resources", "ATD.TO": "Alimentation Couche-Tard", "DOL.TO": "Dollarama",
    "BCE.TO": "BCE Bell Canada", "T.TO": "Telus", "MFC.TO": "Manulife Financial", "SLF.TO": "Sun Life Financial",
    "BN.TO": "Brookfield", "TRI.TO": "Thomson Reuters", "CSU.TO": "Constellation Software",
    "L.TO": "Loblaw", "WN.TO": "George Weston", "FTS.TO": "Fortis", "EMA.TO": "Emera",
    "QSR.TO": "Restaurant Brands International", "OTEX.TO": "Open Text", "TFII.TO": "TFI International",
    "WCN.TO": "Waste Connections", "ABX.TO": "Barrick Gold", "NTR.TO": "Nutrien", "CCO.TO": "Cameco",
    "BB.TO": "BlackBerry", "LSPD.TO": "Lightspeed Commerce", "IFC.TO": "Intact Financial",
    # Popular ETFs
    "XEQT.TO": "iShares Core Equity ETF Portfolio", "VEQT.TO": "Vanguard All-Equity ETF Portfolio",
    "XGRO.TO": "iShares Core Growth ETF Portfolio", "VGRO.TO": "Vanguard Growth ETF Portfolio",
    "XBAL.TO": "iShares Core Balanced ETF Portfolio", "VBAL.TO": "Vanguard Balanced ETF Portfolio",
    "XIU.TO": "iShares S&P/TSX 60 Index ETF", "XIC.TO": "iShares Core S&P/TSX Capped Composite Index ETF",
    "VFV.TO": "Vanguard S&P 500 Index ETF", "ZSP.TO": "BMO S&P 500 Index ETF", "XUS.TO": "iShares Core S&P 500 Index ETF",
    "SPY": "SPDR S&P 500 ETF", "VOO": "Vanguard S&P 500 ETF", "IVV": "iShares Core S&P 500 ETF",
    "QQQ": "Invesco QQQ Nasdaq 100", "VTI": "Vanguard Total Stock Market ETF", "TQQQ": "ProShares UltraPro QQQ",
}

# Words that carry no identity ("inc", "corp") — ignored in name matching.
_STOPWORDS = {
    "inc", "corp", "corporation", "co", "company", "ltd", "limited", "plc", "the", "of", "and",
    "sa", "ag", "nv", "lp", "llc", "holdings", "group", "class", "cl", "a", "b", "etf", "fund", "trust",
}
_CLEAN = re.compile(r"[^A-Za-z0-9 .\-&'^=]")
_WORD = re.compile(r"[a-z0-9]+")


# ── Normalization ─────────────────────────────────────────────────

def normalize_query(q: str | None) -> str:
    """Trim, drop odd characters, collapse spaces, cap length. '' = nothing to search."""
    if not q:
        return ""
    s = _CLEAN.sub(" ", str(q))
    s = " ".join(s.split())[:MAX_QUERY_LEN].strip()
    if not re.search(r"[A-Za-z0-9]", s):
        return ""
    return s


def _words(text: str | None) -> list[str]:
    return [w for w in _WORD.findall((text or "").lower()) if w not in _STOPWORDS]


def base_symbol(symbol: str) -> str:
    s = symbol.upper()
    for suf, _ in _SUFFIX_LABELS:
        if s.endswith(suf):
            return s[: -len(suf)]
    return s


def label_for(symbol: str, exchange: str | None = None) -> str:
    s = symbol.upper()
    for suf, label in _SUFFIX_LABELS:
        if s.endswith(suf):
            return label
    code = str(exchange or "").upper()
    if code in EXCHANGE_LABELS:
        return EXCHANGE_LABELS[code]
    return "US"


def _type_for(symbol: str, hint: str | None = None) -> str:
    h = str(hint or "").lower()
    if symbol.upper().endswith("-USD") or h == "crypto":
        return "crypto"
    if h == "etf":
        return "etf"
    if h in ("stock", "equity"):
        return "stock"
    try:
        from app.scanners.universe import get_asset_class
        return {"ETF": "etf", "CRYPTO": "crypto"}.get(get_asset_class(symbol), "stock")
    except Exception:
        return "stock"


# ── Local candidates ──────────────────────────────────────────────

def _load_local() -> list[dict]:
    """Every symbol Signa knows, with a name when one is stored (blocking DB reads)."""
    from app.db import queries

    by_sym: dict[str, dict] = {}

    def add(symbol: str | None, name: str | None = None, exchange: str | None = None, typ: str | None = None):
        sym = str(symbol or "").strip().upper()
        if not sym or len(sym) > 20:
            return
        cur = by_sym.get(sym)
        if cur is None:
            by_sym[sym] = {"symbol": sym, "name": name or None, "exchange": exchange or None, "type_hint": typ}
        else:
            cur["name"] = cur["name"] or name or None
            cur["exchange"] = cur["exchange"] or exchange or None
            cur["type_hint"] = cur["type_hint"] or typ

    for sym, name in CRYPTO_ALIASES.items():
        add(sym, name, None, "crypto")
    for loader, label in ((queries.get_active_tickers, "tickers"), (queries.get_all_holdings, "holdings")):
        try:
            for r in loader() or []:
                add(r.get("symbol"), r.get("name"), r.get("exchange"), r.get("asset_type"))
        except Exception as e:
            logger.debug(f"symbol_search: {label} load failed: {e}")
    try:
        for sym in queries.get_all_watchlist_symbols() or set():
            add(sym)
    except Exception as e:
        logger.debug(f"symbol_search: watchlist load failed: {e}")

    for sym, name in KNOWN_NAMES.items():
        add(sym, name)

    out = []
    for c in by_sym.values():
        c["words"] = _words(c["name"])
        c["base"] = base_symbol(c["symbol"])
        out.append(c)
    return out


def local_candidates() -> list[dict]:
    cached = _local_cache.get("all")
    if cached is None:
        cached = _load_local()
        _local_cache.set("all", cached)
    return cached


def _ratio(a: str, b: str) -> float:
    """difflib similarity, nudged up for transposed letters ("telas" ~ "tesla")."""
    r = SequenceMatcher(None, a, b).ratio()
    if len(a) == len(b) and sorted(a) == sorted(b):
        r = min(1.0, r + 0.1)
    return r


def score_local(q: str, cands: list[dict]) -> tuple[list[tuple[float, dict]], dict[str, str]]:
    """Score local candidates. Returns ([(score, cand)], {typed_word: corrected_word})."""
    q_sym = q.upper().replace(" ", "")
    q_words = _words(q) or [w for w in _WORD.findall(q.lower())]
    q_name = " ".join(_WORD.findall(q.lower()))
    corrections: dict[str, tuple[float, str]] = {}
    scored: list[tuple[float, dict]] = []

    for c in cands:
        sym, base, words = c["symbol"], c["base"], c["words"]
        score = 0.0
        if q_sym == sym:
            score = 100
        elif q_sym == base:
            score = 96
        elif sym.startswith(q_sym) or base.startswith(q_sym):
            score = 85 - min(len(base) - len(q_sym), 10)
        if words and q_words:
            name_full = " ".join(words)
            if name_full.startswith(q_name) or " ".join(_WORD.findall((c["name"] or "").lower())).startswith(q_name):
                score = max(score, 78)
            elif all(any(w.startswith(qw) for w in words) for qw in q_words):
                score = max(score, 72)
            else:
                # Fuzzy: every typed word (3+ chars) must be close to some name word.
                best: list[tuple[float, str, str]] = []
                for qw in q_words:
                    if len(qw) < 3:
                        best = []
                        break
                    r, w = max(((_ratio(qw, w), w) for w in words), default=(0.0, ""))
                    if r < FUZZY_MIN:
                        best = []
                        break
                    best.append((r, qw, w))
                if best:
                    avg = sum(r for r, _, _ in best) / len(best)
                    score = max(score, 50 + avg * 10)
                    for r, qw, w in best:
                        if qw != w and r > corrections.get(qw, (0.0, ""))[0]:
                            corrections[qw] = (r, w)
        if score > 0:
            scored.append((score, c))
    return scored, {qw: w for qw, (_, w) in corrections.items()}


def corrected_query(q: str, corrections: dict[str, str]) -> str | None:
    if not corrections:
        return None
    out = " ".join(corrections.get(w, w) for w in _WORD.findall(q.lower()))
    return out if out and out != q.lower() else None


# ── Yahoo ─────────────────────────────────────────────────────────

def _yahoo_raw(q: str) -> list[dict]:
    import yfinance as yf
    return list(yf.Search(q, max_results=10, news_count=0).quotes or [])


async def yahoo_search(q: str) -> list[dict]:
    """Raw Yahoo quotes for a query (cached 1h; failures and timeouts are not cached)."""
    key = q.lower()
    cached = _yahoo_cache.get(key)
    if cached is not None:
        return cached
    try:
        quotes = await asyncio.wait_for(asyncio.to_thread(_yahoo_raw, q), timeout=YAHOO_TIMEOUT_S)
    except Exception as e:
        logger.debug(f"symbol_search: yahoo search '{q}' failed: {type(e).__name__}: {e}")
        return []
    _yahoo_cache.set(key, quotes, ttl=YAHOO_TTL_S if quotes else YAHOO_EMPTY_TTL_S)
    return quotes


def filter_yahoo(quotes: list[dict]) -> list[dict]:
    """Keep US / Canadian stocks + ETFs and USD crypto pairs, in Yahoo's order."""
    out = []
    for qt in quotes or []:
        sym = str(qt.get("symbol") or "").upper()
        typ = _QUOTE_TYPES.get(str(qt.get("quoteType") or "").upper())
        code = str(qt.get("exchange") or "").upper()
        if not sym or not typ or code not in EXCHANGE_LABELS:
            continue
        label = EXCHANGE_LABELS[code]
        if typ == "crypto":
            if not sym.endswith("-USD"):
                continue
            label = "Crypto"
        elif label == "Crypto":
            continue
        out.append({
            "symbol": sym,
            "name": qt.get("longname") or qt.get("shortname") or qt.get("longName") or qt.get("shortName"),
            "exchange": code,
            "exchange_label": label,
            "type": typ,
        })
    return out


def yahoo_relevant(q: str, yahoo: list[dict]) -> bool:
    """Does any Yahoo row actually match what was typed (symbol or name prefix)?
    Yahoo answers some typos with loosely related names ("telas" -> Texas ...)."""
    q_sym = q.upper().replace(" ", "")
    q_words = _WORD.findall(q.lower())
    for y in yahoo:
        if y["symbol"].startswith(q_sym) or base_symbol(y["symbol"]) == q_sym:
            return True
        words = _WORD.findall((y["name"] or "").lower())
        if q_words and all(any(w.startswith(qw) for w in words) for qw in q_words):
            return True
    return False


_PREFERRED = re.compile(r"-P[A-Z]{0,2}(\.(TO|V|NE))?$")


# ── Merge ─────────────────────────────────────────────────────────

def _name_key(name: str | None) -> str:
    return " ".join(_words(name)[:3])


def merge(local: list[tuple[float, dict]], yahoo: list[dict], limit: int) -> list[dict]:
    rows: dict[str, dict] = {}
    for score, c in local:
        rows[c["symbol"]] = {
            "symbol": c["symbol"],
            "name": c["name"],
            "exchange": c["exchange"],
            "exchange_label": label_for(c["symbol"], c["exchange"]),
            "type": _type_for(c["symbol"], c.get("type_hint")),
            "source": "signa",
            "_score": score,
        }
    for i, y in enumerate(yahoo):
        score = 60 - i * 1.5
        if y["exchange_label"] == "OTC":
            score = 5 - i * 0.1
        elif _PREFERRED.search(y["symbol"]):  # preferred shares (RY-PS.TO) after common
            score = 20 - i * 0.1
        cur = rows.get(y["symbol"])
        if cur:
            cur["_score"] = max(cur["_score"], score)
            cur["name"] = y["name"] or cur["name"]  # Yahoo long name beats our short alias
            cur["exchange"] = y["exchange"]
            cur["exchange_label"] = y["exchange_label"]
            cur["type"] = y["type"]
        else:
            rows[y["symbol"]] = {**y, "source": "yahoo", "_score": score}

    ranked = sorted(rows.values(), key=lambda r: (-r["_score"], r["symbol"]))

    # Dual listings (RY.TO / RY): keep a company's Canadian + US lines together,
    # Canadian first when both are present.
    out: list[dict] = []
    used: set[str] = set()
    for r in ranked:
        if r["symbol"] in used:
            continue
        group = [r]
        key = _name_key(r["name"])
        if key and r["type"] != "crypto" and r["exchange_label"] != "OTC":
            for o in ranked:
                if (o["symbol"] not in used and o is not r and o["exchange_label"] != "OTC"
                        and base_symbol(o["symbol"]) == base_symbol(r["symbol"]) and _name_key(o["name"]) == key):
                    group.append(o)
        group.sort(key=lambda g: 0 if g["exchange_label"] in _CAN_LABELS else 1)
        for g in group:
            used.add(g["symbol"])
            out.append({k: v for k, v in g.items() if k != "_score"})
    return out[:limit]


async def search(q: str | None, limit: int = 8) -> list[dict]:
    query = normalize_query(q)
    limit = max(1, min(int(limit or 8), MAX_LIMIT))
    if not query:
        return []
    try:
        cands = await asyncio.to_thread(local_candidates)
    except Exception as e:
        logger.debug(f"symbol_search: local candidates failed: {e}")
        cands = []
    local, corrections = score_local(query, cands)

    yahoo = filter_yahoo(await yahoo_search(query))
    if not yahoo_relevant(query, yahoo):
        fixed = corrected_query(query, corrections)
        if fixed:
            # Corrected matches first, then whatever Yahoo made of the raw text.
            yahoo = filter_yahoo(await yahoo_search(fixed)) + yahoo
    return merge(local, yahoo, limit)


def _reset_caches() -> None:
    _local_cache.clear()
    _yahoo_cache.clear()
