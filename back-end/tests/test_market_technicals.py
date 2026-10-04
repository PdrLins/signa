"""app/market/technicals.py: the values and rules behind the Signa checks."""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("DEBUG", "true")

from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from app.core.config import settings
from app.core.market_calendar import is_daily_bar_complete
from app.market.technicals import compute_indicators, drop_incomplete_bar, rsi, technical_filter

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def passing_tech(price=100.0, **over) -> dict:
    """Uptrend, RSI 55, 5% above SMA50, ~$100M/day: passes every rule."""
    t = {"current_price": price, "last_close": price, "sma_50": price / 1.05, "sma_200": price / 1.20,
         "rsi": 55.0, "volume_avg": 1_000_000, "volume_avg_20": 1_000_000,
         "dollar_volume_avg_20": price * 1_000_000}
    t.update(over)
    return t


def _equity_df(last_day: str, n: int = 80, last_volume: float = 1_000_000):
    idx = pd.bdate_range(end=last_day, periods=n).tz_localize(ET)
    close = np.linspace(100, 120, n)
    rng = np.random.default_rng(3)
    vol = rng.normal(1_000_000.0, 100_000.0, n)
    vol[-1] = last_volume
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": vol}, index=idx)


def _wilder_rsi(closes: list[float], n: int = 14) -> float:
    """Textbook Wilder RSI (first average = mean of the first n moves)."""
    d = np.diff(closes)
    g, lo = np.clip(d, 0, None), np.clip(-d, 0, None)
    ag, al = g[:n].mean(), lo[:n].mean()
    for i in range(n, len(d)):
        ag = (ag * (n - 1) + g[i]) / n
        al = (al * (n - 1) + lo[i]) / n
    return 100 - 100 / (1 + ag / al)


# ---------------------------------------------------------------- filter

def test_defaults():
    assert settings.tech_filter_max_rsi == 75.0
    assert settings.tech_filter_max_ext_sma50_pct == 15.0
    assert settings.tech_filter_min_dollar_volume == 10_000_000
    assert settings.tech_filter_min_dollar_volume_crypto == 50_000_000


def test_clean_uptrend_passes():
    assert technical_filter(passing_tech(), {}, "STOCK") == (True, [])


@pytest.mark.parametrize("over,reason", [
    ({"sma_200": None}, "insufficient_history"),
    ({"sma_50": None}, "insufficient_history"),
    ({"last_close": None, "current_price": None}, "insufficient_history"),
    ({"sma_200": 101.0, "sma_50": 102.0}, "below_sma200"),
    ({"sma_50": 90.0, "sma_200": 92.0}, "sma50_below_sma200"),
    ({"rsi": 76.0}, "rsi_overbought"),
    ({"sma_50": 100 / 1.16}, "overextended_vs_sma50"),
    ({"dollar_volume_avg_20": 9_000_000}, "low_liquidity"),
    ({"dollar_volume_avg_20": None, "volume_avg_20": None, "volume_avg": None}, "no_liquidity_data"),
])
def test_each_condition_fails(over, reason):
    passed, reasons = technical_filter(passing_tech(**over), {}, "STOCK")
    assert not passed and reasons[0] == reason


def test_rsi_boundary_and_missing_rsi():
    assert technical_filter(passing_tech(rsi=75.0), {}, "STOCK")[0]
    assert technical_filter(passing_tech(rsi=None), {}, "STOCK")[0]


def test_all_failures_reported_in_order():
    t = passing_tech(sma_50=80.0, sma_200=110.0, rsi=80.0, dollar_volume_avg_20=1.0)
    assert technical_filter(t, {}, "STOCK")[1] == [
        "below_sma200", "sma50_below_sma200", "rsi_overbought", "overextended_vs_sma50", "low_liquidity"]


def test_empty_input():
    assert technical_filter(None, None, None) == (False, ["insufficient_history", "no_liquidity_data"])


def test_share_volume_fallback_times_price():
    assert technical_filter(passing_tech(dollar_volume_avg_20=None, volume_avg_20=200_000), {}, "STOCK")[0]
    assert technical_filter(passing_tech(dollar_volume_avg_20=None, volume_avg_20=50_000), {}, "STOCK")[1] \
        == ["low_liquidity"]


def test_crypto_volume_is_already_usd_with_higher_floor():
    t = passing_tech(price=0.10, volume_avg_20=60_000_000, dollar_volume_avg_20=6_000_000)
    assert technical_filter(t, {}, "CRYPTO")[0]
    assert technical_filter(passing_tech(price=0.10, volume_avg_20=40_000_000), {}, "CRYPTO")[1] == ["low_liquidity"]


def test_thresholds_are_settings(monkeypatch):
    t = passing_tech(sma_50=100 / 1.20, sma_200=100 / 1.40)
    assert not technical_filter(t, {}, "STOCK")[0]
    monkeypatch.setattr(settings, "tech_filter_max_ext_sma50_pct", 25.0)
    assert technical_filter(t, {}, "STOCK")[0]


# ---------------------------------------------------------------- indicators

def test_rsi_matches_wilder():
    rng = np.random.default_rng(7)
    closes = list(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 300))))
    assert rsi(pd.Series(closes)) == pytest.approx(_wilder_rsi(closes), abs=0.05)
    assert rsi(pd.Series(closes[:10])) is None


def test_values_on_real_bars():
    df = _equity_df("2026-09-25", n=260)
    tech = compute_indicators(df)
    close = df["Close"]
    assert tech["sma_50"] == round(float(close.iloc[-50:].mean()), 2)
    assert tech["sma_200"] == round(float(close.iloc[-200:].mean()), 2)
    assert tech["rsi"] == 100.0   # a straight line up has no losses
    assert tech["dollar_volume_avg_20"] == pytest.approx(
        float((close.iloc[-20:] * df["Volume"].iloc[-20:]).mean()), rel=1e-6)
    assert "sma_200" not in compute_indicators(df.iloc[-100:])
    assert compute_indicators(df.iloc[:5]) == {} and compute_indicators(None) == {}


# ---------------------------------------------------------------- incomplete bar

def test_drops_today_bar_during_session():
    df = _equity_df("2026-09-28")  # Monday
    out, dropped = drop_incomplete_bar(df, "NYSE", datetime(2026, 9, 28, 11, 0, tzinfo=ET))
    assert dropped and len(out) == len(df) - 1


def test_keeps_today_bar_after_close():
    df = _equity_df("2026-09-28")
    assert not drop_incomplete_bar(df, "NYSE", datetime(2026, 9, 28, 16, 30, tzinfo=ET))[1]


def test_keeps_yesterday_bar_premarket():
    df = _equity_df("2026-09-25")  # Friday
    assert not drop_incomplete_bar(df, "NYSE", datetime(2026, 9, 28, 8, 0, tzinfo=ET))[1]


def test_live_price_kept_when_partial_bar_dropped():
    df = _equity_df("2026-09-28", last_volume=150_000)
    tech = compute_indicators(df, exchange="NYSE", now=datetime(2026, 9, 28, 10, 30, tzinfo=ET))
    assert tech["incomplete_bar_dropped"] is True
    assert tech["current_price"] == round(float(df["Close"].iloc[-1]), 2)
    assert tech["last_close"] == round(float(df["Close"].iloc[-2]), 2)


def test_crypto_uses_completed_utc_bars():
    assert is_daily_bar_complete("CRYPTO", date(2026, 9, 27), datetime(2026, 9, 28, 1, 0, tzinfo=UTC))
    assert not is_daily_bar_complete("CRYPTO", date(2026, 9, 28), datetime(2026, 9, 28, 23, 0, tzinfo=UTC))
