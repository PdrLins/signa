-- Migration 001: signal_thinking table (Stage 1 of self-learning loop)
--
-- WHY: Distinguish hypotheses (low confidence, under observation) from
-- knowledge (validated, proven). Hypotheses get fed to Claude as "Working
-- Hypotheses" with explicit low-confidence framing. When observations_supporting
-- reaches graduation_threshold (and contradicting stays low), the entry can
-- be promoted to signal_knowledge.
--
-- HOW TO APPLY: Paste this entire file into the Supabase Dashboard SQL editor
-- and run it. Idempotent — safe to run multiple times.

CREATE TABLE IF NOT EXISTS signal_thinking (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hypothesis                  TEXT NOT NULL,
    prediction                  TEXT NOT NULL,
    pattern_match               JSONB NOT NULL,
    invalidation_conditions     JSONB,
    created_by                  VARCHAR NOT NULL,
    observations_supporting     INT DEFAULT 0,
    observations_contradicting  INT DEFAULT 0,
    observations_neutral        INT DEFAULT 0,
    status                      VARCHAR DEFAULT 'active',
    graduation_threshold        INT DEFAULT 5,
    graduated_to                UUID REFERENCES signal_knowledge(id),
    last_evaluated_at           TIMESTAMPTZ,
    notes                       TEXT,
    created_at                  TIMESTAMPTZ DEFAULT now(),
    updated_at                  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_signal_thinking_active
    ON signal_thinking(status) WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_signal_thinking_created_by
    ON signal_thinking(created_by);
