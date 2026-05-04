"""Regression test: wallet_max_entries_per_symbol_per_day cap.

Day 21 lesson: SEZL hit Filter D 3 times in one day (May 1). Without
this cap, the per-day cap (3) could be entirely consumed by a single
ticker. The per-day cap clips by score; this cap clips by symbol.
Both apply.

These tests pin the config value and the in-memory accounting that
decides whether a symbol can be re-entered today. They don't exercise
the full process_virtual_trades flow (which requires Supabase + signal
data), but they validate the gate logic itself.
"""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("DEBUG", "true")

from collections import Counter

from app.core.config import settings


class TestPerSymbolCapDefault:
    def test_default_is_one_per_symbol_per_day(self):
        # The brain may try the same name across multiple scans. The
        # default is "at most once per symbol per day" — if changed,
        # the SEZL/ONDS-91 concentration risk returns. Any bump above
        # 1 needs documented rationale (e.g., new evidence that DCA
        # works for specific buckets).
        assert settings.wallet_max_entries_per_symbol_per_day == 1


class TestPerSymbolCapLogic:
    """Mirror the inline gate logic in process_virtual_trades. The
    actual code is one branch:

        sym_cap = settings.wallet_max_entries_per_symbol_per_day
        if sym_cap > 0 and counter[symbol] >= sym_cap:
            skip

    These tests exercise that branch directly.
    """

    def _admit(self, symbol: str, counter: Counter, cap: int) -> bool:
        return not (cap > 0 and counter[symbol] >= cap)

    def test_first_entry_admitted(self):
        counter = Counter()
        assert self._admit("SEZL", counter, cap=1) is True

    def test_second_entry_blocked(self):
        counter = Counter({"SEZL": 1})
        assert self._admit("SEZL", counter, cap=1) is False

    def test_different_symbol_admitted_when_other_at_cap(self):
        # Capping SEZL must not block UNRELATED tickers from entering.
        counter = Counter({"SEZL": 1})
        assert self._admit("APLD", counter, cap=1) is True

    def test_cap_zero_disables_gate(self):
        # Setting cap=0 means "no per-symbol limit" — escape hatch.
        counter = Counter({"SEZL": 5})
        assert self._admit("SEZL", counter, cap=0) is True

    def test_cap_two_admits_first_two_blocks_third(self):
        # If the cap is bumped to 2 (e.g., to allow DCA), the gate
        # must enforce the new threshold. Pin the math.
        counter = Counter()
        for i in range(2):
            assert self._admit("SEZL", counter, cap=2) is True
            counter["SEZL"] += 1
        assert self._admit("SEZL", counter, cap=2) is False


class TestPerSymbolCapInteractionWithPerDayCap:
    """The two caps stack — both must pass for an entry to be admitted.
    The per-symbol cap is checked FIRST in process_virtual_trades so the
    log line names the more specific reason.
    """

    def test_per_symbol_check_runs_before_per_day_check(self):
        # Verify by reading the source: the per-symbol gate appears
        # BEFORE the per-day gate in both the BUY path and the SHORT path.
        # If reordered, the operator would see "daily entry cap reached"
        # for a symbol already entered today — wrong reason in the log.
        from pathlib import Path

        src = Path("app/services/virtual_portfolio.py").read_text()

        per_sym_buy = src.find("Per-symbol per-day cap (Day 21): block re-entry")
        per_day_buy = src.find("Per-day cap (Day 19): if we've already opened")
        assert per_sym_buy > 0 and per_day_buy > 0, "both BUY-path comments must exist"
        assert per_sym_buy < per_day_buy, (
            "per-symbol gate must appear BEFORE per-day gate in BUY path "
            "so the log reason is the more specific one"
        )

        per_sym_short = src.find("Per-symbol per-day cap (Day 21) — same gate")
        per_day_short = src.find("Per-day cap (Day 19) — applies to SHORTs too")
        assert per_sym_short > 0 and per_day_short > 0, "both SHORT-path comments must exist"
        assert per_sym_short < per_day_short, (
            "per-symbol gate must appear BEFORE per-day gate in SHORT path"
        )
