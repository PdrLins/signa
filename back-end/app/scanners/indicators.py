"""Technical indicator calculations using pandas-ta.

Computes RSI, MACD, Bollinger Bands, SMA crossovers, volume trends, and ATR.
"""

import pandas as pd
import pandas_ta as ta
from loguru import logger


def compute_indicators(df: pd.DataFrame) -> dict:
    """Compute all technical indicators from an OHLCV DataFrame.

    Args:
        df: DataFrame with Open, High, Low, Close, Volume columns.

    Returns:
        Dict with all computed indicator values.
    """
    if df.empty or len(df) < 14:
        logger.warning("Not enough data for technical analysis")
        return {}

    try:
        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        volume = df["Volume"]
        current_price = float(close.iloc[-1])

        result = {"current_price": round(current_price, 2)}

        # RSI (14-period)
        rsi_series = ta.rsi(close, length=14)
        if rsi_series is not None and not rsi_series.empty:
            result["rsi"] = round(float(rsi_series.iloc[-1]), 2)

        # MACD (12, 26, 9)
        macd_df = ta.macd(close, fast=12, slow=26, signal=9)
        if macd_df is not None and not macd_df.empty:
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

        # Volume analysis
        if not volume.empty:
            result["volume_avg"] = round(float(volume.mean()), 0)
            if volume.std() > 0:
                result["volume_zscore"] = round(
                    float((volume.iloc[-1] - volume.mean()) / volume.std()), 2
                )

        # ATR (14-period)
        atr_series = ta.atr(high, low, close, length=14)
        if atr_series is not None and not atr_series.empty and pd.notna(atr_series.iloc[-1]):
            result["atr"] = round(float(atr_series.iloc[-1]), 4)

        # vs SMA percentages
        if "sma_50" in result and result["sma_50"] > 0:
            result["vs_sma50"] = round(((current_price - result["sma_50"]) / result["sma_50"]) * 100, 2)
        if "sma_200" in result and result["sma_200"] > 0:
            result["vs_sma200"] = round(((current_price - result["sma_200"]) / result["sma_200"]) * 100, 2)

        # Momentum (5-day and 20-day percentage change)
        if len(close) >= 6:
            result["momentum_5d"] = round(((current_price - float(close.iloc[-6])) / float(close.iloc[-6])) * 100, 2)
        if len(close) >= 21:
            result["momentum_20d"] = round(((current_price - float(close.iloc[-21])) / float(close.iloc[-21])) * 100, 2)

        # Volume ratio (current vs 20-day average)
        if not volume.empty and len(volume) >= 20:
            vol_avg_20 = float(volume.iloc[-20:].mean())
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
