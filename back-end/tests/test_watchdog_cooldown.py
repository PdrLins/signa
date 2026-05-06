"""Regression test: post-WATCHDOG_EXIT re-buy cooldown.

Day 26 lesson: VZ failed Apr 14 via WATCHDOG_EXIT, re-entered Apr 16,
failed again via WATCHDOG_EXIT. FN failed Apr 28 via WATCHDOG_EXIT,
re-entered May 5 at higher score 87, failed again via WATCHDOG_EXIT.
**Two of two closed re-entries within 7 days lost 100% of the time.**

Mechanism: WATCHDOG_EXIT signals the *name* is bleeding in the current
regime, not just that one entry was poorly timed. Score-based gates
don't help because both re-entries had different scores (FN 79 → 87,
VZ score not directly relevant). The fix: a 7-day cooldown on the
symbol after any WATCHDOG_EXIT or WATCHDOG_FORCE_SELL close.

Tests pin the config + the gating logic shape (verified by reading
the source for ordering — the watchdog cooldown gate must run alongside
the existing thesis cooldown gate at the brain entry decision point).
"""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("DEBUG", "true")

from app.core.config import settings


class TestWatchdogCooldownConfig:
    def test_default_is_168_hours_one_week(self):
        # Pinned at 7 days. If shortened, the FN-style 7-day re-entry
        # case slips through again. Bump only with documented evidence.
        assert settings.brain_watchdog_exit_cooldown_hours == 168

    def test_separate_from_thesis_cooldown(self):
        # The two cooldowns are distinct concepts:
        #  - thesis-rebuy = AI thrash, 60-min default
        #  - watchdog-exit = name bleeding, 168-hour default
        # If they're equal, someone collapsed them — flag it.
        assert (
            settings.brain_thesis_rebuy_cooldown_minutes * 60
            != settings.brain_watchdog_exit_cooldown_hours * 3600
        ), "thesis and watchdog cooldowns must remain distinct"


class TestWatchdogCooldownWiring:
    """Verify the cooldown set is queried, populated, and consulted at
    the entry gate. Source-level checks because the full process_virtual_trades
    flow needs Supabase + signal data.
    """

    def test_watchdog_cooldown_query_exists(self):
        from pathlib import Path

        src = Path("app/services/virtual_portfolio.py").read_text()
        # The cooldown query must filter on both WATCHDOG_EXIT and
        # WATCHDOG_FORCE_SELL — catastrophic exits also indicate a
        # bleeding name and should trigger cooldown.
        assert '["WATCHDOG_EXIT", "WATCHDOG_FORCE_SELL"]' in src, (
            "Watchdog cooldown query must include both soft (EXIT) and "
            "hard (FORCE_SELL) watchdog closes — both signal name-level decay"
        )

    def test_watchdog_cooldown_set_consulted_at_entry_gate(self):
        from pathlib import Path

        src = Path("app/services/virtual_portfolio.py").read_text()
        # The entry gate must reference the new cooldown set alongside
        # the existing thesis cooldown. Both must be checked; either one
        # excludes the symbol.
        assert "watchdog_cooldown_symbols" in src
        assert "symbol not in watchdog_cooldown_symbols" in src, (
            "Entry gate must check `symbol not in watchdog_cooldown_symbols` "
            "to enforce the post-WATCHDOG_EXIT cooldown"
        )

    def test_watchdog_cooldown_uses_hours_setting(self):
        from pathlib import Path

        src = Path("app/services/virtual_portfolio.py").read_text()
        assert "brain_watchdog_exit_cooldown_hours" in src, (
            "The cooldown must be configurable via settings, not hardcoded"
        )


class TestCooldownsAreOrthogonal:
    """The thesis cooldown and watchdog cooldown are independent. A
    symbol could be in either, both, or neither. Make sure no code
    accidentally treats them as one set.
    """

    def test_two_separate_sets_in_source(self):
        from pathlib import Path

        src = Path("app/services/virtual_portfolio.py").read_text()
        assert "cooldown_brain_symbols: set[str] = set()" in src
        assert "watchdog_cooldown_symbols: set[str] = set()" in src
        # The two sets must be referenced separately in the gate, not
        # merged into one before the check (which would lose the ability
        # to log the specific reason).
        thesis_idx = src.find("symbol not in cooldown_brain_symbols")
        watchdog_idx = src.find("symbol not in watchdog_cooldown_symbols")
        assert thesis_idx > 0 and watchdog_idx > 0
        assert abs(thesis_idx - watchdog_idx) < 200, (
            "Both cooldown checks must be at the same gate"
        )
