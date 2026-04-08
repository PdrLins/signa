-- ============================================================
-- Signa Database Schema — Complete (19 tables)
-- Idempotent — safe to re-run at any time.
-- Run in Supabase SQL Editor.
-- Last updated: 2026-04-06
-- ============================================================


-- 1. USERS
CREATE TABLE IF NOT EXISTS users (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username          VARCHAR UNIQUE NOT NULL,
    password_hash     VARCHAR NOT NULL,
    telegram_chat_id  VARCHAR UNIQUE NOT NULL,
    is_active         BOOLEAN DEFAULT TRUE,
    login_attempts    INT DEFAULT 0,
    locked_until      TIMESTAMPTZ,
    created_at        TIMESTAMPTZ DEFAULT now(),
    last_login        TIMESTAMPTZ
);

-- 2. OTP CODES
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
CREATE INDEX IF NOT EXISTS idx_otp_session ON otp_codes(session_token);
CREATE INDEX IF NOT EXISTS idx_otp_user ON otp_codes(user_id);

-- 3. TOKEN BLACKLIST
CREATE TABLE IF NOT EXISTS token_blacklist (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token_jti   VARCHAR UNIQUE NOT NULL,
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
    revoked_at  TIMESTAMPTZ DEFAULT now(),
    expires_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_blacklist_jti ON token_blacklist(token_jti);

-- 4. AUDIT LOGS
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
CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_logs(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC);

-- 5. TICKERS
CREATE TABLE IF NOT EXISTS tickers (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol      VARCHAR UNIQUE NOT NULL,
    name        VARCHAR,
    exchange    VARCHAR,
    bucket      VARCHAR,
    is_active   BOOLEAN DEFAULT TRUE,
    added_at    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tickers_active ON tickers(is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_tickers_symbol ON tickers(symbol);

-- 6. SCANS
CREATE TABLE IF NOT EXISTS scans (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scan_type         VARCHAR NOT NULL,
    started_at        TIMESTAMPTZ,
    completed_at      TIMESTAMPTZ,
    tickers_scanned   INT DEFAULT 0,
    candidates        INT DEFAULT 0,
    signals_found     INT DEFAULT 0,
    gems_found        INT DEFAULT 0,
    status            VARCHAR DEFAULT 'RUNNING',
    error_message     TEXT,
    progress_pct      INT DEFAULT 0,
    phase             VARCHAR DEFAULT 'starting',
    current_ticker    VARCHAR,
    market_regime     VARCHAR,
    triggered_by      VARCHAR DEFAULT 'scheduler',  -- 'scheduler' or 'manual'
    created_at        TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_scans_status ON scans(status);
CREATE INDEX IF NOT EXISTS idx_scans_started ON scans(started_at DESC);

-- 7. SIGNALS
CREATE TABLE IF NOT EXISTS signals (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker_id         UUID REFERENCES tickers(id) ON DELETE SET NULL,
    symbol            VARCHAR NOT NULL,
    action            VARCHAR NOT NULL,
    status            VARCHAR DEFAULT 'CONFIRMED',
    score             INT DEFAULT 0 CHECK (score >= 0 AND score <= 100),
    confidence        INT DEFAULT 0 CHECK (confidence >= 0 AND confidence <= 100),
    -- AI synthesis status: validated/low_confidence/failed/skipped
    -- More honest than inferring from confidence==0 (which conflated failure
    -- with intentional skipping). Used by the brain auto-buy guard.
    ai_status         VARCHAR DEFAULT 'skipped',
    is_gem            BOOLEAN DEFAULT FALSE,
    is_discovered     BOOLEAN DEFAULT FALSE,
    bucket            VARCHAR,
    asset_type        VARCHAR,
    exchange          VARCHAR,
    price_at_signal   DECIMAL,
    target_price      DECIMAL,
    stop_loss         DECIMAL,
    risk_reward       DECIMAL,
    catalyst          TEXT,
    sentiment_score   INT,
    reasoning         TEXT,
    gem_reason        VARCHAR,
    entry_window      VARCHAR,
    market_regime     VARCHAR,
    catalyst_type     VARCHAR,
    account_recommendation VARCHAR,
    technical_data    JSONB DEFAULT '{}'::jsonb,
    fundamental_data  JSONB DEFAULT '{}'::jsonb,
    macro_data        JSONB DEFAULT '{}'::jsonb,
    grok_data         JSONB DEFAULT '{}'::jsonb,
    signal_style      VARCHAR,
    contrarian_score  INT,
    probability_vs_spy DOUBLE PRECISION,
    factor_labels     JSONB,
    kelly_recommendation JSONB DEFAULT '{}'::jsonb,
    scan_id           UUID REFERENCES scans(id) ON DELETE SET NULL,
    created_at        TIMESTAMPTZ DEFAULT now(),
    updated_at        TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_signals_symbol_date ON signals(symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_scan ON signals(scan_id);
CREATE INDEX IF NOT EXISTS idx_signals_gem ON signals(is_gem, created_at DESC) WHERE is_gem = TRUE;
CREATE INDEX IF NOT EXISTS idx_signals_score ON signals(score DESC);
CREATE INDEX IF NOT EXISTS idx_signals_created ON signals(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_action_date ON signals(action, created_at DESC);

-- Migration for existing installs (safe to re-run):
ALTER TABLE signals ADD COLUMN IF NOT EXISTS ai_status VARCHAR DEFAULT 'skipped';

-- 8. PORTFOLIO
CREATE TABLE IF NOT EXISTS portfolio (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    symbol          VARCHAR NOT NULL,
    bucket          VARCHAR,
    account_type    VARCHAR,
    shares          DECIMAL,
    avg_cost        DECIMAL,
    currency        VARCHAR DEFAULT 'CAD',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_portfolio_symbol ON portfolio(symbol);

-- 9. WATCHLIST
CREATE TABLE IF NOT EXISTS watchlist (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
    symbol      VARCHAR NOT NULL,
    added_at    TIMESTAMPTZ DEFAULT now(),
    notes       TEXT,
    UNIQUE(user_id, symbol)
);
CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id);

-- 10. ALERTS
CREATE TABLE IF NOT EXISTS alerts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
    signal_id   UUID REFERENCES signals(id) ON DELETE SET NULL,
    alert_type  VARCHAR NOT NULL,
    message     TEXT NOT NULL,
    sent_at     TIMESTAMPTZ,
    status      VARCHAR DEFAULT 'PENDING',
    created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);

-- 11. POSITIONS
CREATE TABLE IF NOT EXISTS positions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID REFERENCES users(id) ON DELETE CASCADE,
    symbol              VARCHAR NOT NULL,
    entry_price         DECIMAL NOT NULL,
    entry_date          TIMESTAMPTZ DEFAULT now(),
    shares              DECIMAL NOT NULL,
    account_type        VARCHAR,
    bucket              VARCHAR,
    currency            VARCHAR DEFAULT 'CAD',
    target_price        DECIMAL,
    stop_loss           DECIMAL,
    notes               TEXT,
    status              VARCHAR DEFAULT 'OPEN',
    exit_price          DECIMAL,
    exit_date           TIMESTAMPTZ,
    exit_reason         VARCHAR,
    pnl_amount          DECIMAL,
    pnl_percent         DECIMAL,
    last_signal_score   INT,
    last_signal_status  VARCHAR,
    last_alerted_pnl    DECIMAL,
    market_regime       VARCHAR,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status) WHERE status = 'OPEN';
CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol);

-- 12. BRAIN SESSIONS (2FA)
CREATE TABLE IF NOT EXISTS brain_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id),
    otp_hash        VARCHAR NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    used_at         TIMESTAMPTZ,
    brain_token_jti VARCHAR UNIQUE,
    ip_address      VARCHAR,
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_brain_sessions_user ON brain_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_brain_sessions_jti ON brain_sessions(brain_token_jti);

-- 13. INVESTMENT RULES (brain)
CREATE TABLE IF NOT EXISTS investment_rules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR UNIQUE NOT NULL,
    rule_type       VARCHAR NOT NULL,
    bucket          VARCHAR NOT NULL DEFAULT 'BOTH',
    description     TEXT,
    formula         TEXT,
    threshold_min   DOUBLE PRECISION,
    threshold_max   DOUBLE PRECISION,
    threshold_unit  VARCHAR DEFAULT 'absolute',
    is_blocker      BOOLEAN DEFAULT FALSE,
    weight_safe     DOUBLE PRECISION DEFAULT 0,
    weight_risk     DOUBLE PRECISION DEFAULT 0,
    is_active       BOOLEAN DEFAULT TRUE,
    source_name     VARCHAR,
    source_url      VARCHAR,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_investment_rules_type ON investment_rules(rule_type);
CREATE INDEX IF NOT EXISTS idx_investment_rules_active ON investment_rules(is_active) WHERE is_active = TRUE;

-- 14. SIGNAL KNOWLEDGE (brain)
CREATE TABLE IF NOT EXISTS signal_knowledge (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic           VARCHAR NOT NULL,
    key_concept     VARCHAR UNIQUE NOT NULL,
    explanation     TEXT NOT NULL,
    formula         TEXT,
    example         TEXT,
    is_active       BOOLEAN DEFAULT TRUE,
    source_name     VARCHAR,
    source_url      VARCHAR,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_signal_knowledge_topic ON signal_knowledge(topic);
CREATE INDEX IF NOT EXISTS idx_signal_knowledge_active ON signal_knowledge(is_active) WHERE is_active = TRUE;

-- 15. TRADE OUTCOMES (self-learning)
CREATE TABLE IF NOT EXISTS trade_outcomes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_id       UUID REFERENCES signals(id),
    symbol          VARCHAR NOT NULL,
    action          VARCHAR NOT NULL,
    score           INT,
    bucket          VARCHAR,
    signal_date     TIMESTAMPTZ NOT NULL,
    entry_price     DOUBLE PRECISION,
    exit_price      DOUBLE PRECISION,
    days_held       INT,
    pnl_pct         DOUBLE PRECISION,
    pnl_amount      DOUBLE PRECISION,
    target_price    DOUBLE PRECISION,
    stop_loss       DOUBLE PRECISION,
    hit_target      BOOLEAN DEFAULT FALSE,
    hit_stop        BOOLEAN DEFAULT FALSE,
    signal_correct  BOOLEAN,
    market_regime   VARCHAR,
    catalyst_type   VARCHAR,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_trade_outcomes_symbol ON trade_outcomes(symbol);
CREATE INDEX IF NOT EXISTS idx_trade_outcomes_date ON trade_outcomes(signal_date DESC);

-- 16. BRAIN SUGGESTIONS (self-learning)
CREATE TABLE IF NOT EXISTS brain_suggestions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_date   TIMESTAMPTZ NOT NULL,
    period_start    TIMESTAMPTZ,
    period_end      TIMESTAMPTZ,
    trades_analyzed INT DEFAULT 0,
    win_rate        DOUBLE PRECISION,
    avg_return_pct  DOUBLE PRECISION,
    rule_id         UUID,
    rule_name       VARCHAR,
    suggestion_type VARCHAR NOT NULL,
    current_value   JSONB,
    proposed_value  JSONB,
    reasoning       TEXT NOT NULL,
    confidence      INT DEFAULT 50,
    expected_impact TEXT,
    status          VARCHAR DEFAULT 'PENDING',
    reviewed_at     TIMESTAMPTZ,
    reviewed_by     UUID,
    rejection_reason TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_brain_suggestions_status ON brain_suggestions(status);
CREATE INDEX IF NOT EXISTS idx_brain_suggestions_date ON brain_suggestions(analysis_date DESC);


-- 17. USER SETTINGS (per-user preferences)
CREATE TABLE IF NOT EXISTS user_settings (
    user_id     UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    theme       VARCHAR DEFAULT 'midnight',
    language    VARCHAR DEFAULT 'en',
    updated_at  TIMESTAMPTZ DEFAULT now()
);


-- 18. VIRTUAL TRADES (brain accuracy tracking)
CREATE TABLE IF NOT EXISTS virtual_trades (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    symbol          VARCHAR NOT NULL,
    action          VARCHAR NOT NULL,
    entry_price     DOUBLE PRECISION,
    entry_date      TIMESTAMPTZ,
    entry_score     INT,
    exit_price      DOUBLE PRECISION,
    exit_date       TIMESTAMPTZ,
    exit_score      INT,
    exit_action     VARCHAR,
    pnl_pct         DOUBLE PRECISION,
    pnl_amount      DOUBLE PRECISION,
    is_win          BOOLEAN,
    status          VARCHAR DEFAULT 'OPEN',
    bucket          VARCHAR,
    signal_style    VARCHAR,
    source          VARCHAR DEFAULT 'watchlist',
    target_price    DOUBLE PRECISION,
    stop_loss       DOUBLE PRECISION,
    exit_reason     VARCHAR,            -- SIGNAL, STOP_HIT, TARGET_HIT, TIME_EXPIRED
    -- Brain tiered trust model: which tier triggered this buy and what
    -- position size multiplier was applied. NULL for non-brain (watchlist)
    -- trades. Used to analyze win rate by tier and tune the model.
    entry_tier         INT,             -- 1=validated, 2=low_confidence, 3=tech_only
    trust_multiplier   DOUBLE PRECISION, -- 1.0 (full size) or 0.5 (half size)
    -- Pre-market review flag: when an equity gets a SELL/AVOID signal outside
    -- market hours, the position is flagged here. The first scan after open
    -- re-checks the signal: if still bad → execute sell, if recovered → clear.
    pending_review_at      TIMESTAMPTZ,
    pending_review_action  VARCHAR,     -- SELL, AVOID, or FORCE_SELL (sentinel for /forcesell user override)
    pending_review_score   INT,
    pending_review_reason  TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_virtual_trades_symbol ON virtual_trades(symbol);
CREATE INDEX IF NOT EXISTS idx_virtual_trades_status ON virtual_trades(status);
CREATE INDEX IF NOT EXISTS idx_virtual_trades_source ON virtual_trades(source);
CREATE INDEX IF NOT EXISTS idx_virtual_trades_pending_review ON virtual_trades(pending_review_at) WHERE pending_review_at IS NOT NULL;

-- Migration for existing installs (safe to re-run):
ALTER TABLE virtual_trades ADD COLUMN IF NOT EXISTS pending_review_at TIMESTAMPTZ;
ALTER TABLE virtual_trades ADD COLUMN IF NOT EXISTS pending_review_action VARCHAR;
ALTER TABLE virtual_trades ADD COLUMN IF NOT EXISTS pending_review_score INT;
ALTER TABLE virtual_trades ADD COLUMN IF NOT EXISTS pending_review_reason TEXT;
ALTER TABLE virtual_trades ADD COLUMN IF NOT EXISTS entry_tier INT;
ALTER TABLE virtual_trades ADD COLUMN IF NOT EXISTS trust_multiplier DOUBLE PRECISION;
CREATE INDEX IF NOT EXISTS idx_virtual_trades_entry_tier ON virtual_trades(entry_tier) WHERE entry_tier IS NOT NULL;


-- 18b. AI RETRY QUEUE (tickers whose AI synthesis failed — retry on next scan)
-- When synthesis errors out (transient API issue, timeout, all providers down),
-- the ticker is added here. The next scan prepends these to the AI candidate
-- list so good signals don't get lost to one-off failures.
CREATE TABLE IF NOT EXISTS ai_retry_queue (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol          VARCHAR NOT NULL UNIQUE,
    failure_count   INT DEFAULT 1,
    last_failed_at  TIMESTAMPTZ DEFAULT now(),
    last_error      TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ai_retry_queue_failed_at ON ai_retry_queue(last_failed_at DESC);


-- 19. VIRTUAL SNAPSHOTS (daily equity curve for performance charts)
CREATE TABLE IF NOT EXISTS virtual_snapshots (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_date               DATE NOT NULL UNIQUE,
    brain_open                  INT DEFAULT 0,
    brain_unrealized_pnl        DOUBLE PRECISION DEFAULT 0,
    brain_cumulative_pnl        DOUBLE PRECISION DEFAULT 0,
    watchlist_open              INT DEFAULT 0,
    watchlist_unrealized_pnl    DOUBLE PRECISION DEFAULT 0,
    watchlist_cumulative_pnl    DOUBLE PRECISION DEFAULT 0,
    spy_price                   DOUBLE PRECISION,
    created_at                  TIMESTAMPTZ DEFAULT now()
);


-- 20. AI USAGE (budget tracking)
CREATE TABLE IF NOT EXISTS ai_usage (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider        VARCHAR NOT NULL,
    call_type       VARCHAR NOT NULL,
    ticker          VARCHAR,
    estimated_cost  DOUBLE PRECISION DEFAULT 0,
    success         BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ai_usage_provider ON ai_usage(provider, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_usage_date ON ai_usage(created_at DESC);


-- 21. WATCHDOG EVENTS (brain watchdog decision log for self-learning)
CREATE TABLE IF NOT EXISTS watchdog_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol          VARCHAR NOT NULL,
    event_type      VARCHAR NOT NULL,       -- ALERT, CLOSE, HOLD_THROUGH_DIP, RECOVERY, ESCALATION
    price           DOUBLE PRECISION,
    entry_price     DOUBLE PRECISION,
    pnl_pct         DOUBLE PRECISION,
    stop_loss       DOUBLE PRECISION,
    stop_distance_pct DOUBLE PRECISION,
    sentiment_label VARCHAR,                -- bullish, neutral, bearish
    sentiment_score INT,
    action_taken    VARCHAR,                -- warned, closed, held, escalated
    in_watchlist    BOOLEAN DEFAULT FALSE,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_watchdog_events_symbol ON watchdog_events(symbol);
CREATE INDEX IF NOT EXISTS idx_watchdog_events_type ON watchdog_events(event_type);
CREATE INDEX IF NOT EXISTS idx_watchdog_events_date ON watchdog_events(created_at DESC);


-- ============================================================
-- TRIGGERS (auto-update updated_at)
-- ============================================================

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS signals_updated_at ON signals;
CREATE TRIGGER signals_updated_at BEFORE UPDATE ON signals FOR EACH ROW EXECUTE FUNCTION update_updated_at();
DROP TRIGGER IF EXISTS portfolio_updated_at ON portfolio;
CREATE TRIGGER portfolio_updated_at BEFORE UPDATE ON portfolio FOR EACH ROW EXECUTE FUNCTION update_updated_at();
DROP TRIGGER IF EXISTS positions_updated_at ON positions;
CREATE TRIGGER positions_updated_at BEFORE UPDATE ON positions FOR EACH ROW EXECUTE FUNCTION update_updated_at();
DROP TRIGGER IF EXISTS trg_investment_rules_updated ON investment_rules;
CREATE TRIGGER trg_investment_rules_updated BEFORE UPDATE ON investment_rules FOR EACH ROW EXECUTE FUNCTION update_updated_at();
DROP TRIGGER IF EXISTS trg_signal_knowledge_updated ON signal_knowledge;
CREATE TRIGGER trg_signal_knowledge_updated BEFORE UPDATE ON signal_knowledge FOR EACH ROW EXECUTE FUNCTION update_updated_at();


-- ============================================================
-- FUNCTIONS
-- ============================================================

CREATE OR REPLACE FUNCTION increment_otp_attempts(otp_uuid UUID)
RETURNS VOID AS $$
BEGIN UPDATE otp_codes SET attempts = attempts + 1 WHERE id = otp_uuid; END;
$$ LANGUAGE plpgsql;


-- ============================================================
-- REALTIME
-- ============================================================

DO $$ BEGIN ALTER PUBLICATION supabase_realtime ADD TABLE signals; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER PUBLICATION supabase_realtime ADD TABLE alerts; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN ALTER PUBLICATION supabase_realtime ADD TABLE positions; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
