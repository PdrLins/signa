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
