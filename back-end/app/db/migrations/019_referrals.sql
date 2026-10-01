-- ============================================================
-- 019_referrals.sql — account IDs, invite-only sign-up, referrals
-- ============================================================
--
-- WHY
--   Signa grows by invitation. Every user gets a short visible ACCOUNT ID
--   (8 characters, e.g. "K7M2QX9A") that is also their INVITE CODE. A new
--   account can only be created with a valid code (POST /auth/register).
--   When the invited friend starts using Signa (saves their first holding or
--   adds their first watchlist symbol) the referral is "rewarded" and the
--   referrer, if free, follows 5 more stocks (at most +25: free limit is
--   10 + min(5 x rewarded, 25)). Premium / owner stay unlimited.
--
-- WHAT
--   users.account_id   VARCHAR(8) UNIQUE NOT NULL, alphabet
--                      ABCDEFGHJKMNPQRSTUVWXYZ23456789 (no 0/O/1/I/L).
--                      Existing users are backfilled here (collision-safe
--                      loop); the app generates it for new users.
--   users.referred_by  who invited this user (NULL for older accounts)
--   referrals          one row per invited user (referred_id UNIQUE):
--       status         'pending' (signed up) | 'rewarded' (first follow)
--       rewarded_at    when it became rewarded (set once, conditional update)
--   users.slot_bonus   is NOT used: the bonus is counted from referrals rows.
--
-- HOW TO APPLY (after 016, 017 and 018_email_sign_in.sql)
--   Supabase dashboard → SQL Editor → paste this file → Run.
--   (or: psql "$DATABASE_URL" -f back-end/app/db/migrations/019_referrals.sql)
--   Idempotent: safe to run more than once.
--
-- BEFORE IT IS APPLIED
--   POST /auth/register, GET /auth/referral/{code} and GET /referrals answer
--   503 {"detail": {"code": "migration_required",
--   "migration": "019_referrals.sql"}}. Everything else works as before:
--   "account_id" is null in /auth/me and /profile, the free slot limit is 10.
--
-- RLS
--   Enabled with no policies, like 007/013-017 (backend uses service_role).
-- ============================================================

ALTER TABLE users ADD COLUMN IF NOT EXISTS account_id VARCHAR(8);
ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by UUID REFERENCES users(id) ON DELETE SET NULL;

-- Random account ID from the unambiguous alphabet.
CREATE OR REPLACE FUNCTION signa_new_account_id() RETURNS VARCHAR(8) AS $$
DECLARE
  alphabet CONSTANT TEXT := 'ABCDEFGHJKMNPQRSTUVWXYZ23456789';
  result TEXT := '';
BEGIN
  FOR i IN 1..8 LOOP
    result := result || substr(alphabet, 1 + floor(random() * length(alphabet))::INT, 1);
  END LOOP;
  RETURN result;
END;
$$ LANGUAGE plpgsql VOLATILE;

-- Backfill: one user at a time, retrying on the (very unlikely) collision.
DO $$
DECLARE
  u RECORD;
  candidate VARCHAR(8);
BEGIN
  FOR u IN SELECT id FROM users WHERE account_id IS NULL LOOP
    LOOP
      candidate := signa_new_account_id();
      EXIT WHEN NOT EXISTS (SELECT 1 FROM users WHERE account_id = candidate);
    END LOOP;
    UPDATE users SET account_id = candidate WHERE id = u.id;
  END LOOP;
END $$;

ALTER TABLE users ALTER COLUMN account_id SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_account_id ON users (account_id);

DO $$ BEGIN
  ALTER TABLE users ADD CONSTRAINT users_account_id_format
    CHECK (account_id ~ '^[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{8}$');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS referrals (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    referrer_id  UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    referred_id  UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    status       VARCHAR(10) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'rewarded')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    rewarded_at  TIMESTAMPTZ,
    CHECK (referrer_id <> referred_id)
);

CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals (referrer_id, status);

ALTER TABLE referrals ENABLE ROW LEVEL SECURITY;

COMMENT ON COLUMN users.account_id IS
  'Visible account ID and invite code (8 chars, ABCDEFGHJKMNPQRSTUVWXYZ23456789). Migration 019.';
COMMENT ON COLUMN users.slot_bonus IS
  'Unused since 015/019: the free slot bonus is computed from rewarded referrals (10 + min(5 x n, 25)).';
