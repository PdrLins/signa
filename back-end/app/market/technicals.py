"""Technical values for the Signa checks (plain pandas, no pandas-ta).

compute_indicators -> {"current_price", "last_close", "incomplete_bar_dropped",
"rsi", "sma_50", "sma_200", "volume_avg", "volume_avg_20",
"dollar_volume_avg_20"} from a daily OHLCV DataFrame. RSI(14) uses Wilder
smoothing, the same values pandas-ta gives. The still-forming daily bar is
dropped first (when the exchange is known), so the checks never move with
intraday ticks.

technical_filter -> (passed, reasons): the rule set behind the uptrend,
not_overheated and liquidity checks. Thresholds are settings
(tech_filter_*). Pure.
"""

from __future__ import annotations

import math
from datetime import datetime

import pandas as pd
from loguru import logger

from app.core.config import settings

RSI_LENGTH = 14


def _num(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _bar_date(ts, exchange: str | None):
    """Calendar date of a daily bar. Yahoo stamps a stock's daily bar at
    midnight in its exchange's own zone (Tokyo, São Paulo, New York ...), so
    its own date is the session date; converting to New York would move Asian
    bars to the day before. Crypto bars are UTC days."""
    ts = pd.Timestamp(ts)
    if ts.tzinfo is not None and exchange == "CRYPTO":
        ts = ts.tz_convert("UTC")
    return ts.date()


def drop_incomplete_bar(df: pd.DataFrame, exchange: str | None,
                        now: datetime | None = None) -> tuple[pd.DataFrame, bool]:
    """(df without the still-forming daily bar, dropped?)."""
    if df is None or df.empty or exchange is None:
        return df, False
    from app.core.market_calendar import is_daily_bar_complete
    if is_daily_bar_complete(exchange, _bar_date(df.index[-1], exchange), now):
        return df, False
    return df.iloc[:-1], True


def rsi(close: pd.Series, length: int = RSI_LENGTH) -> float | None:
    """Wilder RSI of the last bar (None with fewer than length + 1 closes)."""
    if close is None or len(close) <= length:
        return None
    diff = close.diff()
    gain = diff.clip(lower=0).ewm(alpha=1 / length, min_periods=length).mean()
    loss = (-diff.clip(upper=0)).ewm(alpha=1 / length, min_periods=length).mean()
    g, lo = _num(gain.iloc[-1]), _num(loss.iloc[-1])
    if g is None or lo is None:
        return None
    if lo == 0:
        return 100.0 if g > 0 else 50.0
    return 100 - 100 / (1 + g / lo)


def _sma(close: pd.Series, length: int) -> float | None:
    if len(close) < length:
        return None
    return _num(close.iloc[-length:].mean())


def compute_indicators(df: pd.DataFrame, exchange: str | None = None,
                       now: datetime | None = None) -> dict:
    """Values used by the Signa checks ({} without enough data). Never raises."""
    if df is None or df.empty:
        return {}
    try:
        live_price = float(df["Close"].iloc[-1])
        df, dropped = drop_incomplete_bar(df, exchange, now)
        if df.empty or len(df) < RSI_LENGTH:
            return {}
        close = df["Close"].astype(float)
        volume = df["Volume"].astype(float) if "Volume" in df else pd.Series(dtype=float)
        last = float(close.iloc[-1])
        out: dict = {"current_price": round(live_price, 2), "last_close": round(last, 2),
                     "incomplete_bar_dropped": dropped}
        r = rsi(close)
        if r is not None:
            out["rsi"] = round(r, 2)
        for n, key in ((50, "sma_50"), (200, "sma_200")):
            v = _sma(close, n)
            if v is not None:
                out[key] = round(v, 2)
        if not volume.empty:
            v20 = volume.iloc[-20:]
            out["volume_avg"] = round(float(volume.mean()), 0)
            out["volume_avg_20"] = round(float(v20.mean()), 0)
            out["dollar_volume_avg_20"] = round(float((close.iloc[-20:] * v20).mean()), 0)
        return out
    except Exception as e:
        logger.warning(f"technicals: compute failed: {e}")
        return {}


def technical_filter(technical_data: dict | None, fundamental_data: dict | None = None,
                     asset_class: str | None = None) -> tuple[bool, list[str]]:
    """(passed, reasons). Reasons, in order:
      trend      price > SMA200 and SMA50 > SMA200 ("insufficient_history"
                 when a value is missing, else "below_sma200",
                 "sma50_below_sma200")
      extension  RSI(14) <= tech_filter_max_rsi ("rsi_overbought"), price
                 <= tech_filter_max_ext_sma50_pct % above SMA50
                 ("overextended_vs_sma50")
      liquidity  20-session average dollar volume >= tech_filter_min_dollar_volume
                 (crypto: tech_filter_min_dollar_volume_crypto; Yahoo crypto
                 volume is already USD) -> "no_liquidity_data" / "low_liquidity"
    """
    t = technical_data or {}
    f = fundamental_data or {}
    reasons: list[str] = []

    price = _num(t.get("last_close")) or _num(t.get("current_price"))
    sma50, sma200 = _num(t.get("sma_50")), _num(t.get("sma_200"))
    if not price or not sma50 or not sma200:
        reasons.append("insufficient_history")
    else:
        if price <= sma200:
            reasons.append("below_sma200")
        if sma50 <= sma200:
            reasons.append("sma50_below_sma200")

    r = _num(t.get("rsi"))
    if r is not None and r > settings.tech_filter_max_rsi:
        reasons.append("rsi_overbought")
    if price and sma50 and (price / sma50 - 1.0) * 100.0 > settings.tech_filter_max_ext_sma50_pct:
        reasons.append("overextended_vs_sma50")

    is_crypto = ((asset_class or "").upper() == "CRYPTO"
                 or (f.get("quote_type") or "").upper() == "CRYPTOCURRENCY")
    if is_crypto:
        dollar_vol = _num(t.get("volume_avg_20")) or _num(t.get("volume_avg"))
    else:
        dollar_vol = _num(t.get("dollar_volume_avg_20"))
        if dollar_vol is None and price:
            shares = _num(t.get("volume_avg_20")) or _num(t.get("volume_avg"))
            dollar_vol = shares * price if shares is not None else None
    floor = (settings.tech_filter_min_dollar_volume_crypto if is_crypto
             else settings.tech_filter_min_dollar_volume)
    if dollar_vol is None:
        reasons.append("no_liquidity_data")
    elif dollar_vol < floor:
        reasons.append("low_liquidity")

    return (not reasons), reasons
