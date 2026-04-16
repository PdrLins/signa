"""Scan-scoped context for suppressing Telegram notifications per scan type.

The user doesn't want every scheduled scan pinging Telegram. For example the
PRE_MARKET scan runs at 6:00 AM ET before they're awake, so those notifications
are noise. Rather than threading a `scan_type` argument through every nested
call (flush_brain_notifications, monitor_positions, budget alerts, thesis
tracker), we use a `contextvars.ContextVar` — asyncio-aware, propagates
naturally through awaits, and isolates per-scan-task state.

Flow
-----
1. `run_scan(scan_type)` calls `set_current_scan_type(scan_type)` at the very
   top. The returned `Token` is restored in a `finally` so scan boundaries
   stay clean.
2. Any code path inside the scan that ends up calling
   `telegram_bot.send_message()` reads the current scan_type via
   `get_current_scan_type()`.
3. If that scan_type is in `settings.notify_scans_disabled`, the send is
   suppressed (non-urgent only — OTPs and other `urgent=True` sends still go
   through).

Outside of a scan (watchdog, manual API calls, OTPs) the ContextVar is None
and no filtering happens.
"""

from __future__ import annotations

import contextvars

_current_scan_type: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "signa_current_scan_type", default=None
)


def set_current_scan_type(scan_type: str | None) -> contextvars.Token:
    """Bind the current scan_type to this async task. Returns a reset Token."""
    return _current_scan_type.set(scan_type)


def reset_current_scan_type(token: contextvars.Token) -> None:
    """Restore the previous scan_type (pair with set_current_scan_type)."""
    _current_scan_type.reset(token)


def get_current_scan_type() -> str | None:
    """Return the scan_type of the currently running scan, or None if none."""
    return _current_scan_type.get()


def is_scan_notifications_disabled() -> bool:
    """True if the running scan (if any) is in the disabled list."""
    from app.core.config import settings

    scan_type = _current_scan_type.get()
    if not scan_type:
        return False
    disabled = {
        s.strip().upper()
        for s in (settings.notify_scans_disabled or "").split(",")
        if s.strip()
    }
    return scan_type.upper() in disabled
