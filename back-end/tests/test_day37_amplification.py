"""Day-37 amplification — REVERSED by the 2026-09 decision-quality reset.

Day 37 raised Tier-1 sizing to 15% of balance x 4 entries/day with a
"+$50 cumulative P&L" floor as the only brake. For an unmeasured edge that
is far too aggressive, and the floor was not a drawdown measure at all.
The reset replaces it with:

  * risk-based sizing: 1% of equity at risk per trade, cap 10% per position
    (`wallet.calc_risk_position_size`; the old calc_position_size_usd is gone),
  * a real peak-to-trough drawdown breaker (-10% from peak halts entries),
  * no per-day entry cap (max open positions + risk sizing bound exposure).

These tests pin the new defaults so the amplification can't creep back.
"""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("DEBUG", "true")

from app.core.config import settings  # noqa: E402
from app.services import wallet  # noqa: E402


class TestAmplificationRemoved:
    def test_percent_of_balance_sizer_removed(self):
        assert not hasattr(wallet, "calc_position_size_usd")
        assert hasattr(wallet, "calc_risk_position_size")

    def test_risk_defaults(self):
        assert settings.brain_risk_per_trade_pct == 1.0
        assert settings.brain_max_position_pct == 10.0

    def test_per_day_caps_disabled(self):
        assert settings.wallet_max_entries_per_day == 0
        assert settings.wallet_max_entries_per_symbol_per_day == 0

    def test_cumulative_pnl_floor_replaced_by_drawdown_from_peak(self):
        assert settings.wallet_auto_revert_pnl_floor is None
        assert settings.brain_max_drawdown_pct == 10.0

    def test_max_position_equals_risk_cap(self):
        # 15% position on a 1R stop of 1.5% = same 1% risk, but a wide stop
        # can never push a position past 10% of equity.
        _, alloc = wallet.calc_risk_position_size(10_000, 10_000, 100.0, 99.0,
                                                  min_trade_usd=100, commission_usd=0)
        assert alloc == 1_000.0
