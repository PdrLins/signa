Show the coding conventions and patterns for Signa backend.

## Language & Style
- Python 3.12+
- Modern type hints: `X | None` not `Optional[X]`, `list[str]` not `List[str]`
- f-strings for formatting
- Docstrings on public functions only
- No unused imports

## Async Patterns
- All FastAPI routes are `async def`
- AI clients use `asyncio.Lock()` for async-safe singletons
- yfinance calls wrapped in `asyncio.to_thread()` (sync library)
- DB queries are synchronous (Supabase client limitation) — called directly from async functions
- `asyncio.gather()` for parallel I/O (data fetching, API calls)
- `asyncio.Semaphore` for concurrency control (10 concurrent API calls per scan)

## Auth Pattern
- Middleware (`app/middleware/auth.py`) validates JWT and sets `request.state.user`
- Dependency (`app/core/dependencies.py`) reads `request.state.user` — never re-validates
- No duplicate auth checks

## Service Layer Pattern
- Routes are thin: validate input → call service → return response
- Services contain business logic
- Services call `app/db/queries.py` for database operations
- Exception: portfolio routes currently bypass service layer (known tech debt)

## Security Rules
- HTML-escape ALL dynamic values in Telegram messages: `from html import escape`
- Validate ticker format with regex: `^[A-Z0-9.\-]{1,10}$`
- Use `Path(pattern=...)` for ticker path params, `UUID` type for ID path params
- Use `Literal[...]` for enum-like query params (scan_type, bucket)
- Never log tokens or secrets — generic messages only
- Use `hmac.compare_digest()` for any secret comparison
- All IP extraction goes through `app/core/utils.get_client_ip()` (trusted proxy aware)

## AI Client Pattern
- Async-safe singleton with `asyncio.Lock()` + double-checked locking
- Retry loop with exponential backoff (2^attempt seconds) on rate limit errors
- Immediate break on 4xx API errors and JSON parse errors
- Return structured fallback dict on failure (never crash the pipeline)
- Shared `clean_json_response()` in `app/ai/prompts.py`

## Config Pattern
- All env vars in `app/core/config.py` via `pydantic-settings`
- Startup validators prevent insecure defaults (JWT secret, auth flag)
- Access via `from app.core.config import settings`

## Database Pattern
- Thread-safe singleton client in `app/db/supabase.py`
- All queries in `app/db/queries.py` — never raw Supabase calls in services/routes
- Don't mutate input dicts: `update_data = {**data, "key": value}`
- Select specific columns where possible (never `SELECT *` for user queries that don't need password_hash)

## Ticker Conventions
- TSX stocks use `.TO` suffix: `SHOP.TO`, `RY.TO`
- US stocks use plain symbols: `AAPL`, `NVDA`
- Always call `.upper()` before storing or querying
- Validate format before any DB or API operation

## File Organization
- One router per domain in `app/api/v1/`
- One service per domain in `app/services/`
- Pydantic models in `app/models/` (grouped by domain)
- Data ingestion in `app/scanners/`
- AI integrations in `app/ai/`
- All prompts in `app/ai/prompts.py`
