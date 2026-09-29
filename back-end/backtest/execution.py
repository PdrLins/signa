"""Daily-bar execution of the LIVE exit policy (`virtual_portfolio.evaluate_exit`).

`evaluate_exit` takes one price. A daily bar has four, and the intraday
order of high and low is unknown, so each bar is replayed conservatively:

  1. OPEN  (skipped on the entry day — we bought at this open)
     evaluate_exit(open): a gap through the stop / target, or a time
     expiry, exits AT THE OPEN (a gap-down stop fills at the open, i.e.
     worse than the stop).
  2. LOW   evaluate_exit(low) against the stop in force → STOP_HIT /
     TRAILING_STOP filled AT THE STOP. Tested BEFORE the high: when a bar
     touches both stop and target we assume the stop came first.
  3. HIGH  evaluate_exit(high) → TARGET_HIT filled AT THE TARGET.
     Otherwise the live trailing ratchet is applied from the new peak.
  4. CLOSE evaluate_exit(close): if the stop ratcheted up from today's
     high is above the close, price fell through it after the high →
     exit at that stop.

All slippage / commission / FX on exit comes from the LIVE
`compute_close_amounts` (the caller does that); here we only decide
(reason, reference price). The clock handed to `evaluate_exit` is a
fixed 14:30 UTC on each bar date, so TIME_EXPIRED (whole calendar days
since entry >= brain_max_hold_days) fires at the open of the expiry day.
SIGNAL exits cannot fire: the live rule needs an AI SELL/AVOID call,
which never exists in a tech-only run.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from backtest import live

STOP_REASONS = ("STOP_HIT", "TRAILING_STOP")


def clock(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 14, 30, tzinfo=timezone.utc)


def _apply(pos: dict, dec) -> None:
    if dec.stop is not None:
        pos["stop_loss"] = dec.stop
    if dec.peak is not None:
        pos["peak_price"] = dec.peak


def new_position(symbol: str, d: date, fill: float, levels: dict, shares: float = 1.0,
                 **extra) -> dict:
    """A position row in the live `virtual_trades` shape."""
    pos = {
        "symbol": symbol,
        "source": "brain",
        "direction": "LONG",
        "status": "OPEN",
        "entry_price": fill,
        "entry_date": clock(d).isoformat(),
        "stop_loss": levels["stop"],
        "initial_stop": levels["stop"],
        "target_price": levels["target"],
        "entry_atr": levels["atr"],
        "peak_price": fill,
        "shares": shares,
    }
    pos.update(extra)
    return pos


def open_step(pos: dict, o: float, d: date) -> tuple[str, float] | None:
    dec = live.evaluate_exit(pos, o, clock(d))
    if dec.reason:
        return dec.reason, float(o)
    _apply(pos, dec)
    return None


def intraday_step(pos: dict, h: float, low: float, c: float, d: date) -> tuple[str, float] | None:
    now = clock(d)
    dec = live.evaluate_exit(pos, low, now)
    if dec.reason in STOP_REASONS:
        return dec.reason, float(dec.stop)
    dec = live.evaluate_exit(pos, h, now)
    if dec.reason == "TARGET_HIT":
        return "TARGET_HIT", float(pos["target_price"])
    _apply(pos, dec)
    dec = live.evaluate_exit(pos, c, now)
    if dec.reason in STOP_REASONS:
        return dec.reason, float(dec.stop)
    if dec.reason:
        return dec.reason, float(c)
    _apply(pos, dec)
    return None


def step_bar(pos: dict, bar: tuple[float, float, float, float], d: date,
             entered_today: bool) -> tuple[str, float] | None:
    """Full bar (open then intraday). Used by the per-symbol study."""
    o, h, low, c = bar
    if not entered_today:
        r = open_step(pos, o, d)
        if r:
            return r
    return intraday_step(pos, h, low, c, d)
