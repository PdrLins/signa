"""Behavioral tests: slippage/commission on both sides, and CAD→USD FX."""

from tests.brain_fakes import FakeDB, patch_db, wallet_row  # noqa: I001

import pytest

from app.core.config import settings
from app.services import virtual_portfolio as vp
from tests.test_brain_entry_gate import brain_trades, make_sig
from tests.test_brain_exits import book, open_long


def bps(symbol):
    return vp.slippage_bps(symbol) / 10_000


class TestSlippageBothSides:
    def test_defaults(self):
        assert settings.brain_slippage_bps_stock == 10.0
        assert settings.brain_slippage_bps_crypto == 20.0

    def test_entry_fill_pays_up(self):
        db = FakeDB({"brain_wallet": [wallet_row()], "virtual_trades": []})
        with patch_db(db):
            vp.process_virtual_trades([make_sig(price=100.0)], set(), [])
        (t,) = brain_trades(db)
        assert t["entry_ref_price"] == 100.0
        assert t["entry_price"] == pytest.approx(100.0 * (1 + bps("AAA")))

    def test_exit_fill_receives_less_and_pnl_is_net(self):
        db = book(open_long(entry=100.0, shares=10.0))
        with patch_db(db, prices={"AAA": 120.0}):
            vp.check_virtual_exits([])
        t = db.rows("virtual_trades")[0]
        fill = 120.0 * (1 - bps("AAA"))
        assert t["exit_ref_price"] == 120.0
        assert t["exit_price"] == pytest.approx(fill)
        assert t["pnl_amount"] == pytest.approx(10 * fill - 1_000.0, abs=1e-3)
        assert db.rows("brain_wallet")[0]["balance"] == pytest.approx(9_000.0 + 10 * fill)

    def test_crypto_uses_wider_slippage(self):
        assert vp.apply_slippage(100.0, "BUY", "BTC-USD") == pytest.approx(100.2)
        assert vp.apply_slippage(100.0, "SELL", "BTC-USD") == pytest.approx(99.8)

    def test_round_trip_at_same_quote_loses_costs(self, monkeypatch):
        monkeypatch.setattr(settings, "brain_commission_usd", 1.0)
        trade = open_long(entry=vp.apply_slippage(50.0, "BUY", "AAA"), shares=20.0)
        trade["position_size_usd"] = trade["entry_price"] * 20 + 1.0  # entry commission in basis
        amounts = vp.compute_close_amounts(trade, 50.0)
        expected = 20 * 50.0 * (1 - bps("AAA")) - 1.0 - trade["position_size_usd"]
        assert amounts["pnl_usd"] == pytest.approx(expected)
        assert amounts["pnl_usd"] < -2.0  # two commissions + two slippages


class TestFX:
    def test_cad_listing_sized_and_booked_in_usd(self):
        db = FakeDB({"brain_wallet": [wallet_row()], "virtual_trades": []})
        with patch_db(db, fx=0.72):
            vp.process_virtual_trades([make_sig("RY.TO", price=100.0, stop=None, target=None, atr=6.0)], set(), [])
        (t,) = brain_trades(db)
        assert t["currency"] == "CAD" and t["fx_to_usd_entry"] == 0.72
        # prices stay native (CAD); cash is USD
        assert t["position_size_usd"] == pytest.approx(t["shares"] * t["entry_price"] * 0.72, rel=1e-4)
        risk_usd = t["shares"] * (t["entry_price"] - t["stop_loss"]) * 0.72
        assert risk_usd == pytest.approx(100.0, rel=1e-3)

    def test_cad_listing_skipped_without_fx(self):
        db = FakeDB({"brain_wallet": [wallet_row()], "virtual_trades": []})
        with patch_db(db, fx=None):
            vp.process_virtual_trades([make_sig("RY.TO")], set(), [])
        assert brain_trades(db) == []
        assert db.rows("brain_decisions")[0]["reason"] == "fx_unavailable_CAD"
