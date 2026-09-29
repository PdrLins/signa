"""Behavioral tests: wallet atomicity ordering, reconcile_wallet, drawdown breaker."""

from tests.brain_fakes import USER_ID, FakeDB, patch_db, wallet_row  # noqa: I001

import pytest

from app.core.config import settings
from app.services import virtual_portfolio as vp
from app.services import wallet
from tests.test_brain_entry_gate import brain_trades, make_sig
from tests.test_brain_exits import book, open_long


class TestReconcile:
    def test_identity_holds(self):
        r = wallet.reconcile_numbers(balance=8_950.0, collateral=0.0, open_long_cost_basis=1_000.0,
                                     net_deposits=10_000.0, realized_pnl=-50.0)
        assert r["ok"] and r["diff"] == 0

    def test_detects_uncredited_close(self):
        r = wallet.reconcile_numbers(balance=8_000.0, collateral=0.0, open_long_cost_basis=1_000.0,
                                     net_deposits=10_000.0, realized_pnl=0.0)
        assert not r["ok"] and r["diff"] == pytest.approx(-1_000.0)

    def test_reconcile_after_real_open_and_close(self):
        db = FakeDB({"brain_wallet": [wallet_row()], "virtual_trades": [], "signal_thinking": []})
        with patch_db(db, prices={"AAA": 130.0}):
            vp.process_virtual_trades([make_sig(price=100.0)], set(), [])
            assert wallet.reconcile_wallet(USER_ID)["ok"]
            vp.check_virtual_exits([])  # 130 > target 115 -> TARGET_HIT
            assert brain_trades(db)[0]["status"] == "CLOSED"
            assert wallet.reconcile_wallet(USER_ID)["ok"]


class TestAtomicOrdering:
    def test_insert_failure_refunds_debit(self):
        db = FakeDB({"brain_wallet": [wallet_row()], "virtual_trades": []})
        db.fail_ops["insert"] = {"virtual_trades"}
        with patch_db(db):
            res = vp.process_virtual_trades([make_sig()], set(), [])
        assert res["buys"] == 0
        assert db.rows("brain_wallet")[0]["balance"] == pytest.approx(10_000.0)
        assert not db.rows("wallet_transactions")

    def test_debit_happens_before_insert(self):
        db = FakeDB({"brain_wallet": [wallet_row()], "virtual_trades": []})
        with patch_db(db):
            vp.process_virtual_trades([make_sig()], set(), [])
        order = [(c[0], c[1]) for c in db.calls if c[1] in ("insert", "update")]
        assert order.index(("brain_wallet", "update")) < order.index(("virtual_trades", "insert"))
        (tx,) = db.rows("wallet_transactions")
        assert tx["trade_id"] == brain_trades(db)[0]["id"]

    def test_close_already_closed_elsewhere_reverses_credit(self):
        trade = open_long()
        db = book(dict(trade, status="CLOSED"))  # another path won the race
        with patch_db(db):
            res = vp.close_virtual_trade(trade, 120.0, "TARGET_HIT", None)
        assert res["skipped"]
        assert db.rows("brain_wallet")[0]["balance"] == pytest.approx(9_000.0)

    def test_close_update_error_reverses_credit(self):
        db = book(open_long())
        db.fail_ops["update"] = {"virtual_trades"}
        with patch_db(db):
            res = vp.close_virtual_trade(db.rows("virtual_trades")[0], 120.0, "TARGET_HIT", None)
        assert res["skipped"] and db.rows("virtual_trades")[0]["status"] == "OPEN"
        assert db.rows("brain_wallet")[0]["balance"] == pytest.approx(9_000.0)


class TestDrawdownBreaker:
    def test_pure_peak_to_trough(self):
        assert not vp.drawdown_breaker_tripped(9_100, 10_000, 10)
        assert vp.drawdown_breaker_tripped(9_000, 10_000, 10)
        # measured from the PEAK, not from starting capital or cumulative P&L
        assert vp.drawdown_breaker_tripped(10_700, 12_000, 10)
        assert settings.brain_max_drawdown_pct == 10.0

    def test_breaker_blocks_new_entries(self):
        db = FakeDB({"brain_wallet": [wallet_row(balance=10_700.0, deposited=10_000.0, peak=12_000.0)],
                     "virtual_trades": []})
        with patch_db(db):
            vp.process_virtual_trades([make_sig()], set(), [])
        assert brain_trades(db) == []
        assert db.rows("brain_decisions")[0]["reason"].startswith("drawdown_breaker")

    def test_peak_ratchets_up_with_equity(self):
        db = FakeDB({"brain_wallet": [wallet_row(balance=11_000.0, peak=10_000.0)], "virtual_trades": []})
        with patch_db(db):
            vp.process_virtual_trades([], set(), [])
        assert db.rows("brain_wallet")[0]["peak_equity"] == pytest.approx(11_000.0)
