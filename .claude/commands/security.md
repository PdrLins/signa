Show the Signa backend security architecture.

## Authentication Flow
1. `POST /auth/login` — bcrypt password check → 6-digit OTP → HMAC-SHA256 hash (session_token as salt) → stored in `otp_codes` → sent via Telegram → returns `session_token`
2. `POST /auth/verify-otp` — lookup by session_token → check expiry (120s) → check attempts (3 max, atomic RPC increment) → constant-time `hmac.compare_digest` → issue JWT → blacklist OTP
3. JWT: PyJWT HS256, 1hr expiry, payload: `sub`, `username`, `iat`, `exp`, `jti`. Refresh blacklists old token.

## Brain Editor 2FA (second layer on top of JWT)
1. `POST /brain/challenge` — rate-limited (3/15min per user via TTLCache) → OTP sent to user's Telegram (from DB, not env var) → stored in `brain_sessions`
2. `POST /brain/verify` — validates OTP → issues brain token (separate secret, 15min expiry) → JTI mandatory, verified against `brain_sessions`
3. All brain write endpoints require both JWT + `X-Brain-Token` header via `require_brain_token` dependency

## Rate Limiting (app/middleware/rate_limit.py)
Three tiers, all IP-based, thread-safe with `threading.Lock`:
| Tier | Paths | Limit | Window | Notes |
|------|-------|-------|--------|-------|
| AUTH | /auth/login, /auth/verify-otp | 5 | 15 min | Failures only, IP blocked on exceed |
| STRICT | /scans/trigger, /learning/analyze, /learning/outcomes | 3 | 5 min | All requests counted |
| STANDARD | All other protected endpoints | 60 | 1 min | All requests counted |

Lock held only for dict operations — DB audit log and response sent outside lock.

## Token Blacklist
- Checked on every authenticated request via `is_token_blacklisted()`
- TTL-cached: blacklisted tokens cached 5min, non-blacklisted 30s
- Expired tokens purged by 2AM daily cleanup job

## Startup Validators (app/core/config.py)
- `JWT_SECRET_KEY` cannot be empty or "change-me-in-production"
- `AUTH_ENABLED=false` only allowed when `DEBUG=true`
- `BRAIN_TOKEN_SECRET` required when auth enabled
- `CORS_ORIGINS=["*"]` blocked in production

## Input Validation
- Ticker paths: regex `^[A-Z0-9.\-]{1,10}$` (Path + Field)
- IDs: UUID type
- OTP: `^\d{6}$`
- Enum fields: `Literal[...]` for scan_type, bucket, action, status, account_type, currency
- Text fields: `max_length` on all string inputs (500-5000 depending on field)
- Budget: Pydantic model with `ge`/`le` constraints

## Webhook Security
- Validates `X-Telegram-Bot-Api-Secret-Token` via `hmac.compare_digest` (timing-safe)
- Rejects ALL requests when `TELEGRAM_WEBHOOK_SECRET` not configured (empty = rejected)
- Only responds to messages from `settings.telegram_chat_id`

## WebSocket Security (logs/stream)
- Requires both JWT (`?jwt=`) AND brain token (`?token=`) as query params
- Validates both tokens and verifies user match before accepting connection

## Audit Events (app/models/audit.py)
LOGIN_ATTEMPT, OTP_SENT/VERIFIED/FAILED/EXPIRED, TOKEN_ISSUED/REFRESHED/REVOKED, UNAUTHORIZED_ACCESS, RATE_LIMIT_EXCEEDED, BRAIN_CHALLENGE_SENT, BRAIN_ACCESS_GRANTED/DENIED/LOCKED, BRAIN_RULE_UPDATED, BRAIN_KNOWLEDGE_UPDATED, BUDGET_UPDATED, CONFIG_UPDATED, LEARNING_ANALYSIS_RUN, LEARNING_SUGGESTION_APPROVED/REJECTED/APPLIED

## Caching Architecture (app/core/cache.py)
All in-memory caches are bounded `TTLCache` instances (max_size + auto-expiry):
| Cache | Max Size | TTL | Purpose |
|-------|----------|-----|---------|
| blacklist_cache | 5000 | 30s | Token blacklist lookups |
| stats_cache | 100 | 30s | Daily stats queries |
| price_cache | 500 | 60s | yfinance price data |
| brain_challenge_cache | 500 | 15min | Brain OTP rate limiting |
| brain_otp_attempt_cache | 500 | 15min | Brain OTP attempt tracking |
| brain_lockout_cache | 500 | 15min | Brain lockout tracking |

Plus service-level caches: `price_cache.py` (TTLCache, 500, 5min), `knowledge_service.py` (TTLCache, 200, 5min).

## Key Files
- `app/core/security.py` — JWT (PyJWT), bcrypt, OTP, create_brain_token
- `app/core/cache.py` — TTLCache + shared instances
- `app/middleware/auth.py` — JWT middleware + blacklist check
- `app/middleware/brain_auth.py` — Brain 2FA dependency
- `app/middleware/rate_limit.py` — Tiered rate limiting
- `app/services/auth_service.py` — Login/OTP/token logic
