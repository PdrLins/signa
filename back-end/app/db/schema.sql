-- ============================================================
-- Signa — database schema (product only; the brain's tables are in Signa Advisor)
-- ============================================================
-- Creates the Signa schema on an EMPTY Supabase project in one run: the
-- product tables + migrations 010-026 (kept in migrations/ as history; they
-- are already included here). The brain's tables (scans, signals, positions,
-- virtual trades, knowledge, learning, AI usage...) are not part of Signa.
--
-- How: Supabase dashboard -> SQL Editor -> New query -> paste -> Run.
-- Idempotent (IF NOT EXISTS / ON CONFLICT): safe to run twice. Tested on
-- Postgres: one run creates 37 tables with RLS on; a second run changes nothing.
-- Changes after 032: add a numbered file in migrations/ (033, 034, ...),
-- run it on the database, and fold it into this file.
--
-- Afterwards: put the new project's URL and service_role key in the
-- server's SUPABASE_URL / SUPABASE_KEY, then create your user with
-- create_user.py (or sign up with an invite code).
-- Built 2026-10-03 from the pre-split schema + migrations 010-026.
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

-- Migration 019 (referrals): users.account_id VARCHAR(8) UNIQUE NOT NULL
-- (visible account ID = invite code), users.referred_by UUID -> users(id).
-- Later sections (011+) add more users columns.
ALTER TABLE users ADD COLUMN IF NOT EXISTS account_id VARCHAR(8) UNIQUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by UUID REFERENCES users(id) ON DELETE SET NULL;

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

-- 17. USER SETTINGS (per-user preferences)
CREATE TABLE IF NOT EXISTS user_settings (
    user_id     UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    theme       VARCHAR DEFAULT 'midnight',
    language    VARCHAR DEFAULT 'en',
    updated_at  TIMESTAMPTZ DEFAULT now()
);

-- updated_at trigger function + the OTP attempts RPC
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS portfolio_updated_at ON portfolio;
CREATE TRIGGER portfolio_updated_at BEFORE UPDATE ON portfolio FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE OR REPLACE FUNCTION increment_otp_attempts(otp_uuid UUID)
RETURNS VOID AS $$
BEGIN UPDATE otp_codes SET attempts = attempts + 1 WHERE id = otp_uuid; END;
$$ LANGUAGE plpgsql;

-- ############################################################
-- 010_holdings.sql
-- ############################################################

-- ============================================================
-- 010_holdings.sql — "My holdings": the owner's REAL long-term positions
-- ============================================================
--
-- WHY
--   Signa's short-term brain trades a virtual (paper) wallet. The owner's
--   real money is in long-term holdings (index ETFs, quality stocks, some
--   speculative names) at Wealthsimple. "My holdings" lets Signa watch those
--   positions (trend, drawdown, earnings, cited red flags, concentration),
--   run long-term reviews, and rank "where could new cash go?" considerations.
--
--   The old `portfolio` table (see the PORTFOLIO table above) was never used by the UI (the
--   /portfolio page was a "coming soon" stub) and has no unique key, no
--   resolved-symbol metadata and no monitoring columns. `holdings` replaces
--   it; any existing portfolio rows are copied over below (idempotent). The
--   /portfolio page now redirects to /holdings.
--
-- COLUMNS
--   symbol          resolved Yahoo symbol (XEQT.TO, NVDA, BTC-USD)
--   input_symbol    what the owner typed (XEQT)
--   shares/avg_cost NULL until the owner enters them — every feature works
--                   without them (weights / gains need them)
--   account         TFSA | RRSP | FHSA | NON_REGISTERED | OTHER | NULL
--   holding_status  latest monitor snapshot (price, changes, trend, drawdown,
--                   earnings, red flags, sentiment-check date) — JSONB
--   alert_state     last ALERTED state, for Telegram de-duplication — JSONB
--   last_review     latest long-term review summary (verdict, scorecard
--                   ratings, key concern) — JSONB
--   user_settings.holdings_review_all_at   last "review all" run (rate limit)
--
-- HOW TO APPLY (after 009)
--   Supabase dashboard → SQL Editor → paste this file → Run.
--   (or: psql "$DATABASE_URL" -f back-end/app/db/migrations/010_holdings.sql)
--   Idempotent: safe to run more than once.
--
-- BEFORE IT IS APPLIED
--   The rest of the backend keeps working. /api/v1/holdings answers 503
--   {"code": "holdings_unavailable"} and the 17:45 ET monitor job logs a
--   warning and does nothing.
--
-- RLS
--   Enabled with no policies, like 007: the backend uses the service_role
--   key (bypasses RLS); the public anon key gets no access.
-- ============================================================

CREATE TABLE IF NOT EXISTS holdings (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    symbol            VARCHAR(24) NOT NULL,
    input_symbol      VARCHAR(24),
    name              TEXT,
    exchange          VARCHAR(24),
    currency          VARCHAR(8),
    asset_type        VARCHAR(16),
    shares            NUMERIC,
    avg_cost          NUMERIC,
    account           VARCHAR(20),
    notes             TEXT,
    holding_status    JSONB,
    status_updated_at TIMESTAMPTZ,
    alert_state       JSONB,
    last_review       JSONB,
    last_reviewed_at  TIMESTAMPTZ,
    created_at        TIMESTAMPTZ DEFAULT now(),
    updated_at        TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT holdings_user_symbol_key UNIQUE (user_id, symbol),
    CONSTRAINT holdings_shares_positive CHECK (shares IS NULL OR shares > 0),
    CONSTRAINT holdings_avg_cost_positive CHECK (avg_cost IS NULL OR avg_cost > 0),
    CONSTRAINT holdings_account_valid CHECK (
        account IS NULL OR account IN ('TFSA', 'RRSP', 'FHSA', 'NON_REGISTERED', 'OTHER')
    )
);

-- Columns added after a first version of this table (safe to re-run)
ALTER TABLE holdings ADD COLUMN IF NOT EXISTS alert_state JSONB;
ALTER TABLE holdings ADD COLUMN IF NOT EXISTS last_reviewed_at TIMESTAMPTZ;
ALTER TABLE holdings ADD COLUMN IF NOT EXISTS status_updated_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_holdings_user ON holdings(user_id);

-- updated_at trigger (update_updated_at() is defined above)
DROP TRIGGER IF EXISTS holdings_updated_at ON holdings;
CREATE TRIGGER holdings_updated_at BEFORE UPDATE ON holdings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- "Review all" rate limit (settings.holdings_review_all_days)
ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS holdings_review_all_at TIMESTAMPTZ;

-- Carry over any rows from the unused legacy `portfolio` table.
-- (010's copy of the legacy portfolio rows into holdings is left out: a new database has none.)

ALTER TABLE public.holdings ENABLE ROW LEVEL SECURITY;

-- ############################################################
-- 011_access_levels.sql
-- ############################################################

-- ============================================================
-- 011_access_levels.sql — access levels per user + feature catalog
-- ============================================================
--
-- WHY
--   Signa becomes multi-user: a free tier (tracker), a later premium tier,
--   and the owner (everything, including the brain). Each user gets an
--   access_level; each area (page) and action (button / API operation) has
--   a minimum level in access_features. The API enforces it (403
--   {"code": "upgrade_required"}); web and iOS clients read the allowed
--   keys from GET /api/v1/auth/me.
--
-- WHAT
--   users.access_level   free | premium | owner   (default free)
--   users.slot_bonus     extra followed-stock slots (invites, later)
--   users.telegram_chat_id  now optional (free users have no Telegram)
--   access_features      key -> min_level. Rows override the defaults in
--                        app/core/access.py; a key with no row uses the
--                        code default. Unknown keys require owner.
--
-- EXISTING USERS
--   Signa had one user (the owner) before this migration, so every existing
--   user is set to owner. New users default to free.
--
-- CHANGE A LEVEL LATER
--   UPDATE users SET access_level = 'premium' WHERE username = 'someone';
--   UPDATE access_features SET min_level = 'premium' WHERE key = 'area.check';
--   (the API picks changes up within 60 seconds)
--
-- HOW TO APPLY (after 010)
--   Supabase dashboard → SQL Editor → paste this file → Run.
--   Idempotent: safe to run more than once. Before it is applied, every
--   user is treated as owner (single-user behaviour).
--
-- RLS
--   Enabled with no policies, like 007: the backend uses the service_role
--   key; the public anon key gets no access.
-- ============================================================

ALTER TABLE users ADD COLUMN IF NOT EXISTS access_level VARCHAR(16);
ALTER TABLE users ADD COLUMN IF NOT EXISTS slot_bonus INT NOT NULL DEFAULT 0;

-- Existing accounts predate multi-user: they are the owner.
UPDATE users SET access_level = 'owner' WHERE access_level IS NULL;

ALTER TABLE users ALTER COLUMN access_level SET DEFAULT 'free';
ALTER TABLE users ALTER COLUMN access_level SET NOT NULL;
DO $$ BEGIN
  ALTER TABLE users ADD CONSTRAINT users_access_level_check
    CHECK (access_level IN ('free', 'premium', 'owner'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

ALTER TABLE users ALTER COLUMN telegram_chat_id DROP NOT NULL;

CREATE TABLE IF NOT EXISTS access_features (
    key          VARCHAR(64) PRIMARY KEY,
    min_level    VARCHAR(16) NOT NULL CHECK (min_level IN ('free', 'premium', 'owner')),
    description  TEXT,
    updated_at   TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE access_features ENABLE ROW LEVEL SECURITY;

-- Seed the catalog. ON CONFLICT DO NOTHING keeps levels already changed.
INSERT INTO access_features (key, min_level, description) VALUES
  ('area.today', 'owner', 'Today: brain dashboard'),
  ('area.signals', 'owner', 'Signals from the brain''s scans'),
  ('area.check', 'owner', 'Check a stock (AI)'),
  ('area.positions', 'owner', 'Paper-trading positions and wallet'),
  ('area.performance', 'owner', 'Is it working? (brain track record)'),
  ('area.brain', 'owner', 'Brain rules, knowledge and learning'),
  ('area.holdings', 'free', 'My holdings'),
  ('area.watchlist', 'free', 'Watchlist'),
  ('area.how_it_works', 'free', 'How it works'),
  ('area.settings', 'free', 'Settings'),
  ('area.integrations', 'owner', 'Integrations, AI config and budgets'),
  ('area.logs', 'owner', 'Live logs'),
  ('action.scan.trigger', 'owner', 'Start a scan'),
  ('action.check.run', 'owner', 'Run an AI stock check'),
  ('action.check.compare', 'owner', 'Compare 2-3 stocks with AI'),
  ('action.holdings.edit', 'free', 'Add, edit and remove holdings'),
  ('action.holdings.refresh', 'owner', 'Refresh holdings monitor (may use Grok)'),
  ('action.holdings.review', 'owner', 'AI review of holdings'),
  ('action.holdings.allocate', 'owner', 'Where could new cash go? (AI)'),
  ('action.watchlist.edit', 'free', 'Add and remove watchlist stocks'),
  ('action.positions.manage', 'owner', 'Open, edit and close positions'),
  ('action.wallet.manage', 'owner', 'Deposit to / withdraw from the paper wallet'),
  ('action.brain.edit', 'owner', 'Edit brain rules and knowledge'),
  ('action.learning.manage', 'owner', 'Approve / apply learning suggestions'),
  ('action.settings.ai', 'owner', 'Change AI config and budgets'),
  ('system.ai', 'owner', 'Trigger AI calls (Grok, Claude, Codex)'),
  ('system.unlimited_slots', 'owner', 'No limit on followed stocks')
ON CONFLICT (key) DO NOTHING;

-- ############################################################
-- 012_free_areas.sql
-- ############################################################

-- ============================================================
-- 012_free_areas.sql — feature keys for the free stock page and dividends
-- ============================================================
-- Adds the two free areas to access_features (the code already defaults
-- them to free; the rows make the catalog complete and editable).
-- HOW TO APPLY (after 011): Supabase SQL Editor → paste → Run. Idempotent.
-- ============================================================

INSERT INTO access_features (key, min_level, description) VALUES
  ('area.stock', 'free', 'Stock page: price, dividends, events, Signa checks'),
  ('area.dividends', 'free', 'Dividend calendar and expected income')
ON CONFLICT (key) DO NOTHING;

-- ############################################################
-- 013_portfolio_foundation.sql
-- ############################################################

-- ============================================================
-- 013_portfolio_foundation.sql — portfolio tracker foundation (global, free)
-- ============================================================
--
-- WHY
--   Signa becomes a global, free portfolio tracker (plus the owner-only
--   brain). A tracker needs what "My holdings" (010) does not have:
--   accounts the user creates and names himself ("Wealthsimple",
--   "Questrade", "Ray WS"), the people those accounts belong to, a
--   transaction ledger (manual entry or CSV import with Signa's template —
--   no broker integrations), shared quotes, daily portfolio snapshots and
--   notification preferences. There are NO default accounts: nothing is
--   created for a user until he creates it.
--
-- WHAT
--   user_settings  + display_name, country (ISO 3166-1 alpha-2), home_currency
--                  (default CAD), dividend_tax_view (before|after, default
--                  before; "after" only for premium users in CA/US — enforced
--                  by the API), compare_index (NULL = no benchmark, opt-in),
--                  holdings_native_currency (bool), allocation_targets (JSONB)
--   portfolio_people  who an account belongs to (me, spouse, kid ...)
--   accounts       user-named accounts; account_type is an OPTIONAL tag
--                  (CA: TFSA, RRSP, FHSA, RESP, NON_REGISTERED; US: ROTH_IRA,
--                  TRADITIONAL_IRA, 401K, TAXABLE; OTHER) — premium + CA/US
--                  only, enforced by the API
--   holdings       + account_id. The unique key moves from (user_id, symbol)
--                  to (user_id, COALESCE(account_id, zero-uuid), symbol) so
--                  the same stock can sit in two accounts. The old `account`
--                  column stays (deprecated, no longer written) so nothing
--                  that reads it breaks.
--   transactions   the ledger. `amount` is ALWAYS a positive cash amount;
--                  the direction comes from `type`:
--                    buy        amount = quantity x price (gross); cash out = amount + fee
--                    sell       amount = quantity x price (gross); cash in  = amount - fee
--                    dividend   amount = cash received; quantity optional
--                    deposit / withdrawal   amount = cash moved; symbol NULL
--                    split      quantity = ratio (2 = 2-for-1, 0.1 = 1-for-10); amount NULL
--                    fee        amount = fee charged; symbol optional
--                  source manual|csv; import_batch_id groups one CSV import
--                  (DELETE /transactions/import/{batch_id} undoes it).
--   quotes         latest quote per symbol, shared by all users (refreshed
--                  every 60s during market hours by the scheduler)
--   portfolio_snapshots  daily value per user (account_id NULL = whole
--                  portfolio) and per account, in the user's home currency
--   notification_prefs   per-user alert preferences (JSONB; delivery later)
--   access_features      new feature keys (tracker areas/actions, premium
--                  account types and tax view)
--
-- HOW TO APPLY (after 012)
--   Supabase dashboard → SQL Editor → paste this file → Run.
--   (or: psql "$DATABASE_URL" -f back-end/app/db/migrations/013_portfolio_foundation.sql)
--   Idempotent: safe to run more than once.
--
-- BEFORE IT IS APPLIED
--   The rest of the backend keeps working. /api/v1/holdings keeps working
--   as before (items just carry account_id = null); the new endpoints
--   (/profile, /people, /accounts, /transactions, /notifications/prefs)
--   answer 503 {"code": "migration_required"}; the quotes and snapshot jobs
--   log a warning and do nothing.
--
-- RLS
--   Enabled with no policies, like 007: the backend uses the service_role
--   key (bypasses RLS); the public anon key gets no access.
-- ============================================================


-- ---------------------------------------------------------------- user_settings
ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS display_name VARCHAR(60);
ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS country VARCHAR(2);
ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS home_currency VARCHAR(3) NOT NULL DEFAULT 'CAD';
ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS dividend_tax_view VARCHAR(6) NOT NULL DEFAULT 'before';
ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS compare_index VARCHAR(16);
ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS holdings_native_currency BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS allocation_targets JSONB;
ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS auto_dividends BOOLEAN NOT NULL DEFAULT true;   -- 032

DO $$ BEGIN
  ALTER TABLE user_settings ADD CONSTRAINT user_settings_country_check
    CHECK (country IS NULL OR country ~ '^[A-Z]{2}$');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
  ALTER TABLE user_settings ADD CONSTRAINT user_settings_home_currency_check
    CHECK (home_currency ~ '^[A-Z]{3}$');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
  ALTER TABLE user_settings ADD CONSTRAINT user_settings_tax_view_check
    CHECK (dividend_tax_view IN ('before', 'after'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;


-- ---------------------------------------------------------------- people
CREATE TABLE IF NOT EXISTS portfolio_people (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        VARCHAR(60) NOT NULL,
    color       VARCHAR(7),
    created_at  TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT portfolio_people_user_name_key UNIQUE (user_id, name),
    CONSTRAINT portfolio_people_color_check CHECK (color IS NULL OR color ~ '^#[0-9A-Fa-f]{6}$')
);
CREATE INDEX IF NOT EXISTS idx_portfolio_people_user ON portfolio_people(user_id);
ALTER TABLE public.portfolio_people ENABLE ROW LEVEL SECURITY;


-- ---------------------------------------------------------------- accounts
CREATE TABLE IF NOT EXISTS accounts (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    person_id     UUID REFERENCES portfolio_people(id) ON DELETE SET NULL,
    name          VARCHAR(60) NOT NULL,
    account_type  VARCHAR(20),
    currency      VARCHAR(3) NOT NULL DEFAULT 'CAD',
    cash_balance  NUMERIC NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT accounts_user_name_key UNIQUE (user_id, name),
    CONSTRAINT accounts_currency_check CHECK (currency ~ '^[A-Z]{3}$'),
    CONSTRAINT accounts_type_check CHECK (
        account_type IS NULL OR account_type IN (
            'TFSA', 'RRSP', 'FHSA', 'RESP', 'NON_REGISTERED',
            'ROTH_IRA', 'TRADITIONAL_IRA', '401K', 'TAXABLE',
            'OTHER'
        )
    )
);
CREATE INDEX IF NOT EXISTS idx_accounts_user ON accounts(user_id);

DROP TRIGGER IF EXISTS accounts_updated_at ON accounts;
CREATE TRIGGER accounts_updated_at BEFORE UPDATE ON accounts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
ALTER TABLE public.accounts ENABLE ROW LEVEL SECURITY;


-- ---------------------------------------------------------------- holdings
ALTER TABLE holdings ADD COLUMN IF NOT EXISTS account_id UUID REFERENCES accounts(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_holdings_account ON holdings(account_id);

-- Same stock in two accounts: (user, account, symbol) is unique, with
-- "no account" (NULL) counted as one bucket.
ALTER TABLE holdings DROP CONSTRAINT IF EXISTS holdings_user_symbol_key;
CREATE UNIQUE INDEX IF NOT EXISTS holdings_user_account_symbol_key
    ON holdings (user_id, COALESCE(account_id, '00000000-0000-0000-0000-000000000000'::uuid), symbol);
COMMENT ON COLUMN holdings.account IS
    'DEPRECATED (013): replaced by account_id -> accounts. Kept for old readers; no longer written.';


-- ---------------------------------------------------------------- transactions
CREATE TABLE IF NOT EXISTS transactions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id       UUID REFERENCES accounts(id) ON DELETE SET NULL,
    symbol           VARCHAR(24),
    type             VARCHAR(12) NOT NULL,
    trade_date       DATE NOT NULL,
    quantity         NUMERIC,
    price            NUMERIC,
    amount           NUMERIC,
    currency         VARCHAR(3),
    fee              NUMERIC NOT NULL DEFAULT 0,
    note             TEXT,
    source           VARCHAR(8) NOT NULL DEFAULT 'manual',   -- manual | csv | auto (032: recorded by Signa)
    import_batch_id  UUID,
    created_at       TIMESTAMPTZ DEFAULT now(),
    auto_ref         VARCHAR(100),                            -- 032: auto:<account>:<symbol>:<ex-date>
    CONSTRAINT transactions_type_check CHECK (
        type IN ('buy', 'sell', 'dividend', 'deposit', 'withdrawal', 'split', 'fee')
    ),
    CONSTRAINT transactions_source_check CHECK (source IN ('manual', 'csv', 'auto')),
    CONSTRAINT transactions_currency_check CHECK (currency IS NULL OR currency ~ '^[A-Z]{3}$'),
    CONSTRAINT transactions_fee_check CHECK (fee >= 0),
    CONSTRAINT transactions_amount_check CHECK (amount IS NULL OR amount >= 0)
);
COMMENT ON COLUMN transactions.amount IS
    'Always a positive cash amount; direction comes from type (see migration 013 header).';
COMMENT ON COLUMN transactions.quantity IS
    'Shares for buy/sell/dividend; the split RATIO for split (2 = 2-for-1).';
CREATE INDEX IF NOT EXISTS idx_transactions_user_date ON transactions(user_id, trade_date);
CREATE INDEX IF NOT EXISTS idx_transactions_user_symbol ON transactions(user_id, symbol);
CREATE INDEX IF NOT EXISTS idx_transactions_batch ON transactions(import_batch_id)
    WHERE import_batch_id IS NOT NULL;
ALTER TABLE public.transactions ENABLE ROW LEVEL SECURITY;


-- ---------------------------------------------------------------- quotes (shared)
CREATE TABLE IF NOT EXISTS quotes (
    symbol      VARCHAR(24) PRIMARY KEY,
    price       NUMERIC,
    prev_close  NUMERIC,
    change_pct  NUMERIC,
    currency    VARCHAR(3),
    day_high    NUMERIC,
    day_low     NUMERIC,
    as_of       TIMESTAMPTZ,
    updated_at  TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE public.quotes ENABLE ROW LEVEL SECURITY;


-- ---------------------------------------------------------------- snapshots
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    snapshot_date  DATE NOT NULL,
    account_id     UUID REFERENCES accounts(id) ON DELETE CASCADE,
    market_value   NUMERIC,
    cash           NUMERIC,
    cost_basis     NUMERIC,
    currency       VARCHAR(3) NOT NULL,
    -- positions whose currency could not be converted to `currency`
    -- (only USD/CAD are converted for now): [{symbol, currency, market_value}]
    unconverted    JSONB,
    created_at     TIMESTAMPTZ DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS portfolio_snapshots_user_date_account_key
    ON portfolio_snapshots (user_id, snapshot_date,
                            COALESCE(account_id, '00000000-0000-0000-0000-000000000000'::uuid));
ALTER TABLE public.portfolio_snapshots ENABLE ROW LEVEL SECURITY;


-- ---------------------------------------------------------------- notification prefs
CREATE TABLE IF NOT EXISTS notification_prefs (
    user_id     UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    prefs       JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at  TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE public.notification_prefs ENABLE ROW LEVEL SECURITY;


-- ---------------------------------------------------------------- access features
INSERT INTO access_features (key, min_level, description) VALUES
  ('area.home', 'free', 'Home: portfolio overview'),
  ('area.insights', 'free', 'Portfolio insights (allocation, performance)'),
  ('area.coming_up', 'free', 'Coming up: dividends, earnings and events'),
  ('area.profile', 'free', 'Profile, preferences and notifications'),
  ('action.accounts.edit', 'free', 'Create, edit and delete accounts and people'),
  ('action.transactions.edit', 'free', 'Add, edit and delete transactions'),
  ('action.import.csv', 'free', 'Import transactions from a CSV file'),
  ('action.accounts.type', 'premium', 'Tag accounts with a tax type (TFSA, RRSP, IRA ...)'),
  ('feature.tax_view', 'premium', 'After-tax dividend view')
ON CONFLICT (key) DO NOTHING;

-- ############################################################
-- 014_portfolio_insights.sql
-- ############################################################

-- ============================================================
-- 014_portfolio_insights.sql — history tables for the tracker's insights
-- ============================================================
--
-- WHY
--   Phase 2 of the portfolio tracker (home, performance, dividends
--   summary, coming up, allocation) needs two small daily histories the
--   app can diff against, plus an honest timestamp on shared quotes:
--
--   * "Why your income changed" (GET /dividends/summary) compares today's
--     forward income forecast with the one ~30 days ago: FX, raises, cuts,
--     new / removed shares. That needs one stored forecast per user per day.
--   * "A Signa check changed" (GET /events/upcoming) needs yesterday's
--     check statuses per symbol. The checks are shared market data (the
--     free stock page), so this table is per SYMBOL, not per user.
--   * quotes.as_of used to be the daily bar's date at midnight. It is now
--     the real time of the price and `as_of_source` says how it was
--     obtained, so clients can show "As of 10:42 ET · delayed 15 min".
--
-- WHAT
--   income_forecast_snapshots  one row per user per day (daily job, 18:00 ET):
--       total_home  forward 12-month income in the user's home currency
--                   (before tax; shares x forward annual rate)
--       currency    the home currency used
--       usdcad      CAD per 1 USD used for the conversion
--       per_symbol  {"NVDA": {"shares": 10, "annual_rate": 0.04, "currency": "USD",
--                             "annual_native": 0.4, "annual_home": 0.55}, ...}
--   check_status_daily         one row per symbol per day (daily job, 18:15 ET):
--       statuses    {"uptrend": "pass", "not_overheated": "warn", ...}
--                   (the five Signa checks of the stock page)
--   quotes.as_of_source        'bar' (intraday bar time) | 'fetch' (time the
--                   live daily bar was fetched) | 'close' (the session close
--                   of a finished daily bar)
--   users.last_seen_at         last authenticated request (written at most
--                   once per hour per user by the auth middleware). The
--                   quotes job only refreshes symbols followed by users seen
--                   in the last 7 days (cost control).
--   data_usage_daily           (usage_date, metric) -> count: provider calls
--                   (quotes, daily history, intraday bars ...), symbols
--                   refreshed and requests to the heavy endpoints, so a price
--                   per plan can be set later. Incremented through
--                   increment_data_usage() (atomic), buffered in memory and
--                   flushed every few minutes. Read by GET /admin/usage (owner).
--   access_features            feature.intraday_chart (premium: 5-minute 1D
--                   chart; free gets 15-minute bars) and feature.full_history
--                   (premium: the ALL range; free stops at 1Y)
--
-- HOW TO APPLY (after 013)
--   Supabase dashboard → SQL Editor → paste this file → Run.
--   (or: psql "$DATABASE_URL" -f back-end/app/db/migrations/014_portfolio_insights.sql)
--   Idempotent: safe to run more than once.
--
-- BEFORE IT IS APPLIED
--   Everything keeps working: /dividends/summary returns no "why changed"
--   history (available_from = null), /events/upcoming has no check_changed
--   items, the two daily jobs log a warning and do nothing, quotes are
--   stored without as_of_source, activity falls back to users.last_login,
--   usage counters are dropped (logged) and /admin/usage answers 503
--   migration_required.
--
-- RLS
--   Enabled with no policies, like 007/013 (backend uses service_role).
-- ============================================================


-- ---------------------------------------------------------------- income forecast
CREATE TABLE IF NOT EXISTS income_forecast_snapshots (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    snapshot_date  DATE NOT NULL,
    total_home     NUMERIC,
    currency       VARCHAR(3) NOT NULL,
    usdcad         NUMERIC,
    per_symbol     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT income_forecast_snapshots_user_date_key UNIQUE (user_id, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_income_forecast_user_date
    ON income_forecast_snapshots (user_id, snapshot_date DESC);
ALTER TABLE public.income_forecast_snapshots ENABLE ROW LEVEL SECURITY;


-- ---------------------------------------------------------------- check status (shared)
CREATE TABLE IF NOT EXISTS check_status_daily (
    symbol      VARCHAR(24) NOT NULL,
    check_date  DATE NOT NULL,
    statuses    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (symbol, check_date)
);
CREATE INDEX IF NOT EXISTS idx_check_status_daily_date ON check_status_daily (check_date);
ALTER TABLE public.check_status_daily ENABLE ROW LEVEL SECURITY;


-- ---------------------------------------------------------------- quotes
ALTER TABLE quotes ADD COLUMN IF NOT EXISTS as_of_source VARCHAR(8);
COMMENT ON COLUMN quotes.as_of IS
    'Real time of the price (014): intraday bar time, fetch time of a live daily bar, or the session close.';


-- ---------------------------------------------------------------- activity
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_users_last_seen_at ON users (last_seen_at);


-- ---------------------------------------------------------------- usage metrics
CREATE TABLE IF NOT EXISTS data_usage_daily (
    usage_date  DATE NOT NULL,
    metric      VARCHAR(64) NOT NULL,
    count       BIGINT NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (usage_date, metric)
);
ALTER TABLE public.data_usage_daily ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION increment_data_usage(p_date DATE, p_metric TEXT, p_count BIGINT)
RETURNS VOID LANGUAGE sql AS $$
    INSERT INTO data_usage_daily (usage_date, metric, count, updated_at)
    VALUES (p_date, p_metric, p_count, now())
    ON CONFLICT (usage_date, metric)
    DO UPDATE SET count = data_usage_daily.count + EXCLUDED.count, updated_at = now();
$$;


-- ---------------------------------------------------------------- access features
INSERT INTO access_features (key, min_level, description) VALUES
  ('feature.intraday_chart', 'premium', '5-minute intraday chart (free: 15-minute bars)'),
  ('feature.full_history', 'premium', 'Full portfolio history (ALL range; free: up to 1 year)')
ON CONFLICT (key) DO NOTHING;

-- ############################################################
-- 015_price_alerts_and_slots.sql
-- ############################################################

-- ============================================================
-- 015_price_alerts_and_slots.sql — price alerts + premium slot rules
-- ============================================================
--
-- WHY
--   Followed symbols are what users pay for: free users follow 10 stocks,
--   premium and owner follow any number. Price alerts ("tell me when ENB.TO
--   goes below 50") are the next free-tier hook: free users keep up to 3
--   active alerts, premium and owner have no limit.
--
-- WHAT
--   price_alerts              one row per alert (API: /api/v1/alerts):
--       direction     'above' (fires when price >= target) | 'below' (price <= target)
--       target_price  in `currency` (the listing currency unless the user
--                     chose another; USD<->CAD are converted at evaluation)
--       active        true until it fires (or the user pauses it)
--       triggered_at  when the quotes job saw the price cross; the alert is
--                     then deactivated and shows in GET /events/upcoming as a
--                     recent "price_alert" item for 7 days
--       last_price    the price (in `currency`) that fired it
--   access_features
--       system.unlimited_slots  owner -> premium (DO UPDATE: the only key
--                     whose level changes here)
--       action.alerts.edit      free    (create / edit / delete alerts)
--       feature.unlimited_alerts premium (no cap on active alerts)
--   users.slot_bonus is KEPT (invite rewards) but no longer raises the free
--   limit: the code caps free at 10 flat (app/core/access.py SLOT_MAX).
--
-- HOW TO APPLY (after 014)
--   Supabase dashboard → SQL Editor → paste this file → Run.
--   (or: psql "$DATABASE_URL" -f back-end/app/db/migrations/015_price_alerts_and_slots.sql)
--   Idempotent: safe to run more than once.
--
-- BEFORE IT IS APPLIED
--   /api/v1/alerts answers 503 {"code": "migration_required",
--   "migration": "015_price_alerts_and_slots.sql"}; the quotes job skips
--   alert evaluation (logged at debug); /events/upcoming reports
--   sources.price_alerts = "unavailable". Slot limits already follow the
--   code (free 10, premium and owner unlimited via SLOT_BASE); the stale
--   011 row (system.unlimited_slots = owner) only makes GET /auth/me show
--   that key as owner-only until this migration updates it.
--
-- RLS
--   Enabled with no policies, like 007/013/014 (backend uses service_role).
-- ============================================================


-- ---------------------------------------------------------------- price alerts
CREATE TABLE IF NOT EXISTS price_alerts (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    symbol        VARCHAR(24) NOT NULL,
    direction     VARCHAR(8) NOT NULL,      -- price/percent: above | below; day_move: up | down | either (031)
    target_price  NUMERIC CHECK (target_price > 0),   -- null for day_move (031)
    currency      VARCHAR(3) NOT NULL,
    note          VARCHAR(200),
    active        BOOLEAN NOT NULL DEFAULT true,
    triggered_at  TIMESTAMPTZ,
    last_price    NUMERIC,
    created_at    TIMESTAMPTZ DEFAULT now(),
    -- 031: percentage alerts
    kind               TEXT NOT NULL DEFAULT 'price',   -- price | percent | day_move
    percent            NUMERIC,
    reference_price    NUMERIC,
    last_triggered_on  DATE,
    last_change_pct    NUMERIC
);
CREATE INDEX IF NOT EXISTS idx_price_alerts_user_id ON price_alerts (user_id);
CREATE INDEX IF NOT EXISTS idx_price_alerts_symbol ON price_alerts (symbol);
-- the quotes job reads only active alerts of the refreshed symbols
CREATE INDEX IF NOT EXISTS idx_price_alerts_active_symbol ON price_alerts (symbol) WHERE active;
ALTER TABLE public.price_alerts ENABLE ROW LEVEL SECURITY;


-- ---------------------------------------------------------------- access features
INSERT INTO access_features (key, min_level, description) VALUES
  ('system.unlimited_slots', 'premium', 'No limit on followed stocks')
ON CONFLICT (key) DO UPDATE
  SET min_level = EXCLUDED.min_level, description = EXCLUDED.description, updated_at = now();

INSERT INTO access_features (key, min_level, description) VALUES
  ('action.alerts.edit', 'free', 'Create, edit and delete price alerts'),
  ('feature.unlimited_alerts', 'premium', 'No limit on active price alerts (free: 3)')
ON CONFLICT (key) DO NOTHING;

COMMENT ON COLUMN users.slot_bonus IS
    'Invite reward slots. Kept, but since 015 it does not raise the free limit (free = 10 flat, premium/owner unlimited).';

-- ############################################################
-- 016_telegram_notifications.sql
-- ############################################################

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

-- ############################################################
-- 017_auth_sessions.sql
-- ############################################################

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

-- ############################################################
-- 018_email_sign_in.sql
-- ############################################################

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

-- ############################################################
-- 019_referrals.sql
-- ############################################################

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

-- ############################################################
-- 020_two_factor.sql
-- ############################################################

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

-- ############################################################
-- 021_extended_hours.sql
-- ############################################################

-- ============================================================
-- 021_extended_hours.sql — pre-market / after-hours prices (Premium)
-- ============================================================
--
-- WHY
--   US stocks also trade before the open (4:00–9:30 ET) and after the close
--   (16:00–20:00 ET). Premium users see those prices (feature.extended_hours);
--   everyone sees crypto 24/7 (no schema change: the off-hours quotes job
--   refreshes followed crypto at the user's plan rate).
--
-- WHAT
--   quotes.ext_price        last pre-market / after-hours trade (listing currency)
--   quotes.ext_change_pct   vs quotes.price (the last regular-session price)
--   quotes.ext_session      'pre' | 'post'
--   quotes.ext_as_of        time of that trade
--   Clients only show it while it is newer than the regular price and the
--   regular session is closed (app/services/quotes.extended_view).
--   access_features: feature.extended_hours = premium
--
-- HOW TO APPLY (after 020)
--   Supabase dashboard → SQL Editor → paste this file → Run.
--   (or: psql "$DATABASE_URL" -f back-end/app/db/migrations/021_extended_hours.sql)
--   Idempotent: safe to run more than once.
--
-- BEFORE IT IS APPLIED
--   No extended prices are stored or shown ("extended": null everywhere);
--   crypto still refreshes 24/7; the 1D chart of Premium users already
--   includes pre/after-hours bars.
-- ============================================================

ALTER TABLE quotes ADD COLUMN IF NOT EXISTS ext_price NUMERIC;
ALTER TABLE quotes ADD COLUMN IF NOT EXISTS ext_change_pct NUMERIC;
ALTER TABLE quotes ADD COLUMN IF NOT EXISTS ext_session VARCHAR(4);
ALTER TABLE quotes ADD COLUMN IF NOT EXISTS ext_as_of TIMESTAMPTZ;

INSERT INTO access_features (key, min_level, description) VALUES
  ('feature.extended_hours', 'premium', 'Pre-market and after-hours prices (US stocks)')
ON CONFLICT (key) DO NOTHING;

-- ############################################################
-- 022_plan_levels.sql
-- ############################################################

-- ============================================================
-- 022_plan_levels.sql — Free / Premium split (decided 2026-10-02)
-- ============================================================
--
-- WHY
--   Free should cover everything needed to understand your own portfolio;
--   Premium adds planning and deeper analysis. Rows in access_features
--   override the code defaults (app/core/access.py), so the levels that
--   earlier migrations stored must be updated here too.
--
-- WHAT
--   feature.intraday_chart    premium -> free  (5-minute 1D bars for everyone)
--   action.accounts.type      premium -> free  (TFSA / RRSP / IRA tags)
--   feature.allocation_plan   new, premium     (target allocation + deposit plan:
--                                               GET/PUT /portfolio/allocation/targets,
--                                               GET /portfolio/allocation/plan)
--   feature.income_quality    new, premium     (GET /portfolio/income-quality/{symbol})
--   feature.similar_funds     new, premium     (reserved: similar funds on the stock page; free since 033)
--   The allocation mix (GET /portfolio/allocation), ETF fund data, sectors,
--   top holdings and the About card stay free.
--
-- HOW TO APPLY (after 021)
--   Supabase dashboard → SQL Editor → paste this file → Run.
--   (or: psql "$DATABASE_URL" -f back-end/app/db/migrations/022_plan_levels.sql)
--   Idempotent: safe to run more than once.
--
-- BEFORE IT IS APPLIED
--   The code defaults already have the new levels, but the stored rows for
--   feature.intraday_chart and action.accounts.type keep them Premium until
--   this runs. The new premium keys work from the code defaults.
-- ============================================================

INSERT INTO access_features (key, min_level, description) VALUES
  ('feature.intraday_chart', 'free', '5-minute intraday chart'),
  ('action.accounts.type', 'free', 'Tag accounts with a tax type (TFSA, RRSP, IRA ...)'),
  ('feature.allocation_plan', 'premium', 'Target allocation and deposit plan'),
  ('feature.income_quality', 'premium', 'Income quality of option-income / covered-call ETFs'),
  ('feature.similar_funds', 'premium', 'Similar funds compared (fee, yield, return)')
ON CONFLICT (key) DO UPDATE SET min_level = EXCLUDED.min_level, description = EXCLUDED.description;

-- ############################################################
-- 023_feedback_reports.sql
-- ############################################################

-- ============================================================================
-- 023_feedback_reports.sql — "Report a problem" from the apps
-- ============================================================================
-- A signed-in user (iOS or web) sends a problem report or an idea:
-- POST /api/v1/feedback. The owner reads and triages them: GET/PATCH
-- /api/v1/feedback (area.admin). A deleted account keeps its reports,
-- anonymized (user_id -> NULL). Idempotent.
-- ============================================================================

CREATE TABLE IF NOT EXISTS feedback_reports (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID REFERENCES users(id) ON DELETE SET NULL,
    kind          VARCHAR(8)  NOT NULL DEFAULT 'bug' CHECK (kind IN ('bug', 'idea', 'other')),
    message       TEXT        NOT NULL CHECK (char_length(message) BETWEEN 1 AND 4000),
    platform      VARCHAR(8)  NOT NULL DEFAULT 'ios' CHECK (platform IN ('ios', 'web')),
    screen        VARCHAR(80),
    app_version   VARCHAR(32),
    build         VARCHAR(32),
    os_version    VARCHAR(32),
    device_model  VARCHAR(64),
    locale        VARCHAR(16),
    diagnostics   JSONB,
    status        VARCHAR(12) NOT NULL DEFAULT 'open'
                  CHECK (status IN ('open', 'in_progress', 'fixed', 'wont_fix', 'duplicate')),
    owner_note    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_feedback_reports_status ON feedback_reports (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_reports_user ON feedback_reports (user_id, created_at DESC);

DROP TRIGGER IF EXISTS feedback_reports_updated_at ON feedback_reports;
CREATE TRIGGER feedback_reports_updated_at BEFORE UPDATE ON feedback_reports
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

ALTER TABLE public.feedback_reports ENABLE ROW LEVEL SECURITY;

-- ############################################################
-- 024_feedback_data_kind.sql
-- ############################################################

-- ============================================================================
-- 024_feedback_data_kind.sql — "Report wrong data" (kind 'data')
-- ============================================================================
-- A one-tap report on a wrong price / dividend / date from the apps:
-- POST /api/v1/feedback {"kind": "data", "symbol": "XEQT.TO",
--   "diagnostics": {"field": "dividend_amount", "shown": "0.21", "expected": "0.19"}}.
-- Idempotent.
-- ============================================================================

ALTER TABLE feedback_reports DROP CONSTRAINT IF EXISTS feedback_reports_kind_check;
ALTER TABLE feedback_reports ADD CONSTRAINT feedback_reports_kind_check
    CHECK (kind IN ('bug', 'idea', 'data', 'other'));
ALTER TABLE feedback_reports ADD COLUMN IF NOT EXISTS symbol VARCHAR(24);
CREATE INDEX IF NOT EXISTS idx_feedback_reports_symbol ON feedback_reports (symbol) WHERE symbol IS NOT NULL;

-- ############################################################
-- 025_push_devices.sql
-- ############################################################

-- ============================================================================
-- 025_push_devices.sql — iOS push notifications (APNs)
-- ============================================================================
-- One row per app install that allowed notifications. The iOS app sends its
-- APNs device token after sign-in (POST /api/v1/notifications/devices) and
-- removes it on sign-out (DELETE). A token belongs to one user: registering
-- it from another account moves it. Tokens Apple reports as invalid are
-- disabled (disabled_at). Delivery reuses notification_prefs and
-- notification_deliveries (dedupe keys prefixed "push:"). Idempotent.
-- ============================================================================

CREATE TABLE IF NOT EXISTS push_devices (
    token         VARCHAR(200) PRIMARY KEY,           -- APNs device token (hex)
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    platform      VARCHAR(8)  NOT NULL DEFAULT 'ios' CHECK (platform IN ('ios')),
    environment   VARCHAR(12) NOT NULL DEFAULT 'production' CHECK (environment IN ('sandbox', 'production')),
    app_version   VARCHAR(32),
    device_name   VARCHAR(80),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    disabled_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_push_devices_user ON push_devices (user_id) WHERE disabled_at IS NULL;

DROP TRIGGER IF EXISTS push_devices_updated_at ON push_devices;
CREATE TRIGGER push_devices_updated_at BEFORE UPDATE ON push_devices
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

ALTER TABLE public.push_devices ENABLE ROW LEVEL SECURITY;

INSERT INTO access_features (key, min_level, description) VALUES
  ('feature.push_all', 'premium', 'Every push notification type (free: price alerts, dividends, earnings, report updates)'),
  ('feature.all_widgets', 'premium', 'Every home-screen and lock-screen widget (free: 1)')
ON CONFLICT (key) DO NOTHING;

-- ############################################################
-- 026_goals.sql
-- ############################################################

-- ============================================================================
-- 026_goals.sql — investing goals (portfolio value, monthly dividend income)
-- ============================================================================
-- Free: 1 goal; Premium (feature.unlimited_goals): unlimited. Progress is
-- computed on read (GET /api/v1/goals); nothing is stored but the target.
-- Idempotent.
-- ============================================================================

CREATE TABLE IF NOT EXISTS goals (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind         VARCHAR(20) NOT NULL CHECK (kind IN ('portfolio_value', 'monthly_income')),
    target       NUMERIC NOT NULL CHECK (target > 0),
    currency     VARCHAR(3) NOT NULL,
    title        VARCHAR(60),
    target_date  DATE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- 034: projection settings
    monthly_contribution  NUMERIC CHECK (monthly_contribution IS NULL OR monthly_contribution >= 0),
    expected_return_pct   NUMERIC CHECK (expected_return_pct IS NULL OR expected_return_pct BETWEEN -20 AND 30)
);
CREATE INDEX IF NOT EXISTS idx_goals_user ON goals (user_id, created_at);

DROP TRIGGER IF EXISTS goals_updated_at ON goals;
CREATE TRIGGER goals_updated_at BEFORE UPDATE ON goals
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

ALTER TABLE public.goals ENABLE ROW LEVEL SECURITY;

INSERT INTO access_features (key, min_level, description) VALUES
  ('feature.unlimited_goals', 'premium', 'Unlimited goals (free: 1)')
ON CONFLICT (key) DO NOTHING;

-- ############################################################
-- 027_performance_indexes.sql
-- ############################################################

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

-- ############################################################
-- 028_suggestions.sql
-- ############################################################

-- ============================================================================
-- 028_suggestions.sql — stock suggestions without AI
-- ============================================================================
-- symbol_profiles   what a symbol is (sector, industry, country, size,
--                   dividend yield), shared by everyone. Written when a stock
--                   page is built and refreshed nightly for followed symbols.
-- symbol_cofollows  "people who follow X also follow Y": anonymous counts of
--                   users following both, computed nightly. Only pairs shared
--                   by at least 5 users are stored; no user ids.
-- Read by app/services/suggestions.py. Idempotent.
-- ============================================================================

CREATE TABLE IF NOT EXISTS symbol_profiles (
    symbol          VARCHAR(24) PRIMARY KEY,
    name            TEXT,
    quote_type      VARCHAR(16),            -- EQUITY | ETF | MUTUALFUND | CRYPTOCURRENCY ...
    sector          VARCHAR(64),
    industry        VARCHAR(96),
    category        VARCHAR(96),            -- funds: Yahoo category ("Canada Equity" ...)
    country         VARCHAR(64),
    exchange        VARCHAR(24),            -- Signa label (B3, TSX, LSE, US ...)
    currency        VARCHAR(3),
    market_cap      NUMERIC,                -- listing currency
    dividend_yield  NUMERIC,                -- FRACTION (0.035 = 3.5%)
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_symbol_profiles_industry ON symbol_profiles (industry);
CREATE INDEX IF NOT EXISTS idx_symbol_profiles_updated ON symbol_profiles (updated_at);
ALTER TABLE public.symbol_profiles ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS symbol_cofollows (
    symbol      VARCHAR(24) NOT NULL,
    other       VARCHAR(24) NOT NULL,
    users       INTEGER NOT NULL CHECK (users > 0),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, other)
);
ALTER TABLE public.symbol_cofollows ENABLE ROW LEVEL SECURITY;

INSERT INTO access_features (key, min_level, description) VALUES
  ('feature.suggestions_all', 'premium', 'Every suggestion (free: 3 similar stocks and 3 also-followed)'),
  ('feature.portfolio_gaps', 'premium', 'Gaps in your portfolio, with ideas to look at')
ON CONFLICT (key) DO NOTHING;

-- ############################################################
-- 029_growth.sql
-- ############################################################

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

-- ############################################################
-- 030_account_lifecycle.sql
-- ############################################################

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

-- ############################################################
-- 031_alert_kinds.sql
-- ############################################################

-- ============================================================================
-- 031_alert_kinds.sql — percentage price alerts
-- ============================================================================
-- price_alerts.kind
--   price     (default, every existing row) fires once at target_price
--   percent   up/down N% from reference_price (the price when it was set);
--             target_price is computed and stored, then it fires like price
--   day_move  the day's move reaches N% (vs the previous close), at most once
--             per trading day; stays active and re-arms the next session
-- percent / reference_price   kept for display (percent and day_move kinds)
-- last_triggered_on / last_change_pct   day_move: the day it last fired and
--             that day's move (for the push text and "once a day")
-- direction now also allows up / down / either (day_move).
-- Idempotent.
-- ============================================================================

ALTER TABLE price_alerts ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'price';
ALTER TABLE price_alerts ADD COLUMN IF NOT EXISTS percent NUMERIC;
ALTER TABLE price_alerts ADD COLUMN IF NOT EXISTS reference_price NUMERIC;
ALTER TABLE price_alerts ADD COLUMN IF NOT EXISTS last_triggered_on DATE;
ALTER TABLE price_alerts ADD COLUMN IF NOT EXISTS last_change_pct NUMERIC;

ALTER TABLE price_alerts DROP CONSTRAINT IF EXISTS price_alerts_kind_check;
ALTER TABLE price_alerts ADD CONSTRAINT price_alerts_kind_check CHECK (kind IN ('price', 'percent', 'day_move'));

-- day_move has no target price
ALTER TABLE price_alerts ALTER COLUMN target_price DROP NOT NULL;

DO $$
DECLARE c TEXT;
BEGIN
    -- the original direction check allowed only above / below
    FOR c IN SELECT conname FROM pg_constraint
             WHERE conrelid = 'public.price_alerts'::regclass AND contype = 'c'
               AND pg_get_constraintdef(oid) ILIKE '%direction%'
    LOOP
        EXECUTE format('ALTER TABLE price_alerts DROP CONSTRAINT %I', c);
    END LOOP;
END $$;
ALTER TABLE price_alerts ALTER COLUMN direction TYPE VARCHAR(8);   -- "either" is 6 letters
ALTER TABLE price_alerts ADD CONSTRAINT price_alerts_direction_check
    CHECK (direction IN ('above', 'below', 'up', 'down', 'either'));

-- ############################################################
-- 032_auto_dividends_fixed_income.sql
-- ############################################################

-- ============================================================================
-- 032_auto_dividends_fixed_income.sql
-- ============================================================================
-- Dividends logged automatically (app/services/auto_dividends.py)
--   transactions.source 'auto'    a dividend Signa recorded from the holding and
--     the stock's dividend history ("estimated"); the user can edit or delete it
--   transactions.auto_ref         auto:<account>:<symbol>:<ex-date>, one per payment
--   auto_dividend_dismissed       payments the user deleted: never re-created
--   user_settings.auto_dividends  on by default; off = nothing new is recorded
-- Fixed income (app/services/fixed_income.py)
--   fixed_income   Tesouro Direto, CDB, LCI/LCA ... entered by hand, valued
--     daily from the indexer (CDI / Selic from Banco Central, fixed rate, IPCA+)
-- Idempotent.
-- ============================================================================

ALTER TABLE transactions ADD COLUMN IF NOT EXISTS auto_ref VARCHAR(100);
CREATE UNIQUE INDEX IF NOT EXISTS transactions_user_auto_ref_key ON transactions (user_id, auto_ref)
    WHERE auto_ref IS NOT NULL;
ALTER TABLE transactions DROP CONSTRAINT IF EXISTS transactions_source_check;
ALTER TABLE transactions ADD CONSTRAINT transactions_source_check CHECK (source IN ('manual', 'csv', 'auto'));

CREATE TABLE IF NOT EXISTS auto_dividend_dismissed (
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    auto_ref    VARCHAR(100) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, auto_ref)
);
ALTER TABLE public.auto_dividend_dismissed ENABLE ROW LEVEL SECURITY;

ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS auto_dividends BOOLEAN NOT NULL DEFAULT true;

CREATE TABLE IF NOT EXISTS fixed_income (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id     UUID REFERENCES accounts(id) ON DELETE SET NULL,
    name           VARCHAR(80) NOT NULL,
    kind           VARCHAR(20) NOT NULL CHECK (kind IN (
                       'tesouro_selic', 'tesouro_prefixado', 'tesouro_ipca', 'cdb', 'lci', 'lca', 'lc',
                       'debenture', 'cri', 'cra', 'other')),
    indexer        VARCHAR(8) NOT NULL CHECK (indexer IN ('cdi', 'selic', 'pre', 'ipca')),
    rate           NUMERIC NOT NULL CHECK (rate >= 0),   -- cdi/selic: % of the index (110); pre: % a year; ipca: spread % a year
    principal      NUMERIC NOT NULL CHECK (principal > 0),
    currency       VARCHAR(3) NOT NULL DEFAULT 'BRL',
    start_date     DATE NOT NULL,
    maturity_date  DATE,
    tax_exempt     BOOLEAN NOT NULL DEFAULT false,      -- LCI / LCA / CRI / CRA for individuals
    note           VARCHAR(200),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fixed_income_user ON fixed_income (user_id);
ALTER TABLE public.fixed_income ENABLE ROW LEVEL SECURITY;

-- ############################################################
-- 033_similar_funds_free.sql
-- ############################################################

-- ============================================================================
-- 033_similar_funds_free.sql — fund comparison for every plan
-- ============================================================================
-- feature.similar_funds   premium -> free   ("Similar funds" table on an ETF's
--   stock page: fee, yield, return). Premium can't be bought yet, so free users
--   shouldn't see it locked.
-- Before it is applied: the code default is already free, but a stored row
-- (from 022) keeps it Premium until this runs. Idempotent.
-- ============================================================================

INSERT INTO access_features (key, min_level, description) VALUES
  ('feature.similar_funds', 'free', 'Similar funds compared (fee, yield, return)')
ON CONFLICT (key) DO UPDATE SET min_level = EXCLUDED.min_level, description = EXCLUDED.description;

-- ############################################################
-- 034_goal_projections.sql
-- ############################################################

-- ============================================================================
-- 034_goal_projections.sql — what the user plans to add to a goal
-- ============================================================================
-- goals.monthly_contribution   planned monthly addition, in the goal's currency
--                              (>= 0; NULL = not set)
-- goals.expected_return_pct    yearly growth the user assumes: portfolio growth
--                              for portfolio_value goals, dividend growth for
--                              monthly_income goals (-20..30; NULL = app default)
-- The app projects the date itself; the back-end only stores these.
-- Before it is applied: goals work without them (the fields are left out).
-- Idempotent.
-- ============================================================================

ALTER TABLE goals ADD COLUMN IF NOT EXISTS monthly_contribution NUMERIC;
ALTER TABLE goals ADD COLUMN IF NOT EXISTS expected_return_pct NUMERIC;

ALTER TABLE goals DROP CONSTRAINT IF EXISTS goals_monthly_contribution_check;
ALTER TABLE goals ADD CONSTRAINT goals_monthly_contribution_check
    CHECK (monthly_contribution IS NULL OR monthly_contribution >= 0);
ALTER TABLE goals DROP CONSTRAINT IF EXISTS goals_expected_return_pct_check;
ALTER TABLE goals ADD CONSTRAINT goals_expected_return_pct_check
    CHECK (expected_return_pct IS NULL OR expected_return_pct BETWEEN -20 AND 30);

-- ############################################################
-- 035_import_mappings.sql
-- ############################################################

-- ============================================================================
-- 035_import_mappings.sql — saved column matching for CSV imports
-- ============================================================================
-- import_mappings   how a user's file with given headers maps to Signa's
--                   fields (app/services/import_mapping.py). One per user and
--                   header signature (a hash of the normalized headers); at
--                   most 20 per user (the oldest is replaced). Saved after a
--                   successful real import with "save_mapping".
-- Before it is applied: imports work, mappings just aren't saved or offered.
-- Idempotent.
-- ============================================================================

CREATE TABLE IF NOT EXISTS import_mappings (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        VARCHAR(60) NOT NULL,
    signature   VARCHAR(64) NOT NULL,
    headers     JSONB NOT NULL DEFAULT '[]'::jsonb,
    mapping     JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, signature)
);
CREATE INDEX IF NOT EXISTS idx_import_mappings_user ON import_mappings (user_id, updated_at DESC);
ALTER TABLE public.import_mappings ENABLE ROW LEVEL SECURITY;

-- ############################################################
-- Signa only: drop the brain's feature keys (inserted by 011, they now
-- live in Signa Advisor; the code ignores unknown keys anyway)
-- ############################################################

DELETE FROM access_features WHERE key IN (
  'area.today', 'area.signals', 'area.check', 'area.positions', 'area.performance', 'area.brain',
  'area.how_it_works', 'area.integrations', 'area.logs',
  'action.scan.trigger', 'action.check.run', 'action.check.compare',
  'action.holdings.refresh', 'action.holdings.review', 'action.holdings.allocate',
  'action.positions.manage', 'action.wallet.manage', 'action.brain.edit', 'action.learning.manage',
  'action.settings.ai', 'system.ai'
);
INSERT INTO access_features (key, min_level, description) VALUES
  ('area.admin', 'owner', 'Admin: data usage')
ON CONFLICT (key) DO NOTHING;


-- ############################################################
-- Row Level Security (from 007): every table, no policies. Only the
-- service_role key (the back-end) can read or write; the public anon key
-- gets nothing. RPC functions: service_role only.
-- ############################################################

DO $$
DECLARE r RECORD;
BEGIN
    FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND NOT rowsecurity LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', r.tablename);
    END LOOP;
END $$;

DO $$
BEGIN
    REVOKE EXECUTE ON FUNCTION public.increment_otp_attempts(UUID) FROM PUBLIC, anon, authenticated;
    REVOKE EXECUTE ON FUNCTION public.increment_data_usage(DATE, TEXT, BIGINT) FROM PUBLIC, anon, authenticated;
    REVOKE EXECUTE ON FUNCTION public.signa_new_account_id() FROM PUBLIC, anon, authenticated;
EXCEPTION WHEN undefined_object THEN
    NULL;  -- roles anon/authenticated absent (non-Supabase Postgres)
END $$;

-- ############################################################
-- Checks (run after; each should return what the comment says)
-- ############################################################
-- 38 tables, all with RLS on:
--   SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname = 'public' ORDER BY 1;
-- No brain keys left:
--   SELECT key, min_level FROM access_features ORDER BY 1;
