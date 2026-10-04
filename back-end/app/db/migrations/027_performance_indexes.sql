-- ============================================================================
-- 027_performance_indexes.sql — indexes for hot lookups and nightly cleanup
-- ============================================================================
-- No table or column changes: the app works without these, only slower.
--   * holdings by symbol: who holds a stock that moved (live alerts), one
--     status write per symbol (holding status job)
--   * price alerts by trigger time (live alerts, Coming up)
--   * users by email (email sign-in / reset filter on the stored lower-case
--     email; the lower(email) unique index can't serve that filter)
--   * the nightly cleanup's deletes (expired tokens, codes, sessions)
--   * users.referred_by (account deletes set it to NULL)
-- Idempotent.
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_holdings_symbol ON holdings (symbol);
CREATE INDEX IF NOT EXISTS idx_price_alerts_triggered ON price_alerts (triggered_at)
    WHERE triggered_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_price_alerts_user_triggered ON price_alerts (user_id, triggered_at DESC)
    WHERE triggered_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_users_email ON users (email) WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_users_referred_by ON users (referred_by) WHERE referred_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_token_blacklist_expires ON token_blacklist (expires_at);
CREATE INDEX IF NOT EXISTS idx_otp_expires ON otp_codes (expires_at);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_abs_expires ON auth_sessions (absolute_expires_at);
CREATE INDEX IF NOT EXISTS idx_auth_refresh_tokens_used ON auth_refresh_tokens (used_at)
    WHERE used_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_telegram_link_codes_expires ON telegram_link_codes (expires_at);
CREATE INDEX IF NOT EXISTS idx_push_devices_disabled ON push_devices (disabled_at)
    WHERE disabled_at IS NOT NULL;
