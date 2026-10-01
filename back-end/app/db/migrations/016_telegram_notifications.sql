-- ============================================================
-- 016_telegram_notifications.sql — per-user Telegram notifications (Premium)
-- ============================================================
--
-- WHY
--   Premium (and owner) users can connect their own Telegram chat and get
--   the notifications they switched on in Profile -> Notifications
--   (notification_prefs, migration 013): ex-dividend reminders, dividends
--   paid, dividend raises/cuts, Signa check changes, earnings, big moves,
--   analyst ratings, economy events — plus their price alerts that fired.
--
-- WHAT
--   telegram_links           one notification chat per user (separate from
--                            users.telegram_chat_id, which stays the login /
--                            OTP chat — connecting does NOT change login):
--       chat_id   UNIQUE: a chat belongs to one user; linking it from a
--                 second account moves it.
--       username  @username or first name shown in the app.
--   telegram_link_codes      one-time codes behind t.me/<bot>?start=<code>
--                            (10 minutes, single use). Only the SHA-256 of the
--                            code is stored; a new code deletes the user's
--                            older unused ones.
--   notification_deliveries  what was already sent (UNIQUE user_id +
--                            dedupe_key, e.g. "exdiv:ENB.TO:2026-10-14"), so
--                            nothing is sent twice.
--   access_features
--       feature.telegram_alerts  premium (connect + receive)
--       area.how_it_works        free -> owner (the page explains the brain;
--                                DO UPDATE)
--
-- HOW TO APPLY (after 015)
--   Supabase dashboard → SQL Editor → paste this file → Run.
--   (or: psql "$DATABASE_URL" -f back-end/app/db/migrations/016_telegram_notifications.sql)
--   Idempotent: safe to run more than once.
--
-- BEFORE IT IS APPLIED
--   /api/v1/notifications/telegram* answer 503 {"code": "migration_required",
--   "migration": "016_telegram_notifications.sql"}; the delivery jobs skip
--   (logged at debug); /start <code> in the bot replies "link expired".
--
-- RLS
--   Enabled with no policies, like 007/013-015 (backend uses service_role).
-- ============================================================


-- ---------------------------------------------------------------- linked chats
CREATE TABLE IF NOT EXISTS telegram_links (
    user_id    UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    chat_id    VARCHAR(32) NOT NULL UNIQUE,
    username   VARCHAR(80),
    linked_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE public.telegram_links ENABLE ROW LEVEL SECURITY;


-- ---------------------------------------------------------------- one-time link codes
CREATE TABLE IF NOT EXISTS telegram_link_codes (
    code_hash   VARCHAR(64) PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_telegram_link_codes_user_id ON telegram_link_codes (user_id);
ALTER TABLE public.telegram_link_codes ENABLE ROW LEVEL SECURITY;


-- ---------------------------------------------------------------- sent notifications (dedupe)
CREATE TABLE IF NOT EXISTS notification_deliveries (
    id          BIGSERIAL PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind        VARCHAR(32) NOT NULL,
    dedupe_key  VARCHAR(200) NOT NULL,
    sent_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, dedupe_key)
);
CREATE INDEX IF NOT EXISTS idx_notification_deliveries_sent_at ON notification_deliveries (sent_at);
ALTER TABLE public.notification_deliveries ENABLE ROW LEVEL SECURITY;


-- ---------------------------------------------------------------- access features
INSERT INTO access_features (key, min_level, description) VALUES
  ('feature.telegram_alerts', 'premium', 'Notifications on Telegram (connect a chat, receive alerts)')
ON CONFLICT (key) DO NOTHING;

INSERT INTO access_features (key, min_level, description) VALUES
  ('area.how_it_works', 'owner', 'How it works (explains the brain)')
ON CONFLICT (key) DO UPDATE
  SET min_level = EXCLUDED.min_level, description = EXCLUDED.description, updated_at = now();
