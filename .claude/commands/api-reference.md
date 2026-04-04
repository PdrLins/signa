Show the full API endpoint reference for Signa backend.

## Public Endpoints (no auth)
- `POST /api/v1/auth/login` — Body: `{ username, password }` → `{ message, session_token }`
- `POST /api/v1/auth/verify-otp` — Body: `{ session_token, otp_code }` → `{ access_token, token_type, expires_in }`
- `GET /api/v1/health` — `{ status, app, uptime_seconds, scheduler_running }`

## Protected Endpoints (require `Authorization: Bearer <token>`)

### Auth
- `POST /api/v1/auth/logout` → `{ message }`
- `POST /api/v1/auth/refresh` → `{ access_token, token_type, expires_in }`

### Signals
- `GET /api/v1/signals?bucket=SAFE_INCOME|HIGH_RISK&min_score=0-100&limit=1-200` → `{ signals[], count }`
- `GET /api/v1/signals/gems?limit=1-100` → `{ signals[], count }`
- `GET /api/v1/signals/{ticker}?limit=1-100` — ticker regex: `^[A-Z0-9.\-]{1,10}$` → `{ signals[], count }`

### Scans
- `GET /api/v1/scans?limit=1-100` → `{ scans[], count }`
- `POST /api/v1/scans/trigger?scan_type=PRE_MARKET|MORNING|PRE_CLOSE|AFTER_CLOSE` — runs in BackgroundTasks → `{ status, message }`

### Watchlist
- `GET /api/v1/watchlist` → `{ items[], count }`
- `POST /api/v1/watchlist/{ticker}` — 201 Created → item
- `DELETE /api/v1/watchlist/{ticker}` → `{ message }`

### Portfolio
- `GET /api/v1/portfolio` → `{ items[], count }`
- `POST /api/v1/portfolio` — Body: `{ symbol, bucket, account_type, shares, avg_cost, currency }` → item
- `PUT /api/v1/portfolio/{id}` — id is UUID → item
- `DELETE /api/v1/portfolio/{id}` → `{ message }`

### Webhook
- `POST /api/v1/telegram/webhook` — validates `X-Telegram-Bot-Api-Secret-Token` header → `{ ok: true }`

## Key Files
- Routes: `app/api/v1/auth.py`, `signals.py`, `watchlist.py`, `portfolio.py`, `scans.py`, `health.py`
- Models: `app/models/auth.py`, `signals.py`, `watchlist.py`, `portfolio.py`
- Webhook handler: `main.py` line 70
