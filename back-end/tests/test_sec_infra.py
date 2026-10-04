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

    def test_every_sink_gets_scrubbed_messages(self):
        from loguru import logger

        from app.services import log_service

        seen: list[str] = []
        logger.configure(patcher=log_service._scrub_patcher)
        sink_id = logger.add(lambda m: seen.append(m.record["message"]), format="{message}")
        try:
            logger.error(f"boom https://api.telegram.org/bot{TG_TOKEN}/getMe")
        finally:
            logger.remove(sink_id)
            logger.configure(patcher=None)
        assert seen and TG_TOKEN not in seen[-1]


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


# ── 8. Middleware order + CORS on 401 ────────────────────────────────

class TestMiddlewareOrder:
    def test_effective_chain(self):
        import main
        names = [m.cls.__name__ for m in main.app.user_middleware]  # outermost first
        assert names == ["CORSMiddleware", "GZipMiddleware", "RateLimitMiddleware", "AuditMiddleware", "AuthMiddleware"]

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


def test_standard_rate_limit_is_per_user_not_per_ip():
    from starlette.requests import Request

    from app.core.security import create_access_token
    from app.middleware.rate_limit import _standard_key

    def req(headers):
        return Request({"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]})

    a = _standard_key(req({"Authorization": "Bearer " + create_access_token("user-a", "a")}))
    b = _standard_key(req({"Authorization": "Bearer " + create_access_token("user-b", "b")}))
    assert a == "user:user-a" and b == "user:user-b"      # same IP, separate buckets
    assert _standard_key(req({"Authorization": "Bearer not-a-token"})) is None   # falls back to IP
    assert _standard_key(req({})) is None


class TestGzip:
    def test_large_json_is_compressed(self):
        from fastapi import FastAPI
        from fastapi.middleware.gzip import GZipMiddleware
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)

        @app.get("/big")
        def big():
            return {"items": [{"symbol": "AAPL", "price": 1.0}] * 200}

        r = TestClient(app).get("/big", headers={"Accept-Encoding": "gzip"})
        assert r.headers.get("content-encoding") == "gzip"
        assert len(r.json()["items"]) == 200
