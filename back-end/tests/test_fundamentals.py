"""Tests for fundamental extraction and bucket classification."""

from backtest.engine.fundamentals import classify_bucket, extract_fundamentals


class TestExtractFundamentals:
    def test_extracts_all_fields(self):
        info = {
            "trailingPE": 25.0,
            "earningsGrowth": 0.15,
            "debtToEquity": 80.0,
            "profitMargins": 0.22,
            "revenueGrowth": 0.10,
            "dividendYield": 0.02,
            "marketCap": 500_000_000_000,
            "sector": "Technology",
            "beta": 1.3,
        }
        result = extract_fundamentals(info)
        assert result["pe_ratio"] == 25.0
        assert result["eps_growth"] == 0.15
        assert result["sector"] == "Technology"
        assert result["data_quality"] == 100.0

    def test_handles_empty_dict(self):
        result = extract_fundamentals({})
        assert result["pe_ratio"] is None
        assert result["data_quality"] == 0.0

    def test_normalizes_high_dividend_yield(self):
        # yfinance returns 0.41 meaning 0.41%, normalize if > 0.20
        result = extract_fundamentals({"dividendYield": 0.41})
        assert result["dividend_yield"] == 0.41 / 100

    def test_normalizes_high_profit_margin(self):
        result = extract_fundamentals({"profitMargins": 27.0})
        assert result["profit_margin"] == 0.27

    def test_uses_cached_key_names(self):
        result = extract_fundamentals({"pe_ratio": 15.0, "dividend_yield": 0.03})
        assert result["pe_ratio"] == 15.0
        assert result["dividend_yield"] == 0.03

    def test_data_quality_partial(self):
        result = extract_fundamentals({"trailingPE": 20.0, "beta": 1.1})
        assert 20 <= result["data_quality"] <= 30


class TestClassifyBucket:
    def test_high_dividend_is_safe(self):
        assert classify_bucket({"dividend_yield": 0.05}) == "SAFE_INCOME"

    def test_high_beta_is_risk(self):
        assert classify_bucket({"dividend_yield": 0.01, "beta": 1.6}) == "HIGH_RISK"

    def test_small_cap_is_risk(self):
        assert classify_bucket({"market_cap": 1_000_000_000}) == "HIGH_RISK"

    def test_utility_sector_is_safe(self):
        assert classify_bucket({"sector": "Utilities"}) == "SAFE_INCOME"

    def test_financial_services_is_safe(self):
        assert classify_bucket({"sector": "Financial Services"}) == "SAFE_INCOME"

    def test_default_is_risk(self):
        assert classify_bucket({}) == "HIGH_RISK"

    def test_priority_order(self):
        # High dividend takes priority over high beta
        assert classify_bucket({"dividend_yield": 0.05, "beta": 2.0}) == "SAFE_INCOME"
