"""Indicators must ignore the still-forming daily bar.

Regression: during market hours yfinance's last row is today's partial
bar — volume z-score read "suspiciously low" every morning and RSI/MACD
moved with live ticks.
"""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("DEBUG", "true")

from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from app.core.market_calendar import is_daily_bar_complete
from app.scanners.indicators import compute_indicators, drop_incomplete_bar

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def _equity_df(last_day: str, n: int = 80, last_volume: float = 1_000_000):
    idx = pd.bdate_range(end=last_day, periods=n).tz_localize(ET)
    close = np.linspace(100, 120, n)
    rng = np.random.default_rng(3)
    vol = rng.normal(1_000_000.0, 100_000.0, n)
    vol[-1] = last_volume
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": vol}, index=idx)


def test_drops_today_bar_during_session():
    df = _equity_df("2026-09-28")  # Monday
    now = datetime(2026, 9, 28, 11, 0, tzinfo=ET)
    out, dropped = drop_incomplete_bar(df, "NYSE", now)
    assert dropped and len(out) == len(df) - 1


def test_keeps_today_bar_after_close():
    df = _equity_df("2026-09-28")
    now = datetime(2026, 9, 28, 16, 30, tzinfo=ET)
    _, dropped = drop_incomplete_bar(df, "NYSE", now)
    assert not dropped


def test_keeps_yesterday_bar_premarket():
    df = _equity_df("2026-09-25")  # Friday
    now = datetime(2026, 9, 28, 8, 0, tzinfo=ET)
    _, dropped = drop_incomplete_bar(df, "NYSE", now)
    assert not dropped


def test_partial_volume_does_not_trigger_low_volume_zscore():
    # Mid-morning: today's bar has 15% of a normal day's volume.
    df = _equity_df("2026-09-28", last_volume=150_000)
    now = datetime(2026, 9, 28, 10, 30, tzinfo=ET)
    legacy = compute_indicators(df)                     # old behaviour
    fixed = compute_indicators(df, exchange="NYSE", now=now)
    assert legacy["volume_zscore"] < -2.0          # false "suspicious volume"
    assert -2.0 < fixed["volume_zscore"] < 2.0
    assert fixed["incomplete_bar_dropped"] is True
    # Live price still reported
    assert fixed["current_price"] == round(float(df["Close"].iloc[-1]), 2)


def test_crypto_uses_completed_utc_bars():
    assert is_daily_bar_complete("CRYPTO", date(2026, 9, 27), datetime(2026, 9, 28, 1, 0, tzinfo=UTC))
    assert not is_daily_bar_complete("CRYPTO", date(2026, 9, 28), datetime(2026, 9, 28, 23, 0, tzinfo=UTC))
    # 22:00 ET Sep 27 is already Sep 28 UTC -> the Sep 28 UTC bar is forming
    assert not is_daily_bar_complete("CRYPTO", date(2026, 9, 28), datetime(2026, 9, 27, 22, 0, tzinfo=ET))


def test_holiday_bar_treated_complete():
    # Thanksgiving: no session, any stray bar is not "forming".
    assert is_daily_bar_complete("NYSE", date(2026, 11, 26), datetime(2026, 11, 26, 11, 0, tzinfo=ET))
