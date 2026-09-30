-- ============================================================
-- 011_access_levels.sql — access levels per user + feature catalog
-- ============================================================
--
-- WHY
--   Signa becomes multi-user: a free tier (tracker), a later premium tier,
--   and the owner (everything, including the brain). Each user gets an
--   access_level; each area (page) and action (button / API operation) has
--   a minimum level in access_features. The API enforces it (403
--   {"code": "upgrade_required"}); web and iOS clients read the allowed
--   keys from GET /api/v1/auth/me.
--
-- WHAT
--   users.access_level   free | premium | owner   (default free)
--   users.slot_bonus     extra followed-stock slots (invites, later)
--   users.telegram_chat_id  now optional (free users have no Telegram)
--   access_features      key -> min_level. Rows override the defaults in
--                        app/core/access.py; a key with no row uses the
--                        code default. Unknown keys require owner.
--
-- EXISTING USERS
--   Signa had one user (the owner) before this migration, so every existing
--   user is set to owner. New users default to free.
--
-- CHANGE A LEVEL LATER
--   UPDATE users SET access_level = 'premium' WHERE username = 'someone';
--   UPDATE access_features SET min_level = 'premium' WHERE key = 'area.check';
--   (the API picks changes up within 60 seconds)
--
-- HOW TO APPLY (after 010)
--   Supabase dashboard → SQL Editor → paste this file → Run.
--   Idempotent: safe to run more than once. Before it is applied, every
--   user is treated as owner (single-user behaviour).
--
-- RLS
--   Enabled with no policies, like 007: the backend uses the service_role
--   key; the public anon key gets no access.
-- ============================================================

ALTER TABLE users ADD COLUMN IF NOT EXISTS access_level VARCHAR(16);
ALTER TABLE users ADD COLUMN IF NOT EXISTS slot_bonus INT NOT NULL DEFAULT 0;

-- Existing accounts predate multi-user: they are the owner.
UPDATE users SET access_level = 'owner' WHERE access_level IS NULL;

ALTER TABLE users ALTER COLUMN access_level SET DEFAULT 'free';
ALTER TABLE users ALTER COLUMN access_level SET NOT NULL;
DO $$ BEGIN
  ALTER TABLE users ADD CONSTRAINT users_access_level_check
    CHECK (access_level IN ('free', 'premium', 'owner'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

ALTER TABLE users ALTER COLUMN telegram_chat_id DROP NOT NULL;

CREATE TABLE IF NOT EXISTS access_features (
    key          VARCHAR(64) PRIMARY KEY,
    min_level    VARCHAR(16) NOT NULL CHECK (min_level IN ('free', 'premium', 'owner')),
    description  TEXT,
    updated_at   TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE access_features ENABLE ROW LEVEL SECURITY;

-- Seed the catalog. ON CONFLICT DO NOTHING keeps levels already changed.
INSERT INTO access_features (key, min_level, description) VALUES
  ('area.today', 'owner', 'Today: brain dashboard'),
  ('area.signals', 'owner', 'Signals from the brain''s scans'),
  ('area.check', 'owner', 'Check a stock (AI)'),
  ('area.positions', 'owner', 'Paper-trading positions and wallet'),
  ('area.performance', 'owner', 'Is it working? (brain track record)'),
  ('area.brain', 'owner', 'Brain rules, knowledge and learning'),
  ('area.holdings', 'free', 'My holdings'),
  ('area.watchlist', 'free', 'Watchlist'),
  ('area.how_it_works', 'free', 'How it works'),
  ('area.settings', 'free', 'Settings'),
  ('area.integrations', 'owner', 'Integrations, AI config and budgets'),
  ('area.logs', 'owner', 'Live logs'),
  ('action.scan.trigger', 'owner', 'Start a scan'),
  ('action.check.run', 'owner', 'Run an AI stock check'),
  ('action.check.compare', 'owner', 'Compare 2-3 stocks with AI'),
  ('action.holdings.edit', 'free', 'Add, edit and remove holdings'),
  ('action.holdings.refresh', 'owner', 'Refresh holdings monitor (may use Grok)'),
  ('action.holdings.review', 'owner', 'AI review of holdings'),
  ('action.holdings.allocate', 'owner', 'Where could new cash go? (AI)'),
  ('action.watchlist.edit', 'free', 'Add and remove watchlist stocks'),
  ('action.positions.manage', 'owner', 'Open, edit and close positions'),
  ('action.wallet.manage', 'owner', 'Deposit to / withdraw from the paper wallet'),
  ('action.brain.edit', 'owner', 'Edit brain rules and knowledge'),
  ('action.learning.manage', 'owner', 'Approve / apply learning suggestions'),
  ('action.settings.ai', 'owner', 'Change AI config and budgets'),
  ('system.ai', 'owner', 'Trigger AI calls (Grok, Claude, Codex)'),
  ('system.unlimited_slots', 'owner', 'No limit on followed stocks')
ON CONFLICT (key) DO NOTHING;
