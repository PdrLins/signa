-- ============================================================
-- 009_breaker_reset.sql — drawdown breaker pause / reset state
-- ============================================================
--
-- WHY
--   The brain's drawdown breaker blocked new entries whenever equity was
--   >= brain_max_drawdown_pct below brain_wallet.peak_equity. Once the book
--   is flat in cash, equity can never climb back to that peak, so after one
--   trip the breaker latched FOREVER (the 2021-2026 backtest showed 1,734
--   blocked days after a single trip).
--
--   The breaker now pauses new entries for brain_drawdown_pause_trading_days
--   (default 10) US trading days after a trip, then resets peak_equity to
--   the current equity and resumes (virtual_portfolio.evaluate_drawdown_breaker).
--   The trip time must survive between scans / restarts, hence this column.
--
-- HOW TO APPLY
--   Supabase dashboard → SQL Editor → paste this file → Run.
--   (or: psql "$DATABASE_URL" -f back-end/app/db/migrations/009_breaker_reset.sql)
--   Idempotent: safe to run more than once.
--
-- BEFORE IT IS APPLIED
--   The backend keeps working: a missing column is logged as a warning and
--   the breaker behaves as "never persisted" (blocked while in drawdown,
--   no timed resume, no Telegram trip/resume notifications).
--
-- NOTE
--   The technical-filter result for each signal is stored inside the
--   existing signals.technical_data JSONB (key "_tech_filter"), so no new
--   signals column is needed.
-- ============================================================

ALTER TABLE brain_wallet ADD COLUMN IF NOT EXISTS breaker_tripped_at TIMESTAMPTZ;

COMMENT ON COLUMN brain_wallet.breaker_tripped_at IS
    'When the drawdown breaker last tripped; NULL = not tripped. New entries pause for '
    'brain_drawdown_pause_trading_days US trading days, then peak_equity resets to equity.';
