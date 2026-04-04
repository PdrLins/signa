"""Shared utility functions."""

import re

from fastapi import Request

from app.core.config import settings

_TICKER_PATTERN = re.compile(r"^[A-Z0-9]{1,10}([.\-][A-Z0-9]{1,5})?$")


def get_client_ip(request: Request) -> str:
    """Extract client IP from request, validating trusted proxies.

    Only trusts X-Forwarded-For if the direct client is a known proxy.
    """
    client_host = request.client.host if request.client else "unknown"

    if client_host in settings.trusted_proxies:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()

    return client_host


def validate_ticker(ticker: str) -> bool:
    """Validate a ticker symbol format."""
    return bool(_TICKER_PATTERN.match(ticker.upper()))
