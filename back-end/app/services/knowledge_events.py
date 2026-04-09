"""Append-only audit log for the brain's learning history.

============================================================
WHAT THIS MODULE IS
============================================================

Every mutation to `signal_thinking` or `signal_knowledge` — and every
observation that updates a hypothesis's evidence counters — appends a row
to the `knowledge_events` table via `log_event()`.

The table is APPEND-ONLY. Never UPDATE, never DELETE. The whole table
IS the audit log. Without this, we have aggregate counters but no
individual events: we cannot answer questions like "which 5 trades
graduated this hypothesis" or "why did the brain start avoiding
META-class signals last Tuesday."

============================================================
EVENT TYPES
============================================================

  thinking_created          A new hypothesis was proposed
  thinking_observation_added A closed trade matched a hypothesis pattern,
                            evidence counter was incremented
  thinking_graduated        Hypothesis became validated knowledge
  thinking_rejected         Counter-evidence won
  thinking_stale            Aged out (no observations for X days)
  thinking_edited           Hypothesis text or pattern_match changed
  knowledge_created         New signal_knowledge row inserted
  knowledge_edited          Existing knowledge row updated
  knowledge_deactivated     is_active flipped to false

============================================================
DESIGN PRINCIPLES
============================================================

1. **Never block business logic.** All write failures are caught and
   logged as warnings. A broken audit log must never prevent a brain
   trade from closing or a hypothesis from updating.

2. **No async.** The Supabase client is sync; the helper is sync.
   One insert per event, ~5ms latency, called at low frequency
   (a few times per scan at most).

3. **Payload schema is intentionally loose.** It's JSONB, so each event
   type can include whatever state matters. Don't try to design a
   universal schema — design for the questions you want to answer later.

4. **Reason is human-readable.** Always write a sentence explaining
   what happened in English, even if the payload is structured. The
   reason is what shows up in the brain editor's audit timeline.
"""

from __future__ import annotations

from typing import Any, Optional

from loguru import logger

from app.db.supabase import get_client


# Allowed event types — keep in sync with the schema comment in
# 003_knowledge_events.sql. Used by callers as constants.
EVENT_THINKING_CREATED = "thinking_created"
EVENT_THINKING_OBSERVATION_ADDED = "thinking_observation_added"
EVENT_THINKING_GRADUATED = "thinking_graduated"
EVENT_THINKING_REJECTED = "thinking_rejected"
EVENT_THINKING_STALE = "thinking_stale"
EVENT_THINKING_EDITED = "thinking_edited"
EVENT_KNOWLEDGE_CREATED = "knowledge_created"
EVENT_KNOWLEDGE_EDITED = "knowledge_edited"
EVENT_KNOWLEDGE_DEACTIVATED = "knowledge_deactivated"
# Stage 6: thesis tracking events
EVENT_THESIS_EVALUATED = "thesis_evaluated"
EVENT_THESIS_INVALIDATED_EXIT = "thesis_invalidated_exit"

OUTCOME_SUPPORTING = "supporting"
OUTCOME_CONTRADICTING = "contradicting"
OUTCOME_NEUTRAL = "neutral"


def log_event(
    event_type: str,
    triggered_by: str,
    *,
    thinking_id: Optional[str] = None,
    knowledge_id: Optional[str] = None,
    trade_id: Optional[str] = None,
    observation_outcome: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
    reason: Optional[str] = None,
) -> Optional[str]:
    """Append a row to the knowledge_events audit log.

    Args:
        event_type: One of the EVENT_* constants above.
        triggered_by: Who/what caused the event. Free-text but conventional
            values are 'auto_extractor', 'claude_journal_analysis',
            'user_manual', 'graduation_logic', 'thesis_tracker',
            'brain_editor_api', 'seed_brain_py'.
        thinking_id: FK to signal_thinking, if the event concerns a hypothesis.
        knowledge_id: FK to signal_knowledge, if the event concerns a knowledge entry.
        trade_id: FK to virtual_trades, if the event was triggered by a closed trade.
        observation_outcome: 'supporting' | 'contradicting' | 'neutral' — only
            meaningful for thinking_observation_added events.
        payload: Free-form JSONB snapshot of relevant state at event time.
            Schema varies by event_type (see module docstring for examples).
        reason: Human-readable explanation. Always write one — it's what
            shows up in the brain editor's audit timeline.

    Returns:
        The id of the inserted row, or None if the insert failed (failures
        are logged as warnings, never raised — audit logging must NEVER
        block business logic).
    """
    try:
        db = get_client()
        row = {
            "event_type": event_type,
            "triggered_by": triggered_by,
            "thinking_id": thinking_id,
            "knowledge_id": knowledge_id,
            "trade_id": trade_id,
            "observation_outcome": observation_outcome,
            "payload": payload,
            "reason": reason,
        }
        result = db.table("knowledge_events").insert(row).execute()
        if result.data:
            event_id = result.data[0].get("id")
            logger.debug(
                f"knowledge_event logged: {event_type} by {triggered_by}"
                + (f" thinking={thinking_id[:8]}" if thinking_id else "")
                + (f" knowledge={knowledge_id[:8]}" if knowledge_id else "")
            )
            return event_id
        return None
    except Exception as e:
        # Audit log failures must never break the calling code. Log a
        # warning and move on. If the table doesn't exist yet, this lets
        # the rest of the code keep running (forward-compatible).
        logger.warning(
            f"Failed to log knowledge_event ({event_type} by {triggered_by}): {e}"
        )
        return None


def get_events_for_thinking(thinking_id: str, limit: int = 100) -> list[dict]:
    """Return all events for one thinking entry, oldest first.

    Used by the brain editor's audit timeline view (post-Stage-7 work)
    and by Claude when re-evaluating whether to graduate a hypothesis.
    """
    try:
        db = get_client()
        result = (
            db.table("knowledge_events")
            .select("*")
            .eq("thinking_id", thinking_id)
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.warning(f"Failed to load events for thinking {thinking_id}: {e}")
        return []


def get_events_for_knowledge(knowledge_id: str, limit: int = 100) -> list[dict]:
    """Return all events for one knowledge entry, oldest first."""
    try:
        db = get_client()
        result = (
            db.table("knowledge_events")
            .select("*")
            .eq("knowledge_id", knowledge_id)
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.warning(f"Failed to load events for knowledge {knowledge_id}: {e}")
        return []
