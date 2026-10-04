"""Supabase client singleton (thread-safe) with auto-reconnect and retry."""

import threading
import time
from functools import wraps

import httpx
from loguru import logger
from supabase import Client, ClientOptions, create_client

from app.core.config import settings

_client: Client | None = None
_http: httpx.Client | None = None
_lock = threading.Lock()
_last_created: float = 0
_MAX_AGE = 1800  # Recreate client every 30 min; with_retry handles stale connections


# Supabase (behind Cloudflare) closes idle keep-alive connections; reusing
# one fails with "Server disconnected without sending a response". The
# transport below retries
# such requests on a fresh connection: reads always, writes only when the
# server provably sent nothing back (the request never reached it).
_RETRY_ATTEMPTS = 3
DB_TIMEOUT_S = 20.0
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_NOT_SENT = ("server disconnected without sending a response", "connectionterminated",
             "connection reset", "broken pipe")


def should_retry_disconnect(method: str, err: Exception) -> bool:
    """True when a dropped connection may be retried without risking a
    duplicate write. Pure (tested)."""
    if not isinstance(err, (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError, httpx.ConnectError)):
        return False
    if method.upper() in _SAFE_METHODS or isinstance(err, httpx.ConnectError):
        return True
    text = str(err).lower()
    return any(m in text for m in _NOT_SENT)


class _ReconnectTransport(httpx.HTTPTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        request.read()   # buffered body, so it can be sent again
        for attempt in range(_RETRY_ATTEMPTS):
            try:
                return super().handle_request(request)
            except Exception as e:
                if attempt == _RETRY_ATTEMPTS - 1 or not should_retry_disconnect(request.method, e):
                    raise
                logger.info(f"Supabase connection dropped ({type(e).__name__}) on {request.method} "
                            f"{request.url.path}, retrying ({attempt + 1}/{_RETRY_ATTEMPTS - 1})")
                time.sleep(0.25 * (attempt + 1))
        raise RuntimeError("unreachable")


def _http_client() -> httpx.Client:
    # HTTP/1.1 with a short keep-alive: idle connections are dropped by us
    # before the server drops them under us.
    return httpx.Client(
        transport=_ReconnectTransport(http2=False, limits=httpx.Limits(
            max_connections=50, max_keepalive_connections=20, keepalive_expiry=20)),
        # A slow query fails in seconds instead of holding a request thread
        # (and the user's screen) for minutes; every read is paged.
        timeout=httpx.Timeout(DB_TIMEOUT_S, connect=5.0),
        follow_redirects=True,
    )


def get_client() -> Client:
    """Get or create the Supabase client singleton.

    Recreates the client if the connection is older than 30 minutes.
    The @with_retry decorator handles stale connection errors.
    """
    global _client, _last_created, _http
    now = time.time()

    c = _client   # one read: reset_client() may set it to None meanwhile
    if c is not None and (now - _last_created) < _MAX_AGE:
        return c

    with _lock:
        # Double-check after acquiring lock
        c = _client
        if c is not None and (now - _last_created) < _MAX_AGE:
            return c

        was_first = _last_created == 0
        old_http = _http
        _http = _http_client()
        c = create_client(settings.supabase_url, settings.supabase_key,
                          options=ClientOptions(httpx_client=_http))
        _client, _last_created = c, now
        if old_http is not None:
            # requests still running on the old client finish first
            t = threading.Timer(60, old_http.close)
            t.daemon = True
            t.start()
        if was_first:
            logger.info("Supabase client initialized")
        else:
            logger.debug("Supabase client reconnected (stale connection)")
        return c


def reset_client():
    """Force reset the client on next call. Use after connection errors."""
    global _client, _last_created
    with _lock:
        _client = None
        _last_created = 0


def with_retry(fn):
    """Decorator that retries a function once on Supabase connection errors.

    On RemoteProtocolError or ConnectionError, resets the client and retries.
    This handles Supabase's aggressive HTTP/2 connection termination.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            error_str = str(e).lower()
            if "disconnected" in error_str or "remoteerror" in error_str or "connectionterminated" in error_str or "remoteprotocol" in error_str:
                logger.warning(f"Supabase connection dropped in {fn.__name__}, reconnecting and retrying...")
                reset_client()
                return fn(*args, **kwargs)
            raise
    return wrapper
