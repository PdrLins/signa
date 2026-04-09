"""Shared date parsing helpers for ISO-8601 strings from the DB.

============================================================
WHY THIS MODULE EXISTS
============================================================

Supabase stores timestamps as ISO-8601 strings with a trailing `Z`:
    "2026-04-09T13:45:00Z"

Python 3.11+ `datetime.fromisoformat` handles `Z` natively, but earlier
versions (3.10 and older) don't — they require the `Z` to be replaced
with `+00:00` first. Signa runs on 3.12 but the existing codebase was
originally written compatible with 3.10 and the `Z` → `+00:00` replacement
became the convention across 8+ call sites:

    virtual_portfolio.py (3 sites)
    watchdog_service.py
    thesis_tracker.py
    position_service.py
    scans.py (2 sites)

Each site had slightly different error handling (some silently defaulted
to `now`, some raised, one had no try/except at all). That's drift waiting
to happen. This module centralizes the parsing with a single opinionated
policy: return None on parse failure, let the caller decide what to do.

============================================================
WHY NOT JUST USE fromisoformat DIRECTLY
============================================================

Three reasons:
  1. The `Z` → `+00:00` convention must be applied consistently
  2. Signa's DB sometimes writes None/empty strings for entry_date on
     certain legacy rows; the helper must tolerate that without raising
  3. Days-held computation has a `max(0, ...)` floor that was repeated
     in every call site

One function, one policy, 5+ sites deduplicated.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def parse_iso_utc(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp string into a timezone-aware datetime.

    Args:
        value: The string to parse. Accepts both `Z` suffix (`...T12:00:00Z`)
            and `+00:00` suffix. None or empty string returns None.

    Returns:
        A timezone-aware `datetime` in UTC, or None if the input is None,
        empty, or unparseable. Never raises — callers must handle None
        explicitly (either skip, raise their own error, or substitute a
        fallback like `datetime.now(timezone.utc)`).
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return None


def days_since(value: Optional[str], now: Optional[datetime] = None) -> int:
    """Return the number of whole days between `value` and `now` (default: utcnow).

    Args:
        value: An ISO-8601 timestamp string to compare against `now`.
        now: Override for "now" — useful for deterministic tests. Defaults
            to `datetime.now(timezone.utc)` when omitted.

    Returns:
        Days elapsed, floored at 0. Returns 0 if `value` is None, empty,
        or unparseable — the caller should check with `parse_iso_utc` first
        if it needs to distinguish "0 days ago" from "unknown".
    """
    dt = parse_iso_utc(value)
    if dt is None:
        return 0
    if now is None:
        now = datetime.now(timezone.utc)
    return max(0, (now - dt).days)
