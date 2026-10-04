-- ============================================================================
-- 029_growth.sql — where users come from and whether they stay
-- ============================================================================
-- signup_sources      one row per user: platform, country, campaign tags
--                     (utm_*), the "How did you hear about Signa?" answer,
--                     the invite code kind, and Apple Search Ads attribution
--                     (token sent by the app, resolved with Apple by a job).
-- user_activity_days  one row per user per day they used the app (US/Eastern
--                     date), for week-2 retention. Written at most once a day.
-- Read by app/services/growth.py (GET /api/v1/admin/growth). Idempotent.
-- ============================================================================

CREATE TABLE IF NOT EXISTS signup_sources (
    user_id          UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    platform         VARCHAR(8),                 -- ios | web
    country          VARCHAR(8),
    heard_from       VARCHAR(24),                -- self-reported (growth.HEARD_FROM)
    utm_source       VARCHAR(64),
    utm_medium       VARCHAR(64),
    utm_campaign     VARCHAR(100),
    utm_content      VARCHAR(100),
    utm_term         VARCHAR(100),
    invite           VARCHAR(12),                -- friend | none
    asa_token        TEXT,                       -- Apple Search Ads token until resolved
    asa_status       VARCHAR(12),                -- pending | attributed | organic | failed
    asa_campaign_id  BIGINT,
    asa_ad_group_id  BIGINT,
    asa_keyword_id   BIGINT,
    asa_country      VARCHAR(4),
    asa_click_date   TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_signup_sources_created ON signup_sources (created_at);
CREATE INDEX IF NOT EXISTS idx_signup_sources_asa_pending ON signup_sources (created_at)
    WHERE asa_status = 'pending';
ALTER TABLE public.signup_sources ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS user_activity_days (
    user_id  UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day      DATE NOT NULL,
    PRIMARY KEY (user_id, day)
);
CREATE INDEX IF NOT EXISTS idx_user_activity_days_day ON user_activity_days (day);
ALTER TABLE public.user_activity_days ENABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS idx_users_created_at ON users (created_at);
CREATE INDEX IF NOT EXISTS idx_holdings_user_created ON holdings (user_id, created_at);
