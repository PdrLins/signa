-- ============================================================================
-- 007_enable_rls.sql — Enable Row Level Security on every Signa table
-- ============================================================================
--
--   !!!  READ BEFORE APPLYING  !!!
--
--   Apply this ONLY after confirming the backend's SUPABASE_KEY is the
--   **service_role** key (Supabase dashboard -> Project Settings -> API ->
--   "service_role" secret). The service_role key BYPASSES RLS; the anon key
--   does NOT. This migration adds NO policies, so once it is applied any
--   client using the anon key (including the backend, if misconfigured)
--   loses ALL read/write access to these tables and the app will break.
--
--   How to check: the backend logs a WARNING at startup if the configured
--   SUPABASE_KEY is an anon key. You can also base64-decode the middle
--   segment of the key and check that "role" is "service_role".
--
--   Order:
--     1. Put the service_role key in back-end/.env (SUPABASE_KEY=...).
--     2. Restart the backend, confirm no "anon" warning and that it works.
--     3. Run this file in the Supabase SQL editor.
--     4. Verify: the public anon key can no longer read any table.
--
-- Why: Supabase exposes every table in the `public` schema through PostgREST
-- to anyone holding the anon key (which is public by design). Without RLS
-- those tables (users.password_hash, otp_codes, audit_logs, trades...) are
-- readable/writable by anyone who learns the project URL + anon key.
--
-- Idempotent: safe to run multiple times; missing tables are skipped.
-- ============================================================================

-- 1. Explicit list of tables from schema.sql and migrations 001-006.
DO $$
DECLARE
    t TEXT;
    tables TEXT[] := ARRAY[
        -- schema.sql
        'users', 'otp_codes', 'token_blacklist', 'audit_logs',
        'tickers', 'scans', 'signals', 'portfolio', 'watchlist', 'alerts',
        'positions', 'brain_sessions', 'investment_rules', 'signal_knowledge',
        'signal_thinking', 'knowledge_events', 'trade_outcomes',
        'brain_suggestions', 'daily_learning_runs', 'user_settings',
        'virtual_trades', 'brain_wallet', 'wallet_transactions',
        'ai_retry_queue', 'virtual_snapshots', 'ai_usage', 'watchdog_events',
        -- migration 005
        'brain_decisions',
        -- referenced by code (log persistence), may not exist
        'app_logs'
    ];
BEGIN
    FOREACH t IN ARRAY tables LOOP
        IF EXISTS (
            SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = t
        ) THEN
            EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
        END IF;
    END LOOP;
END $$;

-- 2. Catch-all: any other table in `public` (e.g. created by migrations
--    005/006 or later) also gets RLS. The backend uses service_role and is
--    unaffected; PostgREST anon/authenticated roles get no access.
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public' AND NOT rowsecurity
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', r.tablename);
    END LOOP;
END $$;

-- 3. RPC functions are callable via PostgREST by anon by default.
--    Only the backend (service_role) should call them.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'increment_otp_attempts') THEN
        REVOKE EXECUTE ON FUNCTION public.increment_otp_attempts(UUID) FROM PUBLIC, anon, authenticated;
    END IF;
EXCEPTION WHEN undefined_object THEN
    NULL;  -- roles anon/authenticated absent (non-Supabase Postgres)
END $$;

-- Verification query (should return zero rows after applying):
--   SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND NOT rowsecurity;
