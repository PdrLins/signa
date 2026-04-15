"""Single source of truth for the daily scan schedule.

============================================================
WHY THIS MODULE EXISTS
============================================================

The scan schedule was previously defined in THREE places:
    app/api/v1/scans.py       — _SCAN_SLOTS for the frontend today view
    app/services/stats_service.py — _SCHEDULE for next_scan_time calculation
    app/scheduler/jobs.py     — scan_slots for APScheduler cron jobs

Adding a slot (MIDDAY at 12:00 PM was added to the scheduler + scans.py
but NOT stats_service.py) caused the "next scan" display on the dashboard
to skip from 10 AM straight to 3 PM, ignoring the 12 PM scan that would
actually run next. Bug symptom: at 11:44 AM the hover card said "Next
Scan 3:00 PM EDT" while the scan agenda correctly showed MIDDAY pending.

This module is the single place that defines the canonical 5 scan slots.
All three consumers import from here. When we add or change a slot, we
change it once and nothing drifts.

============================================================
SHAPE
============================================================

Each slot is a SlotInfo tuple: (scan_type, label, hour, minute).

`scan_type` matches the DB enum used in the `scans` table.
`label` is the English display name (bilingual replacement happens at
the frontend via i18n — the backend stays English here).
`hour` and `minute` are ET (America/New_York).

Helpers on top of the list:
    get_slot(scan_type)     — SlotInfo for a given type
    format_hhmm(scan_type)  — "HH:MM" string (legacy format still used
                              in some API responses)
    next_scan_time_et(now)  — datetime of the next scan after `now`
                              within today's ET schedule, or None if
                              all slots are already past
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import NamedTuple, Optional
from zoneinfo import ZoneInfo


ET = ZoneInfo("America/New_York")


class SlotInfo(NamedTuple):
    scan_type: str   # Matches DB enum: PRE_MARKET | MORNING | MIDDAY | PRE_CLOSE | AFTER_CLOSE
    label: str       # English display name
    hour: int        # ET hour (0-23)
    minute: int      # ET minute (0-59)

    @property
    def hhmm(self) -> str:
        return f"{self.hour:02d}:{self.minute:02d}"


# ─────────────────────────────────────────────────────────────────
# THE CANONICAL SCHEDULE
# ─────────────────────────────────────────────────────────────────
# Adding a scan? Add it here. Both the scheduler cron jobs, the
# frontend today view, and the next-scan-time calculation will
# automatically pick it up.
SCAN_SCHEDULE: list[SlotInfo] = [
    SlotInfo("PRE_MARKET",  "Morning scan", 6,  0),
    SlotInfo("MORNING",     "Market open", 10,  0),
    SlotInfo("MIDDAY",      "Midday",      12,  0),
    SlotInfo("PRE_CLOSE",   "Pre-close",   15,  0),
    SlotInfo("AFTER_CLOSE", "After close", 16, 30),
]


def get_slot(scan_type: str) -> Optional[SlotInfo]:
    """Return the slot for a given scan_type, or None if not found."""
    for slot in SCAN_SCHEDULE:
        if slot.scan_type == scan_type:
            return slot
    return None


def next_scan_time_et(now_et: Optional[datetime] = None) -> Optional[datetime]:
    """Return the datetime of the next scan after `now_et`.

    Returns the next slot TODAY if any remain, otherwise the first slot
    TOMORROW. Always returns a timezone-aware ET datetime. Returns None
    only if the schedule is empty (defensive — should never happen).
    """
    if not SCAN_SCHEDULE:
        return None
    if now_et is None:
        now_et = datetime.now(ET)
    elif now_et.tzinfo is None:
        now_et = now_et.replace(tzinfo=ET)

    today = now_et.date()
    for slot in SCAN_SCHEDULE:
        slot_time = datetime.combine(
            today,
            datetime.min.time().replace(hour=slot.hour, minute=slot.minute),
            tzinfo=ET,
        )
        if slot_time > now_et:
            return slot_time

    # All slots today have passed — return tomorrow's first slot
    tomorrow = today + timedelta(days=1)
    first = SCAN_SCHEDULE[0]
    return datetime.combine(
        tomorrow,
        datetime.min.time().replace(hour=first.hour, minute=first.minute),
        tzinfo=ET,
    )
