-- ============================================================
-- Signa Database Schema — Full (idempotent, safe to re-run)
-- Run this in the Supabase SQL Editor to create all tables.
-- ============================================================

-- ============================================================
-- USERS
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username          VARCHAR UNIQUE NOT NULL,
    password_hash     VARCHAR NOT NULL,
    telegram_chat_id  VARCHAR NOT NULL,
    is_active         BOOLEAN DEFAULT TRUE,
    created_at        TIMESTAMPTZ DEFAULT now(),
    last_login        TIMESTAMPTZ
);

-- ============================================================
-- OTP CODES
-- ============================================================
CREATE TABLE IF NOT EXISTS otp_codes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    session_token   VARCHAR NOT NULL,
    code_hash       VARCHAR NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    used_at         TIMESTAMPTZ,
    attempts        INT DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_otp_session ON otp_codes (session_token);
CREATE INDEX IF NOT EXISTS idx_otp_user ON otp_codes (user_id);

-- ============================================================
-- TOKEN BLACKLIST
-- ============================================================
CREATE TABLE IF NOT EXISTS token_blacklist (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token_jti   VARCHAR UNIQUE NOT NULL,
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
    revoked_at  TIMESTAMPTZ DEFAULT now(),
    expires_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_blacklist_jti ON token_blacklist (token_jti);

-- ============================================================
-- AUDIT LOGS
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_logs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type  VARCHAR NOT NULL,
    user_id     UUID,
    ip_address  VARCHAR,
    user_agent  TEXT,
    metadata    JSONB DEFAULT '{}'::jsonb,
    success     BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_logs (event_type);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs (user_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_ip ON audit_logs (ip_address);

-- ============================================================
-- TICKERS
-- ============================================================
CREATE TABLE IF NOT EXISTS tickers (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol      VARCHAR UNIQUE NOT NULL,
    name        VARCHAR,
    exchange    VARCHAR,           -- TSX, NYSE, NASDAQ
    bucket      VARCHAR,           -- SAFE_INCOME, HIGH_RISK
    is_active   BOOLEAN DEFAULT TRUE,
    added_at    TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tickers_active ON tickers (is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_tickers_exchange ON tickers (exchange);
CREATE INDEX IF NOT EXISTS idx_tickers_symbol ON tickers (symbol);

-- ============================================================
-- SCANS
-- ============================================================
CREATE TABLE IF NOT EXISTS scans (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scan_type         VARCHAR NOT NULL,    -- PRE_MARKET, MORNING, PRE_CLOSE, AFTER_CLOSE
    started_at        TIMESTAMPTZ,
    completed_at      TIMESTAMPTZ,
    tickers_scanned   INT DEFAULT 0,
    signals_found     INT DEFAULT 0,
    gems_found        INT DEFAULT 0,
    status            VARCHAR DEFAULT 'RUNNING',  -- RUNNING, COMPLETE, FAILED
    error_message     TEXT,
    created_at        TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_scans_status ON scans (status);
CREATE INDEX IF NOT EXISTS idx_scans_started ON scans (started_at DESC);

-- ============================================================
-- SIGNALS
-- ============================================================
CREATE TABLE IF NOT EXISTS signals (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker_id         UUID REFERENCES tickers(id) ON DELETE SET NULL,
    symbol            VARCHAR NOT NULL,
    action            VARCHAR NOT NULL,    -- BUY, HOLD, SELL, AVOID
    status            VARCHAR DEFAULT 'CONFIRMED',  -- CONFIRMED, WEAKENING, CANCELLED, UPGRADED
    score             INT DEFAULT 0 CHECK (score >= 0 AND score <= 100),
    confidence        INT DEFAULT 0 CHECK (confidence >= 0 AND confidence <= 100),
    is_gem            BOOLEAN DEFAULT FALSE,
    bucket            VARCHAR,             -- SAFE_INCOME, HIGH_RISK
    price_at_signal   DECIMAL,
    target_price      DECIMAL,
    stop_loss         DECIMAL,
    risk_reward       DECIMAL,
    catalyst          TEXT,
    sentiment_score   INT,
    reasoning         TEXT,
    technical_data    JSONB DEFAULT '{}'::jsonb,
    fundamental_data  JSONB DEFAULT '{}'::jsonb,
    macro_data        JSONB DEFAULT '{}'::jsonb,
    grok_data         JSONB DEFAULT '{}'::jsonb,
    scan_id           UUID REFERENCES scans(id) ON DELETE SET NULL,
    created_at        TIMESTAMPTZ DEFAULT now(),
    updated_at        TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_signals_symbol_date ON signals (symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_scan ON signals (scan_id);
CREATE INDEX IF NOT EXISTS idx_signals_gem ON signals (is_gem, created_at DESC) WHERE is_gem = TRUE;
CREATE INDEX IF NOT EXISTS idx_signals_score ON signals (score DESC);
CREATE INDEX IF NOT EXISTS idx_signals_bucket ON signals (bucket);
CREATE INDEX IF NOT EXISTS idx_signals_action ON signals (action);

-- ============================================================
-- PORTFOLIO
-- ============================================================
CREATE TABLE IF NOT EXISTS portfolio (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol          VARCHAR NOT NULL,
    bucket          VARCHAR,               -- SAFE_INCOME, HIGH_RISK
    account_type    VARCHAR,               -- TFSA, RRSP, TAXABLE
    shares          DECIMAL,
    avg_cost        DECIMAL,
    currency        VARCHAR DEFAULT 'CAD', -- CAD, USD
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_portfolio_symbol ON portfolio (symbol);

-- ============================================================
-- WATCHLIST
-- ============================================================
CREATE TABLE IF NOT EXISTS watchlist (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol      VARCHAR UNIQUE NOT NULL,
    added_at    TIMESTAMPTZ DEFAULT now(),
    notes       TEXT
);

CREATE INDEX IF NOT EXISTS idx_watchlist_symbol ON watchlist (symbol);

-- ============================================================
-- ALERTS
-- ============================================================
CREATE TABLE IF NOT EXISTS alerts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_id   UUID REFERENCES signals(id) ON DELETE SET NULL,
    alert_type  VARCHAR NOT NULL,          -- GEM, MORNING_DIGEST, ENTRY_WINDOW, PRE_CLOSE, EOD
    message     TEXT NOT NULL,
    sent_at     TIMESTAMPTZ,
    status      VARCHAR DEFAULT 'PENDING', -- PENDING, SENT, FAILED
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts (status);
CREATE INDEX IF NOT EXISTS idx_alerts_type ON alerts (alert_type);

-- ============================================================
-- Enable Realtime for key tables
-- ============================================================
DO $$
BEGIN
    ALTER PUBLICATION supabase_realtime ADD TABLE signals;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    ALTER PUBLICATION supabase_realtime ADD TABLE alerts;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================
-- Auto-update updated_at triggers
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS signals_updated_at ON signals;
CREATE TRIGGER signals_updated_at
    BEFORE UPDATE ON signals
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

DROP TRIGGER IF EXISTS portfolio_updated_at ON portfolio;
CREATE TRIGGER portfolio_updated_at
    BEFORE UPDATE ON portfolio
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- ============================================================
-- Atomic OTP attempt increment (prevents race conditions)
-- ============================================================
CREATE OR REPLACE FUNCTION increment_otp_attempts(otp_uuid UUID)
RETURNS VOID AS $$
BEGIN
    UPDATE otp_codes SET attempts = attempts + 1 WHERE id = otp_uuid;
END;
$$ LANGUAGE plpgsql;
