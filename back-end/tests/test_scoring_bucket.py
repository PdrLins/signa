"""Bucket classifier must use REAL fundamentals and never persist a guess.

Regression: _classify_bucket read sector/dividend_yield/market_cap from
bulk screening rows (which never contain them), so every unknown ticker
became SAFE_INCOME and that guess was written to tickers.bucket forever.
"""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("DEBUG", "true")

import pytest

from app.services import scan_service
from app.scanners import market_scanner


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    scan_service._bucket_cache.clear()
    calls = []
    monkeypatch.setattr(
        scan_service.queries, "upsert_ticker",
        lambda sym, **kw: calls.append((sym, kw.get("bucket"))),
    )
    yield calls
    scan_service._bucket_cache.clear()


def test_growth_tech_with_real_fundamentals_is_high_risk(_isolate):
    f = {"sector": "Technology", "dividend_yield": 0.004, "market_cap": 900e9, "quote_type": "EQUITY"}
    assert scan_service._classify_bucket("ZZTECH", f) == "HIGH_RISK"
    assert _isolate == [("ZZTECH", "HIGH_RISK")]


def test_high_yield_utility_is_safe_income(_isolate):
    f = {"sector": "Utilities", "dividend_yield": 0.045, "market_cap": 60e9, "quote_type": "EQUITY"}
    assert scan_service._classify_bucket("ZZUTIL", f) == "SAFE_INCOME"


def test_telecom_with_meaningful_dividend_is_safe(_isolate):
    f = {"sector": "Communication Services", "dividend_yield": 0.05, "market_cap": 150e9}
    assert scan_service._classify_bucket("ZZTEL", f) == "SAFE_INCOME"


def test_small_cap_industrial_is_high_risk(_isolate):
    f = {"sector": "Industrials", "dividend_yield": 0.01, "market_cap": 8e9}
    assert scan_service._classify_bucket("ZZIND", f) == "HIGH_RISK"


def test_energy_is_high_risk_even_with_dividend(_isolate):
    f = {"sector": "Energy", "dividend_yield": 0.06, "market_cap": 200e9}
    assert scan_service._classify_bucket("ZZOIL", f) == "HIGH_RISK"


def test_missing_fundamentals_is_not_persisted_and_not_safe(_isolate):
    # Old behaviour: {} -> SAFE_INCOME, persisted. New: HIGH_RISK for this
    # scan only; no DB write, no cache entry.
    assert scan_service._classify_bucket("ZZUNKNOWN", {}) == "HIGH_RISK"
    assert scan_service._classify_bucket("ZZUNKNOWN", None) == "HIGH_RISK"
    assert _isolate == []
    assert "ZZUNKNOWN" not in scan_service._bucket_cache


def test_missing_then_real_fundamentals_classifies_properly(_isolate):
    scan_service._classify_bucket("ZZLATER", {})
    f = {"sector": "Financial Services", "dividend_yield": 0.035, "market_cap": 120e9}
    assert scan_service._classify_bucket("ZZLATER", f) == "SAFE_INCOME"
    assert _isolate == [("ZZLATER", "SAFE_INCOME")]


@pytest.mark.parametrize("sym", ["TQQQ", "SQQQ", "SOXL", "UVXY", "HQU.TO"])
def test_leveraged_and_inverse_etfs_are_high_risk(sym, _isolate):
    assert scan_service._classify_bucket(sym, None) == "HIGH_RISK"


def test_leveraged_override_beats_stale_db_bucket(_isolate):
    scan_service._bucket_cache["TQQQ"] = "SAFE_INCOME"  # poisoned DB row
    assert scan_service._classify_bucket("TQQQ", {}) == "HIGH_RISK"


def test_unknown_leveraged_etf_detected_by_name(_isolate):
    f = {"quote_type": "ETF", "company_name": "Direxion Daily Widget Bull 3X Shares"}
    assert scan_service._classify_bucket("ZZ3X", f) == "HIGH_RISK"


def test_plain_etf_is_safe_income(_isolate):
    f = {"quote_type": "ETF", "company_name": "Vanguard Short-Term Bond ETF"}
    assert scan_service._classify_bucket("ZZBND", f) == "SAFE_INCOME"


class TestDividendYieldUnits:
    """yfinance reports dividendYield in PERCENT (0.44 == 0.44%)."""

    def test_sub_one_percent_yield_is_not_treated_as_fraction(self):
        # Old: _normalize_pct(0.44) -> 0.44 (44%) -> capped to None.
        info = {"dividendYield": 0.44}
        assert market_scanner._dividend_yield_fraction(info) == pytest.approx(0.0044)

    def test_rate_over_price_preferred(self):
        info = {"dividendRate": 1.04, "regularMarketPrice": 230.0, "dividendYield": 0.45}
        assert market_scanner._dividend_yield_fraction(info) == pytest.approx(1.04 / 230.0)

    def test_percent_above_one(self):
        assert market_scanner._dividend_yield_fraction({"dividendYield": 4.2}) == pytest.approx(0.042)

    def test_trailing_fraction_fallback(self):
        info = {"trailingAnnualDividendYield": 0.031}
        assert market_scanner._dividend_yield_fraction(info) == pytest.approx(0.031)

    def test_payout_ratio_above_100pct_kept(self):
        # A 150% payout is real; the old magnitude heuristic made it 1.5%.
        assert market_scanner._fraction(1.5) == 1.5
