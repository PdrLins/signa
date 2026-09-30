-- ============================================================
-- 012_free_areas.sql — feature keys for the free stock page and dividends
-- ============================================================
-- Adds the two free areas to access_features (the code already defaults
-- them to free; the rows make the catalog complete and editable).
-- HOW TO APPLY (after 011): Supabase SQL Editor → paste → Run. Idempotent.
-- ============================================================

INSERT INTO access_features (key, min_level, description) VALUES
  ('area.stock', 'free', 'Stock page: price, dividends, events, Signa checks'),
  ('area.dividends', 'free', 'Dividend calendar and expected income')
ON CONFLICT (key) DO NOTHING;
