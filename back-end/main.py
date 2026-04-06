"""Signa Backend — FastAPI application entry point.

Run with: uvicorn main:app --reload --port 8000
"""

import hmac
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from app.api.v1 import auth, brain, health, learning, logs, portfolio, positions, scans, signals, stats, tickers, watchlist
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.middleware.audit import AuditMiddleware
from app.middleware.auth import AuthMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.notifications.telegram_bot import handle_command, send_message
from app.scheduler.runner import init_scheduler, start_scheduler, stop_scheduler
from app.services.log_service import init_log_capture


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info(f"Starting {settings.app_name}...")
    logger.info(f"Auth enabled: {settings.auth_enabled}")
    logger.info(f"Debug mode: {settings.debug}")

    init_log_capture()
    init_scheduler()
    start_scheduler()

    yield

    stop_scheduler()

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

# Middleware (outermost first)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuditMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(AuthMiddleware)

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
