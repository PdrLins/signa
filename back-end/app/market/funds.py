"""Fund (ETF) data for the stock page: Yahoo funds_data parsed into the
`fund` block (fees, holdings, sectors, asset mix), plus small asset-type and
currency helpers. Pure except `fetch_funds_data` (yfinance, never raises).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pandas as pd
from loguru import logger


def _num(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _r(v, nd=2) -> float | None:
    f = _num(v)
    return round(f, nd) if f is not None else None


def asset_type_for(symbol: str, info: dict) -> str:
    qt = str((info or {}).get("quoteType") or "").upper()
    if symbol.endswith("-USD") or qt == "CRYPTOCURRENCY":
        return "CRYPTO"
    if qt in ("ETF", "MUTUALFUND"):
        return "ETF"
    if qt == "EQUITY":
        return "STOCK"
    return "OTHER"


def currency_of(symbol: str, info: dict | None = None) -> str:
    from app.market.currency import currency_for, normalize_currency
    c = normalize_currency((info or {}).get("currency"))[0]   # "GBp" -> "GBP"
    return c or currency_for(symbol)


def expense_ratio_fraction(info: dict, ops_value=None) -> tuple[float | None, str | None]:
    """(expense ratio as a FRACTION, source).

    Units differ by source (checked against yfinance 1.7.0 + Yahoo):
      funds_data.fund_operations "Annual Report Expense Ratio" -> fraction (0.002)
      info["netExpenseRatio"]                                -> percent  (0.2)
      info["annualReportExpenseRatio"] (older payloads)      -> fraction
    A "fraction" above 0.05 (5%/yr) is implausible and treated as percent.
    """
    v = _num(ops_value)
    if v is not None and v >= 0:
        return (v / 100 if v > 0.05 else v), "annualReportExpenseRatio"
    v = _num((info or {}).get("netExpenseRatio"))
    if v is not None and v >= 0:
        return v / 100, "netExpenseRatio"
    v = _num((info or {}).get("annualReportExpenseRatio"))
    if v is not None and v >= 0:
        return (v / 100 if v > 0.05 else v), "annualReportExpenseRatio"
    return None, None


_FUND_WORDS = ("etf", "index fund", " fund", "portfolio", "ishares", "vanguard", "spdr", "trust")


def looks_like_fund(name: str | None) -> bool:
    n = f" {(name or '').lower()}"
    return any(w in n for w in _FUND_WORDS)


def parse_holdings(df) -> list[dict]:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []
    out = []
    for sym, row in df.iterrows():
        w = _num(row.get("Holding Percent"))
        out.append({"symbol": str(sym), "name": str(row.get("Name") or "") or None,
                    "weight": round(w * 100, 2) if w is not None else None})
    return out


def _frac_dict(d) -> dict:
    if not isinstance(d, dict):
        return {}
    out = {}
    for k, v in d.items():
        f = _num(v)
        if f is not None and f > 0:
            out[str(k)] = round(f * 100, 2)
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _df_cell(df, row: str, col=None) -> float | None:
    try:
        if df is None or not isinstance(df, pd.DataFrame) or df.empty or row not in df.index:
            return None
        c = col if col is not None and col in df.columns else df.columns[0]
        return _num(df.loc[row, c])
    except Exception:
        return None


def invert_ratio(v) -> float | None:
    """funds_data.equity_holdings reports Price/Earnings and Price/Book
    INVERTED (earnings / book yield): XEQT.TO came back 0.0486 while
    info.trailingPE was 20.6 (1 / 0.0486 = 20.6). A value below 1 is read
    as the inverse; >= 1 is taken as-is (in case Yahoo fixes it)."""
    f = _num(v)
    if f is None or f <= 0:
        return None
    return 1.0 / f if f < 1 else f


def _epoch_date(v) -> str | None:
    f = _num(v)
    if f is None:
        return None
    try:
        return datetime.fromtimestamp(f, timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def build_fund_info(info: dict, fd: dict) -> dict:
    info = info or {}
    overview = fd.get("overview") or {}
    er, er_src = expense_ratio_fraction(info, fd.get("expense_ratio_raw"))
    holdings = fd.get("holdings") or []
    weights = [h["weight"] for h in holdings if h.get("weight") is not None]
    top10 = round(sum(sorted(weights, reverse=True)[:10]), 2) if weights else None
    fund_like = [h for h in holdings if looks_like_fund(h.get("name"))]
    fof = bool(holdings) and len(fund_like) * 2 > len(holdings)
    aum = _num(info.get("totalAssets"))
    return {
        "expense_ratio": round(er * 100, 4) if er is not None else None,   # percent
        "expense_ratio_source": er_src,
        "aum": aum,
        "yield": _r((_num(info.get("yield")) or 0) * 100) if _num(info.get("yield")) is not None else None,
        "family": info.get("fundFamily") or overview.get("family"),
        "category": info.get("category") or overview.get("categoryName"),
        "legal_type": overview.get("legalType") or info.get("legalType"),
        "inception_date": _epoch_date(info.get("fundInceptionDate")),
        "top_holdings": holdings[:15],
        "holdings_listed": len(holdings),
        "top10_weight": top10,
        "fund_of_funds": fof,
        "sector_weights": fd.get("sector_weights") or {},
        "asset_classes": fd.get("asset_classes") or {},
        "pe": _r(_num(info.get("trailingPE")) or invert_ratio(fd.get("pe"))),
        "pb": _r(invert_ratio(fd.get("pb"))),
        "turnover": _r((_num(fd.get("turnover")) or 0) * 100) if _num(fd.get("turnover")) is not None else None,
    }


def fetch_funds_data(symbol: str, ticker=None) -> dict:
    """Ticker.funds_data parsed for build_fund_info (blocking, never raises):
    {"overview", "expense_ratio_raw", "turnover", "total_net_assets",
     "holdings", "sector_weights", "asset_classes", "pe", "pb"}. Used by the
    stock page's `fund` block and similar funds."""
    if ticker is None:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
    t = ticker
    fd: dict = {}
    try:
        f = t.funds_data
        for attr, key in (("fund_overview", "overview"),):
            try:
                fd[key] = getattr(f, attr) or {}
            except Exception:
                fd[key] = {}
        try:
            ops = f.fund_operations
            fd["expense_ratio_raw"] = _df_cell(ops, "Annual Report Expense Ratio")
            fd["turnover"] = _df_cell(ops, "Annual Holdings Turnover")
            fd["total_net_assets"] = _df_cell(ops, "Total Net Assets")
        except Exception:
            pass
        try:
            fd["holdings"] = parse_holdings(f.top_holdings)
        except Exception:
            fd["holdings"] = []
        try:
            fd["sector_weights"] = _frac_dict(f.sector_weightings)
        except Exception:
            pass
        try:
            fd["asset_classes"] = _frac_dict(f.asset_classes)
        except Exception:
            pass
        try:
            eq = f.equity_holdings
            fd["pe"] = _df_cell(eq, "Price/Earnings")
            fd["pb"] = _df_cell(eq, "Price/Book")
        except Exception:
            pass
    except Exception as e:
        logger.debug(f"funds: funds_data({symbol}) failed: {e}")
    return fd
