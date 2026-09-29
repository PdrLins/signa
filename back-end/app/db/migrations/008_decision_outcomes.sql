-- Migration 008: counterfactual outcome tracking for every scan candidate.
--
-- WHY: the brain only learned from trades it actually took. A gate that
-- SKIPs stocks which then outperform is invisible in trade P&L. This
-- migration records, for EVERY signal the scan produced (entered, skipped
-- or never considered), what the price did over the next 5/10/20 trading
-- days, raw and in excess of SPY. That lets the daily learning loop
-- measure: skip-reason effectiveness, p_win calibration, routine (Sonnet)
-- vs decision (Opus) model overturns, and AI-status cohorts.
--
-- Writers:
--   * scan_service  -> signals.routine_ai_signal / signals.decision_overturned
--   * app/services/decision_outcomes.py (scheduler job 17:15 ET)
--       seed_candidates()      -> INSERT candidate_outcomes (one per signal)
--       fill_forward_returns() -> UPDATE fwd_ret_* / spy_ret_* / excess_ret_*
--
-- Returns are DECIMAL fractions (0.05 = +5%). Horizons are TRADING days on
-- the symbol's exchange calendar (crypto: calendar days). The benchmark is
-- SPY for every asset (including .TO and crypto) so all excess returns are
-- comparable — for TSX names this mixes in USD/CAD and US-vs-CA market
-- beta; read TSX excess returns with that in mind.
--
-- HOW TO APPLY: paste into the Supabase SQL editor and run. Idempotent
-- (IF NOT EXISTS everywhere). Apply BEFORE deploying the backend that
-- writes signals.routine_ai_signal — scan_service falls back to inserting
-- without the two new signals columns if they are missing, but the
-- outcome job needs the candidate_outcomes table.

-- ============================================================
-- 1. signals — routine vs decision model audit columns
-- ============================================================
ALTER TABLE signals ADD COLUMN IF NOT EXISTS routine_ai_signal   VARCHAR;
    -- signal from the routine (screening) model; equals ai_signal when no
    -- escalation happened; NULL for tech-only rows
ALTER TABLE signals ADD COLUMN IF NOT EXISTS decision_overturned BOOLEAN;
    -- NULL  = not escalated to the decision model (or it was unavailable)
    -- FALSE = decision model confirmed the routine BUY
    -- TRUE  = decision model returned a different signal (veto)

CREATE INDEX IF NOT EXISTS idx_signals_decision_overturned
    ON signals(decision_overturned, created_at DESC)
    WHERE decision_overturned IS NOT NULL;

-- ============================================================
-- 2. candidate_outcomes — one row per signal, forward returns
-- ============================================================
CREATE TABLE IF NOT EXISTS candidate_outcomes (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_id           UUID NOT NULL UNIQUE REFERENCES signals(id) ON DELETE CASCADE,
    scan_id             UUID,
    symbol              VARCHAR NOT NULL,
    exchange            VARCHAR,
    signal_at           TIMESTAMPTZ NOT NULL,
    price_at_signal     DOUBLE PRECISION,
    action              VARCHAR,
    score               INT,
    ai_status           VARCHAR,
    ai_signal           VARCHAR,
    ai_provider         VARCHAR,
    p_win               DOUBLE PRECISION,
    routine_signal      VARCHAR,
    decision_overturned BOOLEAN,
    bucket              VARCHAR,
    brain_decision      VARCHAR CHECK (brain_decision IS NULL OR brain_decision IN ('ENTER', 'SKIP')),
    skip_reason         TEXT,
    fwd_ret_5d          DOUBLE PRECISION,
    fwd_ret_10d         DOUBLE PRECISION,
    fwd_ret_20d         DOUBLE PRECISION,
    spy_ret_5d          DOUBLE PRECISION,
    spy_ret_10d         DOUBLE PRECISION,
    spy_ret_20d         DOUBLE PRECISION,
    excess_ret_5d       DOUBLE PRECISION,
    excess_ret_10d      DOUBLE PRECISION,
    excess_ret_20d      DOUBLE PRECISION,
    filled_5d_at        TIMESTAMPTZ,
    filled_10d_at       TIMESTAMPTZ,
    filled_20d_at       TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_candidate_outcomes_signal_at
    ON candidate_outcomes(signal_at DESC);
CREATE INDEX IF NOT EXISTS idx_candidate_outcomes_unfilled
    ON candidate_outcomes(signal_at) WHERE filled_20d_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_candidate_outcomes_decision
    ON candidate_outcomes(brain_decision, skip_reason);
CREATE INDEX IF NOT EXISTS idx_candidate_outcomes_symbol
    ON candidate_outcomes(symbol, signal_at DESC);

-- RLS: follow whatever 007_enable_rls.sql decided. If RLS is already on
-- for `signals` (007 applied => backend uses service_role), turn it on
-- here too; otherwise leave it off so an anon-key backend keeps working
-- (007's catch-all will cover this table when it is applied later).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables
        WHERE schemaname = 'public' AND tablename = 'signals' AND rowsecurity
    ) THEN
        ALTER TABLE public.candidate_outcomes ENABLE ROW LEVEL SECURITY;
    END IF;
END $$;
