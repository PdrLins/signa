Show the Signa database schema and query patterns.

## Tables (9 total in Supabase PostgreSQL)

### Auth Tables
- **users** — id (UUID), username (unique), password_hash, telegram_chat_id, is_active, created_at, last_login
- **otp_codes** — id, user_id (FK→users), session_token, code_hash, expires_at, used_at, attempts, created_at
- **token_blacklist** — id, token_jti (unique), user_id (FK→users), revoked_at, expires_at
- **audit_logs** — id, event_type, user_id, ip_address, user_agent, metadata (JSONB), success, created_at

### Business Tables
- **tickers** — id, symbol (unique), name, exchange (TSX/NYSE/NASDAQ), bucket (SAFE_INCOME/HIGH_RISK), is_active, added_at
- **scans** — id, scan_type, started_at, completed_at, tickers_scanned, signals_found, gems_found, status (RUNNING/COMPLETE/FAILED), error_message
- **signals** — id, ticker_id (FK→tickers), symbol, action (BUY/HOLD/SELL/AVOID), status (CONFIRMED/WEAKENING/CANCELLED/UPGRADED), score (0-100), confidence (0-100), is_gem, bucket, price_at_signal, target_price, stop_loss, risk_reward, catalyst, sentiment_score, reasoning, technical_data (JSONB), fundamental_data (JSONB), macro_data (JSONB), grok_data (JSONB), scan_id (FK→scans), created_at, updated_at
- **portfolio** — id, symbol, bucket, account_type (TFSA/RRSP/TAXABLE), shares, avg_cost, currency (CAD/USD), created_at, updated_at
- **watchlist** — id, symbol (unique), added_at, notes
- **alerts** — id, signal_id (FK→signals), alert_type (GEM/MORNING_DIGEST/ENTRY_WINDOW/PRE_CLOSE/EOD), message, sent_at, status (PENDING/SENT/FAILED), created_at

## Key Indexes
- `signals`: (symbol, created_at DESC), (scan_id), (is_gem WHERE TRUE), (score DESC), (bucket), (action)
- `scans`: (status), (started_at DESC)
- `audit_logs`: (event_type), (user_id), (created_at DESC), (ip_address)
- `otp_codes`: (session_token), (user_id)

## Special Features
- **Realtime:** `signals` and `alerts` tables enabled for Supabase Realtime (frontend polling)
- **Triggers:** `updated_at` auto-set on signals and portfolio updates
- **RPC:** `increment_otp_attempts(otp_uuid)` — atomic increment to prevent race conditions

## Query Helper Patterns (app/db/queries.py)
- All functions are synchronous (Supabase client is sync)
- Thread-safe singleton client in `app/db/supabase.py`
- `get_user_by_username` selects specific columns (excludes password_hash from non-auth queries)
- `get_user_by_id` excludes password_hash entirely
- `insert_signals_batch` for bulk inserts after scans
- `get_latest_signals_map` fetches last 500 signals, deduplicates in Python by symbol

## Schema File
`app/db/schema.sql` — run in Supabase SQL Editor to create all tables, indexes, triggers, and RPC functions.
