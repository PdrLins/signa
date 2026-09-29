"""Point-in-time macro snapshot for day t (bars up to and including t).

Reproduces the fields the live `macro_scanner.get_macro_snapshot` feeds to
`regime.get_market_regime` and `compute_score`, computed ONLY from data
available at the close of t:

  vix            ^VIX close on t (last available <= t)
  vix_30d_high   max ^VIX close over the 30 calendar days ending t
  spy_vs_sma50   % distance of SPY's close from its 50-bar SMA (1y window)
  spy_vs_sma200  % distance from its 200-bar SMA
  environment    LIVE `classify_macro_environment` on the above

NOT available historically here (absent → the live code's neutral path):
FRED series (fed funds, 10Y, CPI, unemployment, yield curve, credit
spread), CNN Fear & Greed, VIX term structure, intermarket signals. With
only VIX the live classifier can never reach "hostile" (needs >= 3
hostile signals), so the hostile-macro blocker is inactive in the backtest.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from backtest import live


class MacroSeries:
    def __init__(self, spy: pd.DataFrame | None, vix: pd.DataFrame | None):
        self.spy_close = spy["Close"] if spy is not None and not spy.empty else pd.Series(dtype=float)
        self.vix_close = vix["Close"] if vix is not None and not vix.empty else pd.Series(dtype=float)
        self._memo: dict[date, dict] = {}

    def at(self, t: date) -> dict:
        if t in self._memo:
            return self._memo[t]
        ts = pd.Timestamp(t)
        m: dict = {}
        vix = self.vix_close[self.vix_close.index <= ts]
        if not vix.empty:
            m["vix"] = round(float(vix.iloc[-1]), 2)
            win = vix[vix.index > ts - pd.Timedelta(days=30)]
            if not win.empty:
                m["vix_30d_high"] = round(float(win.max()), 2)
        spy = self.spy_close[(self.spy_close.index <= ts)
                             & (self.spy_close.index > ts - pd.Timedelta(days=366))]
        if not spy.empty:
            last = float(spy.iloc[-1])
            if len(spy) >= 50:
                s50 = float(spy.iloc[-50:].mean())
                if s50 > 0:
                    m["spy_vs_sma50"] = round((last - s50) / s50 * 100, 2)
            if len(spy) >= 200:
                s200 = float(spy.iloc[-200:].mean())
                if s200 > 0:
                    m["spy_vs_sma200"] = round((last - s200) / s200 * 100, 2)
        m["environment"] = live.macro_environment(m)
        m["regime"] = live.market_regime(m)
        self._memo[t] = m
        return m


def warmup_start(start: date, days: int = 420) -> date:
    return start - timedelta(days=days)
