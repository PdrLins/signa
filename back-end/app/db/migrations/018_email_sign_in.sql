-- ============================================================
-- 018_email_sign_in.sql — email accounts, email codes, password reset
-- ============================================================
--
-- WHY
--   Free users around the world don't have Telegram linked to Signa. They
--   sign in with email + password and confirm with a 6-digit code sent by
--   email. The owner keeps the Telegram code. Users can reset a forgotten
--   password and delete their account (App Store requirement).
--
-- WHAT
--   users.email               lower-case, unique (case-insensitive index)
--   users.email_verified_at   set when the user confirmed a code sent to it;
--                             an unverified email never receives sign-in codes
--   users.password_changed_at set on reset / change (all sessions end)
--   otp_codes.purpose         'login' (default; also signup) | 'reset' |
--                             'email' (confirm a new address). A code only
--                             works for its own purpose.
--   otp_codes.email           the address a 'email' / signup code was sent to
--
-- HOW TO APPLY (after 017)
--   Supabase dashboard → SQL Editor → paste this file → Run.
--   (or: psql "$DATABASE_URL" -f back-end/app/db/migrations/018_email_sign_in.sql)
--   Idempotent: safe to run more than once.
--
-- BEFORE IT IS APPLIED
--   Sign-in works as before (Telegram code, or password only for accounts
--   without Telegram). /auth/signup, /auth/password/*, /auth/email/* and
--   DELETE /account answer 503 {"code": "migration_required",
--   "migration": "018_email_sign_in.sql"}.
--
-- RLS
--   Unchanged (backend uses service_role).
-- ============================================================

ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(254);
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_lower ON users (lower(email)) WHERE email IS NOT NULL;

ALTER TABLE otp_codes ADD COLUMN IF NOT EXISTS purpose VARCHAR(16) NOT NULL DEFAULT 'login';
ALTER TABLE otp_codes ADD COLUMN IF NOT EXISTS email VARCHAR(254);

DO $$ BEGIN
  ALTER TABLE otp_codes ADD CONSTRAINT otp_codes_purpose_check CHECK (purpose IN ('login', 'reset', 'email'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
