"""Post-winner / post-loss cooldowns — DISABLED by the 2026-09 reset.

The Day-37 post-winner cooldown (n=3 chase-winner re-entries) and the
Day-47 post-loss cooldown (n=1, OSCR) were fit on tiny samples. The reset
turns both off and replaces them with ONE simple rule: after ANY brain
exit, the same symbol can't be re-entered for
`brain_reentry_cooldown_days` trading days (default 3). The legacy
queries still run if their hours are set > 0.
"""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("DEBUG", "true")

from app.core.config import settings  # noqa: E402


class TestCooldownDefaults:
    def test_post_winner_and_post_loss_off(self):
        assert settings.brain_post_winner_cooldown_hours == 0
        assert settings.brain_post_loss_cooldown_hours == 0

    def test_thesis_rebuy_cooldown_superseded(self):
        assert settings.brain_thesis_rebuy_cooldown_minutes == 0

    def test_single_same_symbol_cooldown(self):
        assert settings.brain_reentry_cooldown_days == 3


class TestLegacyCooldownStillWorksWhenEnabled:
    def test_post_winner_rule_blocks_when_hours_set(self, monkeypatch):
        from datetime import datetime, timezone

        from app.services import virtual_portfolio as vp
        from tests.brain_fakes import FakeDB

        monkeypatch.setattr(settings, "brain_reentry_cooldown_days", 0)
        monkeypatch.setattr(settings, "brain_post_winner_cooldown_hours", 336)
        now = datetime.now(timezone.utc).isoformat()
        db = FakeDB({"virtual_trades": [
            {"symbol": "WIN", "source": "brain", "status": "CLOSED", "exit_date": now, "pnl_amount": 10.0},
            {"symbol": "LOSE", "source": "brain", "status": "CLOSED", "exit_date": now, "pnl_amount": -10.0},
        ]})
        cd = vp._reentry_cooldown_symbols(db)
        assert "WIN" in cd and "LOSE" not in cd
