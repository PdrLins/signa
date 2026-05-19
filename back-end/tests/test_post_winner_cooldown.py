"""Regression test: post-winner cooldown.

Day 37 lesson: 3 of 3 chase-winner re-entries lost (-$67 total).
SOUN-2, IONQ-2, ARM-2 all entered shortly after a profitable close on
the same name, and all three died within 3-5 days. The post-winner
cooldown blocks any wallet symbol whose previous wallet-trade close
within N hours was a positive THESIS_INVALIDATED / TARGET_HIT /
TRAILING_STOP / SIGNAL / ROTATION.
"""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("DEBUG", "true")

from app.core.config import settings


class TestPostWinnerCooldownConfig:
    def test_default_is_336_hours_14_days(self):
        """14 days catches the observed range of chase-winner re-entries
        (1d, 4d, 10d). If shortened below ~240h, the 10-day-gap ARM-2
        case slips through. Bump only with documented backtest."""
        assert settings.brain_post_winner_cooldown_hours == 336

    def test_distinct_from_other_cooldowns(self):
        """Three cooldowns exist now (thesis-rebuy 60min, watchdog-exit
        168h, post-winner 336h). They must remain distinct values so a
        future reader doesn't accidentally collapse them."""
        thesis = settings.brain_thesis_rebuy_cooldown_minutes * 60
        we = settings.brain_watchdog_exit_cooldown_hours * 3600
        pw = settings.brain_post_winner_cooldown_hours * 3600
        assert len({thesis, we, pw}) == 3, (
            "thesis-rebuy, watchdog-exit, and post-winner cooldowns must "
            "all have different durations"
        )


class TestPostWinnerCooldownWiring:
    """Source-level checks that the cooldown is built and consulted at
    the entry gate. The full process_virtual_trades flow needs Supabase
    + signals, so we verify shape here."""

    def test_cooldown_query_filters_positive_wins(self):
        from pathlib import Path

        src = Path("app/services/virtual_portfolio.py").read_text()
        # The query MUST filter on pnl_amount > 0 — otherwise we'd block
        # re-entries after losing thesis-invalidated closes too, which is
        # the WRONG behavior (those are handled by the watchdog cooldown).
        assert ".gt(\"pnl_amount\", 0)" in src, (
            "Post-winner cooldown query must filter on positive pnl_amount "
            "so losing-thesis-invalidated closes don't get treated as wins"
        )

    def test_cooldown_query_includes_signal_and_rotation_exits(self):
        from pathlib import Path

        src = Path("app/services/virtual_portfolio.py").read_text()
        # Day-25/27 winners exited via SIGNAL (USAR) and ROTATION
        # (APLD, MSTR-1). Both are profitable thesis-exits that
        # should trigger the cooldown.
        assert "SIGNAL" in src and "ROTATION" in src and "TRAILING_STOP" in src

    def test_cooldown_filters_wallet_trades_only(self):
        from pathlib import Path

        src = Path("app/services/virtual_portfolio.py").read_text()
        # Legacy 1-share trades are pre-wallet, can't trigger meaningful
        # cooldown on post-wallet re-entries.
        assert "is_wallet_trade" in src
        # And the post-winner block specifically references it
        assert '.eq("is_wallet_trade", True)' in src

    def test_cooldown_consulted_at_entry_gate(self):
        from pathlib import Path

        src = Path("app/services/virtual_portfolio.py").read_text()
        assert "post_winner_cooldown_symbols" in src
        assert "symbol not in post_winner_cooldown_symbols" in src, (
            "Entry gate must check post_winner_cooldown_symbols alongside "
            "the existing watchdog and thesis cooldowns"
        )


class TestThreeCooldownsAreOrthogonal:
    """The three cooldowns catch three different failure modes — they
    must not be merged into one set, so the operator can read the
    specific block reason from logs."""

    def test_three_separate_sets_in_source(self):
        from pathlib import Path

        src = Path("app/services/virtual_portfolio.py").read_text()
        # All three sets are declared separately
        assert "cooldown_brain_symbols: set[str] = set()" in src
        assert "watchdog_cooldown_symbols: set[str] = set()" in src
        assert "post_winner_cooldown_symbols: set[str] = set()" in src
