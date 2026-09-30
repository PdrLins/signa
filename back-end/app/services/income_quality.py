"""Income quality of one payer (GET /api/v1/portfolio/income-quality/{symbol}). No AI.

Shared market data only (dividend profile ~12h, daily closes ~6h), the
result cached per symbol for CACHE_TTL (12h) and shared by every user.

income_class
  cash_like      T-bill / money-market / savings ETFs (holdings_service
                 .CASH_LIKE_FUNDS, or name has "money market", "t-bill",
                 "treasury bill", "high interest savings", "cash management")
  option_income  covered-call / option-income funds (COVERED_CALL_FUNDS,
                 a symbol in UNDERLYING, or name has "covered call",
                 "option income", "premium income", "buywrite", "buy-write",
                 "yieldmax", "enhanced yield", "option strategy")
  steady         everything else that pays

yield_source (short code)
  interest                  cash_like
  option_premiums           option_income
  dividends_from_earnings   a stock with payout ratio <= 100% (or unknown)
  dividends_exceed_earnings a stock with payout ratio > 100%
  fund_distributions        other funds
  flags: ["return_of_capital_possible"] when an option-income fund yields
         >= ROC_YIELD (12%): part of the payout is likely your own capital.

payout_history: the payments of the last 12 months (oldest first) with the
change vs the previous payment; min/max_change_pct over those changes
(month-over-month for monthly payers).

total_return_5y: dividend-adjusted closes (price_cache.fetch_daily_closes,
auto_adjust=True) over the common window of the symbol and its UNDERLYING
(at most 5 years). Returns are in each listing's own currency
(currency_mismatch=true when they differ, e.g. QQCL.TO vs QQQ). Unknown
underlying -> underlying null, comparison null.
"""

from __future__ import annotations

import asyncio
import math
from datetime import date

from app.core.api_errors import api_error
from app.core.cache import TTLCache
from app.services import dividends
from app.services.holdings_service import CASH_LIKE_FUNDS, COVERED_CALL_FUNDS, base_symbol

CACHE_TTL = 12 * 3600
ROC_YIELD = 0.12
_cache = TTLCache(max_size=500, default_ttl=CACHE_TTL)

# Option-income fund -> what it writes options on (hand-maintained).
UNDERLYING: dict[str, str] = {
    "QYLD": "QQQ", "XYLD": "SPY", "RYLD": "IWM", "DJIA": "DIA",
    "JEPI": "SPY", "JEPQ": "QQQ", "SPYI": "SPY", "QQQI": "QQQ", "DIVO": "SPY", "GPIX": "SPY", "GPIQ": "QQQ",
    "NVDY": "NVDA", "TSLY": "TSLA", "CONY": "COIN", "MSTY": "MSTR", "AMZY": "AMZN", "APLY": "AAPL",
    "GOOY": "GOOGL", "MSFO": "MSFT", "NFLY": "NFLX", "FBY": "META", "AMDY": "AMD", "OARK": "ARKK",
    "QQCL.TO": "QQQ", "QQCC.TO": "QQQ", "ZWT.TO": "XLK", "ZWS.TO": "SPY", "ZWH.TO": "SPY",
    "HYLD.TO": "SPY", "ZWC.TO": "XIU.TO", "ZWB.TO": "ZEB.TO", "ZWU.TO": "ZUT.TO",
}
_CASH_WORDS = ("money market", "t-bill", "treasury bill", "high interest savings", "cash management")
_OPTION_WORDS = ("covered call", "option income", "premium income", "buywrite", "buy-write", "yieldmax",
                 "enhanced yield", "option strategy")


def _f(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _r(v, nd=2):
    return round(v, nd) if v is not None and math.isfinite(v) else None


def income_class(symbol: str, profile: dict | None) -> str:
    b = base_symbol(symbol)
    name = f"{(profile or {}).get('name') or ''} {(profile or {}).get('category') or ''}".lower()
    if b in CASH_LIKE_FUNDS or any(w in name for w in _CASH_WORDS):
        return "cash_like"
    if b in COVERED_CALL_FUNDS or symbol.upper() in UNDERLYING or any(w in name for w in _OPTION_WORDS):
        return "option_income"
    return "steady"


def yield_source(cls: str, profile: dict | None) -> tuple[str, list[str]]:
    p = profile or {}
    y = _f(p.get("yield"))
    if cls == "cash_like":
        return "interest", []
    if cls == "option_income":
        return "option_premiums", ["return_of_capital_possible"] if y is not None and y >= ROC_YIELD else []
    if p.get("is_fund"):
        return "fund_distributions", []
    payout = _f(p.get("payout_ratio"))
    return ("dividends_exceed_earnings" if payout is not None and payout > 1.0 else "dividends_from_earnings"), []


def payout_history(profile: dict | None, today: date) -> dict:
    rows = []
    prev = None
    for p in (profile or {}).get("history") or (profile or {}).get("last_payments") or []:
        try:
            d = date.fromisoformat(str(p.get("ex_date"))[:10])
        except ValueError:
            continue
        a = _f(p.get("amount"))
        if a is None or not (0 <= (today - d).days <= 365):
            continue
        rows.append((d, a, bool(p.get("special"))))
    rows.sort()
    out = []
    changes = []
    for d, a, sp in rows:
        ch = (a / prev - 1) * 100 if prev else None
        if ch is not None:
            changes.append(ch)
        out.append({"ex_date": d.isoformat(), "amount": round(a, 6), "special": sp, "change_pct": _r(ch)})
        prev = a
    return {"payments": out, "min_change_pct": _r(min(changes)) if changes else None,
            "max_change_pct": _r(max(changes)) if changes else None}


def window_total_return(a, b=None) -> dict | None:
    """Total return (pct) of series a (and b) over their common window (<= 5y). Pure."""
    import pandas as pd

    if a is None or len(a) < 2:
        return None
    start = a.index[0]
    end = a.index[-1]
    if b is not None and len(b) >= 2:
        start = max(start, b.index[0])
        end = min(end, b.index[-1])
    start = max(start, end - pd.Timedelta(days=int(5 * 365.25)))

    def tr(s):
        w = s[(s.index >= start) & (s.index <= end)]
        return (float(w.iloc[-1]) / float(w.iloc[0]) - 1) * 100 if len(w) >= 2 and float(w.iloc[0]) > 0 else None
    years = (end - start).days / 365.25
    return {"start": start.date().isoformat(), "end": end.date().isoformat(), "years": _r(years, 1),
            "symbol_pct": _r(tr(a)), "underlying_pct": _r(tr(b)) if b is not None and len(b) >= 2 else None}


def build_quality(symbol: str, profile: dict | None, closes: dict, today: date) -> dict:
    """The response body. Pure."""
    from app.services.price_cache import native_currency

    p = profile or {}
    cls = income_class(symbol, p)
    src, flags = yield_source(cls, p)
    und = UNDERLYING.get(symbol.upper())
    ret = window_total_return(closes.get(symbol), closes.get(und) if und else None)
    comparison = None
    if und and ret and ret.get("symbol_pct") is not None and ret.get("underlying_pct") is not None:
        comparison = {"difference_pct": _r(ret["symbol_pct"] - ret["underlying_pct"]),
                      "currency_mismatch": native_currency(symbol) != native_currency(und)}
    y = _f(p.get("yield"))
    return {
        "symbol": symbol,
        "name": p.get("name"),
        "pays_dividend": bool(p.get("pays_dividend")),
        "yield_pct": _r(y * 100) if y is not None else None,
        "frequency": p.get("frequency"),
        "income_class": cls,
        "yield_source": src,
        "flags": flags,
        "payout_history": payout_history(p, today),
        "underlying": und,
        "total_return_5y": ret,
        "comparison": comparison,
        "as_of": today.isoformat(),
    }


async def get_income_quality(raw_symbol: str) -> dict:
    from app.core.utils import validate_ticker
    from app.services.price_cache import fetch_daily_closes

    sym = str(raw_symbol or "").strip().upper()
    if not sym or len(sym) > 24 or not validate_ticker(sym):
        raise api_error("invalid_symbol", "Enter a ticker symbol like JEPI, QQCL.TO or ENB.TO.", 422, field="symbol")
    cached = _cache.get(sym)
    if cached is not None:
        return cached
    profile = await dividends.get_dividend_profile(sym)
    und = UNDERLYING.get(sym)
    closes = await asyncio.to_thread(fetch_daily_closes, [s for s in (sym, und) if s], "5y")
    if closes.get(sym) is None and profile.get("reason") in ("unavailable", "no_dividend") \
            and not profile.get("last_payments") and not profile.get("history"):
        raise api_error("not_found", f"No market data for {sym}.", 404)
    body = build_quality(sym, profile, closes, dividends.today_et())
    _cache.set(sym, body)
    return body
