"""long_term_check pure math + parsing: returns/CAGR, drawdown + recovery,
calendar years, benchmark heuristic, expense-ratio units, scorecard bands,
fallback verdict. No network."""

import math

import pandas as pd
import pytest

from app.services import long_term_check as lt


def _series(values, start="2010-01-04", freq="B"):
    idx = pd.date_range(start, periods=len(values), freq=freq)
    return pd.Series(values, index=idx, dtype=float)


def _geometric(years=12, cagr=0.08, start="2010-01-04"):
    idx = pd.date_range(start, pd.Timestamp(start) + pd.DateOffset(years=years), freq="D")
    t = (idx - idx[0]).days / 365.25
    return pd.Series(100 * (1 + cagr) ** t, index=idx)


# ── returns / CAGR ──

def test_window_return_cagr_on_geometric_series():
    s = _geometric(years=12, cagr=0.08)
    for y in (1, 3, 5, 10):
        r = lt.window_return(s, y)
        assert r["cagr"] == pytest.approx(8.0, abs=0.05)
        assert r["total"] == pytest.approx((1.08 ** y - 1) * 100, abs=0.3)


def test_window_needs_history():
    s = _geometric(years=4)
    assert lt.window_return(s, 5) is None
    assert lt.window_return(s, 10) is None
    assert lt.window_return(s, 3) is not None
    rows = lt.returns_table(s, None)
    assert [r["period"] for r in rows] == ["1y", "3y"]
    assert rows[0]["benchmark_cagr"] is None and rows[0]["excess_cagr"] is None


def test_returns_table_excess_uses_same_end_date():
    a = _geometric(years=11, cagr=0.10)
    b = _geometric(years=11, cagr=0.07)
    rows = lt.returns_table(a, b)
    ten = next(r for r in rows if r["years"] == 10)
    assert ten["excess_cagr"] == pytest.approx(3.0, abs=0.1)
    # benchmark shorter than the window -> no benchmark for that row
    rows2 = lt.returns_table(a, b[b.index >= b.index[-1] - pd.DateOffset(years=4)])
    assert next(r for r in rows2 if r["years"] == 10)["benchmark_cagr"] is None
    assert next(r for r in rows2 if r["years"] == 3)["benchmark_cagr"] is not None


def test_clean_closes_strips_tz_and_bad_rows():
    idx = pd.date_range("2020-01-01", periods=4, freq="D", tz="America/Toronto")
    df = pd.DataFrame({"Close": [1.0, float("nan"), -1.0, 2.0]}, index=idx)
    s = lt.clean_closes(df)
    assert s.index.tz is None and list(s.values) == [1.0, 2.0]
    assert s.index[0] == pd.Timestamp("2020-01-01")


# ── drawdown / recovery ──

def test_max_drawdown_with_recovery():
    s = _series([100, 120, 90, 60, 80, 119, 121, 130])
    d = lt.max_drawdown(s)
    assert d["depth_pct"] == -50.0
    assert d["peak_date"] == s.index[1].date().isoformat()
    assert d["trough_date"] == s.index[3].date().isoformat()
    assert d["recovered"] is True
    assert d["recovery_date"] == s.index[6].date().isoformat()
    assert d["recovery_days"] == (s.index[6] - s.index[3]).days
    assert d["underwater_days"] == (s.index[6] - s.index[1]).days


def test_max_drawdown_not_recovered():
    s = _series([100, 150, 75, 100, 120])
    d = lt.max_drawdown(s)
    assert d["depth_pct"] == -50.0
    assert d["recovered"] is False and d["recovery_date"] is None and d["recovery_days"] is None
    assert d["underwater_days"] == (s.index[-1] - s.index[1]).days
    cur = lt.current_drawdown(s)
    assert cur["pct"] == -20.0 and cur["ath"] == 150


def test_max_drawdown_monotonic():
    d = lt.max_drawdown(_series([1, 2, 3]))
    assert d["depth_pct"] == 0.0 and d["recovered"] is True


def test_volatility_constant_growth_is_zero_and_random_is_positive():
    s = _geometric(years=3, cagr=0.05)
    assert lt.annualized_volatility(s) == pytest.approx(0.0, abs=1e-6)
    alt = _series([100 * (1.01 if i % 2 else 0.99) ** 1 * (1 + 0.0) for i in range(300)])
    v = lt.annualized_volatility(alt)
    assert v is not None and v > 20


def test_calendar_years_and_worst_year():
    idx = pd.to_datetime(["2019-06-03", "2019-12-31", "2020-06-30", "2020-12-31",
                          "2021-12-31", "2022-03-01"])
    s = pd.Series([90, 100, 70, 110, 99, 120], index=idx, dtype=float)
    cal = lt.calendar_year_returns(s)
    # 2019 starts mid-year (skipped), 2022 incomplete (skipped)
    assert [c["year"] for c in cal] == [2020, 2021]
    assert cal[0]["return"] == 10.0 and cal[1]["return"] == -10.0
    assert lt.worst_year(cal) == {"year": 2021, "return": -10.0}


def test_convert_currency_forward_fills():
    b = _series([10, 10, 10], start="2020-01-06", freq="D")
    fx = _series([1.3], start="2020-01-06", freq="D")
    out = lt.convert_currency(b, fx, multiply=True)
    assert list(out.round(2)) == [13.0, 13.0, 13.0]


# ── benchmark heuristic ──

@pytest.mark.parametrize("symbol,at,info,expected", [
    ("XEQT.TO", "ETF", {"longName": "iShares Core Equity ETF Portfolio", "category": None}, "VT"),
    ("VEQT.TO", "ETF", {"longName": "Vanguard All-Equity ETF Portfolio"}, "VT"),
    ("VT", "ETF", {"longName": "Vanguard Total World Stock Index Fund ETF", "category": "Global Large-Stock Blend"}, "VT"),
    ("XIU.TO", "ETF", {"longName": "iShares S&P/TSX 60 Index ETF", "category": "Canadian Equity"}, "XIU.TO"),
    ("SHOP.TO", "STOCK", {"longName": "Shopify Inc."}, "XIU.TO"),
    ("VOO", "ETF", {"longName": "Vanguard S&P 500 ETF", "category": "Large Blend"}, "SPY"),
    ("AAPL", "STOCK", {"longName": "Apple Inc."}, "SPY"),
    ("ETH-USD", "CRYPTO", {}, "BTC-USD"),
    ("BTC-USD", "CRYPTO", {}, None),
])
def test_select_benchmark(symbol, at, info, expected):
    assert lt.select_benchmark(symbol, at, info) == expected


def test_global_keyword_does_not_apply_to_single_stocks():
    # A company with "World" in its name is not a global fund.
    assert lt.select_benchmark("WWE", "STOCK", {"longName": "World Wrestling"}) == "SPY"


def test_asset_type_for():
    assert lt.asset_type_for("BTC-USD", {}) == "CRYPTO"
    assert lt.asset_type_for("XEQT.TO", {"quoteType": "ETF"}) == "ETF"
    assert lt.asset_type_for("VFIAX", {"quoteType": "MUTUALFUND"}) == "ETF"
    assert lt.asset_type_for("AAPL", {"quoteType": "EQUITY"}) == "STOCK"


# ── expense-ratio units / fund parsing ──

def test_expense_ratio_units():
    # funds_data annualReportExpenseRatio is a fraction (0.002 == 0.20%)
    assert lt.expense_ratio_fraction({}, 0.002) == (0.002, "annualReportExpenseRatio")
    # info.netExpenseRatio is percent (0.2 == 0.20%)
    er, src = lt.expense_ratio_fraction({"netExpenseRatio": 0.2})
    assert er == pytest.approx(0.002) and src == "netExpenseRatio"
    # an implausible "fraction" (> 5%/yr) is read as percent
    assert lt.expense_ratio_fraction({"annualReportExpenseRatio": 0.75})[0] == pytest.approx(0.0075)
    assert lt.expense_ratio_fraction({}) == (None, None)


def test_build_fund_info_xeqt_like():
    info = {"netExpenseRatio": 0.2, "totalAssets": 2.2e10, "yield": 0.0157, "trailingPE": 20.6,
            "fundFamily": "BlackRock", "longName": "iShares Core Equity ETF Portfolio"}
    fd = {"expense_ratio_raw": 0.002, "pe": 0.0486, "pb": 0.324,
          "holdings": [{"symbol": "XTOT.TO", "name": "iShares Core S&P Total U.S. Stk Mkt ETF", "weight": 29.7},
                       {"symbol": "XIC.TO", "name": "iShares Core S&P/TSX Cap Composite ETF", "weight": 25.6},
                       {"symbol": "XEF.TO", "name": "iShares Core MSCI EAFE IMI ETF", "weight": 24.4},
                       {"symbol": "ITOT", "name": "iShares Core S&P Total US Stock Mkt ETF", "weight": 15.4},
                       {"symbol": "XEC.TO", "name": "iShares Core MSCI Emer Mkts IMI ETF", "weight": 4.8}]}
    f = lt.build_fund_info(info, fd)
    assert f["expense_ratio"] == pytest.approx(0.2)
    assert f["yield"] == pytest.approx(1.57)
    assert f["fund_of_funds"] is True and f["top10_weight"] == pytest.approx(99.9)
    assert f["pe"] == pytest.approx(20.6)
    assert f["pb"] == pytest.approx(1 / 0.324, abs=0.01)
    d = lt.score_diversification("ETF", f)
    assert d["rating"] == "good" and d["params"]["funds"] == 5


def test_invert_ratio():
    assert lt.invert_ratio(0.05) == pytest.approx(20.0)
    assert lt.invert_ratio(18.0) == 18.0
    assert lt.invert_ratio(None) is None and lt.invert_ratio(0) is None


def test_income_trend_and_fundamentals():
    df = pd.DataFrame({pd.Timestamp("2025-12-31"): [200.0, 40.0], pd.Timestamp("2022-12-31"): [100.0, 20.0]},
                      index=["Total Revenue", "Net Income"])
    trend = lt.income_trend(df)
    assert [t["year"] for t in trend] == [2022, 2025]
    info = {"marketCap": 1000.0, "freeCashflow": 50.0, "trailingPE": 18.0, "returnOnEquity": 0.2,
            "operatingMargins": 0.25, "debtToEquity": 80.0, "currentRatio": 1.6, "payoutRatio": 0.3,
            "fiveYearAvgDividendYield": 1.2, "dividendRate": 2.0, "currentPrice": 100.0}
    f = lt.build_fundamentals(info, trend, {"eps_revision_momentum": 1.234})
    assert f["valuation"]["fcf_yield"] == 5.0
    assert f["growth"]["revenue_cagr"] == pytest.approx(25.99, abs=0.01)
    assert f["dividend"]["yield"] == 2.0 and f["dividend"]["payout_ratio"] == 30.0
    assert f["estimates"]["revision_momentum"] == 1.23
    assert lt.score_valuation("STOCK", None, f)["rating"] == "good"
    assert lt.score_quality("STOCK", f)["rating"] == "good"


# ── scorecard bands ──

@pytest.mark.parametrize("er,rating", [(0.03, "good"), (0.25, "good"), (0.26, "fair"), (0.60, "fair"), (0.95, "poor")])
def test_cost_bands(er, rating):
    assert lt.score_cost("ETF", {"expense_ratio": er})["rating"] == rating


def test_cost_na_for_stock_and_missing():
    assert lt.score_cost("STOCK", None)["rating"] == "n/a"
    assert lt.score_cost("ETF", {"expense_ratio": None})["rating"] == "n/a"


@pytest.mark.parametrize("top10,rating", [(25.0, "good"), (40.0, "fair"), (70.0, "poor")])
def test_diversification_bands(top10, rating):
    assert lt.score_diversification("ETF", {"top10_weight": top10, "fund_of_funds": False})["rating"] == rating


def test_diversification_single_stock_and_crypto():
    assert lt.score_diversification("STOCK", None)["rating"] == "poor"
    assert lt.score_diversification("CRYPTO", None)["rating"] == "poor"


def _row(y, a, b):
    return {"period": f"{y}y", "years": y, "asset_cagr": a, "benchmark_cagr": b,
            "excess_cagr": None if b is None else round(a - b, 2)}


def test_track_record_bands_use_longest_window():
    rows = [_row(1, 30, 10), _row(3, 9.5, 10), _row(5, 6, 10)]
    item = lt.score_track_record(rows, "SPY")
    assert item["params"]["period"] == "5y" and item["rating"] == "poor"
    assert lt.score_track_record([_row(3, 9.5, 10)], "SPY")["rating"] == "good"
    assert lt.score_track_record([_row(3, 8, 10)], "SPY")["rating"] == "fair"
    assert lt.score_track_record([_row(1, 50, 10)], "SPY")["rating"] == "n/a"
    # no benchmark (BTC itself): absolute CAGR bands
    assert lt.score_track_record([_row(5, 40, None)], None)["rating"] == "good"
    assert lt.score_track_record([_row(5, -5, None)], None)["rating"] == "poor"


def test_valuation_bands():
    v = lambda pe, fcf: {"valuation": {"trailing_pe": pe, "fcf_yield": fcf}}  # noqa: E731
    assert lt.score_valuation("STOCK", None, v(15, 6))["rating"] == "good"
    assert lt.score_valuation("STOCK", None, v(50, 1))["rating"] == "poor"
    assert lt.score_valuation("STOCK", None, v(-5, None))["rating"] == "poor"
    assert lt.score_valuation("STOCK", None, v(30, None))["rating"] == "fair"
    assert lt.score_valuation("STOCK", None, v(None, None))["rating"] == "n/a"
    assert lt.score_valuation("ETF", {"pe": 17}, None)["rating"] == "good"
    assert lt.score_valuation("ETF", {"pe": None}, None)["rating"] == "n/a"
    assert lt.score_valuation("CRYPTO", None, None)["rating"] == "n/a"


def test_risk_bands():
    assert lt.score_risk({"depth_pct": -30}, 15)["rating"] == "good"
    assert lt.score_risk({"depth_pct": -55}, 25)["rating"] == "fair"
    assert lt.score_risk({"depth_pct": -80}, 70)["rating"] == "poor"
    assert lt.score_risk(None, None)["rating"] == "n/a"


def test_quality_only_for_stocks():
    assert lt.score_quality("ETF", {})["rating"] == "n/a"
    q = {"quality": {"roe": 3, "operating_margin": 2, "debt_to_equity": 350, "current_ratio": 0.7}}
    assert lt.score_quality("STOCK", q)["rating"] == "poor"


# ── fallback verdict ──

def _sc(**ratings):
    return [{"key": k, "rating": r, "reason": ""} for k, r in ratings.items()]


def test_fallback_verdict():
    good = _sc(cost="good", diversification="good", track_record="good", valuation="fair", risk="good", quality="n/a")
    assert lt.fallback_verdict(good, "ETF", []) == "SOLID"
    one_poor = _sc(cost="poor", diversification="good", track_record="good", risk="good")
    assert lt.fallback_verdict(one_poor, "ETF", []) == "REASONABLE_WITH_CAVEATS"
    two_poor = _sc(cost="poor", diversification="poor", track_record="good", risk="good")
    assert lt.fallback_verdict(two_poor, "ETF", []) == "NOT_A_GOOD_FIT"
    # a stock's inherent single-company "poor" is not counted
    stock = _sc(cost="n/a", diversification="poor", track_record="good", valuation="good", risk="fair", quality="good")
    assert lt.fallback_verdict(stock, "STOCK", []) == "SOLID"
    assert lt.fallback_verdict(stock, "STOCK", [{"category": "litigation"}]) == "REASONABLE_WITH_CAVEATS"
    assert lt.fallback_verdict(stock, "STOCK", [{"category": "fraud"}]) == "NOT_A_GOOD_FIT"
    assert lt.fallback_verdict(good, "CRYPTO", []) == "NOT_A_GOOD_FIT"
    sparse = _sc(cost="n/a", track_record="n/a", risk="good")
    assert lt.fallback_verdict(sparse, "ETF", []) == "REASONABLE_WITH_CAVEATS"


def test_material_red_flags_filters_uncited_and_immaterial():
    grok = {"confidence": 70, "red_flags": [
        {"text": "SEC accounting probe", "url": "https://x.com/a", "severity": "medium", "category": "accounting"},
        {"text": "minor suit", "url": "https://x.com/b", "severity": "low", "category": "litigation"},
        {"text": "uncited fraud", "severity": "critical", "category": "fraud"},
    ]}
    flags = lt.material_red_flags(grok, 1e11)
    assert [f["text"] for f in flags] == ["SEC accounting probe"]
    assert lt.material_red_flags({**grok, "error": "x"}, 1e11) == []
    assert lt.material_red_flags({**grok, "confidence": 0}, 1e11) == []


def test_clean_nan():
    assert lt._clean({"a": [float("nan"), 1.0], "b": math.inf}) == {"a": [None, 1.0], "b": None}
