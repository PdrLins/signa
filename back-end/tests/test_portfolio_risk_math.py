"""Portfolio risk math on synthetic return series (no network)."""

import math

import numpy as np
import pandas as pd
import pytest

from app.core.config import settings
from app.services import portfolio_risk as pr

N = 130


def _closes_from_returns(rets: dict[str, np.ndarray], start="2026-03-02") -> dict[str, pd.Series]:
    idx = pd.bdate_range(start, periods=len(next(iter(rets.values()))) + 1)
    return {s: pd.Series(100 * np.cumprod(np.r_[1.0, 1 + r]), index=idx, name=s) for s, r in rets.items()}


def factor_returns(loadings: dict[str, float], seed=0, n=N, vol=0.01):
    """r_i = ρ_i·f + sqrt(1-ρ_i²)·e_i  → corr(r_i, f) ≈ ρ_i."""
    rng = np.random.default_rng(seed)
    f = rng.standard_normal(n)
    out = {"F": f * vol}
    for s, rho in loadings.items():
        out[s] = (rho * f + math.sqrt(1 - rho ** 2) * rng.standard_normal(n)) * vol
    return out


class TestCorrelation:
    def test_pair_correlation_matches_numpy(self):
        r = factor_returns({"A": 0.9, "B": 0.1}, seed=1)
        rets = pr.returns_frame(_closes_from_returns(r), lookback=500)
        c = pr.pair_correlation(rets, "A", "F", min_obs=40)
        expected = np.corrcoef(r["A"], r["F"])[0, 1]
        assert c == pytest.approx(expected, abs=1e-9)
        assert c > 0.8
        assert abs(pr.pair_correlation(rets, "B", "F", min_obs=40)) < 0.35

    def test_insufficient_overlap_returns_none(self):
        r = factor_returns({"A": 0.9}, n=20)
        rets = pr.returns_frame(_closes_from_returns(r))
        assert pr.pair_correlation(rets, "A", "F", min_obs=40) is None
        assert pr.pair_correlation(rets, "A", "MISSING", min_obs=5) is None

    def test_lookback_trims_rows_and_weekend_rows_dropped(self):
        r = factor_returns({"A": 0.5})
        closes = _closes_from_returns(r)
        # crypto-style series with weekend bars
        cidx = pd.date_range(closes["A"].index[0], closes["A"].index[-1], freq="D", tz="UTC")
        closes["X-USD"] = pd.Series(np.linspace(100, 120, len(cidx)), index=cidx.tz_localize(None))
        rets = pr.returns_frame(closes, lookback=60)
        assert len(rets) == 60
        assert (pd.DatetimeIndex(rets.index).dayofweek < 5).all()


class TestRule:
    def test_pairwise_threshold(self):
        blocked, d = pr.evaluate_correlation_rule({"A": 0.81, "B": 0.2},
                                                  max_pairwise=0.8, cluster_threshold=0.7, cluster_max=2)
        assert blocked and d["rule"] == "pairwise" and d["max_corr_symbol"] == "A"
        blocked, d = pr.evaluate_correlation_rule({"A": 0.79, "B": 0.2},
                                                  max_pairwise=0.8, cluster_threshold=0.7, cluster_max=2)
        assert not blocked and d["rule"] is None

    def test_cluster_threshold(self):
        blocked, d = pr.evaluate_correlation_rule({"A": 0.75, "B": 0.72, "C": 0.1},
                                                  {"A": 0.1, "B": 0.1, "C": 0.1},
                                                  max_pairwise=0.8, cluster_threshold=0.7, cluster_max=2)
        assert blocked and d["rule"] == "correlated_cluster"
        assert d["cluster_symbols"] == ["A", "B"]
        assert d["weighted_exposure"] == pytest.approx(0.075 + 0.072 + 0.01)
        blocked, d = pr.evaluate_correlation_rule({"A": 0.75, "B": 0.69},
                                                  max_pairwise=0.8, cluster_threshold=0.7, cluster_max=2)
        assert not blocked and d["n_above_cluster_threshold"] == 1

    def test_empty_never_blocks(self):
        blocked, d = pr.evaluate_correlation_rule({})
        assert not blocked


class TestBetaVol:
    def test_beta_and_portfolio_beta(self):
        rng = np.random.default_rng(3)
        spy = rng.standard_normal(N) * 0.01
        r = {"SPY": spy, "HI": 1.5 * spy + rng.standard_normal(N) * 0.002,
             "LO": 0.5 * spy + rng.standard_normal(N) * 0.002}
        rets = pr.returns_frame(_closes_from_returns(r), lookback=500)
        betas = pr.symbol_betas(rets, ["HI", "LO"], min_obs=40)
        assert betas["HI"] == pytest.approx(1.5, abs=0.05)
        assert betas["LO"] == pytest.approx(0.5, abs=0.05)
        assert pr.portfolio_beta({"HI": 0.2, "LO": 0.4}, betas) == pytest.approx(
            0.2 * betas["HI"] + 0.4 * betas["LO"])

    def test_vol_matches_wSw(self):
        r = factor_returns({"A": 0.6, "B": 0.3}, seed=7)
        rets = pr.returns_frame(_closes_from_returns(r), lookback=500)
        w = {"A": 0.3, "B": 0.2}
        cov = rets[["A", "B"]].cov().to_numpy()
        wv = np.array([0.3, 0.2])
        expected = math.sqrt(wv @ cov @ wv) * math.sqrt(252)
        assert pr.portfolio_volatility(rets, w, min_obs=40) == pytest.approx(expected)
        # two perfectly identical assets: vol adds linearly
        r2 = {"A": r["A"], "A2": r["A"]}
        rets2 = pr.returns_frame(_closes_from_returns(r2), lookback=500)
        v_a = pr.portfolio_volatility(rets2, {"A": 0.5}, min_obs=40)
        assert pr.portfolio_volatility(rets2, {"A": 0.25, "A2": 0.25}, min_obs=40) == pytest.approx(v_a)

    def test_largest_cluster(self):
        r = factor_returns({"A": 0.97, "B": 0.97, "C": 0.0}, seed=2)
        rets = pr.returns_frame(_closes_from_returns(r), lookback=500)
        corr = rets[["A", "B", "C"]].corr()
        assert pr.largest_cluster(corr, 0.7) == ["A", "B"]


def loader_for(r):
    closes = _closes_from_returns(r)
    return lambda syms: {s: closes[s] for s in syms if s in closes}


class TestCheckCorrelationLimit:
    book = [{"symbol": "A", "cost_usd": 1000.0}, {"symbol": "B", "cost_usd": 1000.0}]

    def test_blocks_duplicate(self):
        r = factor_returns({"A": 0.95, "B": 0.0}, seed=4)
        r["CAND"] = r["A"] * 1.1
        chk = pr.check_correlation_limit(symbol="CAND", alloc_usd=500, equity_usd=10_000,
                                         open_book=self.book, closes_loader=loader_for(r))
        assert chk.reason == "correlation_limit"
        assert chk.details["rule"] == "pairwise" and chk.details["max_corr_symbol"] == "A"
        assert chk.details["max_corr"] > 0.99

    def test_allows_uncorrelated(self):
        r = factor_returns({"A": 0.0, "B": 0.0, "CAND": 0.0}, seed=5)
        chk = pr.check_correlation_limit(symbol="CAND", alloc_usd=500, equity_usd=10_000,
                                         open_book=self.book, closes_loader=loader_for(r))
        assert chk.reason is None and chk.details["status"] == "checked"
        assert chk.details["n_open_checked"] == 2

    def test_missing_candidate_history_does_not_block(self):
        r = factor_returns({"A": 0.9, "B": 0.9}, seed=6)
        chk = pr.check_correlation_limit(symbol="CAND", alloc_usd=500, equity_usd=10_000,
                                         open_book=self.book, closes_loader=loader_for(r))
        assert chk.reason is None
        assert chk.details == {"status": "skipped", "why": "no_candidate_history"}

    def test_loader_failure_does_not_block(self):
        def boom(_):
            raise RuntimeError("yahoo down")
        chk = pr.check_correlation_limit(symbol="CAND", alloc_usd=500, equity_usd=10_000,
                                         open_book=self.book, closes_loader=boom)
        assert chk.reason is None and chk.details["status"] == "skipped"

    def test_open_position_without_data_is_ignored(self):
        r = factor_returns({"CAND": 0.0}, seed=8)
        r["A"] = r["CAND"]  # duplicate but B missing
        chk = pr.check_correlation_limit(symbol="CAND", alloc_usd=500, equity_usd=10_000,
                                         open_book=self.book, closes_loader=loader_for(
                                             {k: v for k, v in r.items()}))
        assert chk.reason == "correlation_limit"
        assert chk.details["no_data"] == ["B"]

    def test_no_open_positions_skips_without_fetch(self):
        def boom(_):
            raise AssertionError("should not fetch")
        chk = pr.check_correlation_limit(symbol="CAND", alloc_usd=500, equity_usd=10_000,
                                         open_book=[], closes_loader=boom)
        assert chk.reason is None and chk.details["why"] == "no_open_positions"

    def test_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "brain_correlation_check_enabled", False)
        chk = pr.check_correlation_limit(symbol="CAND", alloc_usd=500, equity_usd=10_000,
                                         open_book=self.book, closes_loader=None)
        assert chk.reason is None and chk.details == {"status": "disabled"}

    def test_beta_cap_optional(self, monkeypatch):
        rng = np.random.default_rng(9)
        spy = rng.standard_normal(N) * 0.01
        r = {"SPY": spy, "A": 2.0 * spy + rng.standard_normal(N) * 0.02,
             "B": rng.standard_normal(N) * 0.01, "CAND": 2.0 * spy + rng.standard_normal(N) * 0.02}
        kw = dict(symbol="CAND", alloc_usd=5_000, equity_usd=10_000, open_book=self.book,
                  closes_loader=loader_for(r))
        assert pr.check_correlation_limit(**kw).reason is None  # cap off by default
        monkeypatch.setattr(settings, "brain_max_portfolio_beta", 1.0)
        chk = pr.check_correlation_limit(**kw)
        assert chk.reason == "portfolio_beta_limit"
        assert chk.details["post_trade_beta"] > 1.0


class TestMetrics:
    def test_metrics_summary(self):
        rng = np.random.default_rng(10)
        spy = rng.standard_normal(N) * 0.01
        r = {"SPY": spy, "A": spy + rng.standard_normal(N) * 0.001,
             "B": spy + rng.standard_normal(N) * 0.001, "C": rng.standard_normal(N) * 0.01}
        book = [{"symbol": s, "cost_usd": 1000.0} for s in ("A", "B", "C", "GONE")]
        m = pr.get_portfolio_risk_metrics(book, 10_000, closes_loader=loader_for(r))
        assert m["n_positions"] == 4
        assert m["missing"] == ["GONE"]
        assert m["largest_cluster"] == {"symbols": ["A", "B"], "weight": 0.2}
        assert m["max_pair"]["a"] in ("A", "B") and m["max_pair"]["corr"] > 0.95
        assert m["beta"] == pytest.approx(0.1 * (m["betas"]["A"] + m["betas"]["B"] + m["betas"]["C"]), abs=1e-3)
        assert m["vol_annual_pct"] > 0

    def test_metrics_empty_book(self):
        m = pr.get_portfolio_risk_metrics([], 10_000, closes_loader=lambda s: {})
        assert m["n_positions"] == 0 and m["beta"] is None
