# Signa Database

35 tables on Supabase (PostgreSQL). A new project is created by running
`schema.sql` once in the SQL Editor (idempotent). Every table has Row Level
Security on with no policies: only the back-end's service_role key can read
or write. Database changes: add `migrations/0NN_name.sql` (next free number),
run it, and fold it into `schema.sql`. `migrations/010`–`031` are history and
already included in `schema.sql`.

Access goes through `queries.py` and the services (supabase-py / PostgREST).

## Users and sign-in

| Table | Purpose |
|-------|---------|
| **users** | Accounts: username, bcrypt hash, `access_level` (free / premium / owner), `account_id` (8-char invite code), `referred_by`, optional email, two-step method + Telegram chat, `last_seen_at`. |
| **auth_sessions** / **auth_refresh_tokens** | One session per signed-in device; iOS rotating refresh tokens (hash only). |
| **otp_codes** | Sign-in / reset / email codes (hash, expiry, attempts). |
| **two_factor_setup** | Pending Telegram two-step setup. |
| **token_blacklist** | Revoked access tokens until they expire. |
| **referrals** | Who invited whom; `rewarded` after the invited user's first followed stock. |
| **access_features** | Plan level per feature key (overrides the defaults in `app/core/access.py`). |
| **audit_logs** | Security events (sign-in, failures, sign-ups). |
| **feedback_reports** | Problem reports and ideas sent from the apps (owner triages: status + note). |

## Portfolio (per user)

| Table | Purpose |
|-------|---------|
| **user_settings** | Theme, language, profile (country, home currency, tax view, compare index, allocation targets). |
| **portfolio_people** / **accounts** | People and their accounts (optional tax type). |
| **holdings** | One row per (account, symbol): shares, average cost, `holding_status` (daily price snapshot). |
| **transactions** | Buys, sells, dividends, deposits… (CSV import batches). |
| **watchlist** | Followed symbols that aren't held. |
| **price_alerts** | Above / below price alerts. |
| **portfolio_snapshots** | Daily value per user and account. |
| **income_forecast_snapshots** | Daily forward dividend forecast (for "why your income changed"). |
| **push_devices** | iOS push tokens per signed-in install (APNs). |
| **notification_prefs**, **telegram_links**, **telegram_link_codes**, **notification_deliveries** | Premium Telegram notifications: preferences, connected chat, link codes, de-dup log. |
| **goals** | Investing goals (portfolio value or monthly dividend income). |
| **portfolio** | Legacy, unused. |

## Shared

| Table | Purpose |
|-------|---------|
| **quotes** | Latest price per followed symbol (regular + extended hours). |
| **check_status_daily** | Daily Signa check status per followed symbol. |
| **data_usage_daily** | Usage counters (provider calls, refreshed symbols). |
| **symbol_profiles** | What a symbol is (sector, industry, country, size, dividend yield) for suggestions. |
| **reserved_usernames** | Usernames of deleted accounts, held 90 days. |
| **job_runs** | Last start / success / error of each scheduled job (owner report, alerts, catch-up). |
| **signup_sources** | Where each user came from: campaign tags, "how did you hear", Apple Search Ads ids. |
| **user_activity_days** | One row per user per day they used the app (week-2 retention). |
| **symbol_cofollows** | Anonymous "followed together" counts (pairs shared by 5+ users, no user ids). |

## Functions

`update_updated_at()` (trigger), `increment_otp_attempts(uuid)`,
`increment_data_usage(date, text, bigint)`, `signa_new_account_id()`; all
callable by service_role only.
