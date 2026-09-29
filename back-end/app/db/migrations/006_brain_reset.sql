-- Migration 006: brain decision-quality reset (schema only — no data changes)
--
-- WHY: the brain was rebuilt around risk-based sizing, hard ATR stops with
-- an ATR trailing ratchet, realistic fills (slippage/fees/FX), a
-- peak-to-trough drawdown breaker and an auditable entry funnel. This
-- migration adds the columns/tables that code needs. It MUST be applied
-- before the new backend runs (VIRTUAL_TRADES_CLOSE_FIELDS selects the new
-- virtual_trades columns).
--
-- Data wipe is NOT done here: run `python scripts/reset_brain.py --confirm`
-- (archives to JSON first) after applying this file.
--
-- HOW TO APPLY: paste into the Supabase SQL editor and run. Idempotent.

-- ============================================================
-- 1. virtual_trades — levels, costs, FX, sector, entry evidence
-- ============================================================
ALTER TABLE virtual_trades ADD COLUMN IF NOT EXISTS tier_reason       TEXT;
ALTER TABLE virtual_trades ADD COLUMN IF NOT EXISTS initial_stop      DOUBLE PRECISION;
    -- stop at entry; defines 1R. stop_loss is the live (possibly trailed) stop
ALTER TABLE virtual_trades ADD COLUMN IF NOT EXISTS entry_atr         DOUBLE PRECISION;
    -- ATR(14) at entry (native currency) — drives the trailing distance
ALTER TABLE virtual_trades ADD COLUMN IF NOT EXISTS entry_rr          DOUBLE PRECISION;
    -- reward:risk computed in code from the fill price
ALTER TABLE virtual_trades ADD COLUMN IF NOT EXISTS entry_p_win       DOUBLE PRECISION;
ALTER TABLE virtual_trades ADD COLUMN IF NOT EXISTS entry_ai_signal   VARCHAR;
ALTER TABLE virtual_trades ADD COLUMN IF NOT EXISTS entry_ref_price   DOUBLE PRECISION;
    -- quoted price at decision time; entry_price is the fill after slippage
ALTER TABLE virtual_trades ADD COLUMN IF NOT EXISTS exit_ref_price    DOUBLE PRECISION;
    -- quoted price at exit; exit_price is the fill after slippage
ALTER TABLE virtual_trades ADD COLUMN IF NOT EXISTS fees_usd          DOUBLE PRECISION DEFAULT 0;
ALTER TABLE virtual_trades ADD COLUMN IF NOT EXISTS currency          VARCHAR DEFAULT 'USD';
    -- native quote currency; prices on the row are native, cash is USD
ALTER TABLE virtual_trades ADD COLUMN IF NOT EXISTS fx_to_usd_entry   DOUBLE PRECISION DEFAULT 1.0;
ALTER TABLE virtual_trades ADD COLUMN IF NOT EXISTS fx_to_usd_exit    DOUBLE PRECISION;
ALTER TABLE virtual_trades ADD COLUMN IF NOT EXISTS sector            VARCHAR;
    -- snapshotted at entry for the per-sector position cap

CREATE INDEX IF NOT EXISTS idx_virtual_trades_brain_exit
    ON virtual_trades(source, status, exit_date DESC);

-- ============================================================
-- 2. brain_wallet.peak_equity — drawdown breaker reference
-- ============================================================
ALTER TABLE brain_wallet ADD COLUMN IF NOT EXISTS peak_equity DOUBLE PRECISION DEFAULT 0;

-- ============================================================
-- 3. virtual_snapshots.brain_equity — real USD equity curve
-- ============================================================
ALTER TABLE virtual_snapshots ADD COLUMN IF NOT EXISTS brain_equity DOUBLE PRECISION;

-- ============================================================
-- 4. signal_thinking.expected_direction — what the hypothesis predicts
-- ============================================================
ALTER TABLE signal_thinking ADD COLUMN IF NOT EXISTS expected_direction VARCHAR;
    -- 'loss' (cohort under-performs) | 'win' (over-performs); NULL = infer from text

-- ============================================================
-- 5. brain_decisions — one row per candidate per scan (entry funnel)
-- ============================================================
CREATE TABLE IF NOT EXISTS brain_decisions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scan_id     UUID,
    symbol      VARCHAR NOT NULL,
    decided_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    decision    VARCHAR NOT NULL CHECK (decision IN ('ENTER', 'SKIP')),
    reason      TEXT,
        -- e.g. 'ai_buy' | 'not_ai_buy_rejected_sell' | 'rr_below_min_1.40'
        --      | 'max_open_positions_8' | 'sector_cap_technology'
        --      | 'reentry_cooldown_3d' | 'drawdown_breaker_...' | 'market_closed'
    score       INT,
    ai_status   VARCHAR,
    ai_signal   VARCHAR,
    details     JSONB
        -- {tier, fill, stop, target, rr, levels_source, shares, alloc_usd,
        --  risk_usd, sector, p_win, trade_id, ...}
);
CREATE INDEX IF NOT EXISTS idx_brain_decisions_scan    ON brain_decisions(scan_id);
CREATE INDEX IF NOT EXISTS idx_brain_decisions_symbol  ON brain_decisions(symbol, decided_at DESC);
CREATE INDEX IF NOT EXISTS idx_brain_decisions_decided ON brain_decisions(decided_at DESC);
CREATE INDEX IF NOT EXISTS idx_brain_decisions_reason  ON brain_decisions(decision, reason);

-- RLS: intentionally not enabled here — migration 007_enable_rls.sql owns
-- RLS for every table (it requires the service_role key first).
