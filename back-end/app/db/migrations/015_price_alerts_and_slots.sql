-- ============================================================
-- 015_price_alerts_and_slots.sql — price alerts + premium slot rules
-- ============================================================
--
-- WHY
--   Followed symbols are what users pay for: free users follow 10 stocks,
--   premium and owner follow any number. Price alerts ("tell me when ENB.TO
--   goes below 50") are the next free-tier hook: free users keep up to 3
--   active alerts, premium and owner have no limit.
--
-- WHAT
--   price_alerts              one row per alert (API: /api/v1/alerts):
--       direction     'above' (fires when price >= target) | 'below' (price <= target)
--       target_price  in `currency` (the listing currency unless the user
--                     chose another; USD<->CAD are converted at evaluation)
--       active        true until it fires (or the user pauses it)
--       triggered_at  when the quotes job saw the price cross; the alert is
--                     then deactivated and shows in GET /events/upcoming as a
--                     recent "price_alert" item for 7 days
--       last_price    the price (in `currency`) that fired it
--   access_features
--       system.unlimited_slots  owner -> premium (DO UPDATE: the only key
--                     whose level changes here)
--       action.alerts.edit      free    (create / edit / delete alerts)
--       feature.unlimited_alerts premium (no cap on active alerts)
--   users.slot_bonus is KEPT (invite rewards) but no longer raises the free
--   limit: the code caps free at 10 flat (app/core/access.py SLOT_MAX).
--
-- HOW TO APPLY (after 014)
--   Supabase dashboard → SQL Editor → paste this file → Run.
--   (or: psql "$DATABASE_URL" -f back-end/app/db/migrations/015_price_alerts_and_slots.sql)
--   Idempotent: safe to run more than once.
--
-- BEFORE IT IS APPLIED
--   /api/v1/alerts answers 503 {"code": "migration_required",
--   "migration": "015_price_alerts_and_slots.sql"}; the quotes job skips
--   alert evaluation (logged at debug); /events/upcoming reports
--   sources.price_alerts = "unavailable". Slot limits already follow the
--   code (free 10, premium and owner unlimited via SLOT_BASE); the stale
--   011 row (system.unlimited_slots = owner) only makes GET /auth/me show
--   that key as owner-only until this migration updates it.
--
-- RLS
--   Enabled with no policies, like 007/013/014 (backend uses service_role).
-- ============================================================


-- ---------------------------------------------------------------- price alerts
CREATE TABLE IF NOT EXISTS price_alerts (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    symbol        VARCHAR(24) NOT NULL,
    direction     VARCHAR(5) NOT NULL CHECK (direction IN ('above', 'below')),
    target_price  NUMERIC NOT NULL CHECK (target_price > 0),
    currency      VARCHAR(3) NOT NULL,
    note          VARCHAR(200),
    active        BOOLEAN NOT NULL DEFAULT true,
    triggered_at  TIMESTAMPTZ,
    last_price    NUMERIC,
    created_at    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_price_alerts_user_id ON price_alerts (user_id);
CREATE INDEX IF NOT EXISTS idx_price_alerts_symbol ON price_alerts (symbol);
-- the quotes job reads only active alerts of the refreshed symbols
CREATE INDEX IF NOT EXISTS idx_price_alerts_active_symbol ON price_alerts (symbol) WHERE active;
ALTER TABLE public.price_alerts ENABLE ROW LEVEL SECURITY;


-- ---------------------------------------------------------------- access features
INSERT INTO access_features (key, min_level, description) VALUES
  ('system.unlimited_slots', 'premium', 'No limit on followed stocks')
ON CONFLICT (key) DO UPDATE
  SET min_level = EXCLUDED.min_level, description = EXCLUDED.description, updated_at = now();

INSERT INTO access_features (key, min_level, description) VALUES
  ('action.alerts.edit', 'free', 'Create, edit and delete price alerts'),
  ('feature.unlimited_alerts', 'premium', 'No limit on active price alerts (free: 3)')
ON CONFLICT (key) DO NOTHING;

COMMENT ON COLUMN users.slot_bonus IS
    'Invite reward slots. Kept, but since 015 it does not raise the free limit (free = 10 flat, premium/owner unlimited).';
