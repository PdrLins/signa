"""Regression test: Day-37 amplification ship.

Pedro committed to the 20%/month goal. To close the gap from current
0.10%/day → 0.91%/day target, we bumped:
  - Tier 1 sizing: 10% → 15% (1.5x)
  - Per-day cap: 3 → 4 (1.33x)
  - Max position cap: 15% → 20% (room for Tier 1 + buffer)

Combined: ~2x daily output (~$10/day instead of $5/day).

The drawdown circuit breaker bounds the experiment: if cumulative
wallet-era P&L drops below +$50, the next scan reverts to pre-Day-37
defaults (10% / 5% / cap 3) — capping further losses while we wait
for the trend to re-establish.
"""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("DEBUG", "true")

from app.core.config import settings
from app.services.wallet import calc_position_size_usd


class TestNewDefaults:
    def test_tier1_sizing_is_15pct(self):
        # Bumped from 10 → 15. If this regresses, the 1.5x amplification
        # is silently undone.
        assert settings.wallet_position_pct_tier1 == 15.0

    def test_max_position_cap_is_20pct(self):
        # Bumped from 15 → 20 to leave headroom for Tier 1 + trust_multiplier.
        # Below 20% would silently clip Tier 1 entries.
        assert settings.wallet_max_position_pct == 20.0

    def test_per_day_cap_is_4(self):
        # Bumped from 3 → 4. Combined with the sizing bump, total daily
        # deployment can reach 60% of pocket (vs 30% pre-Day-37).
        assert settings.wallet_max_entries_per_day == 4

    def test_drawdown_floor_default(self):
        assert settings.wallet_auto_revert_pnl_floor == 50.0


class TestCalcPositionSizeOverrides:
    """The override params let process_virtual_trades pass clamped values
    when the drawdown circuit breaker has tripped, WITHOUT mutating
    settings (which would affect other code paths)."""

    def test_no_override_uses_settings(self):
        # On $4000 balance, Tier 1 sizing = 4000 * 15% = 600
        assert calc_position_size_usd(4000, 1, 1.0) == 600.0

    def test_breaker_override_clamps_to_old_defaults(self):
        # Override: tier1=10%, max=15% (the pre-Day-37 values).
        # Should produce 400, not 600.
        result = calc_position_size_usd(
            4000, 1, 1.0,
            tier1_pct_override=10.0,
            max_pct_override=15.0,
        )
        assert result == 400.0

    def test_override_respects_hard_cap(self):
        # If the override is 25% but max cap is 15%, the cap wins.
        # 4000 * 15% = 600
        result = calc_position_size_usd(
            4000, 1, 1.0,
            tier1_pct_override=25.0,
            max_pct_override=15.0,
        )
        assert result == 600.0

    def test_override_only_applies_to_tier1(self):
        # Tier 2/3 sizing is unaffected by the tier1 override
        result = calc_position_size_usd(
            4000, 2, 1.0,
            tier1_pct_override=25.0,
        )
        # Tier 2 = 5% of 4000 = 200, regardless of tier1 override
        assert result == 200.0


class TestDrawdownBreakerWiring:
    """Source-level checks that the breaker reads cumulative P&L and
    clamps effective sizing constants before any entry is processed."""

    def test_breaker_logic_in_source(self):
        from pathlib import Path

        src = Path("app/services/virtual_portfolio.py").read_text()
        # The breaker must read cumulative P&L from closed wallet trades
        assert "_drawdown_breaker_tripped" in src
        assert "wallet_auto_revert_pnl_floor" in src
        # And clamp the effective constants
        assert "_eff_tier1_pct" in src
        assert "_eff_max_pct" in src
        assert "_eff_max_per_day" in src

    def test_breaker_clamps_to_safe_defaults(self):
        from pathlib import Path

        src = Path("app/services/virtual_portfolio.py").read_text()
        # The clamp values must be the pre-Day-37 conservative defaults
        # (10% / 15% / cap 3), NOT the new aggressive ones — otherwise
        # the breaker is a no-op.
        assert "_eff_tier1_pct = 10.0 if _drawdown_breaker_tripped" in src
        assert "_eff_max_pct = 15.0 if _drawdown_breaker_tripped" in src
        assert "_eff_max_per_day = 3 if _drawdown_breaker_tripped" in src

    def test_overrides_passed_to_compute_wallet_fields(self):
        from pathlib import Path

        src = Path("app/services/virtual_portfolio.py").read_text()
        # Both BUY and SHORT paths must pass the clamped values
        assert src.count("tier1_pct_override=_eff_tier1_pct") >= 2, (
            "tier1_pct_override should be passed to _compute_wallet_fields on both BUY and SHORT paths"
        )
        assert src.count("max_pct_override=_eff_max_pct") >= 2

    def test_per_day_cap_uses_effective(self):
        from pathlib import Path

        src = Path("app/services/virtual_portfolio.py").read_text()
        # Both call sites should reference _eff_max_per_day, not settings directly
        # (the cap=settings.wallet_max_entries_per_day would bypass the breaker)
        assert src.count("cap = _eff_max_per_day") == 2, (
            "Per-day cap must use _eff_max_per_day in both BUY and SHORT paths"
        )
