"""Richer equity data: estimate revisions, relative strength, short/insider
parsing, and the get_fundamentals merge. No network — yfinance is mocked."""

import asyncio

import numpy as np
import pandas as pd
import pytest

from app.scanners import enrichment, market_scanner
from app.scanners.indicators import compute_relative_strength


@pytest.fixture(autouse=True)
def _clear_caches():
    from app.core.cache import price_cache
    enrichment._enrichment_cache.clear()
    enrichment._benchmark_cache.clear()
    price_cache.clear()
    yield
    enrichment._enrichment_cache.clear()
    enrichment._benchmark_cache.clear()
    price_cache.clear()


def _eps_trend():
    return pd.DataFrame(
        {
            "current": [1.10, 1.20, 4.40, 5.00],
            "7daysAgo": [1.09, 1.19, 4.38, 4.98],
            "30daysAgo": [1.00, 1.18, 4.30, 4.80],
            "60daysAgo": [0.98, 1.15, 4.20, 4.70],
            "90daysAgo": [1.00, 1.10, 4.00, 4.00],
        },
        index=pd.Index(["0q", "+1q", "0y", "+1y"], name="period"),
    )


def _eps_revisions():
    return pd.DataFrame(
        {
            "upLast7days": [1, 0, 1, 1],
            "upLast30days": [5, 2, 6, 4],
            "downLast7Days": [0, 0, 0, 0],   # Yahoo's odd capitalisation
            "downLast30days": [1, 0, 1, 2],
        },
        index=pd.Index(["0q", "+1q", "0y", "+1y"], name="period"),
    )


# ── Estimate revisions ─────────────────────────────────────────────

class TestEstimateRevisions:
    def test_revision_math(self):
        out = enrichment.parse_estimate_revisions(_eps_trend(), _eps_revisions())
        assert out["eps_est_change_0q_30d_pct"] == pytest.approx(10.0)   # 1.10 vs 1.00
        assert out["eps_est_change_0q_90d_pct"] == pytest.approx(10.0)
        assert out["eps_est_change_fy1_30d_pct"] == pytest.approx(4.17)  # 5.00 vs 4.80
        assert out["eps_est_change_fy1_90d_pct"] == pytest.approx(25.0)  # 5.00 vs 4.00
        assert out["eps_revision_momentum"] == pytest.approx((10 + 10 + 4.17 + 25) / 4, abs=0.01)
        # 0q + +1y rows: up 5+4, down 1+2
        assert out["eps_revisions_up_30d"] == 9
        assert out["eps_revisions_down_30d"] == 3

    def test_falls_back_to_current_year_when_next_year_missing(self):
        trend = _eps_trend().drop(index="+1y")
        out = enrichment.parse_estimate_revisions(trend, None)
        assert out["eps_est_change_fy1_90d_pct"] == pytest.approx(10.0)  # 0y 4.40 vs 4.00
        assert "eps_revisions_up_30d" not in out

    def test_tiny_base_is_ignored(self):
        trend = pd.DataFrame({"current": [0.03], "30daysAgo": [0.01]}, index=["0q"])
        assert enrichment.parse_estimate_revisions(trend, None) == {}

    def test_missing_or_bad_inputs(self):
        assert enrichment.parse_estimate_revisions(None, None) == {}
        assert enrichment.parse_estimate_revisions(pd.DataFrame(), pd.DataFrame()) == {}
        trend = pd.DataFrame({"current": [np.nan], "30daysAgo": [1.0]}, index=["0q"])
        assert enrichment.parse_estimate_revisions(trend, "garbage") == {}


# ── Insider / short interest ───────────────────────────────────────

def _insider_df(net=150_000, buys=4, sells=1, pct=0.012):
    return pd.DataFrame({
        "Insider Purchases Last 6m": [
            "Purchases", "Sales", "Net Shares Purchased (Sold)",
            "Total Insider Shares Held", "% Net Shares Purchased (Sold)",
            "% Buy Shares", "% Sell Shares",
        ],
        "Shares": [200_000, 50_000, net, 10_000_000, pct, 0.02, 0.005],
        "Trans": [buys, sells, buys + sells, pd.NA, pd.NA, pd.NA, pd.NA],
    })


class TestInsiderAndShort:
    def test_insider_parse(self):
        out = enrichment.parse_insider_purchases(_insider_df())
        assert out == {
            "insider_net_shares_6m": 150_000,
            "insider_buy_count_6m": 4,
            "insider_sell_count_6m": 1,
            "insider_net_pct_6m": 0.012,
        }

    def test_insider_missing_rows_and_values(self):
        df = _insider_df(net=None)
        df = df[df.iloc[:, 0] != "Sales"]
        out = enrichment.parse_insider_purchases(df)
        assert "insider_net_shares_6m" not in out
        assert "insider_sell_count_6m" not in out
        assert out["insider_buy_count_6m"] == 4
        assert enrichment.parse_insider_purchases(None) == {}
        assert enrichment.parse_insider_purchases(pd.DataFrame()) == {}

    def test_short_trend(self):
        out = enrichment.parse_short_interest(
            {"sharesShort": 13_000_000, "sharesShortPriorMonth": 10_000_000, "shortRatio": 2.345}
        )
        assert out["short_interest_change_pct"] == pytest.approx(30.0)
        assert out["short_ratio_days"] == 2.35
        assert out["short_shares"] == 13_000_000

    def test_short_missing_fields(self):
        assert enrichment.parse_short_interest({}) == {}
        assert enrichment.parse_short_interest(None) == {}
        out = enrichment.parse_short_interest({"sharesShort": 5, "sharesShortPriorMonth": 0})
        assert "short_interest_change_pct" not in out
        assert enrichment.parse_short_interest({"sharesShort": "n/a"}) == {}


# ── Relative strength ──────────────────────────────────────────────

class TestRelativeStrength:
    @pytest.mark.parametrize("sector,etf", [
        ("Technology", "XLK"), ("Financial Services", "XLF"), ("Energy", "XLE"),
        ("Healthcare", "XLV"), ("Consumer Cyclical", "XLY"), ("Consumer Defensive", "XLP"),
        ("Industrials", "XLI"), ("Basic Materials", "XLB"), ("Utilities", "XLU"),
        ("Real Estate", "XLRE"), ("Communication Services", "XLC"),
    ])
    def test_sector_map(self, sector, etf):
        assert enrichment.benchmark_for("ABC", sector) == etf

    def test_tsx_and_unknown(self):
        assert enrichment.benchmark_for("SHOP.TO", "Technology") == "XIU.TO"
        assert enrichment.benchmark_for("ABC.V", None) == "XIU.TO"
        assert enrichment.benchmark_for("ABC", "Conglomerates") is None
        assert enrichment.benchmark_for("ABC", None) is None

    def test_period_returns_windows(self):
        close = np.linspace(100, 200, 130)
        out = enrichment.period_returns(pd.DataFrame({"Close": close}))
        assert out["return_3m"] == pytest.approx((200 / close[-63] - 1) * 100, abs=0.01)
        assert out["return_6m"] == pytest.approx((200 / close[-126] - 1) * 100, abs=0.01)
        short = enrichment.period_returns(pd.DataFrame({"Close": close[:70]}))
        assert "return_6m" not in short and "return_3m" in short
        assert enrichment.period_returns(None) == {}

    def test_relative_strength_math(self):
        tech = {"momentum_3m": 12.0, "momentum_6m": 20.0}
        fund = {"rs_benchmark": "XLK", "rs_benchmark_return_3m": 5.0,
                "rs_benchmark_return_6m": 25.0, "spy_return_3m": 4.0, "spy_return_6m": 10.0}
        assert compute_relative_strength(tech, fund) == {
            "rs_benchmark": "XLK", "rs_vs_benchmark_3m": 7.0, "rs_vs_benchmark_6m": -5.0,
            "rs_vs_spy_3m": 8.0, "rs_vs_spy_6m": 10.0,
        }

    def test_relative_strength_missing(self):
        assert compute_relative_strength({}, {"spy_return_3m": 4.0}) == {}
        assert compute_relative_strength({"momentum_3m": 5.0}, {}) == {}
        assert compute_relative_strength(None, None) == {}
        # 6m history too short on the stock side → only 3m
        out = compute_relative_strength({"momentum_3m": 5.0}, {"spy_return_3m": 1.0, "spy_return_6m": 2.0})
        assert out == {"rs_vs_spy_3m": 4.0}


# ── Fetch + get_fundamentals merge (mocked yfinance) ──────────────

class _FakeTicker:
    calls: list[str] = []

    def __init__(self, symbol):
        self.symbol = symbol
        _FakeTicker.calls.append(symbol)

    @property
    def info(self):
        return {
            "quoteType": "EQUITY", "sector": "Technology", "marketCap": 3e12,
            "sharesShort": 110, "sharesShortPriorMonth": 100, "shortPercentOfFloat": 0.01,
        }

    @property
    def eps_trend(self):
        return _eps_trend()

    @property
    def eps_revisions(self):
        return _eps_revisions()

    @property
    def insider_purchases(self):
        return _insider_df()

    def history(self, period="1y"):
        n = 200
        if self.symbol == "XLK":
            close = np.full(n, 100.0)
            close[-1] = 110.0
        elif self.symbol == "SPY":
            close = np.full(n, 100.0)
            close[-1] = 105.0
        else:
            raise RuntimeError("no history for stocks in this fake")
        return pd.DataFrame({"Close": close})


def test_get_fundamentals_merges_enrichment(monkeypatch):
    _FakeTicker.calls = []
    monkeypatch.setattr(market_scanner.yf, "Ticker", _FakeTicker)
    monkeypatch.setattr(enrichment.yf, "Ticker", _FakeTicker)

    out = asyncio.run(market_scanner.get_fundamentals("ACME"))
    assert out["market_cap"] == 3e12
    assert out["eps_revisions_up_30d"] == 9
    assert out["insider_net_shares_6m"] == 150_000
    assert out["short_interest_change_pct"] == pytest.approx(10.0)
    assert out["rs_benchmark"] == "XLK"
    assert out["rs_benchmark_return_3m"] == pytest.approx(10.0)
    assert out["spy_return_3m"] == pytest.approx(5.0)

    # Second ticker in the same sector reuses the cached ETF history.
    from app.core.cache import price_cache
    price_cache.clear()
    before = _FakeTicker.calls.count("XLK")
    asyncio.run(market_scanner.get_fundamentals("OTHER"))
    assert _FakeTicker.calls.count("XLK") == before


def test_enrichment_skips_non_equity_and_disabled(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(enrichment.yf, "Ticker", _FakeTicker)
    assert asyncio.run(enrichment.get_enrichment("SPY", {"quoteType": "ETF"})) == {}
    assert asyncio.run(enrichment.get_enrichment("BTC-USD", {"quoteType": "CRYPTOCURRENCY"})) == {}
    monkeypatch.setattr(settings, "enrichment_fetch_enabled", False)
    assert asyncio.run(enrichment.get_enrichment("ACME", {"quoteType": "EQUITY"})) == {}


def test_enrichment_tolerates_yfinance_failures(monkeypatch):
    class _Broken:
        def __init__(self, symbol):
            pass

        @property
        def eps_trend(self):
            raise RuntimeError("boom")

        @property
        def insider_purchases(self):
            raise RuntimeError("boom")

        def history(self, period="1y"):
            raise RuntimeError("boom")

    monkeypatch.setattr(enrichment.yf, "Ticker", _Broken)
    out = asyncio.run(enrichment.get_enrichment(
        "ACME", {"quoteType": "EQUITY", "sector": "Energy", "sharesShort": 1, "sharesShortPriorMonth": 2},
    ))
    assert out == {"short_shares": 1, "short_shares_prior_month": 2, "short_interest_change_pct": -50.0}
