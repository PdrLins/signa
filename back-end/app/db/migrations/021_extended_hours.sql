-- ============================================================
-- 021_extended_hours.sql — pre-market / after-hours prices (Premium)
-- ============================================================
--
-- WHY
--   US stocks also trade before the open (4:00–9:30 ET) and after the close
--   (16:00–20:00 ET). Premium users see those prices (feature.extended_hours);
--   everyone sees crypto 24/7 (no schema change: the off-hours quotes job
--   refreshes followed crypto at the user's plan rate).
--
-- WHAT
--   quotes.ext_price        last pre-market / after-hours trade (listing currency)
--   quotes.ext_change_pct   vs quotes.price (the last regular-session price)
--   quotes.ext_session      'pre' | 'post'
--   quotes.ext_as_of        time of that trade
--   Clients only show it while it is newer than the regular price and the
--   regular session is closed (app/services/quotes.extended_view).
--   access_features: feature.extended_hours = premium
--
-- HOW TO APPLY (after 020)
--   Supabase dashboard → SQL Editor → paste this file → Run.
--   (or: psql "$DATABASE_URL" -f back-end/app/db/migrations/021_extended_hours.sql)
--   Idempotent: safe to run more than once.
--
-- BEFORE IT IS APPLIED
--   No extended prices are stored or shown ("extended": null everywhere);
--   crypto still refreshes 24/7; the 1D chart of Premium users already
--   includes pre/after-hours bars.
-- ============================================================

ALTER TABLE quotes ADD COLUMN IF NOT EXISTS ext_price NUMERIC;
ALTER TABLE quotes ADD COLUMN IF NOT EXISTS ext_change_pct NUMERIC;
ALTER TABLE quotes ADD COLUMN IF NOT EXISTS ext_session VARCHAR(4);
ALTER TABLE quotes ADD COLUMN IF NOT EXISTS ext_as_of TIMESTAMPTZ;

INSERT INTO access_features (key, min_level, description) VALUES
  ('feature.extended_hours', 'premium', 'Pre-market and after-hours prices (US stocks)')
ON CONFLICT (key) DO NOTHING;
