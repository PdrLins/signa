"""Notification preferences (migration 013, table notification_prefs).

Stored as one JSONB object per user. Delivery comes in a later phase; this
only keeps what the user wants. Every key is an object so channels (push,
email) can be added later without changing the shape:

  exdiv_reminder   {"enabled": true}   ex-dividend date coming up
  dividend_paid    {"enabled": true}   a dividend was paid
  dividend_change  {"enabled": true}   a dividend was raised / cut
  check_changed    {"enabled": true}   a Signa check on a held stock changed
  earnings         {"enabled": true}   earnings date coming up
  big_move         {"enabled": true, "threshold_pct": 5}   daily move >= threshold
  analyst_ratings  {"enabled": false}  analyst up/downgrades
  economy          {"enabled": true}   big economy events (rates, CPI)

No row -> DEFAULTS. PUT merges a partial object; unknown keys/fields -> 422.
"""

from __future__ import annotations

import copy
import math
from typing import Any

from fastapi import status

from app.core.api_errors import api_error
from app.db import queries

DEFAULTS: dict[str, dict[str, Any]] = {
    "exdiv_reminder": {"enabled": True},
    "dividend_paid": {"enabled": True},
    "dividend_change": {"enabled": True},
    "check_changed": {"enabled": True},
    "earnings": {"enabled": True},
    "big_move": {"enabled": True, "threshold_pct": 5.0},
    "analyst_ratings": {"enabled": False},
    "economy": {"enabled": True},
}
THRESHOLD_MIN, THRESHOLD_MAX = 1.0, 50.0


def merge_with_defaults(stored: dict | None) -> dict:
    """Stored values over the defaults; junk in the DB is ignored."""
    out = copy.deepcopy(DEFAULTS)
    for key, val in (stored or {}).items():
        if key not in out or not isinstance(val, dict):
            continue
        if isinstance(val.get("enabled"), bool):
            out[key]["enabled"] = val["enabled"]
        if key == "big_move":
            t = val.get("threshold_pct")
            if isinstance(t, (int, float)) and not isinstance(t, bool) and THRESHOLD_MIN <= t <= THRESHOLD_MAX:
                out[key]["threshold_pct"] = float(t)
    return out


def _bad(message: str, key: str) -> Exception:
    return api_error("invalid_prefs", message, 422, field=key)


def apply_patch(current: dict, patch: dict) -> dict:
    """Validate a partial update and return the full new prefs."""
    if not isinstance(patch, dict) or not patch:
        raise api_error("nothing_to_update", "No preferences to update.", status.HTTP_400_BAD_REQUEST)
    out = copy.deepcopy(current)
    for key, val in patch.items():
        if key not in DEFAULTS:
            raise _bad(f"Unknown preference '{key}'.", key)
        if not isinstance(val, dict) or not val:
            raise _bad(f"'{key}' must be an object like {{\"enabled\": true}}.", key)
        allowed = set(DEFAULTS[key])
        for field, v in val.items():
            if field not in allowed:
                raise _bad(f"Unknown field '{field}' in '{key}'.", key)
            if field == "enabled":
                if not isinstance(v, bool):
                    raise _bad(f"'{key}.enabled' must be true or false.", key)
                out[key]["enabled"] = v
            elif field == "threshold_pct":
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) \
                        or not THRESHOLD_MIN <= v <= THRESHOLD_MAX:
                    raise _bad(f"big_move.threshold_pct must be between {THRESHOLD_MIN:g} and {THRESHOLD_MAX:g}.",
                               key)
                out[key]["threshold_pct"] = float(v)
    return out


def get_prefs(user_id: str) -> dict:
    row = queries.get_notification_prefs(user_id)
    return {"prefs": merge_with_defaults((row or {}).get("prefs")),
            "is_default": row is None, "updated_at": (row or {}).get("updated_at")}


def update_prefs(user_id: str, patch: dict) -> dict:
    row = queries.get_notification_prefs(user_id)
    new = apply_patch(merge_with_defaults((row or {}).get("prefs")), patch)
    saved = queries.upsert_notification_prefs(user_id, new)
    return {"prefs": new, "is_default": False, "updated_at": saved.get("updated_at")}
