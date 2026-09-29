"""Behavioral tests: risk-based sizing and portfolio limits."""

from tests.brain_fakes import FakeDB, patch_db, wallet_row  # noqa: I001

import pytest

from app.core.config import settings
from app.services import virtual_portfolio as vp
from app.services.wallet import calc_risk_position_size
from tests.test_brain_entry_gate import brain_trades, make_sig


class TestRiskSizeMath:
    def test_one_percent_risk_when_under_cap(self):
        # equity 10k, 1% = $100 risk; entry 50, stop 40 -> $10/share -> 10 shares = $500 (5%)
        shares, alloc = calc_risk_position_size(10_000, 10_000, 50.0, 40.0,
                                                risk_pct=1.0, max_position_pct=10.0,
                                                min_trade_usd=100, commission_usd=0)
        assert shares == pytest.approx(10.0)
        assert alloc == pytest.approx(500.0)
        assert shares * (50.0 - 40.0) == pytest.approx(100.0)  # loss at stop = 1% equity

    def test_capped_at_max_position_pct(self):
        # tight stop: $100 / $1 = 100 shares * $50 = $5,000 -> capped to 10% = $1,000
        shares, alloc = calc_risk_position_size(10_000, 10_000, 50.0, 49.0,
                                                risk_pct=1.0, max_position_pct=10.0,
                                                min_trade_usd=100, commission_usd=0)
        assert alloc == pytest.approx(1_000.0)
        assert shares == pytest.approx(20.0)

    def test_capped_by_free_cash_and_minimum(self):
        _, alloc = calc_risk_position_size(10_000, 300, 50.0, 40.0, risk_pct=1.0,
                                           max_position_pct=10.0, min_trade_usd=100, commission_usd=0)
        assert alloc == pytest.approx(300.0)
        assert calc_risk_position_size(10_000, 50, 50.0, 40.0, min_trade_usd=100) == (0.0, 0.0)

    def test_invalid_stop_means_no_trade(self):
        assert calc_risk_position_size(10_000, 10_000, 50.0, 50.0) == (0.0, 0.0)
        assert calc_risk_position_size(10_000, 10_000, 50.0, 55.0) == (0.0, 0.0)

    def test_defaults(self):
        assert settings.brain_risk_per_trade_pct == 1.0
        assert settings.brain_max_position_pct == 10.0
        assert settings.brain_max_open_positions == 8
        assert settings.brain_max_per_sector == 2
        assert settings.brain_max_crypto_pct == 25.0


class TestEndToEndSizing:
    def test_loss_at_stop_is_one_percent_of_equity(self):
        db = FakeDB({"brain_wallet": [wallet_row()], "virtual_trades": []})
        with patch_db(db):
            vp.process_virtual_trades([make_sig(price=100.0, stop=None, target=None, atr=6.0)], set(), [])
        (t,) = brain_trades(db)
        risk_usd = t["shares"] * (t["entry_price"] - t["stop_loss"])
        assert risk_usd == pytest.approx(100.0, rel=1e-3)
        assert t["position_size_usd"] <= 1_000.0 + 1e-6
        assert db.rows("brain_wallet")[0]["balance"] == pytest.approx(10_000 - t["position_size_usd"])


class TestPortfolioLimits:
    def book(self, n, **kw):
        return [{"symbol": f"S{i}", "sector": kw.get("sector", f"X{i}"),
                 "is_crypto": kw.get("is_crypto", False), "cost_usd": kw.get("cost", 500.0)}
                for i in range(n)]

    def test_crypto_cap_shrinks_then_blocks(self):
        # 25% of 10k = 2,500; 2,000 already in crypto -> only 500 room
        alloc, reason = vp.check_portfolio_limits(
            symbol="ETH-USD", sector=None, is_crypto=True, alloc_usd=1_000,
            equity_usd=10_000, open_book=self.book(2, is_crypto=True, cost=1_000))
        assert reason is None and alloc == pytest.approx(500.0)
        alloc, reason = vp.check_portfolio_limits(
            symbol="ETH-USD", sector=None, is_crypto=True, alloc_usd=1_000,
            equity_usd=10_000, open_book=self.book(2, is_crypto=True, cost=1_250))
        assert reason == "crypto_cap"

    def test_sector_and_max_open(self):
        _, reason = vp.check_portfolio_limits(
            symbol="NEW", sector="Energy", is_crypto=False, alloc_usd=500,
            equity_usd=10_000, open_book=self.book(2, sector="Energy"))
        assert reason.startswith("sector_cap")
        _, reason = vp.check_portfolio_limits(
            symbol="NEW", sector="Energy", is_crypto=False, alloc_usd=500,
            equity_usd=10_000, open_book=self.book(8))
        assert reason.startswith("max_open_positions")
