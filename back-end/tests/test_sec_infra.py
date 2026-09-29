"""Security regression tests — log scrubbing, client IP, rate-limit exemption,
middleware order. No DB / network.
"""

from types import SimpleNamespace

import pytest

from app.services.log_service import scrub_secrets

TG_TOKEN = "1234567890:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"


# ── 7. Log scrubbing ─────────────────────────────────────────────────

class TestLogScrubber:
    @pytest.mark.parametrize("secret_line, secret", [
        (f"Telegram send failed: Client error for url 'https://api.telegram.org/bot{TG_TOKEN}/sendMessage'", TG_TOKEN),
        (f"token is {TG_TOKEN}", TG_TOKEN),
        ("GET https://api.example.com/v1?api_key=s3cr3tVALUE&x=1", "s3cr3tVALUE"),
        ("gemini https://generativelanguage.googleapis.com/v1?key=AIzaSyD-abcdefghijklmnopqrstuvwx", "AIzaSyD-abcdefghijklmnopqrstuvwx"),
        ("anthropic key sk-ant-api03-AbCdEf123456_-xyz", "sk-ant-api03-AbCdEf123456_-xyz"),
        ("grok key xai-AbCdEfGh12345678", "xai-AbCdEfGh12345678"),
        ("AIzaSyA1234567890abcdefghijklmnop leaked", "AIzaSyA1234567890abcdefghijklmnop"),
        ("jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1MSJ9.Sfl-KxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
         "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1MSJ9.Sfl-KxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"),
        ("Authorization: Bearer abc.def-ghi_jkl", "abc.def-ghi_jkl"),
    ])
    def test_redacts(self, secret_line, secret):
        out = scrub_secrets(secret_line)
        assert secret not in out
        assert "[REDACTED]" in out

    def test_leaves_normal_messages_alone(self):
        msg = "Scan complete: AAPL score=82 at 12:30:05 (took 1234ms) BUY"
        assert scrub_secrets(msg) == msg

    def test_buffer_and_stream_are_scrubbed(self):
        from loguru import logger

        from app.services import log_service

        q = log_service.subscribe()
        sink_id = logger.add(log_service._loguru_sink, format="{message}")
        try:
            logger.error(f"boom https://api.telegram.org/bot{TG_TOKEN}/getMe")
        finally:
            logger.remove(sink_id)
            log_service.unsubscribe(q)
        assert TG_TOKEN not in log_service._LOG_BUFFER[-1]["message"]
        assert TG_TOKEN not in q.get_nowait()["message"]


# ── 10. X-Forwarded-For handling ─────────────────────────────────────

def _req(client_host, xff=None):
    headers = {"X-Forwarded-For": xff} if xff else {}
    return SimpleNamespace(client=SimpleNamespace(host=client_host), headers=headers)


class TestClientIp:
    def test_untrusted_peer_ignores_header(self):
        from app.core.utils import get_client_ip
        assert get_client_ip(_req("203.0.113.9", "1.1.1.1")) == "203.0.113.9"

    def test_spoofed_leftmost_ignored(self):
        from app.core.utils import get_client_ip
        # Attacker sends "X-Forwarded-For: 6.6.6.6"; proxy appends real IP.
        assert get_client_ip(_req("127.0.0.1", "6.6.6.6, 198.51.100.7")) == "198.51.100.7"

    def test_skips_trusted_hops(self):
        from app.core.utils import get_client_ip
        assert get_client_ip(_req("127.0.0.1", "198.51.100.7, 127.0.0.1")) == "198.51.100.7"

    def test_garbage_falls_back_to_peer(self):
        from app.core.utils import get_client_ip
        assert get_client_ip(_req("127.0.0.1", "not-an-ip")) == "127.0.0.1"


class TestProgressExemption:
    def test_only_real_progress_route(self):
        from app.middleware.rate_limit import _PROGRESS_ROUTE
        assert _PROGRESS_ROUTE.match("/api/v1/scans/0b6f3c1e-1234-4abc-9def-001122334455/progress")
        assert not _PROGRESS_ROUTE.match("/api/v1/auth/login/progress")
        assert not _PROGRESS_ROUTE.match("/api/v1/auth/login?x=/progress")
        assert not _PROGRESS_ROUTE.match("/api/v1/scans/a/b/progress")
        assert not _PROGRESS_ROUTE.match("/api/v1/scans/abc/progress/extra")


# ── 8. Middleware order + CORS on 401 ────────────────────────────────

class TestMiddlewareOrder:
    def test_effective_chain(self):
        import main
        names = [m.cls.__name__ for m in main.app.user_middleware]  # outermost first
        assert names == ["CORSMiddleware", "RateLimitMiddleware", "AuditMiddleware", "AuthMiddleware"]

    def test_401_carries_cors_headers(self, monkeypatch):
        from fastapi.testclient import TestClient

        import main
        from app.middleware import auth as auth_mw
        from app.middleware import rate_limit

        monkeypatch.setattr(auth_mw, "insert_audit_log", lambda **kw: None)
        monkeypatch.setattr(rate_limit, "insert_audit_log", lambda **kw: None)
        origin = main.settings.cors_origins[0]
        client = TestClient(main.app)  # no context manager -> lifespan (scheduler etc.) not run
        r = client.get("/api/v1/signals", headers={"Origin": origin})
        assert r.status_code == 401
        assert r.headers.get("access-control-allow-origin") == origin
