"""Behavioral tests: the brain only auto-buys an AI BUY with R:R >= 2.

Every test drives the real `process_virtual_trades` against the in-memory
FakeDB (tests/brain_fakes.py) and asserts on what was written.
"""

from tests.brain_fakes import USER_ID, FakeDB, patch_db, wallet_row  # noqa: I001

import pytest

from app.core.config import settings
from app.services import virtual_portfolio as vp


def make_sig(symbol="AAA", *, ai_status="validated", ai_signal="BUY", score=80,
             price=100.0, stop=94.0, target=115.0, atr=3.0, sector="Technology", **extra):
    sig = {
        "symbol": symbol, "action": "BUY" if ai_signal == "BUY" else "HOLD",
        "score": score, "price_at_signal": price, "ai_status": ai_status, "ai_signal": ai_signal,
        "stop_loss": stop, "target_price": target, "bucket": "HIGH_RISK",
        "technical_data": {"atr": atr}, "fundamental_data": {"sector": sector},
        "scan_id": "scan-1", "p_win": 0.55,
    }
    sig.update(extra)
    return sig


def run(signals, db=None, **kw):
    db = db or FakeDB({"brain_wallet": [wallet_row()], "virtual_trades": []})
    with patch_db(db, **kw):
        result = vp.process_virtual_trades(signals, set(), [])
    return db, result


def brain_trades(db):
    return [r for r in db.rows("virtual_trades") if r.get("source") == "brain"]


class TestNoAutoBuyWithoutAIBuy:
    @pytest.mark.parametrize("ai_status,ai_signal", [
        ("skipped", None),          # tech-only (old Tier 3)
        ("low_confidence", "BUY"),  # old Tier 2
        ("failed", None),
        ("rejected", "SELL"),
        ("rejected", "HOLD"),
        ("validated", "HOLD"),      # validated but Claude did not say BUY
    ])
    def test_non_ai_buy_is_never_bought(self, ai_status, ai_signal):
        db, res = run([make_sig(ai_status=ai_status, ai_signal=ai_signal, score=95)])
        assert brain_trades(db) == []
        assert res["buys"] == 0
        (decision,) = db.rows("brain_decisions")
        assert decision["decision"] == "SKIP"
        assert decision["ai_status"] == ai_status

    def test_ai_buy_is_bought_and_logged(self):
        db, res = run([make_sig()])
        (trade,) = brain_trades(db)
        assert trade["entry_ai_signal"] == "BUY"
        assert trade["initial_stop"] == trade["stop_loss"]
        (decision,) = db.rows("brain_decisions")
        assert decision["decision"] == "ENTER"
        assert decision["details"]["trade_id"] == trade["id"]
        assert decision["scan_id"] == "scan-1"

    def test_score_floor_still_applies(self):
        db, _ = run([make_sig(score=vp.BRAIN_MIN_SCORE - 1)])
        assert brain_trades(db) == []


class TestRewardRisk:
    def test_claude_levels_below_min_rr_are_rejected(self):
        # fill ~100.10, stop 94 -> risk ~6.1; target 108 -> reward ~7.9 -> R:R 1.3
        db, _ = run([make_sig(stop=94.0, target=108.0)])
        assert brain_trades(db) == []
        assert db.rows("brain_decisions")[0]["reason"].startswith("rr_below_min")

    def test_missing_levels_fall_back_to_atr(self):
        db, _ = run([make_sig(stop=None, target=None, atr=2.0)])
        (t,) = brain_trades(db)
        fill = t["entry_price"]
        assert t["stop_loss"] == pytest.approx(fill - settings.brain_stop_atr_mult * 2.0)
        assert t["target_price"] == pytest.approx(fill + settings.brain_target_r_mult * (fill - t["stop_loss"]))
        assert t["entry_rr"] == pytest.approx(settings.brain_target_r_mult)

    def test_no_levels_and_no_atr_is_skipped(self):
        db, _ = run([make_sig(stop=None, target=None, atr=None)])
        assert brain_trades(db) == []

    def test_compute_entry_levels_rr_is_from_fill_price(self):
        lv = vp.compute_entry_levels(make_sig(stop=90.0, target=120.0), 100.0)
        assert lv["rr"] == pytest.approx(2.0)
        assert lv["reason"] is None


class TestNoRotationAndSlots:
    def test_full_book_waits_instead_of_rotating(self):
        open_rows = [
            {"id": f"t{i}", "symbol": f"H{i}", "source": "brain", "status": "OPEN", "direction": "LONG",
             "entry_price": 10.0, "shares": 10, "position_size_usd": 100.0, "is_wallet_trade": True,
             "sector": f"S{i}", "entry_score": 60, "user_id": USER_ID}
            for i in range(settings.brain_max_open_positions)
        ]
        db = FakeDB({"brain_wallet": [wallet_row(balance=9_200.0)], "virtual_trades": open_rows})
        db, _ = run([make_sig(score=99)], db=db)
        assert len(brain_trades(db)) == settings.brain_max_open_positions
        assert not db.ops("virtual_trades", "update")  # nothing rotated out
        assert db.rows("brain_decisions")[0]["reason"].startswith("max_open_positions")

    def test_sector_cap(self):
        sigs = [make_sig(f"T{i}", sector="Technology", score=90 - i) for i in range(3)]
        db, _ = run(sigs)
        assert len(brain_trades(db)) == settings.brain_max_per_sector

    def test_reentry_cooldown_after_any_exit(self):
        from datetime import datetime, timezone
        closed = {"id": "c1", "symbol": "AAA", "source": "brain", "status": "CLOSED",
                  "exit_date": datetime.now(timezone.utc).isoformat(), "pnl_amount": 50.0}
        db = FakeDB({"brain_wallet": [wallet_row()], "virtual_trades": [closed]})
        db, _ = run([make_sig("AAA")], db=db)
        assert brain_trades(db) == [closed]
        assert db.rows("brain_decisions")[0]["reason"].startswith("reentry_cooldown")


class TestTradingDays:
    def test_trading_days_between_skips_weekends(self):
        from datetime import date
        assert vp.trading_days_between(date(2026, 9, 25), date(2026, 9, 28)) == 1  # Fri -> Mon
        assert vp.trading_days_between(date(2026, 9, 21), date(2026, 9, 24)) == 3
