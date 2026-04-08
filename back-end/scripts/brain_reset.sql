-- ============================================================
-- BRAIN RESET — schema migration + data wipe
-- ============================================================
-- Run this in the Supabase SQL editor (or psql) BEFORE pressing
-- "Scan Now" so the next scan starts from a clean, instrumented slate.
--
-- WHAT THIS DOES (in order):
--   1. Adds `updated_at` to virtual_trades + trigger so any future
--      mutation of a row leaves a fingerprint (CLOSED rows should
--      have updated_at == exit_date forever; if not, that's a bug).
--   2. Wipes all virtual_trades (open + closed). The brain restarts
--      blind — no win/loss history, no open positions.
--   3. Wipes watchdog_events (they reference now-deleted positions).
--   4. Wipes virtual_snapshots (the daily equity curve, will rebuild).
--
-- WHAT THIS DOES *NOT* TOUCH:
--   - users, watchlist, positions (your real positions), signals,
--     trade_outcomes (real-position learning), portfolio, brain_suggestions
--
-- This file is idempotent for the schema parts (CREATE/ALTER use
-- IF NOT EXISTS / OR REPLACE). The DELETE statements are obviously
-- destructive — only run once per intended reset.
-- ============================================================


-- ── 1. SCHEMA: add updated_at + trigger to virtual_trades ──

ALTER TABLE virtual_trades
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

-- The update_updated_at() function already exists in schema.sql; this just
-- attaches it to virtual_trades. Safe to re-run.
DROP TRIGGER IF EXISTS virtual_trades_updated_at ON virtual_trades;
CREATE TRIGGER virtual_trades_updated_at
    BEFORE UPDATE ON virtual_trades
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();


-- ── 2. WIPE: brain virtual trades + dependent rows ──

DELETE FROM watchdog_events;
DELETE FROM virtual_snapshots;
DELETE FROM virtual_trades;


-- ── 3. SANITY: confirm clean state ──
-- Expected after running this whole file:
--   virtual_trades:    0 rows
--   watchdog_events:   0 rows
--   virtual_snapshots: 0 rows

SELECT 'virtual_trades' AS table_name, count(*) AS rows FROM virtual_trades
UNION ALL
SELECT 'watchdog_events', count(*) FROM watchdog_events
UNION ALL
SELECT 'virtual_snapshots', count(*) FROM virtual_snapshots;
