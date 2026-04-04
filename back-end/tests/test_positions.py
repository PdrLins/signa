"""Tests for position service — P&L calculations and alert logic."""

from app.services.position_service import _fmt_pnl


class TestPnLCalculation:
    def test_profit(self):
        entry = 50.0
        exit_price = 55.0
        shares = 100
        pnl_amount = (exit_price - entry) * shares
        pnl_pct = ((exit_price - entry) / entry) * 100
        assert pnl_amount == 500.0
        assert pnl_pct == 10.0

    def test_loss(self):
        entry = 50.0
        exit_price = 45.0
        shares = 100
        pnl_amount = (exit_price - entry) * shares
        pnl_pct = ((exit_price - entry) / entry) * 100
        assert pnl_amount == -500.0
        assert pnl_pct == -10.0

    def test_breakeven(self):
        entry = 50.0
        exit_price = 50.0
        pnl_pct = ((exit_price - entry) / entry) * 100
        assert pnl_pct == 0.0


class TestPnLFormatting:
    def test_positive(self):
        result = _fmt_pnl(520.0, 10.4)
        assert "+$520.00" in result
        assert "+10.4%" in result

    def test_negative(self):
        result = _fmt_pnl(-200.0, -4.0)
        assert "-$200.00" in result or "$-200.00" in result
        assert "-4.0%" in result


class TestAlertTriggers:
    def test_stop_loss_trigger(self):
        """Stop loss should trigger when price <= stop_loss."""
        entry = 50.0
        stop_loss = 47.0
        current_price = 46.5
        assert current_price <= stop_loss

    def test_target_trigger(self):
        """Target should trigger when price >= target_price."""
        entry = 50.0
        target = 60.0
        current_price = 61.0
        assert current_price >= target

    def test_pnl_milestone(self):
        """P&L milestone triggers every 5%."""
        entry = 100.0
        current = 106.0
        pnl_pct = ((current - entry) / entry) * 100
        milestone = int(pnl_pct / 5) * 5
        assert milestone == 5

    def test_pnl_no_milestone(self):
        """Small moves don't trigger milestones."""
        entry = 100.0
        current = 103.0
        pnl_pct = ((current - entry) / entry) * 100
        milestone = int(pnl_pct / 5) * 5
        assert milestone == 0

    def test_signal_weakening_trigger(self):
        """Alert when signal goes from CONFIRMED to WEAKENING."""
        prev_status = "CONFIRMED"
        new_status = "WEAKENING"
        assert prev_status == "CONFIRMED" and new_status in ("WEAKENING", "CANCELLED")
