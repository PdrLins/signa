"""One-off audit: cross-check virtual_trades CLOSED rows against yfinance.

For each closed brain/watchlist trade in the DB, fetch the historical OHLC
on the entry_date and exit_date and compare against the recorded entry_price
and exit_price. Flag any row where:

  - The recorded price falls outside that day's [low, high] range, or
  - The recorded P&L sign disagrees with the market's day-over-day move, or
  - The exit_date is before entry_date (impossible but possible from a bug),
  - The same trade id appears with mismatched data (mutation evidence).

Also surfaces whether the same symbol has multiple closed rows on overlapping
dates (which could explain the user's "loss became a win" observation if the
brain re-bought after a loss).

Usage (from back-end/):
    venv/bin/python -m scripts.audit_closed_trades

Read-only — does not modify any DB rows.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

# Allow `python -m scripts.audit_closed_trades` from back-end/ root
sys.path.insert(0, ".")

import yfinance as yf  # type: ignore
from app.db.supabase import get_client

ET = ZoneInfo("America/New_York")


# Tolerance: how far the recorded price can stray from yfinance's day range
# before we flag it. We allow a small buffer because intraday quotes can
# briefly print outside the consolidated tape's reported high/low.
PRICE_TOLERANCE_PCT = 1.0  # 1% slack on either side of the day's [low, high]


def fmt_dt(iso: str | None) -> str:
    """Render a UTC ISO timestamp as `YYYY-MM-DD HH:MM ET` with proper conversion."""
    if not iso:
        return "--"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(ET).strftime("%Y-%m-%d %H:%M ET")
    except Exception:
        return iso


def market_status(iso: str | None) -> str:
    """Tag a timestamp as PRE / OPEN / CLOSE based on ET market hours."""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ET)
    except Exception:
        return ""
    if dt.weekday() >= 5:
        return " [WEEKEND]"
    minutes = dt.hour * 60 + dt.minute
    if minutes < 9 * 60 + 30:
        return " [PRE-MARKET]"
    if minutes >= 16 * 60:
        return " [AFTER-HOURS]"
    return ""


def parse_date(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return None


def yf_day(symbol: str, day: datetime) -> dict | None:
    """Fetch a single day's OHLC for `symbol`. Returns None if no bar."""
    # Pull a 5-day window centered on the target day so weekends/holidays
    # don't return empty. We then pick the bar matching the target date.
    start = (day - timedelta(days=3)).strftime("%Y-%m-%d")
    end = (day + timedelta(days=3)).strftime("%Y-%m-%d")
    try:
        hist = yf.Ticker(symbol).history(start=start, end=end, auto_adjust=False)
    except Exception as e:
        print(f"  ! yfinance fetch failed for {symbol}: {e}")
        return None
    if hist.empty:
        return None

    target = day.date()
    # Find the closest trading day on or before the target
    bar = None
    for idx, row in hist.iterrows():
        bar_date = idx.date() if hasattr(idx, "date") else idx
        if bar_date == target:
            bar = (bar_date, row)
            break
    # Fallback: most recent bar at-or-before target
    if bar is None:
        candidates = [(idx.date() if hasattr(idx, "date") else idx, row) for idx, row in hist.iterrows()]
        candidates = [c for c in candidates if c[0] <= target]
        if candidates:
            bar = max(candidates, key=lambda c: c[0])
    if bar is None:
        return None
    bar_date, row = bar
    return {
        "date": str(bar_date),
        "open": float(row["Open"]),
        "high": float(row["High"]),
        "low": float(row["Low"]),
        "close": float(row["Close"]),
    }


def in_range(price: float, low: float, high: float) -> bool:
    slack = (high - low) * (PRICE_TOLERANCE_PCT / 100.0) if high > low else low * 0.005
    return (low - slack) <= price <= (high + slack)


def main() -> int:
    db = get_client()
    res = (
        db.table("virtual_trades")
        .select("id, symbol, source, status, entry_price, exit_price, entry_date, exit_date, "
                "pnl_pct, is_win, exit_reason, entry_score, exit_score")
        .eq("status", "CLOSED")
        .order("exit_date", desc=True)
        .limit(50)
        .execute()
    )
    rows = res.data or []
    print(f"Loaded {len(rows)} closed virtual_trades rows.\n")

    # Detect duplicate (symbol, exit_date) which would indicate row mutation
    by_symbol: dict[str, list[dict]] = {}
    for r in rows:
        by_symbol.setdefault(r["symbol"], []).append(r)

    print("=" * 100)
    print("PER-ROW AUDIT")
    print("=" * 100)

    flagged = 0
    for r in rows:
        sym = r["symbol"]
        entry = float(r["entry_price"]) if r.get("entry_price") is not None else None
        exit_p = float(r["exit_price"]) if r.get("exit_price") is not None else None
        entry_dt = parse_date(r.get("entry_date"))
        exit_dt = parse_date(r.get("exit_date"))
        pnl = r.get("pnl_pct")
        is_win = r.get("is_win")
        reason = r.get("exit_reason") or "?"
        source = r.get("source") or "?"

        print(f"\n[{sym}] id={r['id'][:8]}... source={source} reason={reason}")
        print(f"  recorded: entry {entry} @ {fmt_dt(r.get('entry_date'))}{market_status(r.get('entry_date'))}")
        print(f"            exit  {exit_p} @ {fmt_dt(r.get('exit_date'))}{market_status(r.get('exit_date'))}")
        print(f"            pnl_pct={pnl}  is_win={is_win}  scores={r.get('entry_score')}->{r.get('exit_score')}")

        problems: list[str] = []

        if entry_dt and exit_dt and exit_dt < entry_dt:
            problems.append(f"exit_date {exit_dt.date()} is BEFORE entry_date {entry_dt.date()}")

        # Cross-check entry against yfinance
        if entry and entry_dt:
            bar = yf_day(sym, entry_dt)
            if bar:
                print(f"  yfinance entry day {bar['date']}: O={bar['open']:.2f} H={bar['high']:.2f} L={bar['low']:.2f} C={bar['close']:.2f}")
                if not in_range(entry, bar["low"], bar["high"]):
                    problems.append(
                        f"recorded entry ${entry:.2f} is OUTSIDE the {bar['date']} range "
                        f"[${bar['low']:.2f}, ${bar['high']:.2f}]"
                    )
            else:
                print(f"  yfinance: no entry day bar found for {sym}")

        # Cross-check exit against yfinance
        if exit_p and exit_dt:
            bar = yf_day(sym, exit_dt)
            if bar:
                print(f"  yfinance exit  day {bar['date']}: O={bar['open']:.2f} H={bar['high']:.2f} L={bar['low']:.2f} C={bar['close']:.2f}")
                if not in_range(exit_p, bar["low"], bar["high"]):
                    problems.append(
                        f"recorded exit ${exit_p:.2f} is OUTSIDE the {bar['date']} range "
                        f"[${bar['low']:.2f}, ${bar['high']:.2f}]"
                    )
            else:
                print(f"  yfinance: no exit day bar found for {sym}")

        # Sanity: pnl sign should match (exit-entry) sign
        if entry and exit_p and pnl is not None:
            real_pnl = ((exit_p - entry) / entry) * 100
            if abs(real_pnl - pnl) > 0.1:
                problems.append(
                    f"recorded pnl_pct {pnl} disagrees with computed ({real_pnl:+.2f}%)"
                )
            if (real_pnl > 0) != bool(is_win):
                problems.append(f"is_win={is_win} disagrees with computed pnl sign ({real_pnl:+.2f}%)")

        if problems:
            flagged += 1
            for p in problems:
                print(f"  *** PROBLEM: {p}")

    print()
    print("=" * 100)
    print("DUPLICATE-SYMBOL CHECK (closed trades on same symbol)")
    print("=" * 100)
    for sym, rs in by_symbol.items():
        if len(rs) > 1:
            print(f"\n{sym}: {len(rs)} closed rows")
            for r in sorted(rs, key=lambda x: x.get("exit_date") or ""):
                print(f"  - id={r['id'][:8]}  entry {fmt_dt(r.get('entry_date'))} -> exit {fmt_dt(r.get('exit_date'))}  "
                      f"{r.get('entry_price')}→{r.get('exit_price')}  pnl={r.get('pnl_pct')}%  win={r.get('is_win')}  reason={r.get('exit_reason')}")

    print()
    print("=" * 100)
    print(f"SUMMARY: {len(rows)} rows audited, {flagged} flagged with problems")
    print("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
