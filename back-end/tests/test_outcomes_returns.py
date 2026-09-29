"""Counterfactual outcome tracking: horizons, return math, seed + fill (no network)."""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.services import decision_outcomes as do
from tests.brain_fakes import FakeDB

ET = ZoneInfo("America/New_York")
UTC = timezone.utc


def et(y, m, d, hh=10, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ET)


# ── calendar / horizons ─────────────────────────────────────────

def test_classify_exchange():
    assert do.classify_exchange("BTC-USD") == "CRYPTO"
    assert do.classify_exchange("XYZ", asset_type="crypto") == "CRYPTO"
    assert do.classify_exchange("RY.TO") == "TSX"
    assert do.classify_exchange("AAPL", "NASDAQ") == "NASDAQ"
    assert do.classify_exchange("KO") == "NYSE"


def test_horizon_counts_trading_days_skipping_weekend_and_us_holiday():
    # Wed before Thanksgiving: 11/26 closed -> 11/27, 11/30, 12/1, 12/2, 12/3
    assert do.horizon_date(et(2026, 11, 25), 5, "NYSE") == date(2026, 12, 3)
    # Friday signal: 5 sessions = next Friday
    assert do.horizon_date(et(2026, 9, 18), 5, "NYSE") == date(2026, 9, 25)


def test_horizon_uses_exchange_calendar_tsx_vs_nyse():
    # CA Thanksgiving Mon 2026-10-12 is a TSX holiday, not NYSE.
    assert do.horizon_date(et(2026, 10, 9), 5, "NYSE") == date(2026, 10, 16)
    assert do.horizon_date(et(2026, 10, 9), 5, "TSX") == date(2026, 10, 19)


def test_horizon_crypto_calendar_days_in_utc():
    # 22:00 ET Sat = 02:00 UTC Sun -> start Sun (UTC) + 5 = Fri
    sig = et(2026, 9, 19, 22)
    assert do.horizon_date(sig, 5, "CRYPTO") == date(2026, 9, 25)
    assert do.horizon_date(sig, 20, "CRYPTO") == date(2026, 10, 10)


def test_horizon_elapsed_equity_waits_for_close():
    sig = et(2026, 9, 18)  # 5d horizon = Fri 9/25
    assert not do.horizon_elapsed(sig, 5, "NYSE", et(2026, 9, 25, 15, 59))
    assert do.horizon_elapsed(sig, 5, "NYSE", et(2026, 9, 25, 16, 1))
    assert not do.horizon_elapsed(sig, 10, "NYSE", et(2026, 9, 25, 17))


def test_horizon_elapsed_crypto_needs_utc_day_over():
    sig = datetime(2026, 9, 20, 12, tzinfo=UTC)  # 5d -> 9/25 UTC
    assert not do.horizon_elapsed(sig, 5, "CRYPTO", datetime(2026, 9, 25, 23, tzinfo=UTC))
    assert do.horizon_elapsed(sig, 5, "CRYPTO", datetime(2026, 9, 26, 0, 5, tzinfo=UTC))


def test_reference_close_date():
    # intraday Monday -> previous Friday's close
    assert do.reference_close_date(et(2026, 9, 21, 10)) == date(2026, 9, 18)
    # after the close -> same day
    assert do.reference_close_date(et(2026, 9, 21, 16, 30)) == date(2026, 9, 21)
    # Tuesday after Labor Day intraday -> Friday before
    assert do.reference_close_date(et(2026, 9, 8, 11)) == date(2026, 9, 4)
    # weekend -> Friday
    assert do.reference_close_date(et(2026, 9, 20, 12)) == date(2026, 9, 18)


# ── return math ─────────────────────────────────────────────────

def test_simple_and_excess_return():
    assert do.simple_return(100, 110) == pytest.approx(0.10)
    assert do.simple_return(100, None) is None
    assert do.simple_return(0, 5) is None
    assert do.simple_return("100", "90") == pytest.approx(-0.10)
    assert do.excess_return(0.10, 0.03) == pytest.approx(0.07)
    assert do.excess_return(None, 0.03) is None


def test_close_asof_gap_tolerance():
    s = [(date(2026, 9, 18), 10.0), (date(2026, 9, 21), 11.0)]
    assert do.close_asof(s, date(2026, 9, 21)) == 11.0
    assert do.close_asof(s, date(2026, 9, 20)) == 10.0  # weekend -> Friday
    assert do.close_asof(s, date(2026, 9, 17)) is None
    assert do.close_asof(s, date(2026, 10, 5)) is None  # stale beyond 5 days
    assert do.close_asof([], date(2026, 9, 21)) is None


def test_entry_base_price_split_guard():
    assert do.entry_base_price(100.0, 98.0) == 100.0
    # 2:1 split inside window: series is post-split adjusted (50) -> use it
    assert do.entry_base_price(100.0, 50.0) == 50.0
    assert do.entry_base_price(None, 50.0) == 50.0


def _series(start: date, days: int, f) -> list:
    out, d = [], start
    for _ in range(days):
        if d.weekday() < 5:
            out.append((d, f(d)))
        d += timedelta(days=1)
    return out


def test_compute_row_fill_only_elapsed_horizons():
    sig = et(2026, 9, 1, 10)  # Tue; ref close Mon 8/31
    stock = _series(date(2026, 8, 25), 60, lambda d: 100.0 + (d - date(2026, 9, 1)).days)
    spy = _series(date(2026, 8, 25), 60, lambda d: 500.0)
    spy = [(d, 510.0 if d >= date(2026, 9, 2) else 500.0) for d, _ in spy]
    row = {"symbol": "KO", "exchange": "NYSE", "signal_at": sig.isoformat(), "price_at_signal": 100.0}
    h5 = do.horizon_date(sig, 5, "NYSE")   # 9/9 (Labor day skipped)
    h10 = do.horizon_date(sig, 10, "NYSE")
    assert h5 == date(2026, 9, 9)
    now = datetime.combine(h10, datetime.min.time(), ET).replace(hour=17)
    out = do.compute_row_fill(row, stock, spy, now)
    exp5 = (100.0 + (h5 - date(2026, 9, 1)).days) / 100.0 - 1
    assert out["fwd_ret_5d"] == pytest.approx(exp5, abs=1e-6)
    assert out["spy_ret_5d"] == pytest.approx(0.02)
    assert out["excess_ret_5d"] == pytest.approx(exp5 - 0.02, abs=1e-6)
    assert "fwd_ret_10d" in out and "filled_10d_at" in out
    assert "fwd_ret_20d" not in out  # not elapsed

    # Idempotent: an already-filled horizon is never recomputed.
    row2 = {**row, "filled_5d_at": "x", "filled_10d_at": "x"}
    assert do.compute_row_fill(row2, stock, spy, now) == {}


def test_compute_row_fill_missing_data_left_for_retry():
    sig = et(2026, 9, 1, 10)
    row = {"symbol": "GONE", "signal_at": sig.isoformat(), "price_at_signal": 10.0}
    spy = _series(date(2026, 8, 25), 60, lambda d: 500.0)
    now = et(2026, 10, 30, 17)
    assert do.compute_row_fill(row, None, spy, now) == {}
    assert do.compute_row_fill(row, [(date(2026, 8, 31), 10.0)], spy, now) == {}


# ── seed + fill against a fake DB ───────────────────────────────

def _signal(i, symbol, scan, created, price=100.0, **kw):
    return {"id": f"s{i}", "scan_id": scan, "symbol": symbol, "created_at": created,
            "price_at_signal": price, "action": "BUY", "score": 70, "ai_status": "validated",
            "ai_signal": "BUY", "ai_provider": "claude", "p_win": 0.6, "bucket": "HIGH_RISK",
            "exchange": "NYSE", "asset_type": "STOCK", "routine_ai_signal": "BUY",
            "decision_overturned": False, **kw}


def test_build_candidate_rows_joins_brain_decision():
    sigs = [_signal(1, "AAA", "scan1", "2026-09-01T14:00:00+00:00"),
            _signal(2, "BBB", "scan1", "2026-09-01T14:00:00+00:00"),
            _signal(3, "CCC", "scan1", "2026-09-01T14:00:00+00:00", price=None),
            _signal(4, "DDD", "scan1", "2026-09-01T14:00:00+00:00")]
    decs = [{"scan_id": "scan1", "symbol": "AAA", "decision": "SKIP", "reason": "rr_below_min_1.40"},
            {"scan_id": "scan1", "symbol": "BBB", "decision": "ENTER", "reason": "ai_buy"},
            {"scan_id": "scan2", "symbol": "DDD", "decision": "SKIP", "reason": "x"}]
    rows = do.build_candidate_rows(sigs, decs, existing_signal_ids={"s4"})
    by = {r["symbol"]: r for r in rows}
    assert set(by) == {"AAA", "BBB"}  # CCC no price, DDD already tracked
    assert by["AAA"]["brain_decision"] == "SKIP" and by["AAA"]["skip_reason"] == "rr_below_min_1.40"
    assert by["BBB"]["brain_decision"] == "ENTER" and by["BBB"]["skip_reason"] is None
    assert by["AAA"]["routine_signal"] == "BUY" and by["AAA"]["decision_overturned"] is False
    assert by["AAA"]["signal_at"] == "2026-09-01T14:00:00+00:00"


def test_seed_is_idempotent():
    db = FakeDB({
        "signals": [_signal(1, "AAA", "scan1", "2026-09-20T14:00:00+00:00"),
                    _signal(2, "BBB", "scan1", "2026-09-20T14:00:00+00:00")],
        "brain_decisions": [{"scan_id": "scan1", "symbol": "AAA", "decision": "SKIP",
                             "reason": "max_open_positions_8", "decided_at": "2026-09-20T14:01:00+00:00"}],
    })
    since = datetime(2026, 9, 15, tzinfo=UTC)
    with patch("app.db.queries.get_client", return_value=db):
        r1 = do.seed_candidates(since)
        r2 = do.seed_candidates(since)
    assert r1["seeded"] == 2 and r2["seeded"] == 0
    assert len(db.rows("candidate_outcomes")) == 2


def test_fill_forward_returns_batches_one_fetch_and_updates():
    sig_at = et(2026, 9, 1, 10).astimezone(UTC).isoformat()
    db = FakeDB({"candidate_outcomes": [
        {"id": "o1", "symbol": "AAA", "exchange": "NYSE", "signal_at": sig_at, "price_at_signal": 100.0,
         "filled_5d_at": None, "filled_10d_at": None, "filled_20d_at": None},
        {"id": "o2", "symbol": "BTC-USD", "exchange": "CRYPTO", "signal_at": sig_at, "price_at_signal": 50000.0,
         "filled_5d_at": None, "filled_10d_at": None, "filled_20d_at": None},
    ]})
    calls = []

    def fetcher(symbols, start, end):
        calls.append((tuple(symbols), start, end))
        days = [date(2026, 8, 20) + timedelta(days=i) for i in range(60)]
        return {
            "AAA": [(d, 110.0) for d in days if d.weekday() < 5],
            "BTC-USD": [(d, 55000.0) for d in days],
            "SPY": [(d, 500.0) for d in days if d.weekday() < 5],
        }

    now = et(2026, 9, 16, 17)  # 10 NYSE sessions after 9/1 = 9/16; crypto 10d = 9/11
    with patch("app.db.queries.get_client", return_value=db), \
            patch.object(do.settings, "outcomes_fill_max_age_days", 60):
        res = do.fill_forward_returns(now=now, fetcher=fetcher)
    assert len(calls) == 1 and "SPY" in calls[0][0]
    assert res["updated"] == 2
    o1, o2 = db.rows("candidate_outcomes")
    assert o1["fwd_ret_5d"] == pytest.approx(0.10) and o1["excess_ret_10d"] == pytest.approx(0.10)
    assert o1.get("fwd_ret_20d") is None and o1.get("filled_20d_at") is None
    assert o2["fwd_ret_10d"] == pytest.approx(0.10)

    # second run: nothing new elapsed -> no fetch, nothing updated
    calls.clear()
    with patch("app.db.queries.get_client", return_value=db):
        res2 = do.fill_forward_returns(now=now, fetcher=fetcher)
    assert res2["updated"] == 0 and calls == []


def test_fill_tolerates_missing_benchmark():
    sig_at = et(2026, 9, 1, 10).astimezone(UTC).isoformat()
    db = FakeDB({"candidate_outcomes": [
        {"id": "o1", "symbol": "AAA", "exchange": "NYSE", "signal_at": sig_at, "price_at_signal": 100.0,
         "filled_20d_at": None}]})
    with patch("app.db.queries.get_client", return_value=db):
        res = do.fill_forward_returns(now=et(2026, 9, 16, 17), fetcher=lambda *a: {})
    assert res["updated"] == 0
    assert db.rows("candidate_outcomes")[0].get("fwd_ret_5d") is None


def test_run_outcome_tracking_isolates_failures():
    with patch.object(do, "seed_candidates", side_effect=RuntimeError("no table")), \
            patch.object(do, "fill_forward_returns", return_value={"updated": 0}):
        res = do.run_outcome_tracking()
    assert "error" in res["seed"] and res["fill"] == {"updated": 0}
