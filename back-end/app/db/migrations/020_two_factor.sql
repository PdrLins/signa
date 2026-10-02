-- ============================================================
-- 020_two_factor.sql — two-step sign-in (Telegram now, SMS later)
-- ============================================================
--
-- WHY
--   Any user can turn on two-step sign-in: after the password, Signa sends
--   a 6-digit code to their Telegram and they type it in. Setting it up
--   proves the chat is theirs: they open the Signa bot from the app (a
--   one-time start link), the bot sends a code, and the app turns two-step
--   on only after that code is entered. SMS is listed but not available yet
--   (no provider).
--
-- WHAT
--   users.two_factor_method      'telegram' | 'sms' | NULL (off)
--   users.two_factor_enabled_at  when it was turned on
--   Backfill: accounts that already sign in with a Telegram code (the owner:
--   users.telegram_chat_id set) are marked 'telegram', so nothing changes
--   for them.
--   two_factor_setup             one in-progress setup per user:
--       code_hash   SHA-256 of the one-time start code in
--                   t.me/<bot>?start=2fa_<code> (10 minutes)
--       chat_id     the chat that pressed Start (or the user's notification
--                   chat when they chose "use my connected Telegram")
--       otp_hash    the 6-digit code sent to that chat (HMAC, never plain)
--       otp_attempts / expires_at
--   users.telegram_chat_id stays THE sign-in chat (it was already used for
--   the owner's login codes and brain codes). The notification chat of
--   migration 016 (telegram_links) is separate.
--
-- HOW TO APPLY (after 019)
--   Supabase dashboard → SQL Editor → paste this file → Run.
--   (or: psql "$DATABASE_URL" -f back-end/app/db/migrations/020_two_factor.sql)
--   Idempotent: safe to run more than once.
--
-- BEFORE IT IS APPLIED
--   Sign-in works as before (a Telegram code when telegram_chat_id is set).
--   /auth/2fa* answer 503 {"code": "migration_required",
--   "migration": "020_two_factor.sql"}.
--
-- RLS
--   Enabled with no policies, like 007/013-019 (backend uses service_role).
-- ============================================================

ALTER TABLE users ADD COLUMN IF NOT EXISTS two_factor_method VARCHAR(16);
ALTER TABLE users ADD COLUMN IF NOT EXISTS two_factor_enabled_at TIMESTAMPTZ;

DO $$ BEGIN
  ALTER TABLE users ADD CONSTRAINT users_two_factor_method_check
    CHECK (two_factor_method IS NULL OR two_factor_method IN ('telegram', 'sms'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

UPDATE users
   SET two_factor_method = 'telegram', two_factor_enabled_at = COALESCE(two_factor_enabled_at, now())
 WHERE telegram_chat_id IS NOT NULL AND two_factor_method IS NULL;

CREATE TABLE IF NOT EXISTS two_factor_setup (
    user_id       UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    method        VARCHAR(16) NOT NULL DEFAULT 'telegram',
    code_hash     CHAR(64) UNIQUE,
    chat_id       VARCHAR(32),
    chat_label    VARCHAR(80),
    otp_hash      CHAR(64),
    otp_attempts  INT NOT NULL DEFAULT 0,
    expires_at    TIMESTAMPTZ NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE two_factor_setup ENABLE ROW LEVEL SECURITY;
