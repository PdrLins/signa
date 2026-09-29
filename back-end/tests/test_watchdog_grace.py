"""Watchdog grace period — REMOVED with the sentiment exit (2026-09 reset).

The Day-20 grace only protected fresh positions from WATCHDOG_EXIT, the
"one bearish sentiment call + slight loss" exit. That exit is gone: the
watchdog now enforces each position's own hard stop (and target/time) via
`virtual_portfolio.evaluate_exit`, which has no age exemption — a stop is a
stop at minute 0. `new_position_grace_hours` now only affects
THESIS_INVALIDATED closes and defaults to 0 because thesis_tracker requires
two consecutive high-confidence "invalid" calls.
"""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("DEBUG", "true")

from datetime import datetime, timedelta, timezone  # noqa: E402

from app.core.config import settings  # noqa: E402


class TestGraceRemoved:
    def test_grace_default_zero(self):
        assert settings.new_position_grace_hours == 0.0

    def test_event_constant_kept_for_history_queries(self):
        from app.services.watchdog_service import EVENT_GRACE_PROTECTED
        assert EVENT_GRACE_PROTECTED == "GRACE_PROTECTED"

    def test_fresh_position_is_still_stopped_out(self):
        from app.services.virtual_portfolio import evaluate_exit
        pos = {"symbol": "FN", "source": "brain", "direction": "LONG", "entry_price": 100.0,
               "stop_loss": 97.0, "initial_stop": 97.0, "target_price": 106.0,
               "entry_date": (datetime.now(timezone.utc) - timedelta(minutes=8)).isoformat()}
        assert evaluate_exit(pos, 96.9).reason == "STOP_HIT"
        assert evaluate_exit(pos, 97.8).reason is None  # -2.2% above stop: no noise exit
