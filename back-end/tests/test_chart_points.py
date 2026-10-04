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


def test_chart_is_fetched_once_for_everyone(monkeypatch):
    import asyncio

    from app.api.v1 import tickers

    tickers.clear_cache()
    calls = []
    idx = pd.date_range("2026-09-01", periods=3, freq="D")
    df = pd.DataFrame({"Open": [0.5, 2, 3], "High": [0.5, 2, 3], "Low": [0.5, 2, 3], "Close": [0.12345, 2, 3],
                       "Volume": [1, 1, 1]}, index=idx)

    def history(self, **k):
        calls.append(1)
        return df
    monkeypatch.setattr("yfinance.Ticker", lambda _t: type("T", (), {"history": history})())

    async def views():
        return await asyncio.gather(*[tickers.get_ticker_chart("BTC-USD", "3mo", {}) for _ in range(5)])
    bodies = asyncio.run(views())
    assert calls == [1] and all(b["count"] == 3 for b in bodies)
    assert bodies[0]["data_points"][0]["close"] == 0.1235      # cheap prices keep 4 decimals
    tickers.clear_cache()


def test_no_data_is_remembered(monkeypatch):
    import asyncio

    from fastapi import HTTPException

    from app.api.v1 import tickers

    tickers.clear_cache()
    calls = []

    def history(self, **k):
        calls.append(1)
        return pd.DataFrame()
    monkeypatch.setattr("yfinance.Ticker", lambda _t: type("T", (), {"history": history})())
    for _ in range(2):
        try:
            asyncio.run(tickers.get_ticker_chart("NOPE", "1y", {}))
            raise AssertionError("expected 404")
        except HTTPException as e:
            assert e.status_code == 404
    assert calls == [1]
    tickers.clear_cache()


def test_pence_info_becomes_pounds():
    from app.market.currency import normalize_info
    info, k = normalize_info("VOD.L", {"currency": "GBp", "regularMarketPrice": 72.5, "dividendRate": 7.8,
                                       "marketCap": 1e10, "longName": "Vodafone"})
    assert k == 0.01 and info["currency"] == "GBP"
    assert info["regularMarketPrice"] == 0.725 and abs(info["dividendRate"] - 0.078) < 1e-12
    assert info["marketCap"] == 1e10 and info["longName"] == "Vodafone"
    info, k = normalize_info("VUSA.L", {"currency": "GBP", "regularMarketPrice": 80.0})   # ETF priced in pounds
    assert k == 1.0 and info["regularMarketPrice"] == 80.0
