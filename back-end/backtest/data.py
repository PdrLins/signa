"""Historical data for the backtest: yfinance with an on-disk cache.

Cache lives in `backtest/.cache/` (gitignored by the root `.gitignore`).

Prices are yfinance `auto_adjust=True` bars — the same adjustment the live
scanner's `Ticker.history()` uses — so indicators match live, and returns
(strategy AND benchmarks) include dividends via the adjustment.

Fundamentals: yfinance only exposes TODAY's `.info`. Applying it to past
dates is lookahead, so by default only near-static CLASSIFICATION fields
(sector / industry / quote type / name) are kept — they drive the bucket
and the sector cap, never the score. `--include-fundamentals` keeps the
whole current snapshot and the report carries a LOOKAHEAD warning.
"""

from __future__ import annotations

import asyncio
import csv
import json
import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

CACHE_DIR = Path(__file__).resolve().parent / ".cache"

# Point-in-time-safe enough: a company's sector / listing type rarely
# changes. Used for bucket + sector cap only.
STATIC_FUNDAMENTAL_FIELDS = ("sector", "industry", "quote_type", "company_name")

OHLCV = ["Open", "High", "Low", "Close", "Volume"]


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def _normalize(df: pd.DataFrame | None) -> pd.DataFrame:
    """Tz-naive daily DatetimeIndex, OHLCV columns, NaN-close rows dropped."""
    if df is None or df.empty:
        return pd.DataFrame(columns=OHLCV)
    df = df.copy()
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    df.index = idx.normalize()
    df = df[[c for c in OHLCV if c in df.columns]]
    df = df.dropna(subset=["Close"])
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df.astype(float)


def _cache_path(kind: str, key: str) -> Path:
    return CACHE_DIR / kind / f"{_safe(key)}.pkl"


def load_ohlcv(
    tickers: list[str],
    start: date,
    end: date,
    *,
    use_cache: bool = True,
    batch_size: int = 40,
) -> dict[str, pd.DataFrame]:
    """Daily bars for [start, end] per ticker (missing/empty tickers omitted).

    The caller passes a start that already includes the indicator warm-up.
    """
    out: dict[str, pd.DataFrame] = {}
    todo: list[str] = []
    for t in tickers:
        p = _cache_path("ohlcv", f"{t}_{start}_{end}")
        if use_cache and p.exists():
            out[t] = pd.read_pickle(p)
        else:
            todo.append(t)

    if todo:
        import yfinance as yf

        end_excl = (end + timedelta(days=1)).isoformat()
        for i in range(0, len(todo), batch_size):
            batch = todo[i:i + batch_size]
            try:
                raw = yf.download(
                    batch, start=start.isoformat(), end=end_excl, group_by="ticker",
                    auto_adjust=True, progress=False, threads=True,
                )
            except Exception:
                raw = None
            for t in batch:
                try:
                    if raw is None or raw.empty:
                        df = pd.DataFrame()
                    elif isinstance(raw.columns, pd.MultiIndex):
                        df = raw[t] if t in raw.columns.get_level_values(0) else pd.DataFrame()
                    else:
                        df = raw
                except Exception:
                    df = pd.DataFrame()
                df = _normalize(df)
                p = _cache_path("ohlcv", f"{t}_{start}_{end}")
                p.parent.mkdir(parents=True, exist_ok=True)
                df.to_pickle(p)
                out[t] = df
    return {t: df for t, df in out.items() if df is not None and not df.empty}


def load_fundamentals(tickers: list[str], *, use_cache: bool = True) -> dict[str, dict]:
    """CURRENT fundamentals per ticker via the LIVE `market_scanner.get_fundamentals`.

    Cached on disk. Returned unfiltered — `filter_fundamentals` decides what
    the backtest may see.
    """
    from app.scanners import market_scanner

    out: dict[str, dict] = {}
    for t in tickers:
        p = CACHE_DIR / "fundamentals" / f"{_safe(t)}.json"
        if use_cache and p.exists():
            try:
                out[t] = json.loads(p.read_text())
                continue
            except Exception:
                pass
        try:
            f = asyncio.run(market_scanner.get_fundamentals(t)) or {}
        except Exception:
            f = {}
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(f, default=str))
        out[t] = f
    return out


def filter_fundamentals(fund: dict | None, include_all: bool) -> dict:
    fund = dict(fund or {})
    if include_all:
        # Earnings timing keys would be TODAY's calendar applied to the
        # past — even with --include-fundamentals they are meaningless.
        for k in ("earnings_date", "next_earnings_date", "days_to_next_earnings",
                  "trading_days_to_next_earnings", "days_since_last_earnings",
                  "last_eps_surprise_pct"):
            fund.pop(k, None)
        return fund
    return {k: fund[k] for k in STATIC_FUNDAMENTAL_FIELDS if fund.get(k) is not None}


def load_universe_csv(path: str | Path) -> dict[str, tuple[date | None, date | None]]:
    """User-provided historical universe.

    CSV with a `symbol` column and optional `start` / `end` columns (ISO
    dates, inclusive membership window). A symbol is only eligible for new
    signals on dates inside its window. Multiple rows per symbol are
    merged into the widest window.
    """
    out: dict[str, tuple[date | None, date | None]] = {}
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        cols = {c.lower().strip(): c for c in (reader.fieldnames or [])}
        sym_col = cols.get("symbol") or cols.get("ticker")
        if not sym_col:
            raise ValueError("universe CSV needs a 'symbol' (or 'ticker') column")
        for row in reader:
            sym = (row.get(sym_col) or "").strip().upper()
            if not sym:
                continue
            s = (row.get(cols["start"]) or "").strip() if "start" in cols else ""
            e = (row.get(cols["end"]) or "").strip() if "end" in cols else ""
            s_d = date.fromisoformat(s) if s else None
            e_d = date.fromisoformat(e) if e else None
            if sym in out:
                ps, pe = out[sym]
                s_d = None if (ps is None or s_d is None) else min(ps, s_d)
                e_d = None if (pe is None or e_d is None) else max(pe, e_d)
            out[sym] = (s_d, e_d)
    return out
