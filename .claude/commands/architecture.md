Show the Signa backend architecture and how modules connect.

## Module Map

### Core
```
main.py                         → FastAPI app, lifespan, middleware stack, Telegram webhook
app/core/config.py              → Pydantic Settings from .env, startup validators
app/core/security.py            → JWT (PyJWT), bcrypt, OTP (HMAC-SHA256), create_brain_token
app/core/cache.py               → TTLCache class + shared instances (blacklist, stats, price, brain)
app/core/dependencies.py        → get_current_user reads request.state.user
app/core/exceptions.py          → AuthenticationError, RateLimitExceeded, OTPExpired/Invalid
app/core/utils.py               → get_client_ip (trusted proxy aware), validate_ticker (regex)
```

### Middleware (outermost ��� innermost)
```
CORSMiddleware → AuditMiddleware → RateLimitMiddleware → AuthMiddleware → Routes
```
- **AuditMiddleware** — logs method/path/status/duration/IP/username
- **RateLimitMiddleware** — tiered: AUTH (5/15min failures), STRICT (3/5min), STANDARD (60/min). Thread-safe with lock.
- **AuthMiddleware** — JWT validation, token blacklist check (cached), sets request.state.user

### API Routes (app/api/v1/)
```
auth.py       → login, verify-otp, logout, refresh
signals.py    → list signals, gems, ticker history
tickers.py    → ticker detail, chart (OHLCV), ticker signals
scans.py      → scan history, today's slots, trigger (with concurrency guard), progress polling
watchlist.py  → CRUD
portfolio.py  → CRUD
positions.py  → open, close, update, history
stats.py      → daily stats, recent alerts, virtual portfolio, positions summary
brain.py      → highlights, insights, 2FA challenge/verify, rules CRUD, knowledge CRUD, audit
learning.py   → trade outcomes, AI analysis, suggestions approve/reject/apply
logs.py       → recent logs (REST), real-time stream (WebSocket, requires JWT + brain token)
health.py     → health check, parallel integration checks, budget CRUD, AI config CRUD
```

### AI System (app/ai/)
```
provider.py        → Fallback router: synthesis (claude→gemini), sentiment (grok→gemini). Budget-checked.
claude_client.py   → Anthropic synthesis: technical+fundamental+macro+sentiment → BUY/HOLD/SELL/AVOID
grok_client.py     → xAI sentiment: X/Twitter analysis → score, label, confidence, themes, news
gemini_client.py   → Google free tier fallback for both synthesis and sentiment. Rate-limited semaphore.
signal_engine.py   → Scoring (bucket-specific weights), GEM detection (5 conditions), blockers (5 checks), status tracking
prompts.py         → All prompt templates + format_technicals/fundamentals/macro/sentiment + clean_json_response
```

### Signals (app/signals/)
```
regime.py      → Market regime from VIX: TRENDING (<20), VOLATILE (20-30), CRISIS (>30)
kelly.py       → Fractional Kelly (25%) position sizing, score→win_rate mapping, regime adjustments
contrarian.py  → Deep-value detector: below SMA200 + oversold RSI + volume + MACD turning. 3/4 conditions = contrarian.
```

### Scanners (app/scanners/)
```
universe.py        → ~141 tickers: 35 TSX, 43 NYSE, 48 NASDAQ, 15 crypto
market_scanner.py  → yfinance: price history, fundamentals, bulk screening, current price. Cached 60s/5min.
macro_scanner.py   → FRED (fed funds, 10Y, CPI, unemployment) + VIX. Classifies favorable/neutral/hostile.
indicators.py      → RSI(14), MACD(12,26,9), Bollinger(20,2), SMA(50/200), ATR(14), volume Z-score, momentum
prefilter.py       → ~141 → ~50 candidates: volume >= 200K, |change| > 1%, price > $1, 5 crypto slots reserved
```

### Services (app/services/)
```
scan_service.py        → Full scan orchestrator: two-pass pipeline, progress tracking
auth_service.py        → Login, OTP send/verify, JWT issue/revoke/refresh
signal_service.py      → Signal queries + price enrichment
position_service.py    → Position CRUD + monitor (stop-loss, target, P&L milestones, signal weakening)
learning_service.py    → Record outcomes → weekly AI analysis → brain suggestions
knowledge_service.py   → Investment rules + signal knowledge from DB (TTLCache, 5min)
budget_service.py      → Per-provider daily+monthly spend caps, async-safe singleton
stats_service.py       → Daily stats with targeted DB queries (cached 30s)
watchlist_service.py   → Watchlist CRUD
price_cache.py         → Batch yfinance price enrichment (TTLCache, 5min)
virtual_portfolio.py   → Virtual trade tracking for brain accuracy
log_service.py         → In-memory log buffer + WebSocket subscriber queue
```

### Scheduler (app/scheduler/)
```
runner.py  → APScheduler: 4 daily scans (6AM, 10AM, 3PM, 4:30PM ET) + 2AM cleanup job
jobs.py    → Async scan wrappers + cleanup_expired_tokens (purges blacklist, OTPs, brain sessions)
```

### Notifications (app/notifications/)
```
telegram_bot.py   → Send messages, handle 10 bot commands, HTML-escaped. Reusable httpx client.
messages.py       → Bilingual templates (EN/PT): OTP, GEM alert, scan digest, watchlist alert, position alerts, brain OTP
dispatcher.py     → Process pending alert queue from DB
```

### Database (app/db/)
```
supabase.py    → Thread-safe singleton client
queries.py     → All DB operations. Light columns for lists, full select for detail. Blacklist cached.
schema.sql     → 18 tables, indexes, triggers, RPC functions, Realtime
seed_brain.py  → Seeds investment_rules + signal_knowledge tables
```

## Request Flow
```
Request → CORS → Audit (log) → RateLimit (tiered) → Auth (JWT + blacklist cache)
  → Route �� Depends(get_current_user) → Service → queries.py → Supabase �� Response
```

## Scan Flow
```
Scheduler/Trigger → scan_service.run_scan()
  → Universe (141) → Bulk screen → Prefilter (~50) → Macro snapshot + Regime
  → Pass 1: All candidates prescored (technicals + fundamentals, FREE)
  → Pass 2: Top 15 get AI (sentiment + synthesis, PAID, budget-checked)
  → Bottom 35 stored with tech-only scores
  → Batch insert → GEM alerts → Watchlist sell alerts → Scan digest → Position monitor
```
