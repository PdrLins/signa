"""On-demand "Check a stock" — LONG-TERM mode.

Answers "is this a sound long-term holding?" (5+ years) for an ETF, a
stock or a crypto asset. Unlike the short-term check (stock_check.py) it
makes no timing call and gives no sizing advice. Never persists anything.

Pipeline:

  resolving    stock_check.resolve_symbol (shared)
  history      max daily history (auto_adjust=True: dividends reinvested)
  benchmark    benchmark history (+ USD/CAD FX when currencies differ)
  fundamentals ETF: fund profile + funds_data; stock: .info ratios,
               income statement trend, estimate revisions (enrichment)
  sentiment    stocks only: provider.analyze_sentiment (cached) — used ONLY
               for material, cited red flags
  assessment   one decision-tier Claude call (provider.assess_long_term);
               on failure a deterministic verdict from the scorecard

yfinance sources (verified against the installed yfinance 1.7.0):
  * Ticker.history(period="max", auto_adjust=True)
  * Ticker.info — quoteType, longName, currency, category, fundFamily,
    netExpenseRatio (PERCENT units: 0.2 == 0.20%), totalAssets, yield
    (fraction), trailingPE, forwardPE, trailingPegRatio / pegRatio,
    priceToBook, enterpriseToEbitda, freeCashflow, marketCap,
    returnOnEquity / profitMargins / operatingMargins (fractions),
    debtToEquity (PERCENT: 150 == 1.5x), currentRatio, revenueGrowth,
    earningsGrowth, payoutRatio (fraction), fiveYearAvgDividendYield
    (PERCENT), sector, industry. ETFs also carry trailingPE (the
    holdings' weighted P/E).
  * Ticker.funds_data (scrapers/funds.py): fund_overview {categoryName,
    family, legalType}; fund_operations DataFrame (index "Annual Report
    Expense Ratio" / "Annual Holdings Turnover" / "Total Net Assets",
    column = symbol; expense ratio is a FRACTION: 0.002 == 0.20%);
    top_holdings DataFrame (index Symbol, columns Name / Holding Percent
    as a fraction); sector_weightings / asset_classes dicts (fractions);
    equity_holdings DataFrame (index Price/Earnings, Price/Book, ...;
    Yahoo reports these INVERTED — see invert_ratio). fund_operations
    "Total Net Assets" is not in currency units, so AUM comes from
    info["totalAssets"] only.
  * Ticker.income_stmt — annual, rows "Total Revenue" / "Net Income"

Every threshold below is a HEURISTIC, not a law; they are named constants
so they are easy to audit and change. Missing data never raises: the
category is rated "n/a".
"""

from __future__ import annotations

import asyncio
import json
import math
from datetime import datetime, timezone
from typing import Any, Callable

import pandas as pd
from loguru import logger

from app.core.cache import TTLCache
from app.core.config import settings
from app.services import stock_check as sc

ProgressFn = Callable[[str, int], None]
PHASES = ("resolving", "history", "benchmark", "fundamentals", "sentiment", "assessment", "done")

WINDOWS_YEARS = (1, 3, 5, 10)
TRADING_DAYS = 252
CRYPTO_DAYS = 365
VOL_LOOKBACK_YEARS = 5            # volatility uses the last 5y (or all history)
WINDOW_START_TOLERANCE_DAYS = 10  # a window needs history starting within this of its start date

# ── Scorecard thresholds (heuristics) ──
# cost: ETF expense ratio as a FRACTION
ER_GOOD_MAX = 0.0025               # <= 0.25%/yr
ER_FAIR_MAX = 0.0060               # <= 0.60%/yr, above -> poor
# diversification: top-10 holdings weight (fraction of the fund)
TOP10_GOOD_MAX = 0.30
TOP10_FAIR_MAX = 0.50
FUND_OF_FUNDS_GOOD_MIN = 3         # >= 3 underlying funds -> broad
# track record: excess CAGR vs benchmark (percentage points / yr)
TRACK_MIN_YEARS = 3
EXCESS_GOOD_MIN = -1.0             # within 1pp/yr of the index (or better)
EXCESS_FAIR_MIN = -3.0
ABS_CAGR_GOOD_MIN = 7.0            # no benchmark: absolute CAGR bands
ABS_CAGR_FAIR_MIN = 0.0
# valuation (sector-agnostic — see caveat in the reason text)
PE_GOOD_MAX = 20.0
PE_FAIR_MAX = 35.0
FCF_YIELD_GOOD_MIN = 0.05
FCF_YIELD_FAIR_MIN = 0.02
ETF_PE_GOOD_MAX = 18.0
ETF_PE_FAIR_MAX = 28.0
# risk (drawdown over the full history, as a negative %; annualized vol %)
MDD_GOOD_MIN = -40.0
MDD_FAIR_MIN = -60.0
VOL_GOOD_MAX = 20.0
VOL_FAIR_MAX = 35.0
# quality (stocks)
ROE_GOOD_MIN, ROE_FAIR_MIN = 0.15, 0.08
OPM_GOOD_MIN, OPM_FAIR_MIN = 0.15, 0.05
DE_GOOD_MAX, DE_FAIR_MAX = 100.0, 200.0     # yfinance debtToEquity is in percent
CR_GOOD_MIN, CR_FAIR_MIN = 1.5, 1.0

# ── Benchmarks ──
US_BENCHMARK = "SPY"
TSX_BENCHMARK = "XIU.TO"
GLOBAL_BENCHMARK = "VT"
CRYPTO_BENCHMARK = "BTC-USD"
# Global / all-world heuristic: a fund whose category or name contains one
# of these is compared with VT (Vanguard Total World). "equity portfolio"
# catches the Canadian asset-allocation ETFs (XEQT "iShares Core Equity ETF
# Portfolio", VEQT "Vanguard All-Equity ETF Portfolio", ZEQT, ...) which
# hold ~25% Canada / ~45% US / ~30% international, so a world index is the
# fairer yardstick than XIU (Canada only) or SPY (US only).
GLOBAL_KEYWORDS = ("global", "world", "all-world", "all world", "all-country", "all country",
                   "acwi", "equity portfolio", "equity etf portfolio", "all-equity", "all equity")

RATING_POINTS = {"good": 2, "fair": 1, "poor": 0}

CAVEATS = [
    {"code": "not_advice", "text": "Not financial advice. Whether it suits you depends on your goals, horizon and risk tolerance."},
    {"code": "past_returns", "text": "Past returns (dividends reinvested) do not predict future returns."},
    {"code": "heuristics", "text": "The scorecard uses simple rule-of-thumb thresholds; they ignore sector norms and context."},
    {"code": "no_timing", "text": "This is a long-term view: it says nothing about whether this week is a good time to buy."},
]

_data_cache = TTLCache(max_size=300, default_ttl=24 * 3600)
_history_cache = TTLCache(max_size=300, default_ttl=24 * 3600)


def _ttl() -> int:
    return max(1, int(settings.stock_check_long_cache_hours * 3600))


def _num(v) -> float | None:
    return sc._num(v)


def _r(v, nd=2) -> float | None:
    f = _num(v)
    return round(f, nd) if f is not None else None


# ============================================================
# Price-history math (pure)
# ============================================================

def clean_closes(df_or_series) -> pd.Series:
    """Close series with a tz-naive DatetimeIndex, sorted, positive only."""
    if df_or_series is None:
        return pd.Series(dtype=float)
    s = df_or_series["Close"] if isinstance(df_or_series, pd.DataFrame) else df_or_series
    if s is None or len(s) == 0:
        return pd.Series(dtype=float)
    s = pd.to_numeric(s, errors="coerce").dropna()
    s = s[s > 0]
    idx = pd.DatetimeIndex(s.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    s = pd.Series(s.values, index=idx.normalize()).sort_index()
    return s[~s.index.duplicated(keep="last")]


def window_return(closes: pd.Series, years: int, end: pd.Timestamp | None = None) -> dict | None:
    """Total return + CAGR (both %) over the `years` ending at `end`.

    None when the history does not reach back to the window start (within
    WINDOW_START_TOLERANCE_DAYS)."""
    if closes is None or len(closes) < 2:
        return None
    end = end if end is not None else closes.index[-1]
    upto = closes[closes.index <= end]
    if len(upto) < 2:
        return None
    start = end - pd.DateOffset(years=years)
    if upto.index[0] > start + pd.Timedelta(days=WINDOW_START_TOLERANCE_DAYS):
        return None
    before = upto[upto.index <= start]
    p0 = float(before.iloc[-1]) if len(before) else float(upto.iloc[0])
    p1 = float(upto.iloc[-1])
    total = p1 / p0 - 1
    cagr = (p1 / p0) ** (1.0 / years) - 1
    return {"total": round(total * 100, 2), "cagr": round(cagr * 100, 2)}


def history_years(closes: pd.Series) -> float:
    if closes is None or len(closes) < 2:
        return 0.0
    return (closes.index[-1] - closes.index[0]).days / 365.25


def since_inception(closes: pd.Series) -> dict | None:
    yrs = history_years(closes)
    if yrs <= 0:
        return None
    p0, p1 = float(closes.iloc[0]), float(closes.iloc[-1])
    return {"total": round((p1 / p0 - 1) * 100, 2),
            "cagr": round(((p1 / p0) ** (1 / yrs) - 1) * 100, 2) if yrs >= 1 else None,
            "years": round(yrs, 1), "start": closes.index[0].date().isoformat()}


def annualized_volatility(closes: pd.Series, periods_per_year: int = TRADING_DAYS,
                          lookback_years: int = VOL_LOOKBACK_YEARS) -> float | None:
    """Annualized stdev of daily log returns (%), last `lookback_years`."""
    if closes is None or len(closes) < 30:
        return None
    start = closes.index[-1] - pd.DateOffset(years=lookback_years)
    s = closes[closes.index >= start]
    rets = (s / s.shift(1)).apply(lambda x: math.log(x) if x and x > 0 else float("nan")).dropna()
    if len(rets) < 20:
        return None
    return round(float(rets.std(ddof=1)) * math.sqrt(periods_per_year) * 100, 2)


def max_drawdown(closes: pd.Series) -> dict | None:
    """Deepest peak-to-trough fall and its recovery.

    {depth_pct (negative), peak_date, trough_date, recovery_date | None,
     recovered, recovery_days (trough -> back at the old peak),
     underwater_days (peak -> recovery, or peak -> today if not recovered)}
    """
    if closes is None or len(closes) < 2:
        return None
    running = closes.cummax()
    dd = closes / running - 1
    trough = dd.idxmin()
    depth = float(dd.loc[trough])
    if depth >= 0:
        return {"depth_pct": 0.0, "peak_date": None, "trough_date": None, "recovery_date": None,
                "recovered": True, "recovery_days": 0, "underwater_days": 0}
    peak_val = float(running.loc[trough])
    before = closes[closes.index <= trough]
    peak_date = before[before >= peak_val].index[-1]
    after = closes[closes.index > trough]
    rec = after[after >= peak_val]
    rec_date = rec.index[0] if len(rec) else None
    last = closes.index[-1]
    return {
        "depth_pct": round(depth * 100, 2),
        "peak_date": peak_date.date().isoformat(),
        "trough_date": trough.date().isoformat(),
        "recovery_date": rec_date.date().isoformat() if rec_date is not None else None,
        "recovered": rec_date is not None,
        "recovery_days": (rec_date - trough).days if rec_date is not None else None,
        "underwater_days": ((rec_date if rec_date is not None else last) - peak_date).days,
    }


def current_drawdown(closes: pd.Series) -> dict | None:
    if closes is None or len(closes) < 1:
        return None
    ath_date = closes.idxmax()
    ath = float(closes.loc[ath_date])
    return {"pct": round((float(closes.iloc[-1]) / ath - 1) * 100, 2),
            "ath": round(ath, 4), "ath_date": ath_date.date().isoformat()}


def calendar_year_returns(closes: pd.Series) -> list[dict]:
    """Complete calendar years only: year-end close vs prior year-end close.
    The first year counts only when history starts in its first week; the
    current (incomplete) year is excluded."""
    if closes is None or len(closes) < 2:
        return []
    ye = closes.groupby(closes.index.year).last()
    out = []
    years = list(ye.index)
    last_year = closes.index[-1].year
    first = closes.index[0]
    for i, y in enumerate(years):
        if y == last_year and not (closes.index[-1].month == 12 and closes.index[-1].day >= 24):
            continue
        if i == 0:
            if first.month == 1 and first.day <= 7:
                base = float(closes.iloc[0])
            else:
                continue
        else:
            base = float(ye.iloc[i - 1])
        out.append({"year": int(y), "return": round((float(ye.iloc[i]) / base - 1) * 100, 2)})
    return out


def worst_year(cal: list[dict]) -> dict | None:
    return min(cal, key=lambda r: r["return"]) if cal else None


def returns_table(asset: pd.Series, bench: pd.Series | None) -> list[dict]:
    """1/3/5/10y rows (only where the asset has history), same end date."""
    rows = []
    if asset is None or len(asset) < 2:
        return rows
    end = asset.index[-1]
    for y in WINDOWS_YEARS:
        a = window_return(asset, y, end)
        if a is None:
            continue
        b = window_return(bench, y, end) if bench is not None and len(bench) > 1 else None
        rows.append({
            "period": f"{y}y", "years": y,
            "asset_total": a["total"], "asset_cagr": a["cagr"],
            "benchmark_total": b["total"] if b else None,
            "benchmark_cagr": b["cagr"] if b else None,
            "excess_cagr": round(a["cagr"] - b["cagr"], 2) if b else None,
        })
    return rows


def convert_currency(bench: pd.Series, fx: pd.Series | None, multiply: bool) -> pd.Series | None:
    """Re-express a benchmark series in the asset's currency: bench * fx
    (multiply) or bench / fx, with fx forward-filled onto bench dates."""
    if bench is None or fx is None or len(bench) == 0 or len(fx) == 0:
        return None
    f = fx.reindex(fx.index.union(bench.index)).sort_index().ffill().reindex(bench.index)
    out = (bench * f) if multiply else (bench / f)
    return out.dropna()


# ============================================================
# Asset type + benchmark (pure)
# ============================================================

def asset_type_for(symbol: str, info: dict) -> str:
    qt = str((info or {}).get("quoteType") or "").upper()
    if symbol.endswith("-USD") or qt == "CRYPTOCURRENCY":
        return "CRYPTO"
    if qt in ("ETF", "MUTUALFUND"):
        return "ETF"
    if qt == "EQUITY":
        return "STOCK"
    return "OTHER"


def is_global_fund(info: dict, category: str | None = None) -> bool:
    text = " ".join(str(x or "") for x in (
        category, (info or {}).get("category"), (info or {}).get("longName"), (info or {}).get("shortName"),
    )).lower()
    return any(k in text for k in GLOBAL_KEYWORDS)


def select_benchmark(symbol: str, asset_type: str, info: dict, category: str | None = None) -> str | None:
    """Benchmark heuristic (documented at GLOBAL_KEYWORDS):
      crypto -> BTC-USD (None for BTC-USD itself: it IS the benchmark)
      ETF whose name/category reads global/world/all-equity portfolio -> VT
      TSX / TSXV listing (.TO / .V) -> XIU.TO
      everything else -> SPY
    """
    if asset_type == "CRYPTO":
        return None if symbol == CRYPTO_BENCHMARK else CRYPTO_BENCHMARK
    if asset_type == "ETF" and is_global_fund(info, category):
        return GLOBAL_BENCHMARK
    if symbol.endswith((".TO", ".V")):
        return TSX_BENCHMARK
    return US_BENCHMARK


def currency_of(symbol: str, info: dict | None = None) -> str:
    c = str((info or {}).get("currency") or "").upper()
    if c:
        return c
    return "CAD" if symbol.endswith((".TO", ".V")) else "USD"


# ============================================================
# Fund / stock data parsing (pure)
# ============================================================

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


def income_trend(df) -> list[dict]:
    """[{year, revenue, net_income}] oldest -> newest from Ticker.income_stmt."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []
    out = []
    for col in df.columns:
        try:
            year = pd.Timestamp(col).year
        except Exception:
            continue
        rev = _df_cell(df, "Total Revenue", col)
        ni = _df_cell(df, "Net Income", col)
        if rev is None and ni is None:
            continue
        out.append({"year": int(year), "revenue": rev, "net_income": ni})
    return sorted(out, key=lambda r: r["year"])


def growth_cagr(first: float | None, last: float | None, years: int) -> float | None:
    if first is None or last is None or years <= 0 or first <= 0 or last <= 0:
        return None
    return round(((last / first) ** (1 / years) - 1) * 100, 2)


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


def build_fundamentals(info: dict, trend: list[dict], revisions: dict | None) -> dict:
    from app.scanners.market_scanner import _cap_dividend_yield, _dividend_yield_fraction

    info = info or {}
    mcap = _num(info.get("marketCap"))
    fcf = _num(info.get("freeCashflow"))
    fcf_yield = (fcf / mcap) if fcf is not None and mcap else None
    dy = _cap_dividend_yield(_dividend_yield_fraction(info))
    five = _num(info.get("fiveYearAvgDividendYield"))  # percent units
    rev_cagr = ni_cagr = None
    if len(trend) >= 2:
        n = trend[-1]["year"] - trend[0]["year"]
        rev_cagr = growth_cagr(trend[0].get("revenue"), trend[-1].get("revenue"), n)
        ni_cagr = growth_cagr(trend[0].get("net_income"), trend[-1].get("net_income"), n)
    rev = revisions or {}
    return {
        "market_cap": mcap,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "valuation": {
            "trailing_pe": _r(info.get("trailingPE")),
            "forward_pe": _r(info.get("forwardPE")),
            "peg": _r(info.get("trailingPegRatio") if info.get("trailingPegRatio") is not None else info.get("pegRatio")),
            "price_to_book": _r(info.get("priceToBook")),
            "ev_to_ebitda": _r(info.get("enterpriseToEbitda")),
            "fcf_yield": _r(fcf_yield * 100) if fcf_yield is not None else None,       # percent
        },
        "quality": {
            "roe": _r(_pct(info.get("returnOnEquity"))),
            "profit_margin": _r(_pct(info.get("profitMargins"))),
            "operating_margin": _r(_pct(info.get("operatingMargins"))),
            "debt_to_equity": _r(info.get("debtToEquity")),     # percent (150 == 1.5x)
            "current_ratio": _r(info.get("currentRatio")),
        },
        "growth": {
            "revenue_growth": _r(_pct(info.get("revenueGrowth"))),
            "earnings_growth": _r(_pct(info.get("earningsGrowth"))),
            "revenue_cagr": rev_cagr,
            "net_income_cagr": ni_cagr,
            "trend": trend,
        },
        "dividend": {
            "yield": _r(dy * 100) if dy is not None else None,
            "payout_ratio": _r(_pct(info.get("payoutRatio"))),
            "five_year_avg_yield": _r(five),
        },
        "estimates": {
            "revision_momentum": _r(rev.get("eps_revision_momentum")),
            "up_30d": rev.get("eps_revisions_up_30d"),
            "down_30d": rev.get("eps_revisions_down_30d"),
            "fy1_change_90d": _r(rev.get("eps_est_change_fy1_90d_pct")),
        },
    }


def _pct(v) -> float | None:
    f = _num(v)
    return f * 100 if f is not None else None


# ============================================================
# Scorecard (pure)
# ============================================================

def _item(key_code: str, rating: str, reason: str, params: dict | None = None) -> dict:
    """Scorecard row. `key_code` is "<category>:<code>"; the code is a stable
    id of the reason template (the UI localizes it with `params`), `reason`
    is the English fallback."""
    key, _, code = key_code.partition(":")
    return {"key": key, "code": code or key, "rating": rating, "reason": reason, "params": params or {}}


def _band_low(v: float, good_max: float, fair_max: float) -> str:
    return "good" if v <= good_max else "fair" if v <= fair_max else "poor"


def _band_high(v: float, good_min: float, fair_min: float) -> str:
    return "good" if v >= good_min else "fair" if v >= fair_min else "poor"


def _combine(ratings: list[str]) -> str:
    pts = [RATING_POINTS[r] for r in ratings if r in RATING_POINTS]
    if not pts:
        return "n/a"
    m = sum(pts) / len(pts)
    return "good" if m >= 1.5 else "fair" if m >= 0.75 else "poor"


def score_cost(asset_type: str, fund: dict | None) -> dict:
    if asset_type != "ETF":
        return _item("cost:no_fee", "n/a", "No fund fee (you pay only trading costs).")
    er = _num((fund or {}).get("expense_ratio"))
    if er is None:
        return _item("cost:missing", "n/a", "Expense ratio not available.")
    rating = _band_low(er / 100, ER_GOOD_MAX, ER_FAIR_MAX)
    return _item("cost:expense_ratio", rating, f"Expense ratio {er:.2f}%/yr (good ≤ {ER_GOOD_MAX*100:.2f}%, "
                                 f"poor > {ER_FAIR_MAX*100:.2f}%).", {"expense_ratio": er})


def score_diversification(asset_type: str, fund: dict | None) -> dict:
    if asset_type == "STOCK":
        return _item("diversification:single_stock", "poor",
                     "Single company: all the risk sits in one business (an index fund spreads it).")
    if asset_type == "CRYPTO":
        return _item("diversification:single_crypto", "poor", "Single crypto asset: no diversification.")
    if asset_type != "ETF":
        return _item("diversification:missing", "n/a", "Holdings not available.")
    f = fund or {}
    holdings = f.get("top_holdings") or []
    if f.get("fund_of_funds"):
        n = f.get("holdings_listed") or len(holdings)
        rating = "good" if n >= FUND_OF_FUNDS_GOOD_MIN else "fair"
        return _item("diversification:fund_of_funds", rating,
                     f"Fund of funds: holds {n} underlying funds, so concentration is in index funds, "
                     "not single companies.", {"funds": n})
    top10 = _num(f.get("top10_weight"))
    if top10 is None:
        return _item("diversification:missing", "n/a", "Top holdings not available.")
    rating = _band_low(top10 / 100, TOP10_GOOD_MAX, TOP10_FAIR_MAX)
    return _item("diversification:top10", rating, f"Top 10 holdings are {top10:.1f}% of the fund "
                                            f"(good ≤ {TOP10_GOOD_MAX*100:.0f}%, poor > {TOP10_FAIR_MAX*100:.0f}%).",
                 {"top10": top10})


def track_window(rows: list[dict]) -> dict | None:
    """Longest window >= TRACK_MIN_YEARS (prefers one with a benchmark)."""
    eligible = [r for r in rows if r["years"] >= TRACK_MIN_YEARS]
    with_b = [r for r in eligible if r.get("excess_cagr") is not None]
    pool = with_b or eligible
    return max(pool, key=lambda r: r["years"]) if pool else None


def score_track_record(rows: list[dict], benchmark: str | None) -> dict:
    w = track_window(rows)
    if w is None:
        return _item("track_record:short_history", "n/a", f"Less than {TRACK_MIN_YEARS} years of history.",
                     {"years": TRACK_MIN_YEARS})
    if w.get("excess_cagr") is not None:
        ex = w["excess_cagr"]
        rating = _band_high(ex, EXCESS_GOOD_MIN, EXCESS_FAIR_MIN)
        return _item("track_record:vs_benchmark", rating,
                     f"{w['period']} CAGR {w['asset_cagr']:.1f}% vs {benchmark} {w['benchmark_cagr']:.1f}% "
                     f"({ex:+.1f} pp/yr).",
                     {"period": w["period"], "cagr": w["asset_cagr"], "benchmark": benchmark,
                      "benchmark_cagr": w["benchmark_cagr"], "excess": ex})
    rating = _band_high(w["asset_cagr"], ABS_CAGR_GOOD_MIN, ABS_CAGR_FAIR_MIN)
    return _item("track_record:absolute", rating, f"{w['period']} CAGR {w['asset_cagr']:.1f}% (no benchmark comparison).",
                 {"period": w["period"], "cagr": w["asset_cagr"]})


def score_valuation(asset_type: str, fund: dict | None, fundamentals: dict | None) -> dict:
    if asset_type == "ETF":
        pe = _num((fund or {}).get("pe"))
        if pe is None or pe <= 0:
            return _item("valuation:missing", "n/a", "Underlying P/E not available.")
        return _item("valuation:etf_pe", _band_low(pe, ETF_PE_GOOD_MAX, ETF_PE_FAIR_MAX),
                     f"Holdings' average P/E {pe:.1f} (good ≤ {ETF_PE_GOOD_MAX:g}, poor > {ETF_PE_FAIR_MAX:g}).",
                     {"pe": pe})
    if asset_type != "STOCK":
        return _item("valuation:no_earnings", "n/a", "No earnings or cash flows to value.")
    v = (fundamentals or {}).get("valuation") or {}
    pe = _num(v.get("trailing_pe"))
    pe_src = "trailing"
    if pe is None:
        pe, pe_src = _num(v.get("forward_pe")), "forward"
    fcfy = _num(v.get("fcf_yield"))
    parts, subs = [], []
    if pe is not None:
        subs.append("poor" if pe <= 0 else _band_low(pe, PE_GOOD_MAX, PE_FAIR_MAX))
        parts.append(f"{pe_src} P/E {pe:.1f}")
    if fcfy is not None:
        subs.append(_band_high(fcfy / 100, FCF_YIELD_GOOD_MIN, FCF_YIELD_FAIR_MIN))
        parts.append(f"FCF yield {fcfy:.1f}%")
    if not subs:
        return _item("valuation:missing", "n/a", "P/E and free cash flow not available.")
    return _item("valuation:stock", _combine(subs),
                 ", ".join(parts) + f" (sector-agnostic bands: P/E ≤ {PE_GOOD_MAX:g} good, > {PE_FAIR_MAX:g} poor; "
                 f"FCF yield ≥ {FCF_YIELD_GOOD_MIN*100:g}% good, < {FCF_YIELD_FAIR_MIN*100:g}% poor).",
                 {"pe": pe, "pe_basis": pe_src if pe is not None else None, "fcf_yield": fcfy})


def score_risk(mdd: dict | None, vol: float | None) -> dict:
    subs, parts = [], []
    depth = _num((mdd or {}).get("depth_pct"))
    if depth is not None:
        subs.append(_band_high(depth, MDD_GOOD_MIN, MDD_FAIR_MIN))
        parts.append(f"max drawdown {depth:.0f}%")
    if vol is not None:
        subs.append(_band_low(vol, VOL_GOOD_MAX, VOL_FAIR_MAX))
        parts.append(f"volatility {vol:.0f}%/yr")
    if not subs:
        return _item("risk:missing", "n/a", "Not enough history to measure risk.")
    return _item("risk:measured", _combine(subs),
                 ", ".join(parts).capitalize() + f" (good: drawdown shallower than {MDD_GOOD_MIN:.0f}%, "
                 f"volatility ≤ {VOL_GOOD_MAX:.0f}%).", {"max_drawdown": depth, "volatility": vol})


def score_quality(asset_type: str, fundamentals: dict | None) -> dict:
    if asset_type != "STOCK":
        return _item("quality:not_applicable", "n/a", "Applies to individual companies only.")
    q = (fundamentals or {}).get("quality") or {}
    subs, parts = [], []
    roe, opm, de, cr = (_num(q.get(k)) for k in ("roe", "operating_margin", "debt_to_equity", "current_ratio"))
    if roe is not None:
        subs.append(_band_high(roe / 100, ROE_GOOD_MIN, ROE_FAIR_MIN))
        parts.append(f"ROE {roe:.0f}%")
    if opm is not None:
        subs.append(_band_high(opm / 100, OPM_GOOD_MIN, OPM_FAIR_MIN))
        parts.append(f"operating margin {opm:.0f}%")
    if de is not None and de >= 0:
        subs.append(_band_low(de, DE_GOOD_MAX, DE_FAIR_MAX))
        parts.append(f"debt/equity {de / 100:.1f}x")
    if cr is not None:
        subs.append(_band_high(cr, CR_GOOD_MIN, CR_FAIR_MIN))
        parts.append(f"current ratio {cr:.1f}")
    if not subs:
        return _item("quality:missing", "n/a", "Profitability and balance-sheet data not available.")
    return _item("quality:measured", _combine(subs), ", ".join(parts) + " (banks/insurers read differently).",
                 {"roe": roe, "operating_margin": opm, "debt_to_equity": de, "current_ratio": cr})


def build_scorecard(asset_type: str, fund: dict | None, fundamentals: dict | None, rows: list[dict],
                    benchmark: str | None, mdd: dict | None, vol: float | None) -> list[dict]:
    return [
        score_cost(asset_type, fund),
        score_diversification(asset_type, fund),
        score_track_record(rows, benchmark),
        score_valuation(asset_type, fund, fundamentals),
        score_risk(mdd, vol),
        score_quality(asset_type, fundamentals),
    ]


def fallback_verdict(scorecard: list[dict], asset_type: str, red_flags: list[dict]) -> str:
    """Deterministic verdict used when the AI assessment is unavailable.

      crypto, or any material red flag in an integrity category -> NOT_A_GOOD_FIT
      >= 2 poor ratings -> NOT_A_GOOD_FIT
      1 poor rating, any red flag, or fewer than 3 rated categories -> REASONABLE_WITH_CAVEATS
      otherwise -> SOLID
    Single-company "diversification: poor" for a stock is inherent to
    owning one stock and is not counted (it would make every stock "poor").
    """
    if asset_type == "CRYPTO":
        return "NOT_A_GOOD_FIT"
    if any(str(f.get("category") or "").lower() in ("fraud", "accounting", "going_concern") for f in red_flags):
        return "NOT_A_GOOD_FIT"
    counted = [s for s in scorecard if not (asset_type == "STOCK" and s["key"] == "diversification")]
    rated = [s for s in counted if s["rating"] != "n/a"]
    poor = sum(1 for s in rated if s["rating"] == "poor")
    if poor >= 2:
        return "NOT_A_GOOD_FIT"
    if poor == 1 or red_flags or len(rated) < 3:
        return "REASONABLE_WITH_CAVEATS"
    return "SOLID"


def material_red_flags(grok: dict | None, market_cap: float | None) -> list[dict]:
    """Cited AND material flags only (signal_engine.red_flag_block_reason)."""
    from app.ai.signal_engine import red_flag_block_reason

    g = grok or {}
    if g.get("error") or not (g.get("confidence") or 0) > 0:
        return []
    out = []
    for f in g.get("red_flags") or []:
        if isinstance(f, dict) and red_flag_block_reason(f, market_cap):
            out.append({"text": str(f.get("text") or "")[:300], "url": f.get("url"),
                        "severity": f.get("severity"), "category": f.get("category")})
    return out


# ============================================================
# yfinance fetches (blocking, cached)
# ============================================================

def _fetch_history(symbol: str) -> pd.Series:
    cached = _history_cache.get(symbol)
    if cached is not None:
        return cached
    import yfinance as yf

    try:
        df = yf.Ticker(symbol).history(period="max", auto_adjust=True)
    except Exception as e:
        logger.debug(f"long_term: history({symbol}) failed: {e}")
        df = None
    s = clean_closes(df)
    _history_cache.set(symbol, s, ttl=_ttl() if len(s) else 600)
    return s


def _fetch_profile(symbol: str) -> dict:
    """info + (ETF) funds_data + (stock) income statement, cached ~24h."""
    cached = _data_cache.get(symbol)
    if cached is not None:
        return cached
    import yfinance as yf

    t = yf.Ticker(symbol)
    try:
        info = t.info or {}
    except Exception as e:
        logger.debug(f"long_term: info({symbol}) failed: {e}")
        info = {}
    out: dict = {"info": info, "fund": {}, "income": []}
    at = asset_type_for(symbol, info)
    if at == "ETF":
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
            logger.debug(f"long_term: funds_data({symbol}) failed: {e}")
        out["fund"] = fd
    elif at == "STOCK":
        try:
            out["income"] = income_trend(t.income_stmt)
        except Exception as e:
            logger.debug(f"long_term: income_stmt({symbol}) failed: {e}")
    _data_cache.set(symbol, out, ttl=_ttl() if info else 600)
    return out


async def _benchmark_series(bench: str | None, asset_ccy: str) -> tuple[pd.Series | None, str | None]:
    """Benchmark closes in the asset's currency when USD<->CAD, else native.
    Returns (series, note) — note set when the currencies could not be aligned."""
    if not bench:
        return None, None
    s = await asyncio.to_thread(_fetch_history, bench)
    if s is None or len(s) < 2:
        return None, "benchmark_unavailable"
    b_ccy = "CAD" if bench.endswith(".TO") else "USD"
    if b_ccy == asset_ccy:
        return s, None
    if {b_ccy, asset_ccy} == {"USD", "CAD"}:
        fx = await asyncio.to_thread(_fetch_history, "CAD=X")   # CAD per 1 USD
        conv = convert_currency(s, fx, multiply=(b_ccy == "USD"))
        if conv is not None and len(conv) > 1:
            return conv, None
    return s, "benchmark_currency_not_adjusted"


# ============================================================
# Prompt
# ============================================================

def _fmt(v, suffix="") -> str:
    return "n/a" if v is None else f"{v}{suffix}"


def build_prompt(symbol: str, name: str | None, asset_type: str, currency: str, identity_extra: dict,
                 metrics: dict, scorecard: list[dict], red_flags: list[dict]) -> str:
    from app.ai.prompts import LONG_TERM_PROMPT, UNTRUSTED_NOTICE, wrap_untrusted

    identity = wrap_untrusted("yfinance_profile", json.dumps(
        {"symbol": symbol, "name": name, "asset_type": asset_type, "currency": currency, **identity_extra},
        default=str, ensure_ascii=False)[:4000])
    sc_lines = "\n".join(f"- {s['key']}: {s['rating']} — {s['reason']}" for s in scorecard)
    flags = (wrap_untrusted("red_flags", "\n".join(
        f"- [{f.get('severity')}/{f.get('category')}] {f.get('text')} ({f.get('url')})" for f in red_flags))
        if red_flags else ("(none found in a cited search)" if asset_type == "STOCK" else "(not searched for this asset type)"))
    now = datetime.now(timezone.utc)
    return LONG_TERM_PROMPT.format(
        symbol=symbol, today=now.date().isoformat(), untrusted_notice=UNTRUSTED_NOTICE,
        identity=identity, metrics=json.dumps(metrics, default=str, ensure_ascii=False, indent=1)[:9000],
        scorecard=sc_lines, red_flags=flags,
    )


# ============================================================
# The check
# ============================================================

def _noop(_p: str, _pct: int) -> None:
    return None


async def run_long_check(resolved: dict, progress: ProgressFn | None = None) -> dict:
    """Long-term assessment for one resolved symbol. Never persists."""
    from app.ai import provider as ai_provider

    p = progress or _noop
    symbol = resolved["symbol"]
    now = datetime.now(timezone.utc)

    p("history", 10)
    closes, profile = await asyncio.gather(
        asyncio.to_thread(_fetch_history, symbol),
        asyncio.to_thread(_fetch_profile, symbol),
    )
    if closes is None or len(closes) < 60:
        raise sc.StockCheckError("insufficient_data", f"Not enough price history to analyse {symbol}.", 422)
    info = profile.get("info") or {}
    asset_type = asset_type_for(symbol, info)
    currency = currency_of(symbol, info)
    fund_raw = profile.get("fund") or {}
    category = info.get("category") or (fund_raw.get("overview") or {}).get("categoryName")
    name = info.get("longName") or info.get("shortName")

    # ── benchmark ──
    p("benchmark", 30)
    bench = select_benchmark(symbol, asset_type, info, category)
    bench_closes, bench_note = await _benchmark_series(bench, currency)

    per_year = CRYPTO_DAYS if asset_type == "CRYPTO" else TRADING_DAYS
    rows = returns_table(closes, bench_closes)
    mdd = max_drawdown(closes)
    vol = annualized_volatility(closes, per_year)
    cal = calendar_year_returns(closes)
    drawdowns = {
        "max": mdd,
        "current": current_drawdown(closes),
        "worst_year": worst_year(cal),
        "calendar_years": cal[-15:],
        "volatility": vol,
        "history_years": round(history_years(closes), 1),
        "since_inception": since_inception(closes),
    }

    # ── fundamentals ──
    p("fundamentals", 50)
    fund = build_fund_info(info, fund_raw) if asset_type == "ETF" else None
    fundamentals = None
    if asset_type == "STOCK":
        revisions: dict = {}
        try:
            from app.scanners.enrichment import get_enrichment
            revisions = await get_enrichment(symbol, info)
        except Exception as e:
            logger.debug(f"long_term: enrichment failed for {symbol}: {e}")
        fundamentals = build_fundamentals(info, profile.get("income") or [], revisions)

    # ── sentiment (stocks only; material cited red flags only) ──
    red_flags: list[dict] = []
    grok_called = False
    if asset_type == "STOCK" and settings.ai_enabled:
        p("sentiment", 62)
        try:
            grok = await ai_provider.analyze_sentiment(symbol, market_cap=_num(info.get("marketCap")))
            grok_called = True
            red_flags = material_red_flags(grok, _num(info.get("marketCap")))
        except Exception as e:
            logger.warning(f"long_term: sentiment failed for {symbol}: {e}")

    scorecard = build_scorecard(asset_type, fund, fundamentals, rows, bench, mdd, vol)
    fb_verdict = fallback_verdict(scorecard, asset_type, red_flags)

    # ── AI assessment ──
    ai: dict | None = None
    notes: list[dict] = []
    if settings.ai_enabled:
        p("assessment", 75)
        extra = {"category": category, "family": (fund or {}).get("family"),
                 "sector": info.get("sector"), "industry": info.get("industry"),
                 "top_holdings": [(h.get("name") or h.get("symbol"), h.get("weight"))
                                  for h in ((fund or {}).get("top_holdings") or [])[:10]]}
        metrics = {
            "price": resolved.get("price"), "benchmark": bench, "benchmark_note": bench_note,
            "returns_cagr_pct": rows, "drawdowns": {k: v for k, v in drawdowns.items() if k != "calendar_years"},
            "calendar_year_returns_pct": cal[-10:],
            "fund": {k: v for k, v in (fund or {}).items() if k not in ("top_holdings", "family", "category")} or None,
            "fundamentals": fundamentals,
        }
        prompt = build_prompt(symbol, name, asset_type, currency, extra, metrics, scorecard, red_flags)
        try:
            ai = await ai_provider.assess_long_term(symbol, prompt)
        except Exception as e:
            logger.warning(f"long_term: assessment failed for {symbol}: {e}")
            ai = None
        if ai is None:
            notes.append({"code": "ai_unavailable", "params": {},
                          "text": "The AI assessment was unavailable — the verdict comes from the rule-based scorecard."})
    else:
        notes.append({"code": "ai_disabled", "params": {},
                      "text": "AI analysis is disabled — the verdict comes from the rule-based scorecard."})
    if bench_note:
        notes.append({"code": bench_note, "params": {"benchmark": bench}, "text":
                      "Benchmark data unavailable." if bench_note == "benchmark_unavailable"
                      else "Benchmark returns are in its own currency (FX data unavailable)."})

    caveats = list(CAVEATS)
    if asset_type == "CRYPTO":
        caveats.insert(0, {"code": "crypto_high_risk", "text":
                           "Crypto is highly speculative: no cash flows, and drawdowns of 70-80% have happened repeatedly."})
    if asset_type == "STOCK":
        caveats.insert(0, {"code": "single_stock", "text":
                           "Most individual stocks underperform a broad index fund over long periods."})

    ai_provider_name = (ai or {}).pop("_provider", None) if ai else None
    result = {
        "mode": "long",
        "input": resolved.get("input") or symbol,
        "symbol": symbol,
        "exchange": resolved.get("exchange") or sc.exchange_for(symbol),
        "name": name,
        "asset_type": asset_type,
        "currency": currency,
        "price": resolved.get("price") or float(closes.iloc[-1]),
        "verdict": (ai or {}).get("verdict") or fb_verdict,
        "verdict_source": "ai" if ai else "scorecard",
        "scorecard_verdict": fb_verdict,
        "ai_assessment": ai,
        "ai": {"called": settings.ai_enabled, "provider": ai_provider_name, "sentiment_called": grok_called,
               "status": "ok" if ai else ("disabled" if not settings.ai_enabled else "failed")},
        "scorecard": scorecard,
        "returns": rows,
        "benchmark": bench,
        "drawdowns": drawdowns,
        "fund": fund,
        "fundamentals": fundamentals,
        "red_flags": red_flags,
        "notes": notes,
        "data_as_of": closes.index[-1].date().isoformat(),
        "caveats": caveats,
        "checked_at": now.isoformat(),
        "cached": False,
    }
    p("done", 100)
    return _clean(sc._plain(result))


def _clean(v: Any) -> Any:
    """NaN/inf -> None, recursively (JSON-safe)."""
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v
