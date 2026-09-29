"""Portfolio simulation with the LIVE brain's sizing, limits and exits.

Timeline for each calendar day d (union of all symbols' bar dates):

  1. OPEN   open positions with a bar on d: gap / time-expiry exits at the
            open (`execution.open_step`).
  2. ENTRY  pending orders from signals on an earlier day t < d fill at the
            symbol's NEXT bar's OPEN (t+1 open; an equity signal on Friday
            fills Monday). Order = live `brain_entry_sort_key`: filter mode
            → AI p_win, then AI confidence (absent historically, so ties keep
            the prefilter's trend-quality order); score mode → highest score
            first. Gates, in
            the live `_evaluate_brain_entry` order:
              already held → re-entry cooldown (live trading_days_between,
              brain_reentry_cooldown_days) → drawdown breaker (live
              `evaluate_drawdown_breaker`: trip → pause
              brain_drawdown_pause_trading_days US sessions → reset peak) →
              FX available → fill = live apply_slippage(open, BUY) → live
              compute_entry_levels (ATR stop/target, min R:R) → live
              calc_risk_position_size (1% risk, 10% cap, cash) → live
              check_portfolio_limits (max positions, sector, crypto cap) →
              live correlation gate (point-in-time closes).
            Cash out = allocation + commission (live cost basis).
  3. BARS   stop-first intraday exits (`execution.intraday_step`); exit
            cash from the live compute_close_amounts (slippage, commission,
            FX at the exit day).
  4. MARK   equity = cash + Σ shares × last close × FX(d); peak updated.
  5. SIGNAL day-d signals that pass `is_entry` become pending orders.

Not modelled (live behaviour that needs data we don't have): AI tier
gate / AI SELL exits, thesis tracker, watchdog intraday prices, market-
hours checks (fills are at the regular-session open), shorts (off live).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from backtest import execution, live
from backtest.signals import SignalConfig, is_entry

ORDER_TTL_DAYS = 6  # calendar days an unfilled order waits (long weekends / holidays)


@dataclass
class SimConfig:
    initial_cash: float = 10_000.0
    commission_usd: float | None = None   # None = live settings.brain_commission_usd
    drawdown_breaker: bool = True
    correlation_gate: bool = True
    signal: SignalConfig = field(default_factory=SignalConfig)


class FX:
    """USD per 1 unit of native currency, point-in-time (last rate <= d)."""

    def __init__(self, usdcad: pd.DataFrame | None):
        s = usdcad["Close"] if usdcad is not None and not usdcad.empty else pd.Series(dtype=float)
        # Same sanity band as live get_usdcad_rate (1.0-2.0 CAD per USD).
        self.rate = s[(s > 1.0) & (s < 2.0)]

    def to_usd(self, symbol: str, d: date) -> float | None:
        if live.native_currency(symbol) == "USD":
            return 1.0
        r = self.rate[self.rate.index <= pd.Timestamp(d)]
        return (1.0 / float(r.iloc[-1])) if not r.empty else None

    def usd_closes(self, symbol: str, closes: pd.Series) -> pd.Series:
        if live.native_currency(symbol) == "USD":
            return closes
        rate = self.rate.reindex(closes.index, method="ffill")
        return (closes / rate).dropna()


@dataclass
class SimResult:
    equity: pd.Series
    invested: pd.Series
    trades: list[dict]
    skips: Counter
    breaker_days: int
    orders: int
    notional_traded: float
    fees: float
    breaker_trips: int = 0
    breaker_resumes: int = 0


def _bar(bars: dict[str, pd.DataFrame], sym: str, d: date):
    df = bars.get(sym)
    if df is None:
        return None
    ts = pd.Timestamp(d)
    try:
        row = df.loc[ts]
    except KeyError:
        return None
    return float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])


def _last_close(bars, sym, d) -> float | None:
    df = bars.get(sym)
    if df is None:
        return None
    s = df["Close"]
    s = s[s.index <= pd.Timestamp(d)]
    return float(s.iloc[-1]) if not s.empty else None




class Simulator:
    def __init__(self, days: list[date], signals_by_day: dict[date, list[dict]],
                 bars: dict[str, pd.DataFrame], fx: FX, cfg: SimConfig):
        self.days = days
        self.signals_by_day = signals_by_day
        self.bars = bars
        self.fx = fx
        self.cfg = cfg
        s = live.settings
        self.commission = s.brain_commission_usd if cfg.commission_usd is None else cfg.commission_usd
        self.cash = cfg.initial_cash
        self.peak = cfg.initial_cash
        self.positions: dict[str, dict] = {}
        self.last_exit: dict[str, date] = {}
        self.pending: dict[str, tuple[dict, date]] = {}
        self.trades: list[dict] = []
        self.skips: Counter = Counter()
        self.last_px: dict[str, float] = {}
        self.breaker_days = 0          # days on which the breaker blocked entries (paused)
        self.breaker_trips = 0
        self.breaker_resumes = 0
        self.breaker_tripped_at: date | None = None
        self.orders = 0
        self.notional = 0.0
        self.fees = 0.0

    # ── accounting ─────────────────────────────────────────
    def mark(self, d: date) -> tuple[float, float]:
        inv = 0.0
        for sym, p in self.positions.items():
            px = self.last_px.get(sym) or p["entry_price"]
            f = self.fx.to_usd(sym, d) or p["fx_to_usd_entry"]
            inv += p["shares"] * px * f
        return self.cash + inv, inv

    def open_book(self) -> list[dict]:
        return [{"symbol": sym, "sector": p["sector"], "is_crypto": live.is_crypto(sym),
                 "cost_usd": p["position_size_usd"], "direction": "LONG", "id": sym}
                for sym, p in self.positions.items()]

    def close(self, sym: str, reason: str, ref: float, d: date) -> None:
        p = self.positions.pop(sym)
        f = self.fx.to_usd(sym, d) or p["fx_to_usd_entry"]
        amt = live.compute_close_amounts(p, ref, f)
        self.cash += amt["balance_delta"]
        self.notional += p["shares"] * amt["fill"] * f
        self.fees += self.commission
        risk = p.get("risk_usd") or 0.0
        self.trades.append({
            "symbol": sym, "signal_date": p["signal_date"].isoformat(),
            "entry_date": p["entry_day"].isoformat(), "exit_date": d.isoformat(),
            "entry_fill": round(p["entry_price"], 6), "exit_fill": round(amt["fill"], 6),
            "exit_ref": round(ref, 6), "shares": p["shares"],
            "cost_usd": p["position_size_usd"],
            "pnl_usd": round(amt["pnl_usd"], 2), "pnl_pct": round(amt["pnl_pct"], 3),
            "r_multiple": round(amt["pnl_usd"] / risk, 3) if risk > 0 else None,
            "exit_reason": reason, "score": p["entry_score"], "bucket": p["bucket"],
            "sector": p["sector"], "regime": p["market_regime"],
            "hold_days": (d - p["entry_day"]).days,
        })
        self.last_exit[sym] = d

    # ── entry gates (live order, see module doc) ───────────
    def closes_loader(self, d: date):
        """Point-in-time USD closes (strictly before d, 1y) for the live
        correlation gate."""
        lo = pd.Timestamp(d) - pd.Timedelta(days=365)

        def _load(symbols: list[str]) -> dict:
            out = {}
            for sym in symbols:
                df = self.bars.get(sym)
                if df is None:
                    continue
                c = df["Close"]
                c = c[(c.index < pd.Timestamp(d)) & (c.index > lo)]
                out[sym] = self.fx.usd_closes(sym, c)
            return out
        return _load

    def try_enter(self, sym: str, sig: dict, d: date, open_px: float, equity: float,
                  tripped: bool) -> str | None:
        s = live.settings
        if sym in self.positions:
            return "already_held"
        ex = self.last_exit.get(sym)
        n = s.brain_reentry_cooldown_days
        if ex is not None and n > 0 and live.trading_days_between(ex, d) < n:
            return "reentry_cooldown"
        if tripped:
            return "drawdown_breaker_pause"
        fx = self.fx.to_usd(sym, d)
        if not fx:
            return "fx_unavailable"
        fill = live.apply_slippage(open_px, "BUY", sym)
        levels = live.compute_entry_levels(sig, fill)
        if levels["reason"]:
            return "rr_below_min" if levels["reason"].startswith("rr_below") else levels["reason"]
        risk_ps_usd = abs(fill - levels["stop"]) * fx
        shares, alloc = live.calc_risk_position_size(equity, self.cash, fill * fx,
                                                     fill * fx - risk_ps_usd)
        if shares <= 0:
            return "size_below_minimum"
        book = self.open_book()
        alloc2, why = live.check_portfolio_limits(
            symbol=sym, sector=sig.get("sector"), is_crypto=live.is_crypto(sym),
            alloc_usd=alloc, equity_usd=equity, open_book=book,
        )
        if why:
            return "sector_cap" if why.startswith("sector_cap") else why
        if alloc2 < alloc:
            alloc = round(alloc2, 2)
            shares = round(alloc / (fill * fx), 6)
        if self.cfg.correlation_gate:
            why = live.correlation_gate(symbol=sym, alloc_usd=alloc, equity_usd=equity,
                                        open_book=book, closes_loader=self.closes_loader(d))
            if why:
                return why
        cost = round(alloc + self.commission, 4)
        if cost > self.cash + 1e-6:
            return "insufficient_cash"
        self.cash -= cost
        self.notional += alloc
        self.fees += self.commission
        self.positions[sym] = execution.new_position(
            sym, d, fill, levels, shares,
            position_size_usd=round(cost, 2), is_wallet_trade=True, fx_to_usd_entry=fx,
            fees_usd=self.commission, entry_score=sig["score"], bucket=sig["bucket"],
            sector=sig.get("sector"), market_regime=sig.get("market_regime"),
            signal_date=sig["date"], entry_day=d, risk_usd=shares * risk_ps_usd,
        )
        return None

    # ── main loop ──────────────────────────────────────────
    def run(self) -> SimResult:
        eq, inv = {}, {}
        for d in self.days:
            for sym in [k for k, (_, t) in self.pending.items() if (d - t).days > ORDER_TTL_DAYS]:
                self.pending.pop(sym)
                self.skips["order_expired_no_bar"] += 1

            todays = {sym: _bar(self.bars, sym, d) for sym in set(self.positions) | set(self.pending)}

            # 1. gap / time exits at the open
            for sym in list(self.positions):
                b = todays.get(sym)
                if b is not None:
                    r = execution.open_step(self.positions[sym], b[0], d)
                    if r:
                        self.close(sym, r[0], r[1], d)

            # 2. entries at the open, in the live entry order
            equity, _ = self.mark(d)
            tripped = False
            if self.cfg.drawdown_breaker:
                st = live.evaluate_drawdown_breaker(equity, self.peak, self.breaker_tripped_at, d)
                self.peak, self.breaker_tripped_at = st.peak, st.tripped_at
                self.breaker_trips += int(st.event == "tripped")
                self.breaker_resumes += int(st.event == "resumed")
                tripped = st.blocked
            self.breaker_days += int(bool(tripped))
            mode = self.cfg.signal.mode
            fillable = sorted(
                ((sym, sig) for sym, (sig, t) in self.pending.items()
                 if t < d and todays.get(sym) is not None),
                key=lambda x: live.brain_entry_sort_key(x[1], mode),
            )
            for sym, sig in fillable:
                self.pending.pop(sym, None)
                self.orders += 1
                why = self.try_enter(sym, sig, d, todays[sym][0], equity, tripped)
                if why:
                    self.skips[why] += 1
                else:
                    self.skips["ENTERED"] += 1

            # 3. intraday exits (incl. positions opened this morning)
            for sym in list(self.positions):
                b = todays.get(sym)
                if b is None:
                    continue
                self.last_px[sym] = b[3]
                r = execution.intraday_step(self.positions[sym], b[1], b[2], b[3], d)
                if r:
                    self.close(sym, r[0], r[1], d)

            # 4. mark to market
            equity, invested = self.mark(d)
            self.peak = max(self.peak, equity)
            eq[pd.Timestamp(d)] = equity
            inv[pd.Timestamp(d)] = invested

            # 5. today's signals become orders for each symbol's next bar
            for sig in self.signals_by_day.get(d, []):
                if is_entry(sig, self.cfg.signal):
                    self.pending[sig["symbol"]] = (sig, d)

        if self.days:
            d = self.days[-1]
            for sym in list(self.positions):
                px = self.last_px.get(sym) or _last_close(self.bars, sym, d) or self.positions[sym]["entry_price"]
                self.close(sym, "END_OF_WINDOW", px, d)
            eq[pd.Timestamp(d)] = self.cash
            inv[pd.Timestamp(d)] = 0.0

        return SimResult(pd.Series(eq, dtype=float).sort_index(),
                         pd.Series(inv, dtype=float).sort_index(),
                         self.trades, self.skips, self.breaker_days, self.orders,
                         self.notional, self.fees, self.breaker_trips, self.breaker_resumes)


def simulate(days, signals_by_day, bars, fx: FX, cfg: SimConfig) -> SimResult:
    return Simulator(days, signals_by_day, bars, fx, cfg).run()
