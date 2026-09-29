"""Signa Backend — FastAPI application entry point.

Run with: uvicorn main:app --reload --port 8000
"""

import asyncio
import hmac
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from app.api.v1 import auth, brain, health, learning, logs, portfolio, positions, scans, signals, stats, tickers, wallet, watchlist
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.middleware.audit import AuditMiddleware
from app.middleware.auth import AuthMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.notifications.telegram_bot import handle_command, send_message, start_telegram_worker, stop_telegram_worker
from app.scheduler.runner import init_scheduler, start_scheduler, stop_scheduler
from app.services.log_service import init_log_capture


def _check_supabase_key_role() -> None:
    """Warn if the backend is using the anon key (never logs the key itself).

    Migration 007 enables RLS with no policies; after it is applied only the
    service_role key can read/write, so an anon key would break the backend.
    Conversely, with an anon key and no RLS, the tables are world-readable.
    """
    from app.core.security import supabase_key_role

    role = supabase_key_role(settings.supabase_key)
    if role == "anon":
        logger.warning(
            "SUPABASE_KEY is an ANON key. The backend must use the service_role key. "
            "Do NOT apply migration 007_enable_rls.sql until SUPABASE_KEY is the "
            "service_role key, or the backend will lose database access."
        )
    elif role == "service_role":
        logger.info("Supabase key role: service_role")
    else:
        logger.warning("Could not determine SUPABASE_KEY role (expected service_role)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    init_log_capture()  # first, so the secret scrubber applies to everything below
    logger.info(f"Starting {settings.app_name}...")
    logger.info(f"Debug mode: {settings.debug}")
    _check_supabase_key_role()

    init_scheduler()
    start_scheduler()
    start_telegram_worker()

    # Catch up any missed scans (e.g., app was down during scheduled time)
    from app.scheduler.jobs import catch_up_missed_scans
    asyncio.ensure_future(catch_up_missed_scans())

    yield

    stop_scheduler()
    await stop_telegram_worker()

    # Close the reusable Telegram HTTP client
    from app.notifications.telegram_bot import _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()

    logger.info(f"{settings.app_name} shutting down")


app = FastAPI(
    title="Signa API",
    description="AI Investment Signal Engine",
    version="1.0.0",
    lifespan=lifespan,
    # Disable docs in production
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    openapi_url="/openapi.json" if settings.debug else None,
)

# Middleware. Starlette wraps in reverse order of add_middleware(): the LAST
# one added is the OUTERMOST. Effective request chain:
#     CORS -> RateLimit -> Audit -> Auth -> routes
# CORS must be outermost so every response — including 401s from
# AuthMiddleware and 429s from RateLimitMiddleware — carries CORS headers
# (otherwise the browser hides the status from the front-end).
app.add_middleware(AuthMiddleware)       # innermost: validates JWT
app.add_middleware(AuditMiddleware)      # logs every request that passed rate limiting
app.add_middleware(RateLimitMiddleware)  # rejects floods before any DB/auth work
app.add_middleware(                      # outermost
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Brain-Token"],
)

register_exception_handlers(app)

# Routes — all versioned under /api/v1/
api_prefix = "/api/v1"
app.include_router(auth.router, prefix=api_prefix)
app.include_router(signals.router, prefix=api_prefix)
app.include_router(tickers.router, prefix=api_prefix)
app.include_router(positions.router, prefix=api_prefix)
app.include_router(watchlist.router, prefix=api_prefix)
app.include_router(portfolio.router, prefix=api_prefix)
app.include_router(scans.router, prefix=api_prefix)
app.include_router(stats.router, prefix=api_prefix)
app.include_router(brain.router, prefix=api_prefix)
app.include_router(learning.router, prefix=api_prefix)
app.include_router(logs.router, prefix=api_prefix)
app.include_router(health.router, prefix=api_prefix)
app.include_router(wallet.router, prefix=api_prefix)


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
        message = data.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "")

        # Only respond to the bot owner
        if str(chat_id) != settings.telegram_chat_id:
            return {"ok": True}

        if text.startswith("/"):
            parts = text.split(maxsplit=1)
            command = parts[0].lstrip("/").split("@")[0]
            args = parts[1] if len(parts) > 1 else ""

            # Look up the user by their Telegram chat ID
            from app.db import queries as db_queries
            tg_user = db_queries.get_user_by_telegram_chat_id(str(chat_id))
            user_id = tg_user["id"] if tg_user else ""

            response_text = await handle_command(command, args, user_id=user_id)

            if chat_id and response_text:
                await send_message(str(chat_id), response_text)

    except Exception:
        logger.exception("Telegram webhook error")

    return {"ok": True}


@app.get("/")
async def root():
    return {"app": "Signa", "version": "1.0.0", "docs": "/docs"}
