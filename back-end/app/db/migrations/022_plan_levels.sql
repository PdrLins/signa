-- ============================================================
-- 022_plan_levels.sql — Free / Premium split (decided 2026-10-02)
-- ============================================================
--
-- WHY
--   Free should cover everything needed to understand your own portfolio;
--   Premium adds planning and deeper analysis. Rows in access_features
--   override the code defaults (app/core/access.py), so the levels that
--   earlier migrations stored must be updated here too.
--
-- WHAT
--   feature.intraday_chart    premium -> free  (5-minute 1D bars for everyone)
--   action.accounts.type      premium -> free  (TFSA / RRSP / IRA tags)
--   feature.allocation_plan   new, premium     (target allocation + deposit plan:
--                                               GET/PUT /portfolio/allocation/targets,
--                                               GET /portfolio/allocation/plan)
--   feature.income_quality    new, premium     (GET /portfolio/income-quality/{symbol})
--   feature.similar_funds     new, premium     (reserved: similar funds on the stock page)
--   The allocation mix (GET /portfolio/allocation), ETF fund data, sectors,
--   top holdings and the About card stay free.
--
-- HOW TO APPLY (after 021)
--   Supabase dashboard → SQL Editor → paste this file → Run.
--   (or: psql "$DATABASE_URL" -f back-end/app/db/migrations/022_plan_levels.sql)
--   Idempotent: safe to run more than once.
--
-- BEFORE IT IS APPLIED
--   The code defaults already have the new levels, but the stored rows for
--   feature.intraday_chart and action.accounts.type keep them Premium until
--   this runs. The new premium keys work from the code defaults.
-- ============================================================

INSERT INTO access_features (key, min_level, description) VALUES
  ('feature.intraday_chart', 'free', '5-minute intraday chart'),
  ('action.accounts.type', 'free', 'Tag accounts with a tax type (TFSA, RRSP, IRA ...)'),
  ('feature.allocation_plan', 'premium', 'Target allocation and deposit plan'),
  ('feature.income_quality', 'premium', 'Income quality of option-income / covered-call ETFs'),
  ('feature.similar_funds', 'premium', 'Similar funds compared (fee, yield, return)')
ON CONFLICT (key) DO UPDATE SET min_level = EXCLUDED.min_level, description = EXCLUDED.description;
