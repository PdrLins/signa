"""Technical indicator computation for backtest engine."""

import pandas as pd
import pandas_ta as ta
from loguru import logger


def compute_indicators(df: pd.DataFrame, as_of_date: str) -> dict | None:
    """Compute technical indicators as of a specific date.

    Slices data up to as_of_date to prevent look-ahead bias.
    Returns None if insufficient data or critical values are NaN.
    """
    df = df[df.index <= pd.Timestamp(as_of_date)]

    if len(df) < 50:
        logger.debug(f"Insufficient data for indicators: {len(df)} rows (need 50)")
        return None

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]

    # RSI 14
    rsi_s = ta.rsi(close, length=14)
    rsi = _last(rsi_s)

    # MACD (12, 26, 9)
    macd_df = ta.macd(close, fast=12, slow=26, signal=9)
    macd_line = _last(macd_df.iloc[:, 0]) if macd_df is not None else None
    macd_signal = _last(macd_df.iloc[:, 1]) if macd_df is not None else None
    macd_hist = _last(macd_df.iloc[:, 2]) if macd_df is not None else None

    # Bollinger Bands 20
    bb_df = ta.bbands(close, length=20, std=2)
    bb_lower = _last(bb_df.iloc[:, 0]) if bb_df is not None else None
    bb_mid = _last(bb_df.iloc[:, 1]) if bb_df is not None else None
    bb_upper = _last(bb_df.iloc[:, 2]) if bb_df is not None else None

    bb_pct = None
    if bb_upper is not None and bb_lower is not None and bb_upper != bb_lower:
        current_close = float(close.iloc[-1])
        bb_pct = (current_close - bb_lower) / (bb_upper - bb_lower)
        bb_pct = max(0.0, min(1.0, bb_pct))

    # SMA 50 & 200
    sma50_s = ta.sma(close, length=50)
    sma200_s = ta.sma(close, length=200)
    sma50 = _last(sma50_s)
    sma200 = _last(sma200_s)

    # Current close
    current_close = float(close.iloc[-1])

    # vs SMA (% above/below)
    vs_sma50 = ((current_close - sma50) / sma50) if sma50 else None
    vs_sma200 = ((current_close - sma200) / sma200) if sma200 else None

    # Volume ratio: current / 20-day avg
    vol_avg_20 = volume.rolling(20).mean().iloc[-1]
    current_vol = float(volume.iloc[-1])
    volume_ratio = (current_vol / vol_avg_20) if pd.notna(vol_avg_20) and vol_avg_20 > 0 else None

    # Momentum
    momentum_5d = ((current_close / float(close.iloc[-6])) - 1) if len(close) >= 6 else None
    momentum_20d = ((current_close / float(close.iloc[-21])) - 1) if len(close) >= 21 else None

    # ATR 14
    atr_s = ta.atr(high, low, close, length=14)
    atr = _last(atr_s)

    # ADX 14 (trend strength)
    adx_df = ta.adx(high, low, close, length=14)
    adx = None
    if adx_df is not None and not adx_df.empty:
        adx_col = [c for c in adx_df.columns if 'ADX' in c and 'DM' not in c]
        if adx_col:
            adx = _last(adx_df[adx_col[0]])

    # Multi-period momentum (3m, 6m)
    momentum_3m = ((current_close / float(close.iloc[-63])) - 1) if len(close) >= 63 else None
    momentum_6m = ((current_close / float(close.iloc[-126])) - 1) if len(close) >= 126 else None

    # Validate critical values
    if rsi is None or macd_line is None or sma50 is None:
        logger.debug(f"Critical indicator is NaN (rsi={rsi}, macd={macd_line}, sma50={sma50})")
        return None

    return {
        "rsi": _round(rsi),
        "macd_line": _round(macd_line),
        "macd_signal": _round(macd_signal),
        "macd_hist": _round(macd_hist),
        "bb_upper": _round(bb_upper),
        "bb_mid": _round(bb_mid),
        "bb_lower": _round(bb_lower),
        "bb_pct": _round(bb_pct),
        "sma50": _round(sma50),
        "sma200": _round(sma200),
        "close": _round(current_close),
        "vs_sma50": _round(vs_sma50),
        "vs_sma200": _round(vs_sma200),
        "volume_ratio": _round(volume_ratio),
        "momentum_5d": _round(momentum_5d),
        "momentum_20d": _round(momentum_20d),
        "momentum_3m": _round(momentum_3m),
        "momentum_6m": _round(momentum_6m),
        "adx": _round(adx),
        "atr": _round(atr),
    }


def _last(series: pd.Series | None) -> float | None:
    """Get the last non-NaN value from a series as a Python float."""
    if series is None or series.empty:
        return None
    val = series.iloc[-1]
    if pd.isna(val):
        return None
    return float(val)


def _round(val: float | None) -> float | None:
    """Round to 4 decimal places, or return None."""
    if val is None:
        return None
    return round(float(val), 4)
