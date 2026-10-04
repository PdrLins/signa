"""Signa back-end (portfolio tracker, Free + Premium) — FastAPI entry point.

Run with: uvicorn main:app --reload --port 8000
"""

import hmac
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from app.api.v1 import auth, health, holdings, portfolio, stats, symbols, tickers, watchlist
from app.api.v1 import dividends as dividends_api
from app.api.v1 import stocks as stocks_api
from app.api.v1 import accounts as accounts_api
from app.api.v1 import notifications as notifications_api
from app.api.v1 import profile as profile_api
from app.api.v1 import transactions as transactions_api
from app.api.v1 import admin_usage as admin_usage_api
from app.api.v1 import alerts as alerts_api
from app.api.v1 import allocation as allocation_api
from app.api.v1 import dividend_summary as dividend_summary_api
from app.api.v1 import events as events_api
from app.api.v1 import feedback as feedback_api
from app.api.v1 import widgets as widgets_api
from app.api.v1 import goals as goals_api
from app.api.v1 import suggestions as suggestions_api
from app.api.v1 import growth as growth_api
from app.api.v1 import public as public_api
from app.api.v1 import account as account_api
from app.api.v1 import portfolio_home as portfolio_home_api
from app.api.v1 import referrals as referrals_api
from app.api.v1 import register as register_api
from app.core.config import settings
from app.core.version import APP_VERSION
from app.core.exceptions import register_exception_handlers
from app.middleware.audit import AuditMiddleware
from app.middleware.auth import AuthMiddleware
from app.middleware.body_limit import BodyLimitMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.notifications.telegram_bot import start_telegram_worker, stop_telegram_worker
from app.scheduler.runner import init_scheduler, start_scheduler, stop_scheduler
from app.services.log_service import init_log_capture


def _check_supabase_key_role() -> None:
    """Warn if the backend is using the anon key (never logs the key itself).

    Every table has RLS on with no policies (app/db/schema.sql): only the
    service_role key can read/write, so an anon key would break the backend.
    """
    from app.core.security import supabase_key_role

    role = supabase_key_role(settings.supabase_key)
    if role == "anon":
        logger.warning(
            "SUPABASE_KEY is an ANON key. The backend must use the service_role key "
            "(Supabase -> Project Settings -> API); with the anon key it can't read any table."
        )
    elif role == "service_role":
        logger.info("Supabase key role: service_role")
    else:
        logger.warning("Could not determine SUPABASE_KEY role (expected service_role)")


def _warn_if_login_otp_disabled() -> None:
    if not settings.login_otp_enabled:
        logger.warning(
            "LOGIN_OTP_ENABLED=false — login is password-only (no Telegram code). "
            "Keep the app bound to 127.0.0.1; do not expose it on a network."
        )


async def _catch_up_missed_jobs() -> None:
    """A minute after startup, run daily jobs missed while the server was off
    or the Mac asleep (app/scheduler/health.py). Never raises."""
    import asyncio

    from app.scheduler import health, jobs
    await asyncio.sleep(60)
    try:
        await health.catch_up({name: getattr(jobs, name) for name in (*health.DAILY, *health.MONTHLY)})
    except Exception as e:
        logger.warning(f"Missed-job catch-up failed: {type(e).__name__}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    init_log_capture()  # first, so the secret scrubber applies to everything below
    from app.core import executors
    executors.install()   # 32 request threads (the default is ~5 on a small server)
    logger.info(f"Starting {settings.app_name}...")
    logger.info(f"Debug mode: {settings.debug}")
    _check_supabase_key_role()
    _warn_if_login_otp_disabled()

    init_scheduler()
    start_scheduler()
    from app.core.executors import spawn
    spawn(_catch_up_missed_jobs())
    start_telegram_worker()
    from app.notifications import telegram_updates
    telegram_updates.start_polling()   # local: bot messages without a public webhook

    yield

    stop_scheduler()
    await telegram_updates.stop_polling()
    await stop_telegram_worker()

    # Close the reusable Telegram HTTP client
    from app.notifications.telegram_bot import _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()

    logger.info(f"{settings.app_name} shutting down")


app = FastAPI(
    title="Signa API",
    description="Signa: portfolio tracker",
    version=APP_VERSION,
    lifespan=lifespan,
    # Disable docs in production
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    openapi_url="/openapi.json" if settings.debug else None,
)

# Middleware. Starlette wraps in reverse order of add_middleware(): the LAST
# one added is the OUTERMOST. Effective request chain:
#     CORS -> GZip -> BodyLimit -> RateLimit -> Audit -> Auth -> routes
# CORS must be outermost so every response — including 401s from
# AuthMiddleware and 429s from RateLimitMiddleware — carries CORS headers
# (otherwise the browser hides the status from the front-end).
app.add_middleware(AuthMiddleware)       # innermost: validates JWT
app.add_middleware(AuditMiddleware)      # logs every request that passed rate limiting
app.add_middleware(RateLimitMiddleware)  # rejects floods before any DB/auth work
app.add_middleware(BodyLimitMiddleware)  # 413 for oversized bodies before anything reads them
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)  # JSON shrinks ~5-10x on phones
app.add_middleware(                      # outermost
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-View-As"],
)

register_exception_handlers(app)

# Routes — all versioned under /api/v1/
api_prefix = "/api/v1"
app.include_router(auth.router, prefix=api_prefix)
app.include_router(tickers.router, prefix=api_prefix)
app.include_router(watchlist.router, prefix=api_prefix)
app.include_router(portfolio.router, prefix=api_prefix)
app.include_router(stats.router, prefix=api_prefix)
app.include_router(health.router, prefix=api_prefix)
app.include_router(holdings.router, prefix=api_prefix)
app.include_router(symbols.router, prefix=api_prefix)
app.include_router(dividends_api.router, prefix=api_prefix)
app.include_router(stocks_api.router, prefix=api_prefix)
app.include_router(profile_api.router, prefix=api_prefix)
app.include_router(notifications_api.router, prefix=api_prefix)
app.include_router(accounts_api.people_router, prefix=api_prefix)
app.include_router(accounts_api.router, prefix=api_prefix)
app.include_router(transactions_api.router, prefix=api_prefix)
app.include_router(portfolio_home_api.router, prefix=api_prefix)
app.include_router(allocation_api.router, prefix=api_prefix)
app.include_router(dividend_summary_api.router, prefix=api_prefix)
app.include_router(dividend_summary_api.income_router, prefix=api_prefix)
app.include_router(events_api.router, prefix=api_prefix)
app.include_router(admin_usage_api.router, prefix=api_prefix)
app.include_router(alerts_api.router, prefix=api_prefix)
from app.api.v1 import two_factor as two_factor_api  # noqa: E402
app.include_router(two_factor_api.router, prefix=api_prefix)
app.include_router(register_api.router, prefix=api_prefix)
app.include_router(referrals_api.router, prefix=api_prefix)
app.include_router(feedback_api.router, prefix=api_prefix)
app.include_router(widgets_api.router, prefix=api_prefix)
app.include_router(goals_api.router, prefix=api_prefix)
app.include_router(suggestions_api.router, prefix=api_prefix)
app.include_router(growth_api.router, prefix=api_prefix)
app.include_router(public_api.router, prefix=api_prefix)
app.include_router(account_api.router, prefix=api_prefix)


@app.post("/api/v1/telegram/webhook")
async def telegram_webhook(request: Request):
    """Receive Telegram bot updates via webhook.

    Validates the secret token header set via setWebhook.
    """
    # Verify webhook secret — reject if secret is not configured or doesn't match
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if not settings.telegram_webhook_secret or not secret or not hmac.compare_digest(secret, settings.telegram_webhook_secret):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": "Forbidden"})

    try:
        data = await request.json()
    except Exception:
        return {"ok": True}
    # Same handler as polling (app/notifications/telegram_updates.py)
    from app.notifications.telegram_updates import process_update
    await process_update(data if isinstance(data, dict) else {})

    return {"ok": True}


@app.get("/")
async def root():
    return {"app": "Signa", "version": APP_VERSION, "docs": "/docs"}
