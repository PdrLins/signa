"""Counterfactual outcome tracking for every scan candidate (migration 008).

The brain learns from trades it took; that is blind to the trades it did
NOT take. This module records, for every signal a scan produced, what the
price did over the next 5 / 10 / 20 sessions — raw and in excess of the
benchmark — so the daily learning loop can ask:

  * which SKIP gates keep us out of stocks that went on to outperform?
  * is the AI's p_win calibrated?
  * does the decision model (Opus) veto the right routine (Sonnet) BUYs?
  * do validated signals actually beat rejected / tech-only ones?

Two entry points, both idempotent and safe to re-run (scheduler 17:15 ET):

  seed_candidates(since)   one candidate_outcomes row per signal that has
                           none yet, joined with the brain_decisions row
                           of the same scan + symbol (ENTER/SKIP + reason).
  fill_forward_returns()   for rows whose horizon has elapsed, batch-fetch
                           daily closes (yfinance) and store fwd / SPY /
                           excess returns. Rows missing data stay NULL and
                           are retried on the next run until
                           outcomes_fill_max_age_days.

Conventions (all pure helpers below are unit-tested with fake data):

  * Returns are decimal fractions (0.05 = +5%).
  * Horizon N = the close of the N-th trading session AFTER the signal's
    session on the symbol's exchange calendar (app.core.market_calendar);
    crypto uses N calendar (UTC) days.
  * The stock leg starts at price_at_signal (the quote the scan saw). If
    that quote disagrees with the split-adjusted reference close by >40%
    (a split happened inside the window), the reference close is used.
  * The benchmark leg starts at the last benchmark close known at signal
    time (the previous session's close for a signal before 16:00 ET) and
    ends at the benchmark close on/before the horizon date. Intraday
    signals therefore compare an intraday entry against a close-to-close
    benchmark move — a small, unbiased timing mismatch.
  * The benchmark is SPY for every asset, including .TO names and crypto,
    so every excess return is on one scale (TSX excess embeds USD/CAD and
    US-vs-CA beta; crypto excess is "vs holding SPY instead").
"""

from __future__ import annotations

import bisect
import math
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from loguru import logger

from app.core.config import settings
from app.core.market_calendar import is_daily_bar_complete, is_market_open

ET = ZoneInfo("America/New_York")
UTC = timezone.utc
HORIZONS: tuple[int, ...] = (5, 10, 20)
SESSION_CLOSE_ET = time(16, 0)

# A quote this far from the reference close means a split/bad quote.
_SPLIT_GUARD_RATIO = 1.4
# Max calendar gap tolerated when looking up "close on or before" a date.
_MAX_ASOF_GAP_DAYS = 5

# symbol -> sorted [(date, close), ...]
CloseSeries = Sequence[tuple[date, float]]
CloseFetcher = Callable[[list[str], date, date], dict[str, list[tuple[date, float]]]]


# ============================================================
# Pure helpers — calendar
# ============================================================

def classify_exchange(symbol: str, exchange: str | None = None, asset_type: str | None = None) -> str:
    """Calendar key for a symbol: CRYPTO | TSX | NASDAQ | NYSE."""
    if (asset_type or "").upper() == "CRYPTO" or exchange == "CRYPTO" or symbol.endswith("-USD"):
        return "CRYPTO"
    if exchange in ("TSX", "NYSE", "NASDAQ"):
        return exchange
    if symbol.endswith(".TO"):
        return "TSX"
    return "NYSE"


def parse_ts(value) -> datetime | None:
    """ISO string / datetime -> tz-aware datetime (naive = UTC)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def signal_session_date(signal_at: datetime, exchange: str) -> date:
    """Calendar date the signal belongs to (UTC day for crypto, ET day otherwise)."""
    if exchange == "CRYPTO":
        return signal_at.astimezone(UTC).date()
    return signal_at.astimezone(ET).date()


def horizon_date(signal_at: datetime, horizon: int, exchange: str) -> date:
    """Date whose close closes the N-session window.

    Equities: the N-th trading day strictly after the signal's ET date
    (so a Friday signal's 5d horizon is the next Friday; holidays skipped).
    Crypto: signal UTC date + N calendar days.
    """
    start = signal_session_date(signal_at, exchange)
    if exchange == "CRYPTO":
        return start + timedelta(days=horizon)
    d, count = start, 0
    while count < horizon:
        d += timedelta(days=1)
        if is_market_open(exchange, d):
            count += 1
    return d


def horizon_elapsed(signal_at: datetime, horizon: int, exchange: str, now: datetime | None = None) -> bool:
    """True once the horizon date's daily bar is final."""
    now = now or datetime.now(ET)
    return is_daily_bar_complete(exchange, horizon_date(signal_at, horizon, exchange), now)


def reference_close_date(signal_at: datetime, calendar_exchange: str = "NYSE") -> date:
    """Last session whose close was known at signal time (equity calendar).

    A signal at/after 16:00 ET on a session day sees that day's close;
    anything earlier (pre-market, intraday, weekend) sees the previous
    session's close.
    """
    et = signal_at.astimezone(ET)
    d = et.date()
    if et.time() >= SESSION_CLOSE_ET and is_market_open(calendar_exchange, d):
        return d
    d -= timedelta(days=1)
    for _ in range(15):
        if is_market_open(calendar_exchange, d):
            return d
        d -= timedelta(days=1)
    return d


# ============================================================
# Pure helpers — prices & returns
# ============================================================

def close_asof(series: CloseSeries | None, d: date, max_gap_days: int = _MAX_ASOF_GAP_DAYS) -> float | None:
    """Close on `d`, or the latest close before it within max_gap_days."""
    if not series:
        return None
    dates = [x[0] for x in series]
    i = bisect.bisect_right(dates, d) - 1
    if i < 0:
        return None
    bar_date, close = series[i]
    if (d - bar_date).days > max_gap_days:
        return None
    if close is None or not math.isfinite(close) or close <= 0:
        return None
    return float(close)


def simple_return(start: float | None, end: float | None) -> float | None:
    """end/start - 1, or None when either leg is missing / non-positive."""
    if start is None or end is None:
        return None
    try:
        start, end = float(start), float(end)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(start) and math.isfinite(end)) or start <= 0 or end <= 0:
        return None
    return end / start - 1.0


def excess_return(ret: float | None, bench: float | None) -> float | None:
    """Arithmetic excess return over the benchmark."""
    if ret is None or bench is None:
        return None
    return ret - bench


def entry_base_price(price_at_signal, ref_close: float | None) -> float | None:
    """price_at_signal, unless a split makes it incomparable to the series."""
    try:
        p = float(price_at_signal) if price_at_signal is not None else None
    except (TypeError, ValueError):
        p = None
    if p is None or not math.isfinite(p) or p <= 0:
        return ref_close
    if ref_close and ref_close > 0:
        ratio = p / ref_close
        if ratio > _SPLIT_GUARD_RATIO or ratio < 1 / _SPLIT_GUARD_RATIO:
            return ref_close
    return p


def compute_row_fill(
    row: Mapping,
    closes: CloseSeries | None,
    bench_closes: CloseSeries | None,
    now: datetime,
    horizons: Iterable[int] = HORIZONS,
) -> dict:
    """Fields to UPDATE on one candidate_outcomes row. Pure.

    Only horizons that have elapsed, are not yet filled, and have both the
    stock and the benchmark close available are returned — so re-running
    never overwrites a filled horizon and missing data is retried later.
    """
    signal_at = parse_ts(row.get("signal_at"))
    if signal_at is None:
        return {}
    exchange = classify_exchange(row.get("symbol") or "", row.get("exchange"))
    ref_date_equity = reference_close_date(signal_at, "NYSE")
    stock_ref = close_asof(
        closes,
        signal_session_date(signal_at, exchange) - timedelta(days=1) if exchange == "CRYPTO"
        else reference_close_date(signal_at, exchange),
    )
    base = entry_base_price(row.get("price_at_signal"), stock_ref)
    bench_base = close_asof(bench_closes, ref_date_equity)
    out: dict = {}
    now_iso = now.astimezone(UTC).isoformat()
    for h in horizons:
        if row.get(f"filled_{h}d_at"):
            continue
        if not horizon_elapsed(signal_at, h, exchange, now):
            continue
        hd = horizon_date(signal_at, h, exchange)
        fwd = simple_return(base, close_asof(closes, hd))
        bench = simple_return(bench_base, close_asof(bench_closes, hd))
        if fwd is None or bench is None:
            continue
        out[f"fwd_ret_{h}d"] = round(fwd, 6)
        out[f"spy_ret_{h}d"] = round(bench, 6)
        out[f"excess_ret_{h}d"] = round(fwd - bench, 6)
        out[f"filled_{h}d_at"] = now_iso
    return out


# ============================================================
# Pure helpers — seeding
# ============================================================

def _decision_index(decisions: Iterable[Mapping]) -> dict[tuple[str, str], Mapping]:
    """(scan_id, symbol) -> brain_decisions row; ENTER wins, else latest."""
    idx: dict[tuple[str, str], Mapping] = {}
    for d in decisions:
        key = (str(d.get("scan_id")), d.get("symbol"))
        cur = idx.get(key)
        if cur is None:
            idx[key] = d
            continue
        if cur.get("decision") == "ENTER":
            continue
        if d.get("decision") == "ENTER" or str(d.get("decided_at") or "") > str(cur.get("decided_at") or ""):
            idx[key] = d
    return idx


def build_candidate_rows(
    signals: Iterable[Mapping],
    decisions: Iterable[Mapping],
    existing_signal_ids: set[str],
) -> list[dict]:
    """candidate_outcomes rows for signals without one. Pure."""
    idx = _decision_index(decisions)
    rows: list[dict] = []
    seen: set[str] = set()
    for s in signals:
        sid = s.get("id")
        if not sid or sid in existing_signal_ids or sid in seen:
            continue
        symbol = s.get("symbol")
        price = s.get("price_at_signal")
        if not symbol or price is None or not s.get("created_at"):
            continue  # no entry price -> no outcome possible
        try:
            price = float(price)
        except (TypeError, ValueError):
            continue
        seen.add(sid)
        dec = idx.get((str(s.get("scan_id")), symbol))
        decision = dec.get("decision") if dec else None
        p_win = s.get("p_win")
        rows.append({
            "signal_id": sid,
            "scan_id": s.get("scan_id"),
            "symbol": symbol,
            "exchange": classify_exchange(symbol, s.get("exchange"), s.get("asset_type")),
            "signal_at": s.get("created_at"),
            "price_at_signal": price,
            "action": s.get("action"),
            "score": s.get("score"),
            "ai_status": s.get("ai_status"),
            "ai_signal": s.get("ai_signal"),
            "ai_provider": s.get("ai_provider"),
            "p_win": float(p_win) if p_win is not None else None,
            "routine_signal": s.get("routine_ai_signal"),
            "decision_overturned": s.get("decision_overturned"),
            "bucket": s.get("bucket"),
            "brain_decision": decision,
            "skip_reason": dec.get("reason") if decision == "SKIP" else None,
        })
    return rows


# ============================================================
# I/O — yfinance batch fetch
# ============================================================

def download_closes(symbols: list[str], start: date, end: date, chunk: int = 80) -> dict[str, list[tuple[date, float]]]:
    """Daily closes per symbol in [start, end] via batched yf.download.

    Split-adjusted, not dividend-adjusted (auto_adjust=False, 'Close'), so
    the series is comparable with the raw quote in price_at_signal.
    Failures per batch are logged and skipped (tolerant of missing data).
    """
    import pandas as pd
    import yfinance as yf

    out: dict[str, list[tuple[date, float]]] = {}
    syms = sorted({s for s in symbols if s})
    for i in range(0, len(syms), chunk):
        batch = syms[i:i + chunk]
        try:
            data = yf.download(
                " ".join(batch), start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                group_by="ticker", auto_adjust=False, progress=False, threads=False,
            )
        except Exception as e:
            logger.warning(f"outcomes: close download failed for {len(batch)} symbols: {e}")
            continue
        if data is None or getattr(data, "empty", True):
            continue
        for sym in batch:
            try:
                if isinstance(data.columns, pd.MultiIndex):
                    if sym not in data.columns.get_level_values(0):
                        continue
                    col = data[sym]["Close"]
                elif len(batch) == 1:
                    col = data["Close"]
                else:
                    continue
                col = col.dropna()
                series = [(ts.date(), float(v)) for ts, v in col.items() if float(v) > 0]
                if series:
                    out[sym] = sorted(series)
            except Exception:
                continue
    return out


# ============================================================
# Entry points (DB)
# ============================================================

def seed_candidates(since: datetime | None = None) -> dict:
    """Create candidate_outcomes rows for signals created since `since`."""
    from app.db import queries

    since = since or (datetime.now(UTC) - timedelta(days=settings.outcomes_seed_lookback_days))
    since_iso = since.astimezone(UTC).isoformat()
    signals = queries.get_signals_for_outcomes(since_iso)
    if not signals:
        return {"signals": 0, "seeded": 0}
    existing = queries.get_candidate_outcome_signal_ids(since_iso)
    new_signals = [s for s in signals if s.get("id") not in existing]
    decisions = queries.get_brain_decisions_for_scans(
        [s.get("scan_id") for s in new_signals if s.get("scan_id")]
    ) if new_signals else []
    rows = build_candidate_rows(new_signals, decisions, existing)
    queries.insert_candidate_outcomes(rows)
    logger.info(
        f"outcomes: seeded {len(rows)} candidate rows "
        f"({len(signals)} signals since {since_iso[:10]}, {len(existing)} already tracked)"
    )
    return {"signals": len(signals), "seeded": len(rows)}


def fill_forward_returns(now: datetime | None = None, fetcher: CloseFetcher | None = None) -> dict:
    """Fill every elapsed, unfilled horizon. Batch fetch, idempotent."""
    from app.db import queries

    now = now or datetime.now(UTC)
    fetcher = fetcher or download_closes
    bench = settings.outcomes_benchmark
    since = now - timedelta(days=settings.outcomes_fill_max_age_days)
    rows = queries.get_unfilled_candidate_outcomes(since.astimezone(UTC).isoformat())

    due: list[dict] = []
    start: date | None = None
    end: date | None = None
    for r in rows:
        signal_at = parse_ts(r.get("signal_at"))
        if signal_at is None:
            continue
        ex = classify_exchange(r.get("symbol") or "", r.get("exchange"))
        pending = [
            h for h in HORIZONS
            if not r.get(f"filled_{h}d_at") and horizon_elapsed(signal_at, h, ex, now)
        ]
        if not pending:
            continue
        due.append(r)
        first = signal_at.astimezone(ET).date() - timedelta(days=10)
        last = horizon_date(signal_at, max(pending), ex)
        start = first if start is None or first < start else start
        end = last if end is None or last > end else end

    if not due:
        return {"candidates": len(rows), "due": 0, "updated": 0, "horizons_filled": 0}

    symbols = sorted({r["symbol"] for r in due} | {bench})
    closes = fetcher(symbols, start, end)
    bench_closes = closes.get(bench)
    if not bench_closes:
        logger.warning(f"outcomes: no {bench} closes — nothing filled this run")
        return {"candidates": len(rows), "due": len(due), "updated": 0, "horizons_filled": 0}

    updated = filled = 0
    for r in due:
        fields = compute_row_fill(r, closes.get(r["symbol"]), bench_closes, now)
        if not fields:
            continue
        try:
            queries.update_candidate_outcome(r["id"], fields)
        except Exception as e:
            logger.warning(f"outcomes: update failed for {r.get('symbol')} ({r.get('id')}): {e}")
            continue
        updated += 1
        filled += sum(1 for k in fields if k.startswith("filled_"))
    logger.info(
        f"outcomes: filled {filled} horizons on {updated}/{len(due)} due rows "
        f"({len(symbols)} symbols fetched)"
    )
    return {"candidates": len(rows), "due": len(due), "updated": updated, "horizons_filled": filled}


def run_outcome_tracking() -> dict:
    """Seed then fill — the scheduler job body. Each step fails independently."""
    result: dict = {}
    try:
        result["seed"] = seed_candidates()
    except Exception as e:
        logger.warning(f"outcomes: seed failed: {e}")
        result["seed"] = {"error": str(e)}
    try:
        result["fill"] = fill_forward_returns()
    except Exception as e:
        logger.warning(f"outcomes: fill failed: {e}")
        result["fill"] = {"error": str(e)}
    return result
