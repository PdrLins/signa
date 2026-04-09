-- Migration 003: knowledge_events append-only audit log
--
-- WHY: Make the brain's learning history fully traceable. Every time a
-- thinking entry is created, observed, graduated, rejected, or edited
-- — and every time a knowledge entry is created, edited, or deactivated
-- — an event row is appended here. Append-only: never UPDATE, never
-- DELETE. The whole table IS the audit log.
--
-- WITHOUT THIS: we have aggregate counters but no individual events.
-- We can't answer "show me the 5 trades that graduated this hypothesis"
-- or "why did the brain start avoiding META-class signals last Tuesday."
-- Aggregates lose history; events preserve it.
--
-- HOW TO APPLY: paste into Supabase Dashboard SQL editor and run.
-- Idempotent (uses IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS knowledge_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type      VARCHAR NOT NULL,
        -- Allowed values:
        --   'thinking_created'             new hypothesis proposed
        --   'thinking_observation_added'   a closed trade matched, counter incremented
        --   'thinking_graduated'           hypothesis became validated knowledge
        --   'thinking_rejected'            counter-evidence won
        --   'thinking_stale'               aged out (no observations for X days)
        --   'thinking_edited'              hypothesis text or pattern_match changed
        --   'knowledge_created'            new signal_knowledge row inserted
        --   'knowledge_edited'             existing knowledge row updated
        --   'knowledge_deactivated'        is_active flipped to false
    thinking_id     UUID REFERENCES signal_thinking(id),
    knowledge_id    UUID REFERENCES signal_knowledge(id),
    trade_id        UUID REFERENCES virtual_trades(id),
        -- If the event was triggered by a closed trade (e.g., observation
        -- increment, auto-graduation), link it. NULL otherwise.
    triggered_by    VARCHAR NOT NULL,
        -- Examples: 'auto_extractor', 'claude_journal_analysis',
        -- 'user_manual', 'graduation_logic', 'thesis_tracker',
        -- 'brain_editor_api', 'seed_brain_py'
    observation_outcome VARCHAR,
        -- For 'thinking_observation_added' events only:
        -- 'supporting' | 'contradicting' | 'neutral'
    payload         JSONB,
        -- Snapshot of relevant state at event time. Schema varies by
        -- event_type. Examples:
        --   observation_added: {bucket, regime, score, pnl_pct, days_held}
        --   graduated: {observations_supporting, observations_contradicting,
        --               graduation_threshold, knowledge_id_created}
        --   edited: {before: {...}, after: {...}}
    reason          TEXT,
        -- Human-readable explanation, e.g., "Trade META closed -2.4%
        -- — matches pattern_match (SAFE_INCOME/VOLATILE/macd_neg),
        -- supporting count 2 → 3"
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_knowledge_events_thinking
    ON knowledge_events(thinking_id) WHERE thinking_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_knowledge_events_knowledge
    ON knowledge_events(knowledge_id) WHERE knowledge_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_knowledge_events_type
    ON knowledge_events(event_type);

CREATE INDEX IF NOT EXISTS idx_knowledge_events_created
    ON knowledge_events(created_at DESC);

-- ============================================================
-- VERIFICATION (should return 4 rows: the 4 columns named below)
-- ============================================================
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'knowledge_events'
  AND column_name IN ('event_type', 'triggered_by', 'payload', 'reason')
ORDER BY column_name;
