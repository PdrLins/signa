"""app/market/earnings.py: next report date (stock page, Coming up, earnings_soon)."""

import asyncio
from datetime import date

import pandas as pd

from app.core.market_calendar import trading_days_until
from app.market import earnings
from app.market.earnings import build_earnings_context


def _df():
    idx = pd.DatetimeIndex(pd.to_datetime([
        "2026-10-29 16:00", "2026-07-30 16:00", "2026-04-30 16:00",
    ])).tz_localize("America/New_York")
    return pd.DataFrame({
        "EPS Estimate": [1.9, 1.7, 1.6],
        "Reported EPS": [float("nan"), 1.85, 1.55],
        "Surprise(%)": [float("nan"), 8.82, -3.1],
    }, index=idx)


def test_parses_last_surprise_and_next_date():
    ctx = build_earnings_context(None, _df(), today=date(2026, 9, 28))
    assert ctx["next_earnings_date"] == "2026-10-29"
    assert ctx["days_since_earnings"] == (date(2026, 9, 28) - date(2026, 7, 30)).days
    assert ctx["earnings_surprise_pct"] == 8.82


def test_calendar_preferred_for_next_date():
    cal = {"Earnings Date": [date(2026, 10, 27), date(2026, 10, 31)]}
    assert build_earnings_context(cal, _df(), today=date(2026, 9, 28))["next_earnings_date"] == "2026-10-27"


def test_empty_inputs():
    assert build_earnings_context(None, None, today=date(2026, 9, 28))["next_earnings_date"] is None


def test_trading_days():
    assert trading_days_until("NYSE", date(2026, 10, 6), date(2026, 10, 2)) == 2      # weekend
    assert trading_days_until("NYSE", date(2026, 11, 27), date(2026, 11, 25)) == 1    # Thanksgiving
    assert trading_days_until("NYSE", date(2026, 1, 1), date(2026, 2, 1)) is None


def test_earnings_info_stocks_only(monkeypatch):
    async def ctx(symbol):
        return {"next_earnings_date": "2026-10-06"}
    monkeypatch.setattr(earnings, "get_earnings_context", ctx)
    out = asyncio.run(earnings.earnings_info({"symbol": "MSFT", "asset_type": "STOCK"}, date(2026, 10, 2)))
    assert out == {"date": "2026-10-06", "days": 4, "trading_days": 2}
    assert asyncio.run(earnings.earnings_info({"symbol": "XEQT.TO", "asset_type": "ETF"})) is None
    assert asyncio.run(earnings.earnings_info({"symbol": "BTC-USD"})) is None
