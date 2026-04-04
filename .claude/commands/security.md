Show the Signa backend security architecture.

## Authentication Flow
1. `POST /auth/login` — validates username + bcrypt password → generates 6-digit OTP → hashes with HMAC-SHA256 (session_token as salt) → stores in `otp_codes` table → sends OTP via Telegram → returns `session_token`
2. `POST /auth/verify-otp` — looks up OTP by session_token → checks expiration (120s) → checks attempt limit (3 max, atomic increment via PostgreSQL RPC) → constant-time comparison via `hmac.compare_digest` → issues JWT (HS256, 1hr expiry) → blacklists used OTP

## JWT
- Signed with HS256, secret from `JWT_SECRET_KEY` env var (no default — app crashes if missing)
- Payload: `sub` (user_id), `username`, `iat`, `exp`, `jti` (unique ID for blacklisting)
- Validated in `AuthMiddleware` → sets `request.state.user`
- `get_current_user` dependency just reads `request.state.user` (no duplicate validation)
- Logout blacklists the `jti` in `token_blacklist` table
- Refresh issues new JWT and blacklists old one

## Rate Limiting
- In-memory `OrderedDict` with LRU eviction (max 10K entries)
- Only counts **failed** attempts (4xx responses on `/auth/*`)
- 5 login attempts per IP per 15 minutes → IP blocked for 15 minutes
- 3 OTP attempts per session_token → session invalidated

## Security Validators (startup)
- `JWT_SECRET_KEY` cannot be "change-me-in-production" or empty
- `AUTH_ENABLED=false` only works when `DEBUG=true`

## IP Extraction
- Single function `get_client_ip()` in `app/core/utils.py`
- Only trusts `X-Forwarded-For` if direct client IP is in `TRUSTED_PROXIES` list
- Used by all middleware and route handlers

## Input Validation
- Ticker paths: regex `^[A-Z0-9.\-]{1,10}$`
- Portfolio IDs: UUID type
- OTP: exactly 6 digits `^\d{6}$`
- Password: max 128 chars (bcrypt 72-byte limit protection)
- Session token: max 128 chars
- Scan type: `Literal["PRE_MARKET", "MORNING", "PRE_CLOSE", "AFTER_CLOSE"]`
- Bucket: `Literal["SAFE_INCOME", "HIGH_RISK"]`

## Telegram Security
- Webhook validates `X-Telegram-Bot-Api-Secret-Token` header
- Rejects ALL requests when `TELEGRAM_WEBHOOK_SECRET` is not configured
- All dynamic values HTML-escaped in messages (prevents content injection)
- Bot commands validate ticker format before DB operations

## Audit Logging
All events logged to `audit_logs` table: LOGIN_ATTEMPT, OTP_SENT, OTP_VERIFIED, OTP_FAILED, OTP_EXPIRED, TOKEN_ISSUED, TOKEN_REFRESHED, TOKEN_REVOKED, UNAUTHORIZED_ACCESS, RATE_LIMIT_EXCEEDED

## Key Files
- `app/core/security.py` — JWT, bcrypt, OTP hashing
- `app/core/config.py` — startup validators
- `app/middleware/auth.py` — JWT middleware
- `app/middleware/rate_limit.py` — rate limiting
- `app/services/auth_service.py` — login/OTP/token logic
- `app/db/queries.py` — user/OTP/token DB operations
