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
