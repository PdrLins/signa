-- Migration 002: Full schema for the self-learning loop (Stages 1.5, 3, 5, 6)
--
-- WHY: Adds every column the remaining stages of the learning-loop build
-- need. After running this, all DDL for the project is done — Stages 2-7
-- become pure code changes.
--
-- IDEMPOTENT: every statement uses IF NOT EXISTS or DEFAULTs that handle
-- re-runs safely. You can run this script multiple times without errors.
--
-- HOW TO APPLY: paste this entire file into the Supabase Dashboard SQL
-- editor and run it. The verification SELECTs at the bottom confirm
-- everything succeeded.

-- ============================================================
-- STAGE 1.5 — distinguish seeded knowledge from learned knowledge
-- ============================================================
-- Why: when a thinking entry graduates to knowledge, we want to be able
-- to filter and badge those entries differently from the seed entries
-- that came from seed_brain.py / seed_phase1_knowledge.py.

ALTER TABLE signal_knowledge
    ADD COLUMN IF NOT EXISTS source_type VARCHAR DEFAULT 'seed';
-- Allowed values:
--   'seed'                  = original seed_*.py entries
--   'manual'                = added by user via brain editor
--   'learned_from_thinking' = graduated from a signal_thinking hypothesis
--   'auto_extracted'        = future: written by pattern_extractor

ALTER TABLE signal_knowledge
    ADD COLUMN IF NOT EXISTS learned_from_thinking_id UUID
    REFERENCES signal_thinking(id);
-- NULL for seed/manual entries. For learned entries, points to the
-- original hypothesis so we can join back to the evidence trail.

CREATE INDEX IF NOT EXISTS idx_signal_knowledge_source_type
    ON signal_knowledge(source_type);

-- Backfill: explicitly mark every existing row as 'seed' (the default
-- already does this for new rows, but existing rows that pre-date the
-- column will have NULL otherwise).
UPDATE signal_knowledge SET source_type = 'seed' WHERE source_type IS NULL;

-- ============================================================
-- STAGE 5 — invalidation_conditions on signal_knowledge
-- ============================================================
-- Why: knowledge is conditional, not absolute. Every pattern needs to
-- describe (a) when it fires, (b) what to expect, AND (c) when it stops
-- applying. signal_thinking already has this column from migration 001;
-- this adds the matching column to signal_knowledge so graduated
-- entries can preserve the invalidation logic.

ALTER TABLE signal_knowledge
    ADD COLUMN IF NOT EXISTS invalidation_conditions JSONB;

-- ============================================================
-- STAGE 3 — snapshot market_regime on virtual_trades at insert time
-- ============================================================
-- Why: when a brain trade closes, we need to know what regime it was
-- entered in to feed learning_service.record_outcome() and to compute
-- pattern stats. The regime can change between entry and exit, so we
-- snapshot at insert.

ALTER TABLE virtual_trades
    ADD COLUMN IF NOT EXISTS market_regime VARCHAR;

-- ============================================================
-- STAGE 6 — thesis tracking on virtual_trades
-- ============================================================
-- Why: every brain entry must capture WHY it was bought (Claude's
-- reasoning). At every scan we re-evaluate whether the reason still
-- holds. If not, we exit with reason='THESIS_INVALIDATED' regardless
-- of P&L direction. This is the "oil-barrel" exit: sell at +50% when
-- the war ends, even though the position is winning.

ALTER TABLE virtual_trades
    ADD COLUMN IF NOT EXISTS entry_thesis TEXT;
-- Free-text reason for the buy, captured from Claude's reasoning field
-- at insert time. ~500 chars max in practice.

ALTER TABLE virtual_trades
    ADD COLUMN IF NOT EXISTS entry_thesis_keywords JSONB;
-- Structured snapshot of the entry conditions for fast re-eval diff.
-- Example: {"regime": "VOLATILE", "score_at_entry": 78,
--           "macd_histogram": -19.66, "sentiment_score": 65,
--           "catalyst": "Q3 earnings beat", "fear_greed": 21}

ALTER TABLE virtual_trades
    ADD COLUMN IF NOT EXISTS thesis_last_checked_at TIMESTAMPTZ;
-- Last time the thesis was re-evaluated by Claude.

ALTER TABLE virtual_trades
    ADD COLUMN IF NOT EXISTS thesis_last_status VARCHAR;
-- 'valid' | 'weakening' | 'invalid' | NULL (never checked yet)

ALTER TABLE virtual_trades
    ADD COLUMN IF NOT EXISTS thesis_last_reason TEXT;
-- Claude's prose explanation of the most recent thesis check.
-- ~500 chars max.

CREATE INDEX IF NOT EXISTS idx_virtual_trades_thesis_status
    ON virtual_trades(thesis_last_status) WHERE status = 'OPEN';
-- Speeds up the per-scan thesis re-eval query, which scans only
-- open positions and groups by status.

-- ============================================================
-- VERIFICATION
-- ============================================================
-- Run these SELECTs after applying. Each should return rows confirming
-- the columns were added.

-- 1. signal_knowledge new columns
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'signal_knowledge'
  AND column_name IN ('source_type', 'learned_from_thinking_id', 'invalidation_conditions')
ORDER BY column_name;

-- 2. virtual_trades new columns
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'virtual_trades'
  AND column_name IN (
    'market_regime', 'entry_thesis', 'entry_thesis_keywords',
    'thesis_last_checked_at', 'thesis_last_status', 'thesis_last_reason'
  )
ORDER BY column_name;

-- 3. signal_knowledge backfill check — every row should have source_type
SELECT source_type, COUNT(*) FROM signal_knowledge GROUP BY source_type;

-- 4. signal_thinking sanity (already from migration 001) — should show 1 row
SELECT id, status, observations_supporting, observations_contradicting
FROM signal_thinking
WHERE status = 'active';
