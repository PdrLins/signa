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
    logger.add(
        lambda m: print(scrub_secrets(m), end=""),
        level="DEBUG",
        format="<level>{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {module}:{function}:{line} - {message}</level>",
        colorize=True,
    )
    # Persistent log file (daily rotation, 14 days kept) so a missed
    # scheduled job can be diagnosed after a restart. Messages are already
    # scrubbed by the patcher; diagnose=False keeps variable values out of
    # tracebacks.
    from app.core.config import settings
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
    logger.info("Logging initialized")
