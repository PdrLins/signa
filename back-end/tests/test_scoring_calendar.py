"""Holiday generator must reproduce the verified 2026 lists and 2027."""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("DEBUG", "true")

from datetime import date

from app.core.market_calendar import (
    TSX_HOLIDAYS_2026, US_HOLIDAYS_2026, covered_years_for,
    generate_tsx_holidays, generate_us_holidays, is_market_open,
)


def test_generator_matches_verified_2026():
    assert generate_us_holidays(2026) == US_HOLIDAYS_2026
    assert generate_tsx_holidays(2026) == TSX_HOLIDAYS_2026


def test_us_2027():
    assert generate_us_holidays(2027) == frozenset({
        "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
        "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
    })


def test_tsx_2027():
    assert generate_tsx_holidays(2027) == frozenset({
        "2027-01-01", "2027-02-15", "2027-03-26", "2027-05-24", "2027-07-01",
        "2027-08-02", "2027-09-06", "2027-10-11", "2027-12-27", "2027-12-28",
    })


def test_2027_covered_and_enforced():
    assert 2027 in covered_years_for("TSX") and 2027 in covered_years_for("NYSE")
    assert is_market_open("NYSE", date(2027, 11, 25)) is False
    assert is_market_open("TSX", date(2027, 12, 28)) is False


def test_nyse_no_close_when_new_year_on_saturday():
    # 2028-01-01 is a Saturday: NYSE stays open Fri 2027-12-31.
    assert "2027-12-31" not in generate_us_holidays(2027)
    assert is_market_open("NYSE", date(2027, 12, 31)) is True
