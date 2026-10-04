-- ============================================================================
-- 030_account_lifecycle.sql — account deletion, job health
-- ============================================================================
-- Account deletion (App Store 5.1.1(v), LGPD art. 18, PIPEDA):
--   users.deletion_requested_at / deletion_scheduled_at   a requested deletion
--     waits 30 days (sign in to restore); a nightly job then deletes the user
--     (every table cascades) and anonymizes what must stay (security log,
--     problem reports). "Delete now" skips the wait.
--   reserved_usernames   a deleted username stays taken for 90 days (no
--     impersonation of a recently deleted account).
--   referrals.referred_id ON DELETE SET NULL   the friend who invited a
--     deleted user keeps their reward.
-- Job health:
--   job_runs   last start / success / error per scheduled job: owner report,
--     alerts after repeated failures, and catching up runs missed while the
--     server was down or asleep.
-- Idempotent.
-- ============================================================================

ALTER TABLE users ADD COLUMN IF NOT EXISTS deletion_requested_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS deletion_scheduled_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_users_deletion_scheduled ON users (deletion_scheduled_at)
    WHERE deletion_scheduled_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS reserved_usernames (
    username  VARCHAR PRIMARY KEY,
    until     TIMESTAMPTZ NOT NULL
);
ALTER TABLE public.reserved_usernames ENABLE ROW LEVEL SECURITY;

ALTER TABLE referrals ALTER COLUMN referred_id DROP NOT NULL;
ALTER TABLE referrals DROP CONSTRAINT IF EXISTS referrals_referred_id_fkey;
ALTER TABLE referrals ADD CONSTRAINT referrals_referred_id_fkey
    FOREIGN KEY (referred_id) REFERENCES users(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS job_runs (
    job_id           VARCHAR(64) PRIMARY KEY,
    last_started_at  TIMESTAMPTZ,
    last_success_at  TIMESTAMPTZ,
    last_error       TEXT,
    last_error_at    TIMESTAMPTZ,
    failures         INTEGER NOT NULL DEFAULT 0   -- consecutive
);
ALTER TABLE public.job_runs ENABLE ROW LEVEL SECURITY;
