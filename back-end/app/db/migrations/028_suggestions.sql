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
