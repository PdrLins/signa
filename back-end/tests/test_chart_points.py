"""GET /tickers/{ticker}/chart: bars with NaN prices are skipped (they made
the response fail JSON encoding with a 500)."""

import math

import pandas as pd

from app.api.v1.tickers import chart_points


def test_nan_bars_are_skipped_and_volume_defaults():
    idx = pd.date_range("2026-09-28", periods=3, freq="D")
    df = pd.DataFrame({
        "Open": [700.0, math.nan, 710.0], "High": [705.0, math.nan, 715.0],
        "Low": [695.0, math.nan, 705.0], "Close": [702.0, math.nan, 712.5],
        "Volume": [1000, 2000, math.nan],
    }, index=idx)
    pts = chart_points(df)
    assert [p["close"] for p in pts] == [702.0, 712.5]
    assert pts[1]["volume"] == 0
    import json
    json.dumps(pts)   # must be valid JSON
