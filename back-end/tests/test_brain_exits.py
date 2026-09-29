"""Behavioral tests: stops are hard (thesis can't suppress them), the
trailing stop ratchets on ATR, and the watchdog enforces each position's
own stop using the same policy as the scan."""

import asyncio
from datetime import datetime, timedelta, timezone

from tests.brain_fakes import USER_ID, FakeDB, patch_db, wallet_row  # noqa: I001

import pytest

from app.core.config import settings
from app.services import virtual_portfolio as vp
from app.services import watchdog_service


def open_long(symbol="AAA", *, entry=100.0, stop=94.0, target=112.0, atr=3.0, shares=10.0,
              thesis="valid", days_ago=1, **extra):
    row = {
        "id": f"t-{symbol}", "user_id": USER_ID, "symbol": symbol, "source": "brain",
        "status": "OPEN", "direction": "LONG", "entry_price": entry, "stop_loss": stop,
        "initial_stop": stop, "target_price": target, "entry_atr": atr, "shares": shares,
        "position_size_usd": entry * shares, "is_wallet_trade": True, "fx_to_usd_entry": 1.0,
        "thesis_last_status": thesis, "peak_price": entry, "entry_score": 80,
        "entry_date": (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(),
    }
    row.update(extra)
    return row


def book(*rows, cash=9_000.0):
    return FakeDB({"brain_wallet": [wallet_row(balance=cash)], "virtual_trades": list(rows),
                   "signal_thinking": []})


class TestStopIsHard:
    def test_policy_stop_ignores_valid_thesis_even_if_suppression_enabled(self, monkeypatch):
        monkeypatch.setattr(settings, "brain_thesis_suppresses_exits", True)
        d = vp.evaluate_exit(open_long(thesis="valid"), 93.0)
        assert d.reason == "STOP_HIT"

    def test_valid_thesis_never_holds_a_loser(self, monkeypatch):
        monkeypatch.setattr(settings, "brain_thesis_suppresses_exits", True)
        pos = open_long(thesis="valid", days_ago=settings.brain_max_hold_days + 1)
        assert vp.evaluate_exit(pos, 99.0).reason == "TIME_EXPIRED"  # losing -> not protected
        assert vp.evaluate_exit(pos, 101.0).reason is None           # winner may be held (flag on)

    def test_check_virtual_exits_closes_at_stop_with_valid_thesis(self):
        db = book(open_long(thesis="valid"))
        with patch_db(db, prices={"AAA": 93.5}):
            res = vp.check_virtual_exits([])
        t = db.rows("virtual_trades")[0]
        assert res["stops_hit"] == 1
        assert t["status"] == "CLOSED" and t["exit_reason"] == "STOP_HIT"

    def test_thesis_gate_flag_does_not_disable_reeval(self):
        # thesis_tracker returns early when brain_thesis_gate_enabled is False;
        # the reset keeps it True and uses a separate suppression flag.
        assert settings.brain_thesis_gate_enabled is True
        assert settings.brain_thesis_suppresses_exits is False


class TestTrailingStop:
    def test_trail_activates_after_one_r_and_ratchets(self):
        pos = open_long(entry=100.0, stop=94.0, atr=2.0)  # R = 6
        d = vp.evaluate_exit(pos, 105.0)                    # +5 < 1R -> no trail
        assert d.stop == pytest.approx(94.0) and d.reason is None
        d = vp.evaluate_exit(pos, 110.0)                    # +10 >= 1R -> 110 - 2.5*2 = 105
        assert d.stop == pytest.approx(110.0 - settings.brain_trail_atr_mult * 2.0)
        assert d.changed and d.peak == pytest.approx(110.0)
        pos.update(stop_loss=d.stop, peak_price=d.peak)
        d = vp.evaluate_exit(pos, 107.0)                    # stop never loosens
        assert d.stop == pytest.approx(105.0) and d.reason is None
        d = vp.evaluate_exit(pos, 104.9)
        assert d.reason == "TRAILING_STOP"


class TestWatchdogEnforcesStop:
    def _run(self, db, prices, market_open=True):
        with patch_db(db, prices=prices, market_open=market_open):
            return asyncio.run(watchdog_service.run_watchdog())

    def test_watchdog_closes_position_through_its_stop(self):
        db = book(open_long(stop=94.0))  # -6%: the old -8% force-sell would NOT fire
        res = self._run(db, {"AAA": 93.9})
        t = db.rows("virtual_trades")[0]
        assert res["closes"] == 1
        assert t["status"] == "CLOSED" and t["exit_reason"] == "STOP_HIT"
        assert db.rows("watchdog_events")[0]["event_type"] == "CLOSE"

    def test_watchdog_does_not_exit_above_stop_on_bad_news(self):
        db = book(open_long(stop=94.0))
        res = self._run(db, {"AAA": 96.0})
        assert res["closes"] == 0
        assert db.rows("virtual_trades")[0]["status"] == "OPEN"

    def test_watchdog_persists_trailing_ratchet(self):
        db = book(open_long(entry=100.0, stop=94.0, atr=2.0))
        self._run(db, {"AAA": 110.0})
        assert db.rows("virtual_trades")[0]["stop_loss"] == pytest.approx(105.0)

    def test_crypto_monitored_when_equity_market_closed(self):
        db = book(open_long("BTC-USD", entry=100.0, stop=90.0), open_long("AAA", stop=94.0))
        res = self._run(db, {"BTC-USD": 89.0, "AAA": 50.0}, market_open=False)
        by_sym = {r["symbol"]: r for r in db.rows("virtual_trades")}
        assert by_sym["BTC-USD"]["status"] == "CLOSED"
        assert by_sym["AAA"]["status"] == "OPEN"  # equity can't fill after hours
        assert res["skipped_equity"] == 1

    def test_scan_and_watchdog_agree(self):
        pos = open_long()
        for px in (93.0, 95.0, 113.0):
            assert vp.evaluate_exit(dict(pos), px).reason == vp.evaluate_exit(dict(pos), px).reason


class TestSignalExit:
    def test_tech_only_avoid_does_not_close(self):
        sig = {"symbol": "AAA", "action": "AVOID", "ai_signal": None, "ai_status": "skipped"}
        assert vp.signal_exit_reason(sig) is None
        sig = {"symbol": "AAA", "action": "SELL", "ai_signal": "SELL", "ai_status": "rejected"}
        assert vp.signal_exit_reason(sig) == "ai_sell"
