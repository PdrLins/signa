-- ============================================================
-- Positions table — track open/closed trades
-- Run this in Supabase SQL Editor after the main schema.
-- ============================================================

CREATE TABLE IF NOT EXISTS positions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol          VARCHAR NOT NULL,
    entry_price     DECIMAL NOT NULL,
    entry_date      TIMESTAMPTZ DEFAULT now(),
    shares          DECIMAL NOT NULL,
    account_type    VARCHAR,               -- TFSA, RRSP, TAXABLE
    bucket          VARCHAR,               -- SAFE_INCOME, HIGH_RISK
    currency        VARCHAR DEFAULT 'CAD', -- CAD, USD
    target_price    DECIMAL,
    stop_loss       DECIMAL,
    notes           TEXT,

    -- Status
    status          VARCHAR DEFAULT 'OPEN',  -- OPEN, CLOSED, STOPPED_OUT
    exit_price      DECIMAL,
    exit_date       TIMESTAMPTZ,
    exit_reason     VARCHAR,  -- USER_CLOSE, TARGET_HIT, STOP_HIT, SIGNAL_WEAKENED

    -- P&L (computed on close)
    pnl_amount      DECIMAL,
    pnl_percent     DECIMAL,

    -- Tracking
    last_signal_score   INT,
    last_signal_status  VARCHAR,
    last_alerted_pnl    DECIMAL,  -- Last P&L % that triggered an alert (avoid spam)

    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_positions_status ON positions (status) WHERE status = 'OPEN';
CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions (symbol);

DROP TRIGGER IF EXISTS positions_updated_at ON positions;
CREATE TRIGGER positions_updated_at
    BEFORE UPDATE ON positions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- Enable realtime for positions
DO $$
BEGIN
    ALTER PUBLICATION supabase_realtime ADD TABLE positions;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
