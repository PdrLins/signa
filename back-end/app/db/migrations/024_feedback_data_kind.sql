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
