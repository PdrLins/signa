"""Similar funds (Premium, feature.similar_funds) for the stock page.

Yahoo has no "similar funds" data, so peers come from curated groups of
well-known ETFs that track the same thing (PEER_GROUPS). For the fund and up
to MAX_PEERS peers:
  expense_ratio   yearly fee, PERCENT (funds_data, shared 12 h cache)
  return_1y_pct / return_5y_pct
                  total return, PERCENT (dividend-adjusted daily closes,
                  one batched download, price_cache 6 h cache)
Rows: {"symbol", "name", "expense_ratio", "yield" (null: not measured),
       "return_1y_pct", "return_5y_pct", "current" (bool: the page's fund)}.
The whole answer is cached per symbol SIMILAR_TTL. Never raises.
"""

from __future__ import annotations

import concurrent.futures
import math
from typing import Optional

from loguru import logger

from app.core.cache import TTLCache

MAX_PEERS = 5
SIMILAR_TTL = 12 * 3600
FUND_FETCH_TIMEOUT_S = 10

# group -> members (display names). A fund in a group is compared with the others.
PEER_GROUPS: dict[str, list[tuple[str, str]]] = {
    "all_in_one_equity": [("XEQT.TO", "iShares Core Equity ETF Portfolio"), ("VEQT.TO", "Vanguard All-Equity ETF Portfolio"),
                          ("ZEQT.TO", "BMO All-Equity ETF"), ("HEQT.TO", "Global X All-Equity Asset Allocation ETF")],
    "all_in_one_growth": [("XGRO.TO", "iShares Core Growth ETF Portfolio"), ("VGRO.TO", "Vanguard Growth ETF Portfolio"),
                          ("ZGRO.TO", "BMO Growth ETF")],
    "all_in_one_balanced": [("XBAL.TO", "iShares Core Balanced ETF Portfolio"), ("VBAL.TO", "Vanguard Balanced ETF Portfolio"),
                            ("ZBAL.TO", "BMO Balanced ETF")],
    "sp500_cad": [("VFV.TO", "Vanguard S&P 500 Index ETF"), ("ZSP.TO", "BMO S&P 500 Index ETF"),
                  ("XUS.TO", "iShares Core S&P 500 Index ETF"), ("HXS.TO", "Global X S&P 500 Corporate Class ETF"),
                  ("XSP.TO", "iShares Core S&P 500 Index ETF (CAD-Hedged)")],
    "sp500_us": [("VOO", "Vanguard S&P 500 ETF"), ("SPY", "SPDR S&P 500 ETF Trust"), ("IVV", "iShares Core S&P 500 ETF"),
                 ("SPLG", "SPDR Portfolio S&P 500 ETF")],
    "us_total": [("VTI", "Vanguard Total Stock Market ETF"), ("ITOT", "iShares Core S&P Total U.S. Stock Market ETF"),
                 ("SCHB", "Schwab U.S. Broad Market ETF"), ("XUU.TO", "iShares Core S&P U.S. Total Market Index ETF"),
                 ("VUN.TO", "Vanguard U.S. Total Market Index ETF")],
    "nasdaq100": [("QQQ", "Invesco QQQ Trust"), ("QQQM", "Invesco NASDAQ 100 ETF"), ("XQQ.TO", "iShares NASDAQ 100 Index ETF (CAD-Hedged)"),
                  ("ZQQ.TO", "BMO Nasdaq 100 Equity Hedged to CAD Index ETF"), ("ZNQ.TO", "BMO Nasdaq 100 Equity Index ETF")],
    "canada_broad": [("XIC.TO", "iShares Core S&P/TSX Capped Composite Index ETF"), ("VCN.TO", "Vanguard FTSE Canada All Cap Index ETF"),
                     ("ZCN.TO", "BMO S&P/TSX Capped Composite Index ETF"), ("XIU.TO", "iShares S&P/TSX 60 Index ETF"),
                     ("HXT.TO", "Global X S&P/TSX 60 Index Corporate Class ETF")],
    "intl_developed": [("XEF.TO", "iShares Core MSCI EAFE IMI Index ETF"), ("VIU.TO", "Vanguard FTSE Developed All Cap ex North America"),
                       ("ZEA.TO", "BMO MSCI EAFE Index ETF"), ("VEA", "Vanguard FTSE Developed Markets ETF"),
                       ("IEFA", "iShares Core MSCI EAFE ETF")],
    "emerging": [("XEC.TO", "iShares Core MSCI Emerging Markets IMI Index ETF"), ("VEE.TO", "Vanguard FTSE Emerging Markets All Cap"),
                 ("ZEM.TO", "BMO MSCI Emerging Markets Index ETF"), ("VWO", "Vanguard FTSE Emerging Markets ETF"),
                 ("IEMG", "iShares Core MSCI Emerging Markets ETF")],
    "canada_dividend": [("XEI.TO", "iShares S&P/TSX Composite High Dividend Index ETF"), ("CDZ.TO", "iShares S&P/TSX Canadian Dividend Aristocrats"),
                        ("VDY.TO", "Vanguard FTSE Canadian High Dividend Yield"), ("ZDV.TO", "BMO Canadian Dividend ETF"),
                        ("XDV.TO", "iShares Canadian Select Dividend Index ETF")],
    "covered_call_ca": [("ZWC.TO", "BMO Canadian High Dividend Covered Call ETF"), ("ZWB.TO", "BMO Covered Call Canadian Banks ETF"),
                        ("ZWU.TO", "BMO Covered Call Utilities ETF"), ("HMAX.TO", "Hamilton Canadian Financials YIELD MAXIMIZER"),
                        ("ZWE.TO", "BMO Europe High Dividend Covered Call ETF")],
    "covered_call_us": [("JEPI", "JPMorgan Equity Premium Income ETF"), ("JEPQ", "JPMorgan Nasdaq Equity Premium Income ETF"),
                        ("QYLD", "Global X NASDAQ 100 Covered Call ETF"), ("XYLD", "Global X S&P 500 Covered Call ETF"),
                        ("DIVO", "Amplify CWP Enhanced Dividend Income ETF")],
    "us_dividend": [("SCHD", "Schwab U.S. Dividend Equity ETF"), ("VYM", "Vanguard High Dividend Yield ETF"),
                    ("VIG", "Vanguard Dividend Appreciation ETF"), ("DGRO", "iShares Core Dividend Growth ETF"),
                    ("DVY", "iShares Select Dividend ETF")],
    "bonds_ca": [("XBB.TO", "iShares Core Canadian Universe Bond Index ETF"), ("ZAG.TO", "BMO Aggregate Bond Index ETF"),
                 ("VAB.TO", "Vanguard Canadian Aggregate Bond Index ETF")],
    "bonds_us": [("BND", "Vanguard Total Bond Market ETF"), ("AGG", "iShares Core U.S. Aggregate Bond ETF"),
                 ("SCHZ", "Schwab U.S. Aggregate Bond ETF")],
    "reits_ca": [("ZRE.TO", "BMO Equal Weight REITs Index ETF"), ("XRE.TO", "iShares S&P/TSX Capped REIT Index ETF"),
                 ("VRE.TO", "Vanguard FTSE Canadian Capped REIT Index ETF")],
}

_cache = TTLCache(max_size=500, default_ttl=SIMILAR_TTL)


def group_of(symbol: str) -> Optional[str]:
    s = (symbol or "").upper()
    return next((g for g, members in PEER_GROUPS.items() if any(m == s for m, _ in members)), None)


def peers_for(symbol: str) -> list[tuple[str, str]]:
    """Up to MAX_PEERS (symbol, name) in the same group, the fund itself excluded. Pure."""
    g = group_of(symbol)
    if not g:
        return []
    s = symbol.upper()
    return [(m, n) for m, n in PEER_GROUPS[g] if m != s][:MAX_PEERS]


def has_peers(symbol: str) -> bool:
    return bool(peers_for(symbol))


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def period_return(series, years: int) -> Optional[float]:
    """Total return in PERCENT over the last `years` (dividend-adjusted closes;
    None when the history is shorter). Pure."""
    import pandas as pd

    if series is None or len(series) < 2:
        return None
    s = series.dropna()
    if not len(s):
        return None
    end_t = pd.Timestamp(s.index[-1])
    start_t = end_t - pd.DateOffset(years=years)
    # the close on/just before the start date, or (a download that begins a
    # few days after it) the first close within 10 days after it
    before = s[s.index <= start_t]
    if len(before) and (start_t - pd.Timestamp(before.index[-1])).days <= 10:
        a = _f(before.iloc[-1])
    else:
        after = s[s.index > start_t]
        if not len(after) or (pd.Timestamp(after.index[0]) - start_t).days > 10:
            return None
        a = _f(after.iloc[0])
    b = _f(s.iloc[-1])
    return round((b / a - 1) * 100, 2) if a and b else None


def _expense_ratio(symbol: str) -> Optional[float]:
    from app.services import stock_page
    try:
        fd = stock_page._fetch_fund(symbol)
    except Exception:
        return None
    from app.services.long_term_check import expense_ratio_fraction
    try:
        er, _src = expense_ratio_fraction({}, (fd or {}).get("expense_ratio_raw"))
    except Exception:
        return None
    er = _f(er)
    return round(er * 100, 4) if er is not None else None   # fraction -> PERCENT


def build_rows(symbol: str, name: Optional[str]) -> list[dict]:
    """Blocking. [] when the fund has no curated peers."""
    from app.services.price_cache import fetch_daily_closes

    sym = symbol.upper()
    peers = peers_for(sym)
    if not peers:
        return []
    members = [(sym, name)] + peers
    syms = [m for m, _ in members]
    try:
        closes = fetch_daily_closes(syms, period="5y")
    except Exception as e:
        logger.debug(f"similar_funds: closes failed: {e}")
        closes = {}
    fees: dict[str, Optional[float]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futs = {pool.submit(_expense_ratio, s): s for s in syms}
        try:
            for fut in concurrent.futures.as_completed(futs, timeout=FUND_FETCH_TIMEOUT_S):
                fees[futs[fut]] = fut.result()
        except concurrent.futures.TimeoutError:
            logger.debug("similar_funds: some fund fees timed out")
    return [{
        "symbol": s, "name": n,
        "expense_ratio": fees.get(s),
        "yield": None,
        "return_1y_pct": period_return(closes.get(s), 1),
        "return_5y_pct": period_return(closes.get(s), 5),
        "current": s == sym,
    } for s, n in members]


def get_similar(symbol: str, name: Optional[str]) -> list[dict]:
    """Cached per symbol. Never raises."""
    key = symbol.upper()
    hit = _cache.get(key)
    if hit is not None:
        return hit
    try:
        rows = build_rows(key, name)
    except Exception as e:
        logger.warning(f"similar_funds({key}) failed: {e}")
        rows = []
    _cache.set(key, rows, ttl=SIMILAR_TTL if rows else 1800)
    return rows
