-- ============================================================================
-- 034_goal_projections.sql — what the user plans to add to a goal
-- ============================================================================
-- goals.monthly_contribution   planned monthly addition, in the goal's currency
--                              (>= 0; NULL = not set)
-- goals.expected_return_pct    yearly growth the user assumes: portfolio growth
--                              for portfolio_value goals, dividend growth for
--                              monthly_income goals (-20..30; NULL = app default)
-- The app projects the date itself; the back-end only stores these.
-- Before it is applied: goals work without them (the fields are left out).
-- Idempotent.
-- ============================================================================

ALTER TABLE goals ADD COLUMN IF NOT EXISTS monthly_contribution NUMERIC;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS expected_return_pct NUMERIC;

ALTER TABLE goals DROP CONSTRAINT IF EXISTS goals_monthly_contribution_check;
ALTER TABLE goals ADD CONSTRAINT goals_monthly_contribution_check
    CHECK (monthly_contribution IS NULL OR monthly_contribution >= 0);
ALTER TABLE goals DROP CONSTRAINT IF EXISTS goals_expected_return_pct_check;
ALTER TABLE goals ADD CONSTRAINT goals_expected_return_pct_check
    CHECK (expected_return_pct IS NULL OR expected_return_pct BETWEEN -20 AND 30);
