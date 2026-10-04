"""Holding status: the daily price snapshot stored on each holding
(`holdings.holding_status`, migration 010). No AI, no alerts.

  price, prev_close, day_change_pct, change_1m_pct, ytd_pct, ytd_base,
  sma50, sma200, pct_vs_sma200, trend (ok | weak | break | unknown),
  trend_break, death_cross, high_52w, drawdown_pct, as_of

GET /holdings uses it as the price fallback when a symbol has no live quote
and for the YTD base (ytd_pct_live); portfolio snapshots use the same
fallback. Closes come from one batched yfinance download per run, shared by
every user holding a symbol. Runs after the close (scheduler) and for one
user right after they add holdings.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone

import pandas as pd
from loguru import logger

HISTORY_PERIOD = "2y"

_run_lock = asyncio.Lock()


def _r(v, nd=2):
    return round(v, nd) if v is not None and math.isfinite(v) else None


def compute_price_status(closes: pd.Series | None) -> dict:
    """Trend / change / drawdown figures from daily closes (oldest first)."""
    if closes is None or len(closes) < 2:
        return {"error": "no_data"}
    s = closes.dropna()
    s = s[s > 0]
    if len(s) < 2:
        return {"error": "no_data"}
    idx = pd.DatetimeIndex(s.index)
    price = float(s.iloc[-1])
    prev = float(s.iloc[-2])
    last_day = idx[-1]

    def close_on_or_before(ts) -> float | None:
        m = s[idx <= ts]
        return float(m.iloc[-1]) if len(m) else None

    base_1m = close_on_or_before(last_day - pd.Timedelta(days=30))
    ytd_base = close_on_or_before(pd.Timestamp(year=last_day.year, month=1, day=1) - pd.Timedelta(days=1))
    sma50 = float(s.iloc[-50:].mean()) if len(s) >= 50 else None
    sma200 = float(s.iloc[-200:].mean()) if len(s) >= 200 else None
    window = s.iloc[-252:]
    high = float(window.max())
    trend_break = bool(sma200 is not None and price < sma200)
    death_cross = bool(sma50 is not None and sma200 is not None and sma50 < sma200)
    if sma200 is None:
        trend = "unknown"
    elif trend_break:
        trend = "break"
    elif death_cross:
        trend = "weak"
    else:
        trend = "ok"
    return {
        "price": _r(price, 4),
        "prev_close": _r(prev, 4),
        "day_change_pct": _r((price / prev - 1) * 100),
        "change_1m_pct": _r((price / base_1m - 1) * 100) if base_1m else None,
        "ytd_pct": _r((price / ytd_base - 1) * 100) if ytd_base else None,
        "ytd_base": _r(ytd_base, 4),   # last close of the previous year (GET /holdings ytd_pct_live)
        "sma50": _r(sma50, 4),
        "sma200": _r(sma200, 4),
        "pct_vs_sma200": _r((price / sma200 - 1) * 100) if sma200 else None,
        "trend": trend,
        "trend_break": trend_break,
        "death_cross": death_cross,
        "high_52w": _r(high, 4),
        "drawdown_pct": _r((price / high - 1) * 100) if high else None,
        "as_of": last_day.date().isoformat(),
    }


def fetch_closes(symbols: list[str]) -> dict[str, pd.Series]:
    """Fresh daily closes for every symbol (one batched yf.download).
    Blocking — call via asyncio.to_thread. Missing symbols are absent."""
    syms = list(dict.fromkeys(s for s in symbols if s))
    if not syms:
        return {}
    from app.services.price_cache import _close_series_from_download

    out: dict[str, pd.Series] = {}
    try:
        import yfinance as yf

        data = yf.download(syms, period=HISTORY_PERIOD, interval="1d", progress=False,
                           threads=False, auto_adjust=True)
        if data is None or data.empty:
            return {}
        multi = isinstance(data.columns, pd.MultiIndex) and len(syms) > 1
        for sym in syms:
            s = _close_series_from_download(data, sym, multi)
            if s is not None:
                out[sym] = s
    except Exception as e:
        logger.warning(f"holding status: price download failed ({len(syms)} symbols): {e}")
    return out


async def refresh(user_id: str | None = None) -> dict:
    """Recompute and store holding_status for every holding (or one user's)."""
    from app.db import queries

    if _run_lock.locked():
        return {"status": "busy"}
    async with _run_lock:
        try:
            rows = await asyncio.to_thread(queries.get_holdings, user_id) if user_id \
                else await asyncio.to_thread(queries.get_all_holdings)
        except Exception as e:
            logger.warning(f"holding status: holdings unavailable: {e}")
            return {"status": "unavailable"}
        if not rows:
            return {"status": "ok", "holdings": 0, "updated": 0}
        symbols = sorted({str(r.get("symbol") or "").upper() for r in rows if r.get("symbol")})
        closes = await asyncio.to_thread(fetch_closes, symbols)
        now_iso = datetime.now(timezone.utc).isoformat()
        updated = 0
        for r in rows:
            sym = str(r.get("symbol") or "").upper()
            st = compute_price_status(closes.get(sym))
            if st.get("error"):
                continue
            try:
                await asyncio.to_thread(queries.update_holding, str(r["id"]), str(r["user_id"]),
                                        {"holding_status": st, "status_updated_at": now_iso})
                updated += 1
            except Exception as e:
                logger.warning(f"holding status: save {r.get('id')} failed: {e}")
        return {"status": "ok", "holdings": len(rows), "symbols": len(symbols), "updated": updated}


def is_running() -> bool:
    return _run_lock.locked()


def kick(user_id: str) -> bool:
    """Start a background refresh for one user (False when one is running)."""
    if is_running():
        return False
    asyncio.create_task(refresh(user_id))
    return True
