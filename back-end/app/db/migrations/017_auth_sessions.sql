-- ============================================================
-- 017_auth_sessions.sql — signed-in devices and rotating refresh tokens
-- ============================================================
--
-- WHY
--   The iOS app must stay signed in for months without a long-lived token
--   that is easy to steal. Every sign-in now creates a SESSION (one per
--   device). Access tokens (JWT) carry the session id (`sid`) and stop
--   working within a minute of the session being revoked. iOS also gets an
--   opaque REFRESH TOKEN that is rotated on every use; presenting an old
--   (already used) one means it was copied, and the whole session is
--   revoked (reuse detection).
--
-- WHAT
--   auth_sessions          one row per signed-in device
--       client             'web' | 'ios'
--       device_name        "iPhone 16", "Chrome on macOS" (shown in Profile)
--       expires_at         sliding: pushed forward on each refresh
--       absolute_expires_at never moves (hard cap since sign-in)
--       revoked_at / revoked_reason  'logout' | 'user' | 'others' |
--                          'reuse_detected' | 'password_changed' | 'admin'
--   auth_refresh_tokens    every refresh token ever issued, stored ONLY as a
--                          SHA-256 hash. used_at is set when it is rotated;
--                          a used hash presented again = reuse.
--
-- HOW TO APPLY (after 016)
--   Supabase dashboard → SQL Editor → paste this file → Run.
--   (or: psql "$DATABASE_URL" -f back-end/app/db/migrations/017_auth_sessions.sql)
--   Idempotent: safe to run more than once.
--
-- BEFORE IT IS APPLIED
--   Sign-in keeps working exactly as before (no session, no refresh token,
--   no `sid` claim). /auth/token/refresh and /auth/sessions answer 503
--   {"code": "migration_required", "migration": "017_auth_sessions.sql"}.
--
-- RLS
--   Enabled with no policies, like 007/013/014/015 (backend uses service_role).
-- ============================================================

CREATE TABLE IF NOT EXISTS auth_sessions (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    client               VARCHAR(8) NOT NULL CHECK (client IN ('web', 'ios')),
    device_name          VARCHAR(80),
    ip_address           VARCHAR(64),
    user_agent           VARCHAR(300),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at           TIMESTAMPTZ NOT NULL,
    absolute_expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at           TIMESTAMPTZ,
    revoked_reason       VARCHAR(24)
);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions (user_id, revoked_at);

CREATE TABLE IF NOT EXISTS auth_refresh_tokens (
    token_hash   CHAR(64) PRIMARY KEY,             -- sha256 hex of the refresh token
    session_id   UUID NOT NULL REFERENCES auth_sessions(id) ON DELETE CASCADE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    used_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_auth_refresh_tokens_session ON auth_refresh_tokens (session_id);

ALTER TABLE auth_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_refresh_tokens ENABLE ROW LEVEL SECURITY;
