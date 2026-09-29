"""Shared utility functions."""

import ipaddress
import re

from fastapi import Request

from app.core.config import settings

_TICKER_PATTERN = re.compile(r"^[A-Z0-9]{1,10}([.\-][A-Z0-9]{1,5})?$")


def get_client_ip(request: Request) -> str:
    """Extract client IP from request, validating trusted proxies.

    Only trusts X-Forwarded-For if the direct client is a known proxy. The
    header is walked right-to-left and the first hop that is NOT a trusted
    proxy is returned — the leftmost entries are client-controlled and can be
    spoofed to dodge per-IP rate limits.
    """
    client_host = request.client.host if request.client else "unknown"

    if client_host in settings.trusted_proxies:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            hops = [h.strip() for h in forwarded.split(",") if h.strip()]
            for hop in reversed(hops):
                if hop in settings.trusted_proxies:
                    continue
                try:
                    return str(ipaddress.ip_address(hop))
                except ValueError:
                    break  # garbage in the chain — don't trust anything left of it

    return client_host


def validate_ticker(ticker: str) -> bool:
    """Validate a ticker symbol format."""
    return bool(_TICKER_PATTERN.match(ticker.upper()))
