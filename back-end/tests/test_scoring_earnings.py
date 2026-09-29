"""Earnings: context parsing, merge into fundamentals, entry blackout."""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("DEBUG", "true")

from datetime import date

import pandas as pd
import pytest

from app.ai.signal_engine import check_entry_blackout, compute_score
from app.core.config import settings
from app.core.market_calendar import trading_days_until
from app.services.scan_service import _merge_earnings
from app.signals.earnings import build_earnings_context


class TestBlackout:
    @pytest.mark.parametrize("td", [0, 1, 2, 3])
    def test_within_window_blocks(self, td, monkeypatch):
        monkeypatch.setattr(settings, "earnings_blackout_trading_days", 3)
        assert check_entry_blackout({"trading_days_to_next_earnings": td}) is not None

    def test_outside_window_allows(self, monkeypatch):
        monkeypatch.setattr(settings, "earnings_blackout_trading_days", 3)
        assert check_entry_blackout({"trading_days_to_next_earnings": 4}) is None

    def test_unknown_date_allows(self):
        assert check_entry_blackout({}) is None

    def test_disabled_with_zero(self, monkeypatch):
        monkeypatch.setattr(settings, "earnings_blackout_trading_days", 0)
        assert check_entry_blackout({"trading_days_to_next_earnings": 0}) is None


class TestTradingDays:
    def test_skips_weekend(self):
        # Fri 2026-10-02 -> Tue 2026-10-06 = Mon, Tue = 2 sessions
        assert trading_days_until("NYSE", date(2026, 10, 6), date(2026, 10, 2)) == 2

    def test_skips_holiday(self):
        # Wed 2026-11-25 -> Fri 2026-11-27 skips Thanksgiving
        assert trading_days_until("NYSE", date(2026, 11, 27), date(2026, 11, 25)) == 1

    def test_past_is_none(self):
        assert trading_days_until("NYSE", date(2026, 1, 1), date(2026, 2, 1)) is None


class TestMerge:
    def test_merge_sets_blackout_inputs(self):
        f = {}
        ctx = {"next_earnings_date": "2026-10-06", "days_since_earnings": 70,
               "earnings_surprise_pct": 4.1, "drift_signal": "NONE"}
        _merge_earnings(f, ctx, "NYSE", today=date(2026, 10, 2))
        assert f["days_to_next_earnings"] == 4
        assert f["trading_days_to_next_earnings"] == 2
        assert f["last_eps_surprise_pct"] == 4.1
        assert check_entry_blackout(f) is not None

    def test_merge_falls_back_to_info_earnings_date(self):
        f = {"earnings_date": "2026-10-20"}
        _merge_earnings(f, None, "NYSE", today=date(2026, 10, 2))
        assert f["trading_days_to_next_earnings"] == 12
        assert check_entry_blackout(f) is None

    def test_pre_earnings_catalyst_now_reachable(self):
        f = {}
        _merge_earnings(f, {"next_earnings_date": "2026-10-20"}, "NYSE", today=date(2026, 10, 2))
        _, breakdown = compute_score({}, f, {}, {}, {}, "HIGH_RISK")
        assert breakdown["catalyst_type"] == "PRE_EARNINGS"


class TestBuildContext:
    def _df(self):
        idx = pd.DatetimeIndex(pd.to_datetime([
            "2026-10-29 16:00", "2026-07-30 16:00", "2026-04-30 16:00",
        ])).tz_localize("America/New_York")
        return pd.DataFrame({
            "EPS Estimate": [1.9, 1.7, 1.6],
            "Reported EPS": [float("nan"), 1.85, 1.55],
            "Surprise(%)": [float("nan"), 8.82, -3.1],
        }, index=idx)

    def test_parses_last_surprise_and_next_date(self):
        ctx = build_earnings_context(None, self._df(), today=date(2026, 9, 28))
        assert ctx["next_earnings_date"] == "2026-10-29"
        assert ctx["days_since_earnings"] == (date(2026, 9, 28) - date(2026, 7, 30)).days
        assert ctx["earnings_surprise_pct"] == 8.82

    def test_calendar_preferred_for_next_date(self):
        cal = {"Earnings Date": [date(2026, 10, 27), date(2026, 10, 31)]}
        ctx = build_earnings_context(cal, self._df(), today=date(2026, 9, 28))
        assert ctx["next_earnings_date"] == "2026-10-27"

    def test_empty_inputs(self):
        ctx = build_earnings_context(None, None, today=date(2026, 9, 28))
        assert ctx["next_earnings_date"] is None
