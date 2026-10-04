"""Logging setup: loguru to stdout (and optional daily files), with every
message scrubbed of API keys, bot tokens and JWTs first."""

from __future__ import annotations

import logging
import re

from loguru import logger

# ── Secret scrubbing ──
# Applied to every log message before it reaches any sink (terminal, log file). Order matters: specific patterns first.
_REDACTED = "[REDACTED]"
_SCRUB_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Telegram bot token inside API URLs: .../bot123456:ABC-def/sendMessage
    (re.compile(r"bot\d{5,}:[A-Za-z0-9_-]{20,}"), "bot" + _REDACTED),
    # Bare Telegram bot token
    (re.compile(r"\b\d{5,}:[A-Za-z0-9_-]{30,}"), _REDACTED),
    # Anthropic / xAI / Google API keys
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"), _REDACTED),
    (re.compile(r"\bxai-[A-Za-z0-9_-]{8,}"), _REDACTED),
    (re.compile(r"AIza[0-9A-Za-z_-]{20,}"), _REDACTED),
    # JWTs (access/brain tokens, Supabase keys): header.payload[.signature]
    (re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}(?:\.[A-Za-z0-9_-]*)?"), _REDACTED),
    # Bearer tokens in headers
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1" + _REDACTED),
    # Secret-looking query/form params: ?api_key=..., &key=..., token=...
    (re.compile(r"(?i)\b((?:api[_-]?key|apikey|key|token|access_token|jwt|secret|password)=)[^&\s\"'<>]+"), r"\1" + _REDACTED),
    # Personal data that must never sit in a log: sign-in codes inside messages,
    # email addresses, APNs device tokens (64 hex)
    (re.compile(r"<code>\s*\d{4,8}\s*</code>"), "<code>" + _REDACTED + "</code>"),
    (re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
    (re.compile(r"\b[0-9a-fA-F]{64}\b"), "[DEVICE_TOKEN]"),
]


def scrub_secrets(text: str) -> str:
    """Redact API keys, bot tokens, and JWTs from a log string."""
    if not text:
        return text
    for pattern, repl in _SCRUB_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def _scrub_patcher(record) -> None:
    """Loguru patcher: scrub the message before any sink sees it."""
    record["message"] = scrub_secrets(record["message"])


class _InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(exception=record.exc_info, depth=6).log(level, record.getMessage())


def init_log_capture():
    """Initialize the loguru sink. Call once at startup."""
    # Remove default handler and add a better formatted one
    logger.remove()
    logger.configure(patcher=_scrub_patcher)
    # httpx logs full request URLs at INFO (Telegram URLs contain the bot token)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    # Terminal output with clear ERROR/WARNING formatting and colors.
    # Scrub the fully formatted line too (covers exception tracebacks).
    # DEBUG only with DEBUG=true; in production INFO, no colors, and written
    # from a background thread (enqueue) so a slow stdout never blocks a request.
    from app.core.config import settings
    logger.add(
        lambda m: print(scrub_secrets(m), end=""),
        level="DEBUG" if settings.debug else "INFO",
        format="<level>{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {module}:{function}:{line} - {message}</level>",
        colorize=settings.debug,
        enqueue=not settings.debug,
    )
    # Persistent log file (daily rotation, 14 days kept) so a missed
    # scheduled job can be diagnosed after a restart. Messages are already
    # scrubbed by the patcher; diagnose=False keeps variable values out of
    # tracebacks.
    if settings.log_file_dir:
        from pathlib import Path
        log_dir = Path(settings.log_file_dir)
        if not log_dir.is_absolute():
            log_dir = Path(__file__).resolve().parents[2] / log_dir
        log_dir.mkdir(parents=True, exist_ok=True)
        logger.add(
            str(log_dir / "signa_{time:YYYY-MM-DD}.log"),
            level="INFO",
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {module}:{function}:{line} - {message}",
            rotation="00:00",
            retention="14 days",
            enqueue=True,
            backtrace=False,
            diagnose=False,
        )
    # uvicorn's own errors ("Exception in ASGI application" tracebacks) go
    # through stdlib logging: route them into loguru so they reach the log
    # file and the scrubber too.
    for name in ("uvicorn.error",):
        std = logging.getLogger(name)
        std.handlers = [_InterceptHandler()]
        std.propagate = False
    logger.info("Logging initialized")
