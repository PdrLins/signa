"""Thesis re-evaluation: conservative exit gate (conf >= 70 on 2 consecutive checks, once/day)."""

from datetime import datetime, timedelta, timezone

from app.services import thesis_tracker as tt


def test_low_confidence_invalid_is_persisted_as_weakening():
    assert tt.persisted_status({"status": "invalid", "confidence": 65}) == "weakening"
    assert tt.persisted_status({"status": "invalid", "confidence": "80"}) == "invalid"
    assert tt.persisted_status({"status": "garbage"}) == "weakening"
    assert tt.persisted_status({"status": "valid", "confidence": 10}) == "valid"


def test_qualifying_invalid_requires_confidence_70():
    assert not tt.is_qualifying_invalid({"status": "invalid", "confidence": 69})
    assert not tt.is_qualifying_invalid({"status": "invalid"})
    assert tt.is_qualifying_invalid({"status": "invalid", "confidence": 70})


def test_checked_today():
    now = datetime(2026, 9, 28, 15, tzinfo=timezone.utc)
    assert tt.checked_today({"thesis_last_checked_at": now.replace(hour=1).isoformat()}, now)
    assert not tt.checked_today({"thesis_last_checked_at": (now - timedelta(days=1)).isoformat()}, now)
    assert not tt.checked_today({}, now)


def test_single_invalid_verdict_does_not_close(monkeypatch):
    monkeypatch.setattr(tt.settings, "brain_thesis_gate_enabled", True)

    def _boom():
        raise AssertionError("DB must not be touched when nothing qualifies")

    monkeypatch.setattr(tt, "get_client", _boom)
    ctx = {
        "result": {"status": "invalid", "confidence": 95},
        "position": {"symbol": "ACME", "id": 1, "entry_price": 10},
        "live_price": 9.0, "pnl_pct": -10.0, "days_held": 3,
        "exit_eligible": False,
    }
    assert tt.execute_thesis_invalidation_exits({"ACME": ctx}, []) == 0


def test_eligible_but_low_confidence_does_not_close(monkeypatch):
    monkeypatch.setattr(tt.settings, "brain_thesis_gate_enabled", True)
    monkeypatch.setattr(tt, "get_client", lambda: (_ for _ in ()).throw(AssertionError()))
    ctx = {
        "result": {"status": "invalid", "confidence": 50},
        "position": {"symbol": "ACME", "id": 1, "entry_price": 10},
        "live_price": 9.0, "pnl_pct": -10.0, "days_held": 3,
        "exit_eligible": True,
    }
    assert tt.execute_thesis_invalidation_exits({"ACME": ctx}, []) == 0
