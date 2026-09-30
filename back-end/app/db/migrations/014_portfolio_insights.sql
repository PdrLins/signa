-- ============================================================
-- 014_portfolio_insights.sql — history tables for the tracker's insights
-- ============================================================
--
-- WHY
--   Phase 2 of the portfolio tracker (home, performance, dividends
--   summary, coming up, allocation) needs two small daily histories the
--   app can diff against, plus an honest timestamp on shared quotes:
--
--   * "Why your income changed" (GET /dividends/summary) compares today's
--     forward income forecast with the one ~30 days ago: FX, raises, cuts,
--     new / removed shares. That needs one stored forecast per user per day.
--   * "A Signa check changed" (GET /events/upcoming) needs yesterday's
--     check statuses per symbol. The checks are shared market data (the
--     free stock page), so this table is per SYMBOL, not per user.
--   * quotes.as_of used to be the daily bar's date at midnight. It is now
--     the real time of the price and `as_of_source` says how it was
--     obtained, so clients can show "As of 10:42 ET · delayed 15 min".
--
-- WHAT
--   income_forecast_snapshots  one row per user per day (daily job, 18:00 ET):
--       total_home  forward 12-month income in the user's home currency
--                   (before tax; shares x forward annual rate)
--       currency    the home currency used
--       usdcad      CAD per 1 USD used for the conversion
--       per_symbol  {"NVDA": {"shares": 10, "annual_rate": 0.04, "currency": "USD",
--                             "annual_native": 0.4, "annual_home": 0.55}, ...}
--   check_status_daily         one row per symbol per day (daily job, 18:15 ET):
--       statuses    {"uptrend": "pass", "not_overheated": "warn", ...}
--                   (the five Signa checks of the stock page)
--   quotes.as_of_source        'bar' (intraday bar time) | 'fetch' (time the
--                   live daily bar was fetched) | 'close' (the session close
--                   of a finished daily bar)
--   users.last_seen_at         last authenticated request (written at most
--                   once per hour per user by the auth middleware). The
--                   quotes job only refreshes symbols followed by users seen
--                   in the last 7 days (cost control).
--   data_usage_daily           (usage_date, metric) -> count: provider calls
--                   (quotes, daily history, intraday bars ...), symbols
--                   refreshed and requests to the heavy endpoints, so a price
--                   per plan can be set later. Incremented through
--                   increment_data_usage() (atomic), buffered in memory and
--                   flushed every few minutes. Read by GET /admin/usage (owner).
--   access_features            feature.intraday_chart (premium: 5-minute 1D
--                   chart; free gets 15-minute bars) and feature.full_history
--                   (premium: the ALL range; free stops at 1Y)
--
-- HOW TO APPLY (after 013)
--   Supabase dashboard → SQL Editor → paste this file → Run.
--   (or: psql "$DATABASE_URL" -f back-end/app/db/migrations/014_portfolio_insights.sql)
--   Idempotent: safe to run more than once.
--
-- BEFORE IT IS APPLIED
--   Everything keeps working: /dividends/summary returns no "why changed"
--   history (available_from = null), /events/upcoming has no check_changed
--   items, the two daily jobs log a warning and do nothing, quotes are
--   stored without as_of_source, activity falls back to users.last_login,
--   usage counters are dropped (logged) and /admin/usage answers 503
--   migration_required.
--
-- RLS
--   Enabled with no policies, like 007/013 (backend uses service_role).
-- ============================================================


-- ---------------------------------------------------------------- income forecast
CREATE TABLE IF NOT EXISTS income_forecast_snapshots (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    snapshot_date  DATE NOT NULL,
    total_home     NUMERIC,
    currency       VARCHAR(3) NOT NULL,
    usdcad         NUMERIC,
    per_symbol     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT income_forecast_snapshots_user_date_key UNIQUE (user_id, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_income_forecast_user_date
    ON income_forecast_snapshots (user_id, snapshot_date DESC);
ALTER TABLE public.income_forecast_snapshots ENABLE ROW LEVEL SECURITY;


-- ---------------------------------------------------------------- check status (shared)
CREATE TABLE IF NOT EXISTS check_status_daily (
    symbol      VARCHAR(24) NOT NULL,
    check_date  DATE NOT NULL,
    statuses    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (symbol, check_date)
);
CREATE INDEX IF NOT EXISTS idx_check_status_daily_date ON check_status_daily (check_date);
ALTER TABLE public.check_status_daily ENABLE ROW LEVEL SECURITY;


-- ---------------------------------------------------------------- quotes
ALTER TABLE quotes ADD COLUMN IF NOT EXISTS as_of_source VARCHAR(8);
COMMENT ON COLUMN quotes.as_of IS
    'Real time of the price (014): intraday bar time, fetch time of a live daily bar, or the session close.';


-- ---------------------------------------------------------------- activity
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_users_last_seen_at ON users (last_seen_at);


-- ---------------------------------------------------------------- usage metrics
CREATE TABLE IF NOT EXISTS data_usage_daily (
    usage_date  DATE NOT NULL,
    metric      VARCHAR(64) NOT NULL,
    count       BIGINT NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (usage_date, metric)
);
ALTER TABLE public.data_usage_daily ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION increment_data_usage(p_date DATE, p_metric TEXT, p_count BIGINT)
RETURNS VOID LANGUAGE sql AS $$
    INSERT INTO data_usage_daily (usage_date, metric, count, updated_at)
    VALUES (p_date, p_metric, p_count, now())
    ON CONFLICT (usage_date, metric)
    DO UPDATE SET count = data_usage_daily.count + EXCLUDED.count, updated_at = now();
$$;


-- ---------------------------------------------------------------- access features
INSERT INTO access_features (key, min_level, description) VALUES
  ('feature.intraday_chart', 'premium', '5-minute intraday chart (free: 15-minute bars)'),
  ('feature.full_history', 'premium', 'Full portfolio history (ALL range; free: up to 1 year)')
ON CONFLICT (key) DO NOTHING;
