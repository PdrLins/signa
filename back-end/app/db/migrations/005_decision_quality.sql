-- Migration 005: decision-quality reset — AI verdict columns on signals,
-- purge of poisoned ticker buckets.
--
-- WHY:
--   1. signals.ai_status="validated" used to mean only "confidence >= 50",
--      even when Claude's own signal was HOLD/AVOID. The scan now records
--      Claude's verdict, the provider that produced it, and its win
--      probability as first-class columns so the brain can gate on them
--      (previously ai_signal was buried in grok_data._ai_signal).
--   2. The bucket classifier read sector/dividend/market-cap from bulk
--      screening rows that never contained them, so every unknown ticker
--      was persisted as SAFE_INCOME (and TQQQ/SQQQ were "safe" because
--      every known ETF was). tickers.bucket is sticky (upsert never
--      overwrites it), so those wrong buckets would survive the code fix.
--      Clear them; the next scan re-classifies from real fundamentals.
--
-- ai_status vocabulary after this migration:
--   validated       AI signal == BUY and confidence >= ai_validated_min_confidence (60)
--   low_confidence  AI signal == BUY, confidence below that
--   rejected        AI ran but its signal was not BUY
--   failed          provider error / unparseable (confidence 0)
--   skipped         tech-only, AI never ran (never auto-buy)
--
-- HOW TO APPLY: paste into Supabase SQL editor. Idempotent.

ALTER TABLE signals ADD COLUMN IF NOT EXISTS ai_signal   VARCHAR;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS ai_provider VARCHAR;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS p_win       DOUBLE PRECISION;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'signals_p_win_range'
    ) THEN
        ALTER TABLE signals
            ADD CONSTRAINT signals_p_win_range
            CHECK (p_win IS NULL OR (p_win >= 0 AND p_win <= 1));
    END IF;
END $$;

COMMENT ON COLUMN signals.ai_status IS
    'validated | low_confidence | rejected | failed | skipped (see migration 005)';
COMMENT ON COLUMN signals.ai_signal IS
    'Raw synthesis signal from the AI (BUY/HOLD/SELL/AVOID); NULL for tech-only';
COMMENT ON COLUMN signals.ai_provider IS
    'Provider that produced the synthesis (synthesis._provider)';
COMMENT ON COLUMN signals.p_win IS
    'AI-estimated probability the trade hits target before stop, 0..1';

CREATE INDEX IF NOT EXISTS idx_signals_ai_status_date
    ON signals(ai_status, created_at DESC);

-- Purge buckets persisted by the broken classifier (re-derived next scan).
UPDATE tickers SET bucket = NULL WHERE bucket IS NOT NULL;

-- Number of live-search citations backing the sentiment (0 = uncited /
-- not fetched). The full list stays in grok_data.citations.
ALTER TABLE signals ADD COLUMN IF NOT EXISTS sentiment_citations INT DEFAULT 0;
