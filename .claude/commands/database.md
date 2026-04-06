Show the Signa database schema and query patterns.

## Tables (18 total in Supabase PostgreSQL)

### Auth Tables
- **users** — id (UUID), username (unique), password_hash, telegram_chat_id (unique), is_active, created_at, last_login
- **otp_codes** — id, user_id (FK→users), session_token, code_hash, expires_at, used_at, attempts, created_at. Indexes: session_token, user_id.
- **token_blacklist** — id, token_jti (unique), user_id (FK→users), revoked_at, expires_at. Index: token_jti. Purged daily at 2AM.
- **audit_logs** — id, event_type, user_id, ip_address, user_agent, metadata (JSONB), success, created_at. Indexes: event_type, created_at DESC.
- **brain_sessions** — id, user_id (FK→users), otp_hash, expires_at, used_at, brain_token_jti (unique), ip_address, created_at. Purged daily.

### Business Tables
- **tickers** — id, symbol (unique), name, exchange, bucket, is_active. Partial index on is_active=TRUE.
- **scans** — id, scan_type, started_at, completed_at, tickers_scanned, candidates, signals_found, gems_found, status, error_message, progress_pct, phase, current_ticker, market_regime. Indexes: status, started_at DESC.
- **signals** — id, ticker_id (FK), symbol, action, status, score (0-100), confidence (0-100), is_gem, bucket, asset_type, exchange, price_at_signal, target_price, stop_loss, risk_reward, catalyst, sentiment_score, reasoning, market_regime, catalyst_type, account_recommendation, signal_style, contrarian_score, kelly_recommendation (JSONB), technical_data (JSONB), fundamental_data (JSONB), macro_data (JSONB), grok_data (JSONB), scan_id (FK), company_name, created_at, updated_at. Indexes: (symbol, created_at DESC), scan_id, (is_gem WHERE TRUE), score DESC.
- **portfolio** — id, symbol, bucket, account_type, shares, avg_cost, currency, created_at, updated_at
- **watchlist** — id, symbol (unique), added_at, notes
- **alerts** — id, signal_id (FK), alert_type, message, sent_at, status, created_at. Index: status.
- **positions** — id, symbol, entry_price, entry_date, shares, account_type, bucket, currency, target_price, stop_loss, notes, status, exit_price, exit_date, exit_reason, pnl_amount, pnl_percent, last_signal_score, last_signal_status, last_alerted_pnl, market_regime, created_at, updated_at. Partial index: status='OPEN'.

### Brain Tables
- **investment_rules** — id, name (unique), rule_type, bucket, description, formula, threshold_min/max, threshold_unit, is_blocker, weight_safe, weight_risk, is_active, source_name/url, notes. Indexes: rule_type, is_active.
- **signal_knowledge** — id, topic, key_concept (unique), explanation, formula, example, is_active, source_name/url, notes. Indexes: topic, is_active.

### Learning Tables
- **trade_outcomes** — id, signal_id (FK), symbol, action, score, bucket, signal_date, entry_price, exit_price, days_held, pnl_pct, pnl_amount, target_price, stop_loss, hit_target, hit_stop, signal_correct, market_regime, catalyst_type, notes. Indexes: symbol, signal_date DESC.
- **brain_suggestions** — id, analysis_date, period_start/end, trades_analyzed, win_rate, avg_return_pct, rule_id, rule_name, suggestion_type, current_value (JSONB), proposed_value (JSONB), reasoning, confidence, expected_impact, status, reviewed_at, reviewed_by, rejection_reason. Indexes: status, analysis_date DESC.
- **virtual_trades** — id, symbol, action, entry_price/date/score, exit_price/date/score/action, pnl_pct, pnl_amount, is_win, status, bucket, signal_style. Indexes: symbol, status.
- **ai_usage** — id, provider, call_type, ticker, estimated_cost, success, created_at. Indexes: (provider, created_at DESC), created_at DESC.

## Query Patterns (app/db/queries.py)

### Column Selection
- **List endpoints** use `_SIGNAL_LIST_COLUMNS` — excludes JSONB blobs (technical_data, fundamental_data, macro_data, grok_data)
- **Detail endpoints** use `select("*")` — full data for analysis views
- **Scan lists** use `_SCAN_LIST_COLUMNS`
- **User queries** exclude password_hash except during login

### Caching
- `is_token_blacklisted()` — TTL cached (blacklisted=5min, non-blacklisted=30s)
- `blacklist_token()` — immediately sets cache entry

### Special
- **Atomic OTP increment** — PostgreSQL RPC `increment_otp_attempts(otp_uuid)` prevents race conditions
- **Batch signal insert** — `insert_signals_batch()` strips non-DB fields before insert
- **Deduplication** — `get_signals()` deduplicates by symbol in Python, preferring AI-analyzed signals

## Triggers
- `updated_at` auto-set on: signals, portfolio, positions, investment_rules, signal_knowledge

## Realtime
- `signals`, `alerts`, `positions` tables enabled for Supabase Realtime

## Scheduled Cleanup (2AM ET daily)
- Deletes expired `token_blacklist` entries
- Deletes used or expired `otp_codes`
- Deletes expired `brain_sessions`
- Purges expired entries from all in-memory TTL caches
