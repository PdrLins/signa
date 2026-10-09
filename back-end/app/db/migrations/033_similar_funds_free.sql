-- ============================================================================
-- 033_similar_funds_free.sql — fund comparison for every plan
-- ============================================================================
-- feature.similar_funds   premium -> free   ("Similar funds" table on an ETF's
--   stock page: fee, yield, return). Premium can't be bought yet, so free users
--   shouldn't see it locked.
-- Before it is applied: the code default is already free, but a stored row
-- (from 022) keeps it Premium until this runs. Idempotent.
-- ============================================================================

INSERT INTO access_features (key, min_level, description) VALUES
  ('feature.similar_funds', 'free', 'Similar funds compared (fee, yield, return)')
ON CONFLICT (key) DO UPDATE SET min_level = EXCLUDED.min_level, description = EXCLUDED.description;
