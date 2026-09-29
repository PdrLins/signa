"""Pre-filter ranks by trend quality, not today's move."""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("DEBUG", "true")

from app.scanners.prefilter import prefilter_candidates, trend_quality_score


def _row(**kw):
    base = {"price": 50.0, "avg_volume": 1_000_000, "day_change": 0.0}
    base.update(kw)
    return base


def test_quiet_uptrend_beats_one_day_spike():
    data = {
        "SPIKE": _row(day_change=0.12, vs_sma50=-0.05, vs_sma200=-0.10,
                      ret_3m_ex_1w=-0.15, rsi14=62),
        "TREND": _row(day_change=0.002, vs_sma50=0.04, vs_sma200=0.15,
                      sma50_above_sma200=True, ret_3m_ex_1w=0.18, rsi14=58),
    }
    assert prefilter_candidates(data)[0] == "TREND"


def test_quiet_names_no_longer_excluded_by_day_change():
    data = {"QUIET": _row(day_change=0.001, vs_sma50=0.02, vs_sma200=0.05)}
    assert prefilter_candidates(data) == ["QUIET"]


def test_liquidity_gate_still_applies():
    data = {"THIN": _row(avg_volume=10_000), "PENNY": _row(price=0.5)}
    assert prefilter_candidates(data) == []


def test_overbought_penalised():
    good = trend_quality_score(_row(vs_sma50=0.05, vs_sma200=0.1, rsi14=60))
    hot = trend_quality_score(_row(vs_sma50=0.05, vs_sma200=0.1, rsi14=82))
    assert good > hot
