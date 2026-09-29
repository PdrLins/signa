"""Technical indicator calculations using pandas-ta.

Computes RSI, MACD, Bollinger Bands, SMA crossovers, volume trends, and ATR.
"""

from datetime import datetime

import pandas as pd
import pandas_ta as ta
from loguru import logger


def _bar_date(ts, exchange: str | None):
    """Calendar date of a daily bar in the exchange's reference zone."""
    ts = pd.Timestamp(ts)
    if ts.tzinfo is not None:
        tz = "UTC" if exchange == "CRYPTO" else "America/New_York"
        ts = ts.tz_convert(tz)
    return ts.date()


def drop_incomplete_bar(
    df: pd.DataFrame, exchange: str | None, now: datetime | None = None,
) -> tuple[pd.DataFrame, bool]:
    """Drop the still-forming daily bar, if any.

    During the session yfinance's last daily row is today's partial bar:
    its volume is a fraction of a full day (volume z-score reads as
    "suspiciously low" every morning) and its close is a live tick that
    moves RSI/MACD intraday. Indicators must be computed on completed
    bars only. Crypto uses completed UTC daily bars.

    Returns (df_without_partial_bar, dropped).
    """
    if df is None or df.empty or exchange is None:
        return df, False
    from app.core.market_calendar import is_daily_bar_complete
    last_date = _bar_date(df.index[-1], exchange)
    if is_daily_bar_complete(exchange, last_date, now):
        return df, False
    return df.iloc[:-1], True


def compute_indicators(
    df: pd.DataFrame,
    exchange: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Compute all technical indicators from an OHLCV DataFrame.

    Args:
        df: DataFrame with Open, High, Low, Close, Volume columns.
        exchange: 'NYSE' | 'NASDAQ' | 'TSX' | 'CRYPTO'. When given, the
            in-progress daily bar is dropped before computing indicators
            (see `drop_incomplete_bar`). `current_price` still reports
            the live last price; every indicator uses completed bars.
            None keeps the legacy behaviour (use every row as-is).
        now: Clock override for tests.

    Returns:
        Dict with all computed indicator values.
    """
    if df is None or df.empty:
        logger.warning("Not enough data for technical analysis")
        return {}

    live_price = float(df["Close"].iloc[-1])
    df, dropped = drop_incomplete_bar(df, exchange, now)

    if df.empty or len(df) < 14:
        logger.warning("Not enough data for technical analysis")
        return {}

    try:
        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        volume = df["Volume"]
        # Last COMPLETED close — every indicator below is anchored here.
        current_price = float(close.iloc[-1])

        result = {
            "current_price": round(live_price, 2),
            "last_close": round(current_price, 2),
            "incomplete_bar_dropped": dropped,
        }

        # RSI (14-period)
        rsi_series = ta.rsi(close, length=14)
        if rsi_series is not None and not rsi_series.empty:
            result["rsi"] = round(float(rsi_series.iloc[-1]), 2)

        # MACD (12, 26, 9)
        macd_df = ta.macd(close, fast=12, slow=26, signal=9)
        macd_hist_raw = None
        if macd_df is not None and not macd_df.empty:
            if pd.notna(macd_df.iloc[-1, 2]):
                macd_hist_raw = float(macd_df.iloc[-1, 2])
            result["macd"] = round(float(macd_df.iloc[-1, 0]), 4)
            result["macd_signal"] = round(float(macd_df.iloc[-1, 1]), 4)
            result["macd_histogram"] = round(float(macd_df.iloc[-1, 2]), 4)

        # Bollinger Bands (20, 2)
        bb_df = ta.bbands(close, length=20, std=2)
        if bb_df is not None and not bb_df.empty:
            bb_lower = float(bb_df.iloc[-1, 0])
            bb_middle = float(bb_df.iloc[-1, 1])
            bb_upper = float(bb_df.iloc[-1, 2])
            result["bb_lower"] = round(bb_lower, 2)
            result["bb_middle"] = round(bb_middle, 2)
            result["bb_upper"] = round(bb_upper, 2)
            if bb_upper != bb_lower:
                bb_pos = (current_price - bb_lower) / (bb_upper - bb_lower)
                result["bb_position"] = round(max(0.0, min(1.0, bb_pos)), 4)

        # SMA 50 & 200
        sma_50_series = ta.sma(close, length=50)
        sma_200_series = ta.sma(close, length=200)

        if sma_50_series is not None and not sma_50_series.empty and pd.notna(sma_50_series.iloc[-1]):
            result["sma_50"] = round(float(sma_50_series.iloc[-1]), 2)
        if sma_200_series is not None and not sma_200_series.empty and pd.notna(sma_200_series.iloc[-1]):
            result["sma_200"] = round(float(sma_200_series.iloc[-1]), 2)

        # SMA Cross detection
        result["sma_cross"] = "none"
        if "sma_50" in result and "sma_200" in result:
            if sma_50_series is not None and sma_200_series is not None and len(sma_50_series) >= 2 and len(sma_200_series) >= 2:
                prev_50 = sma_50_series.iloc[-2] if pd.notna(sma_50_series.iloc[-2]) else None
                prev_200 = sma_200_series.iloc[-2] if pd.notna(sma_200_series.iloc[-2]) else None
                if prev_50 is not None and prev_200 is not None:
                    if prev_50 < prev_200 and result["sma_50"] > result["sma_200"]:
                        result["sma_cross"] = "golden_cross"
                    elif prev_50 > prev_200 and result["sma_50"] < result["sma_200"]:
                        result["sma_cross"] = "death_cross"

        # Volume analysis. z-score is the last completed bar vs the PRIOR
        # 20 completed bars (the blocker doc's "20-day average"); the old
        # version compared against a 1-year mean that included the bar
        # itself.
        if not volume.empty:
            result["volume_avg"] = round(float(volume.mean()), 0)
            baseline = volume.iloc[-21:-1] if len(volume) >= 21 else volume.iloc[:-1]
            if len(baseline) >= 5 and baseline.std() > 0:
                result["volume_zscore"] = round(
                    float((volume.iloc[-1] - baseline.mean()) / baseline.std()), 2
                )

        # ATR (14-period)
        atr_series = ta.atr(high, low, close, length=14)
        if atr_series is not None and not atr_series.empty and pd.notna(atr_series.iloc[-1]):
            atr_raw = float(atr_series.iloc[-1])
            result["atr"] = round(atr_raw, 4)
            # Price-invariant MACD histogram (ATR units). A raw histogram
            # of 2.0 means very different things on a $10 and a $1000 name.
            # Uses unrounded values so sub-cent assets don't round to 0.
            if macd_hist_raw is not None and atr_raw > 0:
                result["macd_hist_atr"] = round(macd_hist_raw / atr_raw, 4)

        # ADX (14-period) — trend strength indicator
        # ADX > 25 = strong trend (favor momentum), ADX < 20 = range-bound (favor mean reversion)
        adx_series = ta.adx(high, low, close, length=14)
        if adx_series is not None and not adx_series.empty:
            adx_col = [c for c in adx_series.columns if 'ADX' in c and 'DM' not in c]
            if adx_col:
                adx_val = adx_series[adx_col[0]].iloc[-1]
                if pd.notna(adx_val):
                    result["adx"] = round(float(adx_val), 2)

        # vs SMA percentages
        if "sma_50" in result and result["sma_50"] > 0:
            result["vs_sma50"] = round(((current_price - result["sma_50"]) / result["sma_50"]) * 100, 2)
        if "sma_200" in result and result["sma_200"] > 0:
            result["vs_sma200"] = round(((current_price - result["sma_200"]) / result["sma_200"]) * 100, 2)

        # 1-day return (%). When the partial bar was dropped this is the
        # live move vs the last completed close (i.e. today's change so
        # far); otherwise last completed close vs the one before. Display /
        # prompt context only — not used in scoring.
        if dropped and current_price > 0:
            result["momentum_1d"] = round((live_price - current_price) / current_price * 100, 2)
        elif len(close) >= 2 and float(close.iloc[-2]) > 0:
            result["momentum_1d"] = round((current_price - float(close.iloc[-2])) / float(close.iloc[-2]) * 100, 2)

        # Momentum (5-day and 20-day percentage change)
        if len(close) >= 6:
            result["momentum_5d"] = round(((current_price - float(close.iloc[-6])) / float(close.iloc[-6])) * 100, 2)
        if len(close) >= 21:
            result["momentum_20d"] = round(((current_price - float(close.iloc[-21])) / float(close.iloc[-21])) * 100, 2)

        # Multi-period momentum for factor scoring
        if len(close) >= 63:  # ~3 months
            result["momentum_3m"] = round(((current_price - float(close.iloc[-63])) / float(close.iloc[-63])) * 100, 2)
        if len(close) >= 126:  # ~6 months
            result["momentum_6m"] = round(((current_price - float(close.iloc[-126])) / float(close.iloc[-126])) * 100, 2)

        # Volume ratio (current vs 20-day average)
        if not volume.empty and len(volume) >= 21:
            vol_avg_20 = float(volume.iloc[-21:-1].mean())
            if vol_avg_20 > 0:
                result["volume_ratio"] = round(float(volume.iloc[-1]) / vol_avg_20, 2)

        # Price change 5-day (for PEAD detection)
        if len(close) >= 6:
            result["price_change_5d"] = round(((current_price - float(close.iloc[-6])) / float(close.iloc[-6])), 4)

        return result

    except Exception as e:
        logger.error(f"Technical analysis failed: {e}")
        return {}


def compute_momentum_score(indicators: dict) -> float:
    """Compute a simple momentum score (0-100) from technical indicators."""
    score = 50.0

    rsi = indicators.get("rsi")
    if rsi is not None:
        if rsi > 70:
            score += 10
        elif rsi > 50:
            score += 5
        elif rsi < 30:
            score -= 10
        elif rsi < 50:
            score -= 5

    macd_hist = indicators.get("macd_histogram")
    if macd_hist is not None:
        if macd_hist > 0:
            score += 10
        else:
            score -= 10

    bb_pos = indicators.get("bb_position")
    if bb_pos is not None:
        if bb_pos > 0.8:
            score += 5
        elif bb_pos < 0.2:
            score -= 5

    sma_cross = indicators.get("sma_cross")
    if sma_cross == "golden_cross":
        score += 15
    elif sma_cross == "death_cross":
        score -= 15

    vol_z = indicators.get("volume_zscore")
    if vol_z is not None:
        if vol_z > 2:
            score += 10
        elif vol_z > 1:
            score += 5

    return max(0, min(100, score))
