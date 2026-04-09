Show the Signa database schema and query patterns.

## Tables (20 total in Supabase PostgreSQL)

The 2 newest tables are part of the self-learning loop (Stages 1 + 2.5 of `back-end/docs/learning-loop-implementation-plan.md`): `signal_thinking` (hypotheses under observation) and `knowledge_events` (append-only audit log). See `/brain-learning` for the architecture.

### Auth Tables
- **users** — id (UUID), username (unique), password_hash, telegram_chat_id (unique), is_active, created_at, last_login
- **otp_codes** — id, user_id (FK→users), session_token, code_hash, expires_at, used_at, attempts, created_at. Indexes: session_token, user_id.
- **token_blacklist** — id, token_jti (unique), user_id (FK→users), revoked_at, expires_at. Index: token_jti. Purged daily at 2AM.
- **audit_logs** — id, event_type, user_id, ip_address, user_agent, metadata (JSONB), success, created_at. Indexes: event_type, created_at DESC.
- **brain_sessions** — id, user_id (FK→users), otp_hash, expires_at, used_at, brain_token_jti (unique), ip_address, created_at. Purged daily.

### Business Tables
- **tickers** — id, symbol (unique), name, exchange, bucket, is_active. Partial index on is_active=TRUE.
- **scans** — id, scan_type, started_at, completed_at, tickers_scanned, candidates, signals_found, gems_found, status, error_message, progress_pct, phase, current_ticker, market_regime. Indexes: status, started_at DESC.
- **signals** — id, ticker_id (FK), symbol, action, status, score (0-100), confidence (0-100), is_gem, bucket, asset_type, exchange, price_at_signal, target_price, stop_loss, risk_reward, catalyst, sentiment_score, reasoning, gem_reason, entry_window, market_regime, catalyst_type, account_recommendation, signal_style, contrarian_score, kelly_recommendation (JSONB), technical_data (JSONB), fundamental_data (JSONB), macro_data (JSONB), grok_data (JSONB), scan_id (FK), created_at, updated_at. Indexes: (symbol, created_at DESC), scan_id, (is_gem WHERE TRUE), score DESC. Note: `company_name` is NOT a column — it's passed in signal dicts but stripped before insert.
- **portfolio** — id, symbol, bucket, account_type, shares, avg_cost, currency, created_at, updated_at
- **watchlist** — id, symbol (unique), added_at, notes
- **alerts** — id, signal_id (FK), alert_type, message, sent_at, status, created_at. Index: status.
- **positions** — id, symbol, entry_price, entry_date, shares, account_type, bucket, currency, target_price, stop_loss, notes, status, exit_price, exit_date, exit_reason, pnl_amount, pnl_percent, last_signal_score, last_signal_status, last_alerted_pnl, market_regime, created_at, updated_at. Partial index: status='OPEN'.

### Brain Tables
- **investment_rules** — id, name (unique), rule_type, bucket, description, formula, threshold_min/max, threshold_unit, is_blocker, weight_safe, weight_risk, is_active, source_name/url, notes. Indexes: rule_type, is_active.
- **signal_knowledge** — id, topic, key_concept (unique), explanation, formula, example, is_active, source_name/url, notes, **source_type** ('seed' | 'manual' | 'learned_from_thinking' | 'auto_extracted'), **learned_from_thinking_id** (FK→signal_thinking, nullable — points back to the original hypothesis when this entry came from observation), **invalidation_conditions** (JSONB — when this knowledge stops applying). Indexes: topic, is_active, source_type.
- **signal_thinking** *(NEW — Stage 1)* — id, hypothesis (TEXT), prediction (TEXT), pattern_match (JSONB, NOT NULL), invalidation_conditions (JSONB), created_by, observations_supporting/contradicting/neutral (INT), status ('active' | 'graduated' | 'rejected' | 'stale'), graduation_threshold (default 5), graduated_to (FK→signal_knowledge), last_evaluated_at, notes. Distinct from signal_knowledge: thinking entries are guesses with low statistical support; they get fed to Claude as "Working Hypotheses" with explicit low-confidence framing. Indexes: status (partial WHERE active), created_by.
- **knowledge_events** *(NEW — Stage 2.5, append-only audit log)* — id, event_type ('thinking_created' | 'thinking_observation_added' | 'thinking_graduated' | 'thinking_rejected' | 'thinking_stale' | 'thinking_edited' | 'knowledge_created' | 'knowledge_edited' | 'knowledge_deactivated' | 'thesis_evaluated' | 'thesis_invalidated_exit'), thinking_id (FK, nullable), knowledge_id (FK, nullable), trade_id (FK→virtual_trades, nullable), triggered_by (free-text origin tag), observation_outcome ('supporting' | 'contradicting' | 'neutral' — only for observation events), payload (JSONB snapshot), reason (human-readable), created_at. **NEVER UPDATE, NEVER DELETE** — the whole table IS the audit log. Indexes: thinking_id (partial WHERE NOT NULL), knowledge_id (partial), event_type, created_at DESC.

### Learning Tables
- **trade_outcomes** — id, signal_id (FK, **nullable** — virtual trades pass NULL since they're not tied to one specific signal_id), symbol, action, score, bucket, signal_date, entry_price, exit_price, days_held, pnl_pct, pnl_amount, target_price, stop_loss, hit_target, hit_stop, signal_correct, market_regime, catalyst_type, notes. Indexes: symbol, signal_date DESC.
- **brain_suggestions** — id, analysis_date, period_start/end, trades_analyzed, win_rate, avg_return_pct, rule_id, rule_name, suggestion_type, current_value (JSONB), proposed_value (JSONB), reasoning, confidence, expected_impact, status, reviewed_at, reviewed_by, rejection_reason. Indexes: status, analysis_date DESC.
- **virtual_trades** — id, symbol, action, entry_price/date/score, exit_price/date/score/action, pnl_pct, pnl_amount, is_win, status, bucket, signal_style, source ('brain' | 'watchlist'), target_price, stop_loss, exit_reason ('SIGNAL' | 'ROTATION' | 'STOP_HIT' | 'TARGET_HIT' | 'PROFIT_TAKE' | 'TIME_EXPIRED' | 'THESIS_INVALIDATED' | 'WATCHDOG_FORCE_SELL' | 'WATCHDOG_EXIT'), entry_tier (1=validated/2=low_confidence/3=tech_only), trust_multiplier (1.0 or 0.5), pending_review_at/action/score/reason, **market_regime** (snapshotted at insert), **entry_thesis** (TEXT — Claude's reasoning verbatim, captured at brain entry for Stage 6), **entry_thesis_keywords** (JSONB — structured snapshot for the re-eval prompt diff), **thesis_last_checked_at** (TIMESTAMPTZ), **thesis_last_status** ('valid' | 'weakening' | 'invalid' | NULL), **thesis_last_reason** (TEXT). Indexes: symbol, status, source, entry_tier (partial WHERE not null), pending_review_at (partial), thesis_last_status (partial WHERE status='OPEN').
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
