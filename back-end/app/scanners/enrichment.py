"""Richer per-ticker data: estimate revisions, relative-strength benchmarks,
short-interest trend and insider buying.

Everything here is merged into the dict returned by
`market_scanner.get_fundamentals`, so it flows through scan_service
(`fundamental_data`) into `compute_score` and the synthesis prompt
without any call-site change. Relative strength itself needs the
stock's own 3m/6m return, which lives in `technical_data`
(`indicators.compute_indicators`), so the benchmark returns are stored
here and the difference is taken by `indicators.compute_relative_strength`.

yfinance sources (verified against the installed yfinance):
  • `Ticker.eps_trend`      — DataFrame, index 0q/+1q/0y/+1y, columns
                              current / 7daysAgo / 30daysAgo / 60daysAgo /
                              90daysAgo (quoteSummary `earningsTrend`).
  • `Ticker.eps_revisions`  — same index, columns upLast7days /
                              upLast30days / downLast7days / downLast30days
                              (same `earningsTrend` fetch, no extra request).
  • `Ticker.insider_purchases` — 6-month summary table (quoteSummary
                              `netSharePurchaseActivity`): first column
                              holds the row labels ("Purchases", "Sales",
                              "Net Shares Purchased (Sold)", ...), then
                              "Shares" and "Trans".
  • `.info` keys `sharesShort`, `sharesShortPriorMonth`,
    `shortPercentOfFloat`, `shortRatio` (already fetched by
    get_fundamentals — no extra request).
  • Benchmark ETF 1y daily history via `Ticker.history`.

All parsing is defensive: any missing table / column / value yields
None (or an absent key) and never raises. Results are cached per ticker
for `settings.enrichment_cache_hours` (default 12h), benchmark ETF
returns for 6h, so the extra yfinance requests are paid about once per
ticker per day.
"""

import asyncio
import math

import pandas as pd
import yfinance as yf
from loguru import logger

from app.core.cache import TTLCache

_enrichment_cache = TTLCache(max_size=3000, default_ttl=12 * 3600)
_benchmark_cache = TTLCache(max_size=64, default_ttl=6 * 3600)
_benchmark_locks: dict[str, asyncio.Lock] = {}

# yfinance `.info["sector"]` names → SPDR Select Sector ETFs.
SECTOR_ETF: dict[str, str] = {
    "technology": "XLK",
    "information technology": "XLK",
    "financial services": "XLF",
    "financials": "XLF",
    "financial": "XLF",
    "energy": "XLE",
    "healthcare": "XLV",
    "health care": "XLV",
    "consumer cyclical": "XLY",
    "consumer discretionary": "XLY",
    "consumer defensive": "XLP",
    "consumer staples": "XLP",
    "industrials": "XLI",
    "basic materials": "XLB",
    "materials": "XLB",
    "utilities": "XLU",
    "real estate": "XLRE",
    "communication services": "XLC",
}
MARKET_ETF = "SPY"
TSX_BENCHMARK = "XIU.TO"

# ~3 and ~6 months of trading sessions — same windows as
# indicators.compute_indicators' momentum_3m / momentum_6m.
_BARS_3M = 63
_BARS_6M = 126


def _is_tsx(ticker: str) -> bool:
    t = (ticker or "").upper()
    return t.endswith(".TO") or t.endswith(".V") or t.endswith(".CN") or t.endswith(".NE")


def benchmark_for(ticker: str, sector: str | None) -> str | None:
    """Relative-strength benchmark ETF for a ticker.

    TSX/TSXV names are compared against XIU.TO (iShares S&P/TSX 60):
    US sector ETFs trade in USD on a different market, so the spread
    would mostly be FX + market noise. US names map their yfinance
    sector to the SPDR sector ETF; unknown sector → None (the SPY
    comparison still applies).
    """
    if _is_tsx(ticker):
        return TSX_BENCHMARK
    if not sector:
        return None
    return SECTOR_ETF.get(str(sector).strip().lower())


def _f(v) -> float | None:
    """Float or None (NaN / pd.NA / garbage → None)."""
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) or math.isinf(x) else x


def _col(df: pd.DataFrame, name: str):
    """Case-insensitive column lookup (Yahoo mixes `downLast7days` /
    `downLast7Days` across versions)."""
    low = name.lower()
    for c in df.columns:
        if str(c).lower() == low:
            return c
    return None


def _cell(df, period: str, column: str) -> float | None:
    if not isinstance(df, pd.DataFrame) or df.empty or period not in df.index:
        return None
    c = _col(df, column)
    if c is None:
        return None
    try:
        return _f(df.loc[period, c])
    except Exception:
        return None


def _pct_change(cur: float | None, old: float | None, min_base: float = 0.05) -> float | None:
    """Percent change of an EPS estimate; None when the base is ~0 (a
    $0.01 → $0.03 move is +200% and means nothing)."""
    if cur is None or old is None or abs(old) < min_base:
        return None
    return round((cur - old) / abs(old) * 100, 2)


def parse_estimate_revisions(eps_trend, eps_revisions) -> dict:
    """Estimate-revision momentum from yfinance eps_trend / eps_revisions.

    Keys (only set when computable):
      eps_est_change_0q_30d_pct  — current-quarter consensus EPS, % change vs 30 days ago
      eps_est_change_0q_90d_pct  — … vs 90 days ago
      eps_est_change_fy1_30d_pct — next-fiscal-year (+1y) consensus, vs 30 days ago
                                    (falls back to current year 0y)
      eps_est_change_fy1_90d_pct — … vs 90 days ago
      eps_revisions_up_30d / eps_revisions_down_30d — analyst revision
          counts over the last 30 days, summed over 0q and the fiscal-year
          row used above (the same analyst can appear in both).
      eps_revision_momentum      — mean of the available % changes above
          (single summary number used by scoring + prompt).
    """
    out: dict = {}
    fy = "+1y"
    if _cell(eps_trend, fy, "current") is None and _cell(eps_trend, "0y", "current") is not None:
        fy = "0y"
    for period, tag in (("0q", "0q"), (fy, "fy1")):
        cur = _cell(eps_trend, period, "current")
        for days in (30, 90):
            pct = _pct_change(cur, _cell(eps_trend, period, f"{days}daysAgo"))
            if pct is not None:
                out[f"eps_est_change_{tag}_{days}d_pct"] = pct

    ups, downs, seen = 0.0, 0.0, False
    for period in ("0q", fy):
        u = _cell(eps_revisions, period, "upLast30days")
        d = _cell(eps_revisions, period, "downLast30days")
        if u is not None or d is not None:
            seen = True
            ups += u or 0
            downs += d or 0
    if seen:
        out["eps_revisions_up_30d"] = int(ups)
        out["eps_revisions_down_30d"] = int(downs)

    changes = [v for k, v in out.items() if k.startswith("eps_est_change_")]
    if changes:
        out["eps_revision_momentum"] = round(sum(changes) / len(changes), 2)
    return out


def parse_insider_purchases(df) -> dict:
    """Net insider activity over the last ~6 months from `insider_purchases`.

    Keys: insider_net_shares_6m, insider_buy_count_6m, insider_sell_count_6m,
    insider_net_pct_6m (fraction of insider holdings, Yahoo's
    `netPercentInsiderShares`). Missing table / rows → {}.
    """
    if not isinstance(df, pd.DataFrame) or df.empty or len(df.columns) < 2:
        return {}
    label_col = df.columns[0]
    shares_col = _col(df, "Shares")
    trans_col = _col(df, "Trans")
    rows: dict[str, pd.Series] = {}
    for _, row in df.iterrows():
        rows[str(row[label_col]).strip().lower()] = row

    def _get(label: str, col) -> float | None:
        r = rows.get(label)
        if r is None or col is None:
            return None
        try:
            return _f(r[col])
        except Exception:
            return None

    out: dict = {}
    net = _get("net shares purchased (sold)", shares_col)
    if net is not None:
        out["insider_net_shares_6m"] = int(net)
    buys = _get("purchases", trans_col)
    if buys is not None:
        out["insider_buy_count_6m"] = int(buys)
    sells = _get("sales", trans_col)
    if sells is not None:
        out["insider_sell_count_6m"] = int(sells)
    pct = _get("% net shares purchased (sold)", shares_col)
    if pct is not None:
        out["insider_net_pct_6m"] = round(pct, 4)
    return out


def parse_short_interest(info: dict) -> dict:
    """Short-interest trend from `.info` (sharesShort vs prior month).

    Keys: short_shares, short_shares_prior_month, short_interest_change_pct
    (PERCENT change month over month), short_ratio_days (days to cover).
    `short_percent_of_float` is already set by get_fundamentals.
    """
    info = info or {}
    out: dict = {}
    cur = _f(info.get("sharesShort"))
    prior = _f(info.get("sharesShortPriorMonth"))
    if cur is not None:
        out["short_shares"] = int(cur)
    if prior is not None:
        out["short_shares_prior_month"] = int(prior)
    if cur is not None and prior is not None and prior > 0:
        out["short_interest_change_pct"] = round((cur - prior) / prior * 100, 2)
    ratio = _f(info.get("shortRatio"))
    if ratio is not None:
        out["short_ratio_days"] = round(ratio, 2)
    return out


def period_returns(hist) -> dict:
    """~3m / ~6m % returns from a daily history (same bar windows as
    compute_indicators' momentum_3m / momentum_6m)."""
    if not isinstance(hist, pd.DataFrame) or hist.empty or "Close" not in hist.columns:
        return {}
    close = hist["Close"].astype(float).dropna()
    out: dict = {}
    if len(close) < 2:
        return out
    cur = float(close.iloc[-1])
    for bars, key in ((_BARS_3M, "return_3m"), (_BARS_6M, "return_6m")):
        if len(close) >= bars:
            old = float(close.iloc[-bars])
            if old > 0:
                out[key] = round((cur - old) / old * 100, 2)
    return out


async def get_benchmark_returns(symbol: str) -> dict:
    """Cached 3m/6m returns for a benchmark ETF ({} on failure)."""
    cached = _benchmark_cache.get(symbol)
    if cached is not None:
        return cached
    lock = _benchmark_locks.setdefault(symbol, asyncio.Lock())
    async with lock:  # one fetch per ETF even when many tickers miss at once
        cached = _benchmark_cache.get(symbol)
        if cached is not None:
            return cached

        def _fetch():
            return period_returns(yf.Ticker(symbol).history(period="1y"))

        try:
            result = await asyncio.to_thread(_fetch)
        except Exception as e:
            logger.debug(f"Benchmark history failed for {symbol}: {e}")
            result = {}
        # Cache failures briefly so a Yahoo hiccup doesn't disable RS all day.
        _benchmark_cache.set(symbol, result, ttl=6 * 3600 if result else 600)
        return result


def _fetch_analyst_and_insider(ticker: str) -> dict:
    """Blocking yfinance fetch (run in a thread): 2 quoteSummary requests."""
    t = yf.Ticker(ticker)
    out: dict = {}
    try:
        out.update(parse_estimate_revisions(t.eps_trend, t.eps_revisions))
    except Exception as e:
        logger.debug(f"EPS trend/revisions unavailable for {ticker}: {e}")
    try:
        out.update(parse_insider_purchases(t.insider_purchases))
    except Exception as e:
        logger.debug(f"Insider purchases unavailable for {ticker}: {e}")
    return out


async def get_enrichment(ticker: str, info: dict) -> dict:
    """Richer data for an EQUITY, merged into get_fundamentals' result.

    Returns {} for non-equities (ETFs, crypto) or when disabled.
    """
    from app.core.config import settings

    info = info or {}
    if not getattr(settings, "enrichment_fetch_enabled", True):
        return {}
    if str(info.get("quoteType") or "").upper() != "EQUITY":
        return {}

    out: dict = parse_short_interest(info)

    cached = _enrichment_cache.get(ticker)
    if cached is None:
        try:
            cached = await asyncio.to_thread(_fetch_analyst_and_insider, ticker)
        except Exception as e:
            logger.debug(f"Enrichment fetch failed for {ticker}: {e}")
            cached = {}
        hours = getattr(settings, "enrichment_cache_hours", 12)
        _enrichment_cache.set(ticker, cached, ttl=int(hours * 3600) if cached else 1800)
    out.update(cached)

    bench = benchmark_for(ticker, info.get("sector"))
    symbols = [s for s in (bench, MARKET_ETF) if s]
    results = await asyncio.gather(*(get_benchmark_returns(s) for s in symbols))
    by_symbol = dict(zip(symbols, results))
    if bench and by_symbol.get(bench):
        out["rs_benchmark"] = bench
        for k in ("return_3m", "return_6m"):
            if by_symbol[bench].get(k) is not None:
                out[f"rs_benchmark_{k}"] = by_symbol[bench][k]
    spy = by_symbol.get(MARKET_ETF) or {}
    for k in ("return_3m", "return_6m"):
        if spy.get(k) is not None:
            out[f"spy_{k}"] = spy[k]
    return out
