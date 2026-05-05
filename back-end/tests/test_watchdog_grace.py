"""Regression test: WATCHDOG_EXIT grace period for fresh positions.

Day 20 EOD investigation found that the watchdog's sentiment-driven
exit path was firing same-day on HIGH_RISK SHORT-horizon entries due
to the −2% bleed threshold + bearish sentiment combo (FN, NBIS, BTDR
same-day deaths). Fix: suppress WATCHDOG_EXIT during the first
`new_position_grace_hours` after entry. Catastrophic WATCHDOG_FORCE_SELL
(≤−8%) ALWAYS fires regardless of age.

These tests pin the grace logic at the unit level — they don't exercise
the full watchdog tick (which requires Supabase + price fetches), but
they validate the parse_iso_utc + datetime arithmetic that decides
whether a position is in grace.
"""

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("DEBUG", "true")

from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.dates import parse_iso_utc


def _hours_held(entry_iso: str) -> float:
    """Mirror the inline computation in watchdog_service.py."""
    entry_dt = parse_iso_utc(entry_iso)
    if entry_dt is None:
        return 9999.0
    return (datetime.now(timezone.utc) - entry_dt).total_seconds() / 3600


def _in_grace(entry_iso: str) -> bool:
    return _hours_held(entry_iso) < settings.new_position_grace_hours


class TestGraceWindow:
    def test_grace_default_is_24_hours(self):
        # If this changes, the test cases below need to be updated.
        # The grace window is documented in the watchdog code comment
        # and matches the thesis-tracker grace exactly.
        assert settings.new_position_grace_hours == 24.0

    def test_position_at_minute_zero_is_in_grace(self):
        now_iso = datetime.now(timezone.utc).isoformat()
        assert _in_grace(now_iso) is True

    def test_position_at_eight_minutes_is_in_grace(self):
        # FN — 8 minutes after entry. Pre-fix this was killed by
        # WATCHDOG_EXIT at -2.21%. Post-fix it must be grace-protected.
        eight_min_ago = (datetime.now(timezone.utc) - timedelta(minutes=8)).isoformat()
        assert _in_grace(eight_min_ago) is True

    def test_position_at_2_5_hours_is_in_grace(self):
        # BTDR — 2.5 hours after entry. Same-day death at -2.34%.
        # Post-fix this must be grace-protected.
        two_h_30_ago = (datetime.now(timezone.utc) - timedelta(hours=2, minutes=30)).isoformat()
        assert _in_grace(two_h_30_ago) is True

    def test_position_at_19_hours_is_in_grace(self):
        # NBIS — 19h after entry. Day-1 death at -4.24%. Still inside
        # the 24h grace window — must be protected.
        nineteen_h_ago = (datetime.now(timezone.utc) - timedelta(hours=19)).isoformat()
        assert _in_grace(nineteen_h_ago) is True

    def test_position_at_24_5_hours_is_NOT_in_grace(self):
        # Just past the grace window — watchdog can fire normally.
        # The grace must not extend forever.
        past_grace = (datetime.now(timezone.utc) - timedelta(hours=24, minutes=30)).isoformat()
        assert _in_grace(past_grace) is False

    def test_position_at_3_days_is_NOT_in_grace(self):
        three_days_ago = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        assert _in_grace(three_days_ago) is False

    def test_missing_entry_date_is_NOT_in_grace(self):
        # If entry_date is missing or unparseable, hours_held becomes
        # the 9999.0 fallback so the watchdog falls through to its
        # normal path. We never want a parse failure to silently extend
        # protection — that would mask real catastrophic moves.
        assert _hours_held(None) == 9999.0
        assert _hours_held("") == 9999.0
        assert _hours_held("not-a-date") == 9999.0
        assert _in_grace(None) is False


class TestGraceInstrumentation:
    """Day-24 instrumentation: grace-protected close attempts must emit
    a queryable event row so we can later measure 'did grace save this
    position or just delay its death?' by joining back to virtual_trades.
    """

    def test_grace_protected_event_constant_exists(self):
        from app.services.watchdog_service import EVENT_GRACE_PROTECTED
        # Pinned value — used by downstream queries (e.g., dashboard panels
        # filtering watchdog_events by event_type). If renamed, update
        # consumers; do NOT silently change the string.
        assert EVENT_GRACE_PROTECTED == "GRACE_PROTECTED"

    def test_grace_path_emits_event_not_alert(self):
        # Verify by reading the file structure: the GRACE_PROTECTED branch
        # appends a watchdog_events row with event_type=GRACE_PROTECTED,
        # NOT event_type=ALERT. If the branch logic flips, we'd silently
        # lose the audit trail and "grace saved $X" claims would be
        # unverifiable.
        from pathlib import Path

        src = Path("app/services/watchdog_service.py").read_text()
        # The grace branch must reference EVENT_GRACE_PROTECTED.
        grace_event_idx = src.find('"event_type": EVENT_GRACE_PROTECTED')
        assert grace_event_idx > 0, "EVENT_GRACE_PROTECTED must be emitted from the grace branch"
        # And the grace branch must be inside the in_grace + bearish guard.
        grace_guard = src.find('if in_grace and sentiment_label == "bearish":')
        assert 0 < grace_guard < grace_event_idx, (
            "EVENT_GRACE_PROTECTED must be emitted ONLY when in_grace AND sentiment is bearish — "
            "otherwise we'd record grace events for non-grace cases and pollute the audit trail"
        )


class TestGraceDoesNotProtectCatastrophic:
    """Pin the invariant that grace ONLY suppresses WATCHDOG_EXIT, not
    WATCHDOG_FORCE_SELL. The catastrophic path is the safety net — it
    must remain age-blind so a wrong-conviction entry can't rocket past
    -8% just because it's young.
    """

    def test_catastrophic_pnl_triggers_force_sell_regardless_of_age(self):
        # A position 5 minutes old at -10% must STILL be force-sold.
        # The grace check sits AFTER the catastrophic check in the
        # watchdog flow — this test pins the ordering.
        # We verify the ordering by reading the file structure: the
        # `if pnl_total_pct <= -8.0` guard appears BEFORE the
        # `if sentiment_label == "bearish" ... and not in_grace` guard.
        from pathlib import Path

        watchdog_src = Path("app/services/watchdog_service.py").read_text()
        force_sell_idx = watchdog_src.find("pnl_total_pct <= -8.0")
        grace_idx = watchdog_src.find("not in_grace")
        assert force_sell_idx > 0, "catastrophic guard must exist"
        assert grace_idx > 0, "grace guard must exist"
        assert force_sell_idx < grace_idx, (
            "Catastrophic check must run BEFORE grace check, otherwise a "
            "fresh position at -10% would be grace-protected from FORCE_SELL"
        )
