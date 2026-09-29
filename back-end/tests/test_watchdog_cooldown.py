"""Post-WATCHDOG_EXIT re-buy cooldown — DISABLED by the 2026-09 reset.

The Day-26 7-day cooldown was based on n=2 re-entries. The watchdog no
longer emits WATCHDOG_EXIT at all (the sentiment-driven exit was removed;
it now only enforces each position's stop/target/time via the shared exit
policy), so the cooldown is off. Re-entry after ANY exit is governed by
`brain_reentry_cooldown_days`.
"""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("DEBUG", "true")

from pathlib import Path  # noqa: E402

from app.core.config import settings  # noqa: E402


class TestWatchdogCooldown:
    def test_off_by_default(self):
        assert settings.brain_watchdog_exit_cooldown_hours == 0

    def test_watchdog_no_longer_emits_sentiment_exits(self):
        src = Path("app/services/watchdog_service.py").read_text()
        assert "_get_quick_sentiment" not in src
        assert '"WATCHDOG_EXIT")' not in src

    def test_reentry_cooldown_covers_every_exit(self):
        assert settings.brain_reentry_cooldown_days > 0
