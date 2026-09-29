"""Per-symbol per-day cap (Day 21) — superseded by the 2026-09 reset.

The cap existed so one name could not eat the whole per-day entry budget.
After the reset a symbol can't be entered while held (either track), can't
be re-entered for `brain_reentry_cooldown_days` trading days after any
exit, and the per-day entry budget itself is gone. So the cap defaults to
0 (disabled); these tests pin that and the replacement behavior.
"""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("DEBUG", "true")

from app.core.config import settings  # noqa: E402


class TestPerSymbolCap:
    def test_disabled_by_default(self):
        assert settings.wallet_max_entries_per_symbol_per_day == 0
        assert settings.wallet_max_entries_per_day == 0

    def test_same_symbol_twice_in_one_scan_opens_once(self):
        from tests.brain_fakes import FakeDB, patch_db, wallet_row
        from tests.test_brain_entry_gate import brain_trades, make_sig
        from app.services import virtual_portfolio as vp

        db = FakeDB({"brain_wallet": [wallet_row()], "virtual_trades": []})
        with patch_db(db):
            vp.process_virtual_trades([make_sig("SEZL"), make_sig("SEZL", score=85)], set(), [])
        assert len(brain_trades(db)) == 1
