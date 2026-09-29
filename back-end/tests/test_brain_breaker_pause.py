"""Drawdown breaker: trip → pause N US trading days → reset peak → resume.

The old breaker compared equity to an all-time peak forever. Once the book
is flat in cash equity cannot climb back to that peak, so a single trip
blocked entries permanently (backtest: 1,734 blocked days after one trip).
"""

from tests.brain_fakes import USER_ID, FakeDB, patch_db, wallet_row  # noqa: I001

from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from app.core.config import settings
from app.core.market_calendar import is_us_trading_day, us_trading_days_between
from app.services import virtual_portfolio as vp
from app.services import wallet
from backtest.portfolio import FX, SimConfig, Simulator
from backtest.signals import SignalConfig
from tests.test_brain_entry_gate import brain_trades, make_sig

N = 10


def ev(equity, peak, tripped_at, now, n=N):
    return vp.evaluate_drawdown_breaker(equity, peak, tripped_at, now,
                                        max_drawdown_pct=10.0, pause_trading_days=n)


class TestPureBreaker:
    def test_defaults(self):
        assert settings.brain_drawdown_pause_trading_days == 10
        assert settings.brain_max_drawdown_pct == 10.0

    def test_no_drawdown_not_blocked_and_peak_ratchets(self):
        st = ev(11_000, 10_000, None, date(2026, 9, 21))
        assert not st.blocked and st.event is None and st.tripped_at is None
        assert st.peak == 11_000

    def test_small_drawdown_keeps_peak(self):
        st = ev(9_500, 10_000, None, date(2026, 9, 21))
        assert not st.blocked and st.peak == 10_000

    def test_trip(self):
        now = date(2026, 9, 21)
        st = ev(9_000, 10_000, None, now)
        assert st.blocked and st.event == "tripped" and st.tripped_at == now
        assert st.reason == "drawdown_breaker_pause"
        assert (st.days_elapsed, st.days_remaining) == (0, N)

    def test_pause_counts_trading_days(self):
        # tripped Mon 21 Sep 2026; Fri 25 = 4 sessions later
        st = ev(9_000, 10_000, date(2026, 9, 21), date(2026, 9, 25))
        assert st.blocked and st.event is None
        assert (st.days_elapsed, st.days_remaining) == (4, 6)

    def test_weekend_does_not_count(self):
        fri = date(2026, 9, 25)
        assert ev(9_000, 10_000, fri, date(2026, 9, 27)).days_elapsed == 0  # Sunday
        assert ev(9_000, 10_000, fri, date(2026, 9, 28)).days_elapsed == 1  # Monday

    def test_holiday_does_not_count(self):
        # Thanksgiving 2026-11-26 is closed. Trip Fri 20 Nov: 10 sessions end Mon 7 Dec
        # (a weekday-only count would already be 10 on Fri 4 Dec).
        assert not is_us_trading_day(date(2026, 11, 26))
        assert us_trading_days_between(date(2026, 11, 25), date(2026, 11, 27)) == 1
        trip = date(2026, 11, 20)
        st = ev(9_000, 10_000, trip, date(2026, 12, 4))
        assert st.blocked and st.days_elapsed == 9
        st = ev(9_000, 10_000, trip, date(2026, 12, 7))
        assert not st.blocked and st.event == "resumed"

    def test_backtest_years_use_rule_holidays(self):
        # 2024 has no hardcoded list: rules still apply (MLK Day 15 Jan 2024)
        assert not is_us_trading_day(date(2024, 1, 15))
        assert is_us_trading_day(date(2021, 6, 18))  # Juneteenth not observed before 2022

    def test_resume_resets_peak_to_equity(self):
        st = ev(8_700, 10_000, date(2026, 9, 7), date(2026, 9, 28))
        assert not st.blocked and st.event == "resumed"
        assert st.peak == 8_700 and st.tripped_at is None
        # next evaluation from the reset peak: no immediate re-trip
        again = ev(8_700, st.peak, st.tripped_at, date(2026, 9, 29))
        assert not again.blocked and again.event is None

    def test_iso_strings_are_accepted(self):
        trip = "2026-09-21T15:00:00+00:00"
        st = ev(9_000, 10_000, trip, datetime(2026, 9, 22, 15, tzinfo=timezone.utc))
        assert st.blocked and st.days_elapsed == 1 and st.tripped_at == trip


def _run(db, sigs=None):
    q: list = []
    with patch_db(db):
        vp.process_virtual_trades(sigs if sigs is not None else [make_sig()], set(), q)
    return q


class TestLiveWiring:
    def test_trip_is_persisted_logged_and_notified_once(self):
        db = FakeDB({"brain_wallet": [wallet_row(balance=10_700.0, peak=12_000.0)], "virtual_trades": []})
        q = _run(db)
        assert brain_trades(db) == []
        w = db.rows("brain_wallet")[0]
        assert w["breaker_tripped_at"] is not None
        (d,) = db.rows("brain_decisions")
        assert d["reason"] == "drawdown_breaker_pause"
        assert d["details"]["breaker"]["days_remaining"] == settings.brain_drawdown_pause_trading_days
        assert d["details"]["breaker"]["days_elapsed"] == 0
        assert [k for k, _ in q] == ["brain_breaker_tripped"]

        # second scan during the pause: still blocked, no second notification
        q2 = _run(db, [make_sig("BBB")])
        assert q2 == [] and brain_trades(db) == []
        assert db.rows("brain_decisions")[-1]["reason"] == "drawdown_breaker_pause"

    def test_resume_after_pause_resets_peak_and_enters(self):
        long_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        row = dict(wallet_row(balance=10_700.0, peak=12_000.0), breaker_tripped_at=long_ago)
        db = FakeDB({"brain_wallet": [row], "virtual_trades": []})
        q = _run(db)
        w = db.rows("brain_wallet")[0]
        assert w["breaker_tripped_at"] is None
        assert w["peak_equity"] == pytest.approx(10_700.0)
        assert ("brain_breaker_resumed" in [k for k, _ in q])
        assert len(brain_trades(db)) == 1
        # the reset peak is BELOW net deposits (10k) — it must not be floored back up
        _run(db, [make_sig("BBB")])
        assert db.rows("brain_wallet")[0]["breaker_tripped_at"] is None

    def test_missing_column_falls_back_without_crashing(self):
        row = wallet_row(balance=10_700.0, peak=12_000.0)
        row.pop("breaker_tripped_at")  # migration 009 not applied
        db = FakeDB({"brain_wallet": [row], "virtual_trades": []})
        q = _run(db)
        assert brain_trades(db) == []
        assert db.rows("brain_decisions")[0]["reason"] == "drawdown_breaker_pause"
        assert q == []  # would repeat every scan — suppressed
        assert not any("breaker_tripped_at" in (c[2] or {}) for c in db.ops("brain_wallet", "update"))

    def test_set_breaker_state_never_raises(self):
        db = FakeDB({"brain_wallet": [wallet_row()]})
        db.fail_ops["update"] = {"brain_wallet"}
        with patch_db(db):
            assert wallet.set_breaker_state(USER_ID, tripped_at=None, peak_equity=1.0) is False


class TestBacktestBreaker:
    def test_breaker_no_longer_latches(self):
        # April 2024: 22 sessions, no NYSE holiday. Force a trip on day 1 with
        # an artificial peak 2x equity; the old breaker blocked all month.
        days = [ts.date() for ts in pd.bdate_range("2024-04-01", "2024-04-30")]
        idx = pd.DatetimeIndex([pd.Timestamp(d) for d in days])
        df = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0,
                           "Volume": 1e6}, index=idx)
        sigs = {d: [{"date": d, "symbol": "AAA", "score": 80, "action": "BUY", "blocked": False,
                     "blackout": None, "bucket": "HIGH_RISK", "sector": None,
                     "market_regime": "TRENDING", "technical_data": {"atr": 2.0}}] for d in days}
        sim = Simulator(days, sigs, {"AAA": df}, FX(None),
                        SimConfig(correlation_gate=False, signal=SignalConfig(entry_mode="score")))
        sim.peak = 20_000.0
        res = sim.run()
        assert res.breaker_trips == 1 and res.breaker_resumes == 1
        assert res.breaker_days == settings.brain_drawdown_pause_trading_days
        assert res.skips["drawdown_breaker_pause"] >= 1
        assert res.trades and res.trades[0]["entry_date"] == "2024-04-15"  # 10th session after Apr 1
