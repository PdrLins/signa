"""Regression test: market_calendar.is_market_open.

Day 36 (May 18 2026 = Victoria Day) the brain admitted LUN.TO on a
closed TSX, dying for -$19.66 the next session. These tests pin the
holiday filter so the same failure can't recur for any covered year.
"""

import os
from datetime import date

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("DEBUG", "true")

from app.core.market_calendar import is_market_open, covered_years_for


class TestVictoriaDayCase:
    """The exact scenario that motivated this module."""

    def test_tsx_closed_on_victoria_day(self):
        assert is_market_open("TSX", date(2026, 5, 18)) is False

    def test_nyse_open_on_victoria_day(self):
        # US markets are open on Canadian Victoria Day.
        assert is_market_open("NYSE", date(2026, 5, 18)) is True
        assert is_market_open("NASDAQ", date(2026, 5, 18)) is True


class TestTSXHolidays2026:
    """Pin every TSX holiday in 2026 — keeps the calendar honest."""

    def test_new_years_day(self):
        assert is_market_open("TSX", date(2026, 1, 1)) is False

    def test_family_day(self):
        assert is_market_open("TSX", date(2026, 2, 16)) is False

    def test_good_friday(self):
        assert is_market_open("TSX", date(2026, 4, 3)) is False

    def test_canada_day(self):
        assert is_market_open("TSX", date(2026, 7, 1)) is False

    def test_thanksgiving_canadian(self):
        assert is_market_open("TSX", date(2026, 10, 12)) is False

    def test_christmas_day(self):
        assert is_market_open("TSX", date(2026, 12, 25)) is False


class TestUSHolidays2026:
    def test_mlk_day(self):
        assert is_market_open("NYSE", date(2026, 1, 19)) is False

    def test_juneteenth(self):
        assert is_market_open("NYSE", date(2026, 6, 19)) is False

    def test_thanksgiving_us(self):
        assert is_market_open("NYSE", date(2026, 11, 26)) is False


class TestCrypto:
    """Crypto markets are 24/7, including holidays and weekends."""

    def test_open_on_christmas(self):
        assert is_market_open("CRYPTO", date(2026, 12, 25)) is True

    def test_open_on_saturday(self):
        assert is_market_open("CRYPTO", date(2026, 5, 23)) is True

    def test_open_on_victoria_day(self):
        assert is_market_open("CRYPTO", date(2026, 5, 18)) is True


class TestWeekends:
    """Equity exchanges are closed on Saturdays and Sundays."""

    def test_saturday_tsx(self):
        # 2026-05-23 is a Saturday
        assert is_market_open("TSX", date(2026, 5, 23)) is False

    def test_sunday_nyse(self):
        # 2026-05-24 is a Sunday
        assert is_market_open("NYSE", date(2026, 5, 24)) is False


class TestSafeDefaults:
    """The function defaults to 'open' for unknown inputs so we never
    silently block legitimate trades — failures should fall toward
    over-permission, not over-restriction."""

    def test_unknown_exchange_returns_open(self):
        assert is_market_open("LSE", date(2026, 5, 18)) is True

    def test_none_exchange_returns_open(self):
        assert is_market_open(None, date(2026, 5, 18)) is True

    def test_uncovered_year_returns_open(self):
        # 2027 not yet in the hardcoded list — default open so a missing
        # year-roll doesn't accidentally pause all trading.
        assert is_market_open("TSX", date(2027, 5, 17)) is True


class TestCurrentYearCoverage:
    """If this fails in December, time to add next year's holidays.

    The test verifies the calendar covers the year we're currently in.
    If we forget the December year-roll, this fails loudly in CI before
    the brain admits a stale-price entry."""

    def test_current_year_tsx_covered(self):
        from datetime import datetime
        current_year = datetime.now().year
        # Skip in 2026 (the year this was written) — the test bites only
        # when the calendar falls behind reality.
        if current_year > 2026:
            assert current_year in covered_years_for("TSX"), (
                f"TSX calendar missing for {current_year} — update market_calendar.py"
            )
            assert current_year in covered_years_for("NYSE"), (
                f"NYSE calendar missing for {current_year} — update market_calendar.py"
            )
