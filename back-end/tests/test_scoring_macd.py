"""MACD histogram scoring must be price-invariant.

Regression: `macd_hist > 2.0` was in PRICE units — a $1000 stock got the
"surger" bonus on noise while a $20 stock never could.
"""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("DEBUG", "true")

import numpy as np
import pandas as pd

from app.ai.signal_engine import _score_technical_momentum, compute_score
from app.scanners.indicators import compute_indicators


def _frame(scale: float, n: int = 260) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    rets = rng.normal(0.001, 0.015, n)
    close = 100 * np.cumprod(1 + rets)
    # strong recent up-leg so the histogram is clearly positive
    close[-15:] = close[-16] * np.cumprod(1 + np.full(15, 0.012))
    close = close * scale
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "Open": close * 0.995, "High": close * 1.01, "Low": close * 0.99,
        "Close": close, "Volume": rng.integers(1_000_000, 2_000_000, n).astype(float),
    }, index=idx)


def test_indicator_normalised_hist_is_scale_invariant():
    a = compute_indicators(_frame(1.0))
    b = compute_indicators(_frame(50.0))
    assert abs(a["macd_hist_atr"] - b["macd_hist_atr"]) < 1e-3
    # raw histogram is NOT invariant (the old bug)
    assert abs(b["macd_histogram"] / a["macd_histogram"] - 50.0) < 0.5


def test_momentum_score_is_scale_invariant():
    a = compute_indicators(_frame(0.2))
    b = compute_indicators(_frame(20.0))
    assert _score_technical_momentum(a) == _score_technical_momentum(b)
    sa, _ = compute_score(a, {}, {}, {}, {}, "HIGH_RISK")
    sb, _ = compute_score(b, {}, {}, {}, {}, "HIGH_RISK")
    assert sa == sb


def test_large_raw_hist_small_in_atr_units_is_not_strong():
    # $900 stock: raw hist 3.0 (> old 2.0 bar) but only 0.1 ATR.
    td = {"macd_histogram": 3.0, "atr": 30.0}
    weak = _score_technical_momentum(td)
    td_strong = {"macd_histogram": 3.0, "atr": 6.0}  # 0.5 ATR
    assert _score_technical_momentum(td_strong) - weak == 7  # +15 vs +8


def test_small_raw_hist_can_be_strong_for_cheap_stock():
    # $10 stock: raw hist 0.3 (< old 2.0 bar) but 0.6 ATR -> strong.
    td = {"macd_histogram": 0.3, "atr": 0.5}
    assert _score_technical_momentum(td) == 65.0  # 50 + 15


def test_negative_hist_penalised_regardless_of_scale():
    assert _score_technical_momentum({"macd_histogram": -0.01, "atr": 1.0}) == 40.0
