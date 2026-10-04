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
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_goals_user ON goals (user_id, created_at);

DROP TRIGGER IF EXISTS goals_updated_at ON goals;
CREATE TRIGGER goals_updated_at BEFORE UPDATE ON goals
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

ALTER TABLE public.goals ENABLE ROW LEVEL SECURITY;

INSERT INTO access_features (key, min_level, description) VALUES
  ('feature.unlimited_goals', 'premium', 'Unlimited goals (free: 1)')
ON CONFLICT (key) DO NOTHING;
