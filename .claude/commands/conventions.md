Show the coding conventions and patterns for Signa backend.

## Language & Style
- Python 3.12+, modern type hints: `X | None`, `list[str]`, `dict[str, int]`
- f-strings, docstrings on public functions only, no unused imports

## Async Patterns
- All FastAPI routes are `async def`
- Blocking I/O wrapped in `asyncio.to_thread()`: yfinance, Supabase calls in async contexts, Claude/Gemini sync clients
- `asyncio.gather()` for parallel I/O (data fetching, integration health checks)
- `asyncio.Semaphore(10)` for scan concurrency control
- `asyncio.Lock()` for async-safe singletons (budget service)
- `threading.Lock()` for sync-safe shared state (rate limiter, TTLCache)

## Auth Patterns
- AuthMiddleware validates JWT + checks blacklist cache → sets `request.state.user`
- `Depends(get_current_user)` reads `request.state.user` — never re-validates
- `Depends(require_brain_token)` chains to `get_current_user` + validates brain token + enforces JTI
- Brain token created via centralized `security.create_brain_token()`

## Service Layer
- Routes are thin: validate input → call service → return response
- Services contain business logic, call `app/db/queries.py` for DB
- Never call Supabase client directly from routes (except brain.py for session management)

## Caching Pattern
- All in-memory caches use `TTLCache` from `app/core/cache.py` (bounded, thread-safe, auto-expiry)
- Shared instances defined in `cache.py`, imported where needed
- Never use raw `dict` for caching — always TTLCache

## Security Rules
- HTML-escape ALL dynamic values in Telegram messages: `from html import escape`
- Validate tickers: `pattern=r"^[A-Z0-9.\-]{1,10}$"` on Path and Field
- Use `Literal[...]` for enum-like params (scan_type, bucket, action, status, account_type, currency)
- `max_length` on ALL string input fields (500-5000 depending on context)
- `hmac.compare_digest()` for any secret comparison (OTP, webhook)
- All IP extraction through `get_client_ip()` (trusted proxy aware)
- Never log tokens, secrets, or OTP codes

## Database Pattern
- Thread-safe Supabase singleton in `app/db/supabase.py`
- All queries in `app/db/queries.py` — never raw Supabase calls in services
- List endpoints use `_SIGNAL_LIST_COLUMNS` / `_SCAN_LIST_COLUMNS` (no JSONB blobs)
- Detail endpoints use `select("*")`
- Don't mutate input dicts: `update_data = {**data, "key": value}`
- Blacklist lookups are TTL-cached to avoid per-request DB hits

## AI Client Pattern
- Provider router (`app/ai/provider.py`) tries providers in configured order
- Budget checked before every AI call (`budget.can_call()`)
- Retry with exponential backoff on rate limits
- Return structured fallback dict on failure (never crash the pipeline)
- All prompts in `app/ai/prompts.py`

## Rate Limiting Pattern
- Three tiers: AUTH, STRICT, STANDARD
- Thread-safe with `threading.Lock()`
- DB I/O (audit log) always outside the lock
- Brain OTP rate limiting uses TTLCache (auto-expiry, no memory leak)

## Ticker Conventions
- TSX: `.TO` suffix (`SHOP.TO`, `RY.TO`)
- US: plain symbols (`AAPL`, `NVDA`)
- Crypto: `-USD` suffix (`BTC-USD`)
- Always `.upper()` before storing or querying

## File Organization
- One router per domain in `app/api/v1/`
- One service per domain in `app/services/`
- Pydantic models in `app/models/`
- Data ingestion in `app/scanners/`
- AI integrations in `app/ai/`
- Signal logic in `app/signals/`
