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
