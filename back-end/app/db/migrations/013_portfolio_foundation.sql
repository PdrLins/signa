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
    source           VARCHAR(8) NOT NULL DEFAULT 'manual',
    import_batch_id  UUID,
    created_at       TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT transactions_type_check CHECK (
        type IN ('buy', 'sell', 'dividend', 'deposit', 'withdrawal', 'split', 'fee')
    ),
    CONSTRAINT transactions_source_check CHECK (source IN ('manual', 'csv')),
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
