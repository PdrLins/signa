"""Signa Backend — FastAPI application entry point.

Run with: uvicorn main:app --reload --port 8000
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from app.api.v1 import auth, health, portfolio, positions, scans, signals, stats, watchlist
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.middleware.audit import AuditMiddleware
from app.middleware.auth import AuthMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.notifications.telegram_bot import handle_command, send_message
from app.scheduler.runner import init_scheduler, start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info(f"Starting {settings.app_name}...")
    logger.info(f"Auth enabled: {settings.auth_enabled}")
    logger.info(f"Debug mode: {settings.debug}")

    init_scheduler()
    start_scheduler()

    yield

    stop_scheduler()
    logger.info(f"{settings.app_name} shutting down")


app = FastAPI(
    title="Signa API",
    description="AI Investment Signal Engine",
    version="1.0.0",
    lifespan=lifespan,
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
app.include_router(positions.router, prefix=api_prefix)
app.include_router(watchlist.router, prefix=api_prefix)
app.include_router(portfolio.router, prefix=api_prefix)
app.include_router(scans.router, prefix=api_prefix)
app.include_router(stats.router, prefix=api_prefix)
app.include_router(health.router, prefix=api_prefix)


@app.post("/api/v1/telegram/webhook")
async def telegram_webhook(request: Request):
    """Receive Telegram bot updates via webhook.

    Validates the secret token header set via setWebhook.
    """
    # Verify webhook secret (reject if not configured or mismatch)
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not settings.telegram_webhook_secret or secret != settings.telegram_webhook_secret:
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

            response_text = await handle_command(command, args)

            if chat_id and response_text:
                await send_message(str(chat_id), response_text)

    except Exception:
        logger.exception("Telegram webhook error")

    return {"ok": True}


@app.get("/")
async def root():
    return {"app": "Signa", "version": "1.0.0", "docs": "/docs"}
