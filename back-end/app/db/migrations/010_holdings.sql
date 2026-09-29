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
--   The old `portfolio` table (schema.sql §8) was never used by the UI (the
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

-- updated_at trigger (update_updated_at() is defined in schema.sql)
DROP TRIGGER IF EXISTS holdings_updated_at ON holdings;
CREATE TRIGGER holdings_updated_at BEFORE UPDATE ON holdings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- "Review all" rate limit (settings.holdings_review_all_days)
ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS holdings_review_all_at TIMESTAMPTZ;

-- Carry over any rows from the unused legacy `portfolio` table.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'portfolio') THEN
        INSERT INTO holdings (user_id, symbol, input_symbol, currency, shares, avg_cost, account, created_at)
        SELECT DISTINCT ON (p.user_id, upper(p.symbol))
               p.user_id,
               upper(p.symbol),
               upper(p.symbol),
               p.currency,
               CASE WHEN p.shares > 0 THEN p.shares END,
               CASE WHEN p.avg_cost > 0 THEN p.avg_cost END,
               CASE p.account_type
                    WHEN 'TFSA' THEN 'TFSA'
                    WHEN 'RRSP' THEN 'RRSP'
                    WHEN 'TAXABLE' THEN 'NON_REGISTERED'
                    ELSE NULL END,
               p.created_at
          FROM portfolio p
         WHERE p.user_id IS NOT NULL AND p.symbol IS NOT NULL
         ORDER BY p.user_id, upper(p.symbol), p.created_at
        ON CONFLICT (user_id, symbol) DO NOTHING;
    END IF;
END $$;

ALTER TABLE public.holdings ENABLE ROW LEVEL SECURITY;
