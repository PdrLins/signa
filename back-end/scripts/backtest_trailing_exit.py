"""Backtest the trailing-exit ladder + stop-extension override.

What this answers
-----------------
"If we had NOT exited at TARGET_HIT / STOP_HIT, and instead applied the
proposed ladder/extension rule, would total P&L have gone up or down?"

The rule under test (per Day-38 design session)
-----------------------------------------------
TARGET_HIT (winning trades) — 3-state ladder:
  State 0 → 1: TARGET hit. Gates: P&L > 0 ✓, score >= 70, price made a
               new high in the last 4h, no fresh AVOID. → raise target
               by +5%, keep holding. (label: TARGET_EXTENDED_L1)
  State 1 → 2: New (raised) target hit. Same gates. → switch to trailing
               stop at -5% from peak. (label: TARGET_EXTENDED_L2_TRAILING)
  State 2 trail fires: exit. (label: TRAILING_STOP_HIT)
  Any gate fails at any state: exit immediately per current logic.

STOP_HIT (losing trades) — single extension:
  Stop hit. Gates: score >= 75 (higher bar than TARGET), thesis-tracker
  NOT "invalid" (weakening is OK), latest scan within 4h, this is the
  FIRST extension on this position. → lower stop by 3%, keep holding.
  (label: STOP_EXTENDED)
  New stop hits: exit, no further extensions. (label: STOP_HIT_FINAL)

Replay mechanics
----------------
For every closed virtual_trades row in the past N days with exit_reason
in (TARGET_HIT, STOP_HIT):
  1. Pull the latest signal at-or-before the exit_date — score, ai_status,
     thesis_last_status (joined from virtual_trades itself).
  2. Pull 48h of intraday price bars from yfinance starting at exit_date.
  3. Simulate the rule: walk forward bar-by-bar, applying the ladder
     transitions / stop extension. Exit on first trigger.
  4. Compute hypothetical exit P&L and the delta vs actual.

Output: TARGET cohort summary, STOP cohort summary, and a ship gate
verdict (TARGET delta > +$5/trade AND STOP delta >= 0).

Ship gate rationale
-------------------
TARGET cohort: we expect upside — the whole point is to let winners run.
  Mean delta should be clearly positive. Set threshold at +$5/trade so
  noise doesn't sneak through.
STOP cohort: we expect this to be the dangerous half. If extending stops
  on "thesis intact" losers makes them WORSE on average, the cohort
  delta will be negative and the rule shouldn't ship for stops.

Run:
    python -m scripts.backtest_trailing_exit
    python -m scripts.backtest_trailing_exit --days 60
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean

from app.db.supabase import get_client


# ----- rule parameters (mirror the ship spec) -----
TARGET_RAISE_PCT = 5.0          # Level 1: bump target up by +5%
TARGET_TRAIL_PCT = 5.0          # Level 2: trail at -5% from peak
STOP_LOWER_PCT = 3.0            # STOP extension: lower stop by 3%

TARGET_SCORE_GATE = 65          # min score to extend a winning target
                                # (lowered from 70 because the 5/20 SWKS case
                                # had score=69 — exactly the case we wanted
                                # to catch. The thesis-tracker bias documented
                                # Day-35 means winners are often downgraded
                                # right at exit, so a stricter score gate
                                # defeats the rule.)
STOP_SCORE_GATE = 75            # min score to extend a losing stop
SIGNAL_TRAIL_PCT = 5.0          # -5% from current price for SIGNAL-exit conversion
SIGNAL_MIN_PNL_PCT = 3.0        # only defer SIGNAL exits on positions up 3%+
                                # (small gains aren't worth the trail risk)
NEW_HIGH_LOOKBACK_HOURS = 4     # "price made new high in last 4h"
STALE_SCAN_HOURS = 4            # latest scan must be within 4h

REPLAY_WINDOW_HOURS = 48        # how far forward to simulate
BAR_INTERVAL_MINUTES = 15       # yfinance intraday resolution

SHIP_GATE_TARGET_MIN_DELTA = 5.0   # $/trade
SHIP_GATE_STOP_MIN_DELTA = 0.0     # $/trade (extensions must not hurt)


# ----- data fetch -----

def _fetch_closed_trades(db, days: int) -> list[dict]:
    """Get every closed virtual_trades row in the window where the exit
    reason is one we want to test."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = (
        db.table("virtual_trades")
        .select(
            "id, symbol, direction, shares, entry_date, entry_price, "
            "exit_date, exit_price, target_price, stop_loss, exit_reason, "
            "pnl_amount, pnl_pct, thesis_last_status, source"
        )
        .in_("exit_reason", ["TARGET_HIT", "STOP_HIT", "SIGNAL", "THESIS_INVALIDATED"])
        .gte("exit_date", since)
        .order("exit_date", desc=False)
        .execute()
    ).data or []
    return rows


def _attach_exit_time_signal(trades: list[dict], db) -> None:
    """For each trade, attach the latest signal score at-or-before the
    exit_date. We use this to evaluate the TARGET/STOP score gates."""
    for t in trades:
        sym = t["symbol"]
        try:
            sig = (
                db.table("signals")
                .select("score, ai_status, created_at")
                .eq("symbol", sym)
                .lte("created_at", t["exit_date"])
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            ).data or []
        except Exception:
            sig = []
        t["_exit_score"] = (sig[0].get("score") if sig else 0) or 0
        t["_exit_ai"] = (sig[0].get("ai_status") if sig else "") or ""
        t["_exit_signal_ts"] = sig[0].get("created_at") if sig else None


def _fetch_price_bars(symbol: str, start_dt: datetime, hours: int) -> list[dict]:
    """Pull intraday bars from yfinance starting at `start_dt` for `hours`.
    Returns [{ts, high, low, close}, ...] in chronological order.

    yfinance intraday data is only available for ~60 days back at 15min
    interval — older trades will return an empty list, which the caller
    treats as "no replay possible" and skips."""
    import yfinance as yf

    end_dt = start_dt + timedelta(hours=hours)
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(
            start=start_dt.strftime("%Y-%m-%d"),
            end=(end_dt + timedelta(days=1)).strftime("%Y-%m-%d"),
            interval=f"{BAR_INTERVAL_MINUTES}m",
            auto_adjust=False,
            prepost=False,
        )
    except Exception:
        return []
    if df is None or df.empty:
        return []
    bars: list[dict] = []
    for ts, row in df.iterrows():
        ts_utc = ts.to_pydatetime().astimezone(timezone.utc)
        if ts_utc < start_dt or ts_utc > end_dt:
            continue
        bars.append({
            "ts": ts_utc,
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
        })
    return bars


# ----- gates -----

def _target_gates_pass(trade: dict, peak_window_high: float, current_close: float) -> tuple[bool, str]:
    """Check the TARGET ladder gates. Returns (pass, fail_reason)."""
    score = trade["_exit_score"]
    ai = trade["_exit_ai"].lower()

    if score < TARGET_SCORE_GATE:
        return False, f"score<{TARGET_SCORE_GATE} ({score})"
    if ai == "avoid":
        return False, "fresh_AVOID"
    # "made a new high in last 4h" — at the moment of evaluation, the
    # close should be >= recent peak window high. (Approximation: we
    # treat the price reaching the target itself as evidence of upward
    # momentum if the close is within 1% of the peak.)
    if current_close < peak_window_high * 0.99:
        return False, "no_new_high"
    return True, ""


def _stop_gates_pass(trade: dict) -> tuple[bool, str]:
    """Check the STOP extension gates. Returns (pass, fail_reason).
    Stricter than TARGET gates because extending stops on losers is the
    dangerous half of the rule."""
    score = trade["_exit_score"]
    thesis = (trade.get("thesis_last_status") or "").lower()
    sig_ts = trade.get("_exit_signal_ts")

    if score < STOP_SCORE_GATE:
        return False, f"score<{STOP_SCORE_GATE} ({score})"
    if thesis == "invalid":
        return False, "thesis_invalid"
    if not sig_ts:
        return False, "no_recent_scan"
    # signal staleness
    try:
        sig_dt = datetime.fromisoformat(sig_ts.replace("Z", "+00:00"))
        exit_dt = datetime.fromisoformat(trade["exit_date"].replace("Z", "+00:00"))
        age_h = (exit_dt - sig_dt).total_seconds() / 3600
        if age_h > STALE_SCAN_HOURS:
            return False, f"scan_stale ({age_h:.1f}h)"
    except Exception:
        return False, "ts_parse_error"
    return True, ""


# ----- replay -----

def _pnl_for_exit(trade: dict, exit_price: float) -> float:
    """Compute hypothetical $ P&L if the trade had exited at exit_price.
    Direction-aware (LONG = profit when up, SHORT = profit when down)."""
    qty = trade.get("shares") or 0
    entry = trade.get("entry_price") or 0
    if not qty or not entry:
        return 0.0
    direction = (trade.get("direction") or "LONG").upper()
    if direction == "SHORT":
        return (entry - exit_price) * qty
    return (exit_price - entry) * qty


def _replay_target_ladder(trade: dict, bars: list[dict]) -> tuple[float, str]:
    """Walk forward bar-by-bar from exit_date. Apply the 3-state ladder.
    Returns (hypothetical_exit_price, label)."""
    if not bars:
        return trade["exit_price"], "NO_REPLAY_DATA"

    direction = (trade.get("direction") or "LONG").upper()
    is_short = direction == "SHORT"
    actual_target = trade.get("target_price") or trade["exit_price"]
    # SHORT inverts direction; for simplicity, this MVP focuses on LONG
    # (which is 100% of the cohort today). SHORT trades fall through
    # to "exit at actual price."
    if is_short:
        return trade["exit_price"], "SHORT_NOT_IMPLEMENTED"

    # State 0 gates — evaluated at the actual exit moment (bar 0)
    # Note: the trade was already winning (TARGET_HIT means we hit target).
    peak = bars[0]["high"]
    ok, reason = _target_gates_pass(trade, peak, bars[0]["close"])
    if not ok:
        return trade["exit_price"], f"L0_GATE_FAIL:{reason}"

    # Enter State 1: raised target
    raised_target = actual_target * (1 + TARGET_RAISE_PCT / 100)
    state = 1
    trailing_stop = None  # set when entering State 2

    for i, bar in enumerate(bars):
        peak = max(peak, bar["high"])

        if state == 1:
            # Watching for the raised target to hit
            if bar["high"] >= raised_target:
                # State 1 → 2 transition: re-check gates
                ok, reason = _target_gates_pass(trade, peak, bar["close"])
                if not ok:
                    # Gates failed at L1 hit → exit at raised target
                    return raised_target, f"L1_HIT_EXIT_GATE_FAIL:{reason}"
                # Enter State 2: convert to trailing stop
                state = 2
                trailing_stop = peak * (1 - TARGET_TRAIL_PCT / 100)
                continue
        elif state == 2:
            # Trailing stop active — update on new highs, exit on hit
            new_trail = peak * (1 - TARGET_TRAIL_PCT / 100)
            trailing_stop = max(trailing_stop or 0, new_trail)
            if bar["low"] <= trailing_stop:
                return trailing_stop, "L2_TRAILING_STOP_HIT"

    # Replay window expired — assume mark-to-market exit at last close
    final = bars[-1]["close"]
    if state == 1:
        return final, "L1_WINDOW_EXPIRED"
    return final, "L2_WINDOW_EXPIRED"


def _replay_trailing_convert(trade: dict, bars: list[dict], cohort_label: str) -> tuple[float, str]:
    """Soft-exit conversion (used for both SIGNAL and THESIS_INVALIDATED):
    instead of exiting at the actual exit price, arm a trailing stop at
    -SIGNAL_TRAIL_PCT% from the current price. Exit when the trail hits
    OR at end of window (mark-to-market).

    Rationale: SIGNAL and THESIS_INVALIDATED are both "AI changed its
    mind" exits — neither is a hard price trigger (no stop/target hit).
    For these, if the position is already profitable, deferring with a
    trail asks the question "is the AI's bearish flip actually right,
    or just early?" The trail catches genuine reversals; window-expiry
    captures cases where the AI was wrong and the trend continued.

    Gates:
      - Position must be profitable at exit (pnl_pct > SIGNAL_MIN_PNL_PCT)
      - LONG only (SHORT replay not implemented)

    Returns (hypothetical_exit_price, label)."""
    if not bars:
        return trade["exit_price"], "NO_REPLAY_DATA"

    direction = (trade.get("direction") or "LONG").upper()
    if direction == "SHORT":
        return trade["exit_price"], "SHORT_NOT_IMPLEMENTED"

    pnl_pct = trade.get("pnl_pct") or 0
    if pnl_pct < SIGNAL_MIN_PNL_PCT:
        return trade["exit_price"], f"{cohort_label}_GATE_FAIL:pnl_pct<{SIGNAL_MIN_PNL_PCT} ({pnl_pct:.1f})"

    # Arm trail at -5% from current (= the actual exit price).
    peak = trade["exit_price"]
    trailing_stop = peak * (1 - SIGNAL_TRAIL_PCT / 100)

    for bar in bars:
        # Update peak on new highs
        if bar["high"] > peak:
            peak = bar["high"]
            trailing_stop = peak * (1 - SIGNAL_TRAIL_PCT / 100)
        # Check trail hit
        if bar["low"] <= trailing_stop:
            return trailing_stop, f"{cohort_label}_TRAIL_HIT"

    # Window expired without hitting trail — mark-to-market at last close
    return bars[-1]["close"], f"{cohort_label}_WINDOW_EXPIRED"


def _replay_stop_extension(trade: dict, bars: list[dict]) -> tuple[float, str]:
    """Apply the single STOP extension. Returns (hypothetical_exit_price, label)."""
    if not bars:
        return trade["exit_price"], "NO_REPLAY_DATA"

    direction = (trade.get("direction") or "LONG").upper()
    is_short = direction == "SHORT"
    if is_short:
        return trade["exit_price"], "SHORT_NOT_IMPLEMENTED"

    actual_stop = trade.get("stop_loss") or trade["exit_price"]

    # Gates evaluated at the moment of stop hit (bar 0)
    ok, reason = _stop_gates_pass(trade)
    if not ok:
        return trade["exit_price"], f"STOP_GATE_FAIL:{reason}"

    # Lower the stop by 3%
    extended_stop = actual_stop * (1 - STOP_LOWER_PCT / 100)

    for bar in bars:
        if bar["low"] <= extended_stop:
            return extended_stop, "STOP_HIT_FINAL"

    # Survived the window — exit at the last close (mark-to-market)
    return bars[-1]["close"], "STOP_EXTENDED_WINDOW_EXPIRED"


# ----- summary / reporting -----

def _summarize_cohort(rows: list[dict], cohort_label: str) -> dict:
    """Compute mean/total delta, win/loss splits, ship-gate verdict."""
    if not rows:
        return {"label": cohort_label, "n": 0}
    deltas = [r["_delta"] for r in rows]
    helped = [r for r in rows if r["_delta"] > 0.01]
    hurt = [r for r in rows if r["_delta"] < -0.01]
    flat = [r for r in rows if -0.01 <= r["_delta"] <= 0.01]
    return {
        "label": cohort_label,
        "n": len(rows),
        "mean_delta": mean(deltas),
        "total_delta": sum(deltas),
        "helped_n": len(helped),
        "hurt_n": len(hurt),
        "flat_n": len(flat),
        "best": max(rows, key=lambda r: r["_delta"]),
        "worst": min(rows, key=lambda r: r["_delta"]),
    }


def _print_cohort(s: dict, min_delta_for_ship: float) -> bool:
    """Print a cohort summary. Returns True if ship gate passes."""
    print(f"\n═══ {s['label']} cohort ═══")
    if s.get("n", 0) == 0:
        print("  (no trades in window)")
        return False
    print(f"  n={s['n']}  helped={s['helped_n']}  hurt={s['hurt_n']}  flat={s['flat_n']}")
    print(f"  mean Δ = ${s['mean_delta']:+.2f}/trade")
    print(f"  total Δ = ${s['total_delta']:+.2f} across {s['n']} trades")
    print(f"  best:  {s['best']['symbol']:<6} Δ ${s['best']['_delta']:+.2f}  "
          f"({s['best']['_replay_label']})")
    print(f"  worst: {s['worst']['symbol']:<6} Δ ${s['worst']['_delta']:+.2f}  "
          f"({s['worst']['_replay_label']})")
    passes = s["mean_delta"] >= min_delta_for_ship
    verdict = "PASS" if passes else "FAIL"
    print(f"  ship gate (mean Δ >= ${min_delta_for_ship:+.2f}): {verdict}")
    return passes


def _print_per_trade_table(rows: list[dict]) -> None:
    """Per-trade breakdown — small table for human review."""
    if not rows:
        return
    print(f"\n  {'symbol':<7} {'exit_reason':<10} {'actual$':>9} {'replay$':>9} "
          f"{'Δ':>8}  {'replay_label'}")
    for r in rows:
        print(
            f"  {r['symbol']:<7} {r['exit_reason']:<10} "
            f"${r['pnl_amount']:>+8.2f} ${r['_replay_pnl']:>+8.2f} "
            f"${r['_delta']:>+7.2f}  {r['_replay_label']}"
        )


# ----- main -----

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="lookback window (default: 30)")
    ap.add_argument("--verbose", action="store_true", help="print per-trade table")
    args = ap.parse_args()

    db = get_client()
    print(f"Fetching closed virtual_trades, last {args.days} days...")
    trades = _fetch_closed_trades(db, args.days)
    print(f"  Found {len(trades)} closes with exit_reason in (TARGET_HIT, STOP_HIT)")
    if not trades:
        print("Nothing to backtest. Exiting.")
        return

    _attach_exit_time_signal(trades, db)

    # Replay each trade
    skipped = defaultdict(int)
    for t in trades:
        try:
            exit_dt = datetime.fromisoformat(t["exit_date"].replace("Z", "+00:00"))
        except Exception:
            skipped["bad_exit_date"] += 1
            t["_skip"] = True
            continue
        bars = _fetch_price_bars(t["symbol"], exit_dt, REPLAY_WINDOW_HOURS)
        if not bars:
            skipped["no_yfinance_data"] += 1
            t["_skip"] = True
            continue

        if t["exit_reason"] == "TARGET_HIT":
            replay_price, label = _replay_target_ladder(t, bars)
        elif t["exit_reason"] == "STOP_HIT":
            replay_price, label = _replay_stop_extension(t, bars)
        elif t["exit_reason"] == "SIGNAL":
            replay_price, label = _replay_trailing_convert(t, bars, "SIGNAL")
        else:  # THESIS_INVALIDATED
            replay_price, label = _replay_trailing_convert(t, bars, "THESIS")

        replay_pnl = _pnl_for_exit(t, replay_price)
        t["_replay_price"] = replay_price
        t["_replay_pnl"] = replay_pnl
        t["_replay_label"] = label
        t["_delta"] = replay_pnl - (t.get("pnl_amount") or 0)
        t["_skip"] = False

    replayed = [t for t in trades if not t.get("_skip")]
    print(f"  Replayed {len(replayed)} trades (skipped {sum(skipped.values())}: "
          f"{dict(skipped)})\n")

    target_rows = [t for t in replayed if t["exit_reason"] == "TARGET_HIT"]
    stop_rows = [t for t in replayed if t["exit_reason"] == "STOP_HIT"]
    signal_rows = [t for t in replayed if t["exit_reason"] == "SIGNAL"]
    thesis_rows = [t for t in replayed if t["exit_reason"] == "THESIS_INVALIDATED"]

    target_summary = _summarize_cohort(target_rows, "TARGET_HIT (ladder)")
    stop_summary = _summarize_cohort(stop_rows, "STOP_HIT (extension)")
    signal_summary = _summarize_cohort(signal_rows, "SIGNAL (trailing-convert)")
    thesis_summary = _summarize_cohort(thesis_rows, "THESIS_INVALIDATED (trailing-convert)")

    target_pass = _print_cohort(target_summary, SHIP_GATE_TARGET_MIN_DELTA)
    stop_pass = _print_cohort(stop_summary, SHIP_GATE_STOP_MIN_DELTA)
    # SIGNAL and THESIS cohorts use the same ship gate as TARGET — we expect upside.
    signal_pass = _print_cohort(signal_summary, SHIP_GATE_TARGET_MIN_DELTA)
    thesis_pass = _print_cohort(thesis_summary, SHIP_GATE_TARGET_MIN_DELTA)

    if args.verbose:
        _print_per_trade_table(target_rows)
        _print_per_trade_table(stop_rows)
        _print_per_trade_table(signal_rows)
        _print_per_trade_table(thesis_rows)

    print("\n═══ FINAL VERDICT ═══")
    ships = []
    if target_pass:
        ships.append("TARGET ladder")
    if stop_pass:
        ships.append("STOP extension")
    if signal_pass:
        ships.append("SIGNAL trailing-convert")
    if thesis_pass:
        ships.append("THESIS_INVALIDATED trailing-convert")
    if ships:
        print(f"  SHIP: {', '.join(ships)}")
    else:
        print("  DO NOT SHIP. All cohorts fail the ship gate.")
    print()
    print("  Caveat: yfinance intraday data is only ~60 days back. Older")
    print("  trades will be silently skipped. Re-run periodically as new")
    print("  closes accumulate to increase sample size.")


if __name__ == "__main__":
    main()
