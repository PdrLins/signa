"""Security regression tests — passwords, secrets, refresh, username lookup.

Pure unit tests: the Supabase client and query helpers are faked, nothing
touches a database or the network.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import security
from app.core.config import Settings
from app.core.security import (
    create_access_token,
    decode_token_allow_expired,
    hash_password,
    supabase_key_role,
    verify_password,
)

# Generated once with bcrypt 5 (bcrypt.hashpw(pw, gensalt(12))) — a standard
# $2b$ hash exactly like the ones already stored in the users table.
KNOWN_PASSWORD = "correct horse battery staple"
KNOWN_HASH = "$2b$12$ObFvqDminGtidcw4EsEF3.mPLeafq/oyJJ6TrIWQbU3fcnF2KxzE6"

STRONG_A = "a3f1c9e07b2d4f6a8c0e1d3b5a7f9c2e4b6d8f0a1c3e5b7d9f1a3c5e7b9d0f2a"
STRONG_B = "0f9e8d7c6b5a49382716f5e4d3c2b1a0ffeeddccbbaa99887766554433221100"


# ── 1. Password hashing (bcrypt direct, no passlib) ──────────────────

class TestBcrypt:
    def test_known_2b_hash_verifies(self):
        assert verify_password(KNOWN_PASSWORD, KNOWN_HASH) is True

    def test_known_hash_rejects_wrong_password(self):
        assert verify_password("correct horse battery stapl", KNOWN_HASH) is False

    def test_new_hashes_are_2b(self):
        h = hash_password("hunter2-but-longer")
        assert h.startswith("$2b$12$")
        assert verify_password("hunter2-but-longer", h)

    def test_over_72_bytes_rejected_at_creation(self):
        with pytest.raises(ValueError):
            hash_password("x" * 73)
        # multi-byte: 25 * 3 bytes = 75 bytes > 72
        with pytest.raises(ValueError):
            hash_password("€" * 25)

    def test_exactly_72_bytes_ok(self):
        pw = "y" * 72
        assert verify_password(pw, hash_password(pw))

    def test_over_72_bytes_never_verifies_nor_raises(self):
        # A 72-byte prefix match must NOT authenticate a longer password.
        pw = "z" * 72
        h = hash_password(pw)
        assert verify_password(pw + "extra", h) is False

    def test_malformed_hash_returns_false(self):
        assert verify_password("anything", "not-a-bcrypt-hash") is False
        assert verify_password("anything", "") is False

    def test_passlib_not_used(self):
        import app.core.security as mod
        assert "passlib" not in open(mod.__file__).read()


# ── 2. Secret validation ─────────────────────────────────────────────

def _settings(**kw):
    base = dict(
        jwt_secret_key=STRONG_A,
        supabase_url="https://t.supabase.co",
        supabase_key="x",
        cors_origins=["http://localhost:3000"],
    )
    base.update(kw)
    return Settings(_env_file=None, **base)


class TestSecretValidation:
    def test_strong_distinct_secrets_accepted(self):
        s = _settings()
        assert s.jwt_secret_key == STRONG_A

    @pytest.mark.parametrize("bad", [
        "",
        "x",
        "change-me-in-production",
        "generate-with-openssl-rand-hex-32",
        "short-but-random-9f8e7d",           # < 32 chars
        "a" * 64,                              # long but trivially guessable
    ])
    def test_weak_jwt_secret_rejected(self, bad):
        with pytest.raises(ValueError):
            _settings(jwt_secret_key=bad)

    def test_env_example_placeholders_rejected(self):
        """Every secret-looking value shipped in .env.example must fail validation."""
        import pathlib
        example = pathlib.Path(__file__).resolve().parents[1] / ".env.example"
        values = {}
        for line in example.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip()
        with pytest.raises(ValueError):
            _settings(jwt_secret_key=values["JWT_SECRET_KEY"])

    def test_auth_enabled_removed_and_tolerated(self):
        assert "auth_enabled" not in Settings.model_fields
        # An old .env still carrying AUTH_ENABLED must not crash startup.
        _settings(auth_enabled=False)

    def test_retired_brain_keys_tolerated(self):
        """An old .env with the brain's keys (now Signa Advisor) still loads."""
        s = _settings(brain_token_secret="x", anthropic_api_key="k", xai_api_key="k", ai_enabled=True)
        assert not hasattr(s, "brain_token_secret") and not hasattr(s, "anthropic_api_key")


# ── 3. Token refresh ─────────────────────────────────────────────────

class FakeQueries:
    """Stand-in for app.db.queries (no DB)."""

    def __init__(self, blacklisted=()):
        self.blacklisted = set(blacklisted)
        self.audit = []

    def is_token_blacklisted(self, jti):
        return jti in self.blacklisted

    def blacklist_token(self, jti, user_id, expires_at):
        if jti in self.blacklisted:  # emulate UNIQUE(token_jti)
            raise RuntimeError("duplicate key value violates unique constraint")
        self.blacklisted.add(jti)

    def insert_audit_log(self, **kw):
        self.audit.append(kw)


@pytest.fixture
def fake_queries(monkeypatch):
    from app.services import auth_service
    fq = FakeQueries()
    monkeypatch.setattr(auth_service, "queries", fq)
    return fq


@pytest.fixture
def refresh_client():
    from app.api.v1 import auth as auth_routes
    app = FastAPI()
    app.include_router(auth_routes.router, prefix="/api/v1")
    return TestClient(app)


def _post_refresh(client, token):
    return client.post("/api/v1/auth/refresh", headers={"Authorization": f"Bearer {token}"})


class TestRefresh:
    def test_valid_refresh_rotates_and_revokes_old(self, fake_queries, refresh_client):
        token = create_access_token("u1", "pedro")
        old_jti = security.decode_token(token)["jti"]

        r = _post_refresh(refresh_client, token)
        assert r.status_code == 200, r.text
        new = security.decode_token(r.json()["access_token"])
        assert new["sub"] == "u1" and new["jti"] != old_jti
        assert old_jti in fake_queries.blacklisted

    def test_blacklisted_token_rejected(self, fake_queries, refresh_client):
        token = create_access_token("u1", "pedro")
        fake_queries.blacklisted.add(security.decode_token(token)["jti"])
        r = _post_refresh(refresh_client, token)
        assert r.status_code == 401
        assert "access_token" not in r.json()

    def test_replay_after_refresh_rejected(self, fake_queries, refresh_client):
        token = create_access_token("u1", "pedro")
        assert _post_refresh(refresh_client, token).status_code == 200
        assert _post_refresh(refresh_client, token).status_code == 401

    def test_expired_token_within_grace_is_blacklisted(self, fake_queries, refresh_client):
        # Expired 10 minutes ago: decode_token() would fail, so the old code
        # never blacklisted it. The presented JTI must still be revoked.
        token = create_access_token("u1", "pedro", expires_delta=timedelta(minutes=-10))
        jti = decode_token_allow_expired(token)["jti"]
        r = _post_refresh(refresh_client, token)
        assert r.status_code == 200, r.text
        assert jti in fake_queries.blacklisted
        # And it can't be used again
        assert _post_refresh(refresh_client, token).status_code == 401

    def test_token_past_grace_rejected(self, fake_queries, refresh_client):
        token = create_access_token("u1", "pedro", expires_delta=timedelta(hours=-5))
        assert _post_refresh(refresh_client, token).status_code == 401

    def test_absolute_session_cap(self, fake_queries, refresh_client):
        long_ago = int((datetime.now(timezone.utc) - timedelta(hours=25)).timestamp())
        token = create_access_token("u1", "pedro", auth_time=long_ago)
        assert _post_refresh(refresh_client, token).status_code == 401

    def test_auth_time_preserved_across_refresh(self, fake_queries, refresh_client):
        t0 = int((datetime.now(timezone.utc) - timedelta(hours=2)).timestamp())
        token = create_access_token("u1", "pedro", auth_time=t0)
        r = _post_refresh(refresh_client, token)
        assert security.decode_token(r.json()["access_token"])["auth_time"] == t0

    def test_forged_token_rejected(self, fake_queries, refresh_client):
        import jwt
        forged = jwt.encode(
            {"sub": "u1", "username": "pedro", "jti": "j", "exp": 9999999999},
            "generate-with-openssl-rand-hex-32", algorithm="HS256",
        )
        assert _post_refresh(refresh_client, forged).status_code == 401

    def test_missing_token(self, fake_queries, refresh_client):
        r = refresh_client.post("/api/v1/auth/refresh")
        assert r.status_code == 401


# ── 6. Username lookup / login enumeration ───────────────────────────

class FakeQuery:
    def __init__(self, rows, calls):
        self.rows, self.calls = rows, calls
        self.filters = []

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self.calls.append(("eq", col, val))
        self.filters.append((col, val))
        return self

    def ilike(self, col, val):  # must never be used for usernames
        self.calls.append(("ilike", col, val))
        raise AssertionError("ilike used for username lookup")

    def is_(self, col, val):
        self.calls.append(("is_", col, val))
        return self

    def update(self, data):
        self.calls.append(("update", data))
        return self

    def limit(self, n):
        return self

    def execute(self):
        rows = [r for r in self.rows if all(r.get(c) == v for c, v in self.filters)]

        class R:
            data = rows
        return R()


class FakeClient:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def table(self, name):
        return FakeQuery(self.rows, self.calls)


class TestUsernameLookup:
    def test_percent_does_not_match_owner(self, monkeypatch):
        from app.db import queries
        fc = FakeClient([{"id": "1", "username": "pedro", "is_active": True}])
        monkeypatch.setattr(queries, "get_client", lambda: fc)
        assert queries.get_user_by_username("%") is None
        assert queries.get_user_by_username("*") is None
        assert queries.get_user_by_username("p_dro") is None
        assert ("eq", "username", "%") in fc.calls

    def test_case_insensitive_exact_match(self, monkeypatch):
        from app.db import queries
        fc = FakeClient([{"id": "1", "username": "pedro", "is_active": True}])
        monkeypatch.setattr(queries, "get_client", lambda: fc)
        assert queries.get_user_by_username("Pedro")["id"] == "1"


class TestOtpMarkUsed:
    def test_conditional_update_and_affected_rows(self, monkeypatch):
        from app.db import queries
        fc = FakeClient([{"id": "o1", "used_at": None}])
        monkeypatch.setattr(queries, "get_client", lambda: fc)
        assert queries.mark_otp_used("o1") is True
        assert ("is_", "used_at", "null") in fc.calls

        fc2 = FakeClient([])  # already consumed -> no rows affected
        monkeypatch.setattr(queries, "get_client", lambda: fc2)
        assert queries.mark_otp_used("o1") is False


class TestLoginGenericErrors:
    @pytest.fixture
    def login_env(self, monkeypatch):
        from app.db import supabase as supa
        from app.services import auth_service

        user = {
            "id": "u1", "username": "pedro", "password_hash": KNOWN_HASH,
            "telegram_chat_id": "1", "login_attempts": 0, "locked_until": None,
        }
        fq = FakeQueries()
        fq.get_user_by_username = lambda u: dict(user) if u == "pedro" else None
        monkeypatch.setattr(auth_service, "queries", fq)
        fc = FakeClient([])
        monkeypatch.setattr(supa, "get_client", lambda: fc)
        return auth_service, fc

    @pytest.mark.asyncio
    async def test_wrong_password_and_unknown_user_same_message(self, login_env):
        from app.core.exceptions import AuthenticationError
        auth_service, _ = login_env
        with pytest.raises(AuthenticationError) as e1:
            await auth_service.login("pedro", "wrong", "1.2.3.4", "ua")
        with pytest.raises(AuthenticationError) as e2:
            await auth_service.login("nobody", "wrong", "1.2.3.4", "ua")
        assert e1.value.detail == e2.value.detail == "Invalid credentials."
        assert "remaining" not in e1.value.detail

    @pytest.mark.asyncio
    async def test_password_only_login_issues_token_without_otp(self, login_env, monkeypatch):
        from app.core.config import settings
        auth_service, _ = login_env
        sent, logins = [], []
        monkeypatch.setattr(settings, "login_otp_enabled", False)
        monkeypatch.setattr(auth_service, "send_otp_message", lambda *a: sent.append(a))
        monkeypatch.setattr(auth_service.queries, "update_user_last_login", lambda uid: logins.append(uid), raising=False)
        res = await auth_service.login("pedro", KNOWN_PASSWORD, "1.2.3.4", "ua")
        assert res["session_token"] is None
        assert security.decode_token(res["access_token"])["sub"] == "u1"
        assert sent == [] and logins == ["u1"]

    @pytest.mark.asyncio
    async def test_password_only_login_still_rejects_wrong_password(self, login_env, monkeypatch):
        from app.core.config import settings
        from app.core.exceptions import AuthenticationError
        auth_service, _ = login_env
        monkeypatch.setattr(settings, "login_otp_enabled", False)
        with pytest.raises(AuthenticationError):
            await auth_service.login("pedro", "wrong", "1.2.3.4", "ua")

    @pytest.mark.asyncio
    async def test_otp_login_returns_session_not_token(self, login_env, monkeypatch):
        from app.core.config import settings
        auth_service, _ = login_env
        sent = []

        async def fake_send(chat_id, code):
            sent.append(chat_id)

        monkeypatch.setattr(settings, "login_otp_enabled", True)
        monkeypatch.setattr(auth_service, "send_otp_message", fake_send)
        monkeypatch.setattr(auth_service.queries, "insert_otp", lambda **kw: None, raising=False)
        res = await auth_service.login("pedro", KNOWN_PASSWORD, "1.2.3.4", "ua")
        assert res["session_token"] and "access_token" not in res
        assert sent == ["1"]

    def test_lockout_backoff(self):
        from app.services.auth_service import lockout_seconds
        assert [lockout_seconds(n) for n in range(1, 5)] == [0, 0, 0, 0]
        assert lockout_seconds(5) == 60
        assert lockout_seconds(6) == 120
        assert lockout_seconds(50) == 900  # capped at 15 minutes


# ── 5. Supabase key role detection ───────────────────────────────────

class TestSupabaseKeyRole:
    @staticmethod
    def _jwt(role):
        import base64
        import json
        seg = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
        return f"{seg({'alg': 'HS256'})}.{seg({'role': role, 'iss': 'supabase'})}.sig"

    def test_anon(self):
        assert supabase_key_role(self._jwt("anon")) == "anon"

    def test_service_role(self):
        assert supabase_key_role(self._jwt("service_role")) == "service_role"

    def test_new_style_keys(self):
        assert supabase_key_role("sb_publishable_abc") == "anon"
        assert supabase_key_role("sb_secret_abc") == "service_role"

    def test_garbage(self):
        assert supabase_key_role("x") is None
        assert supabase_key_role("") is None
        assert supabase_key_role("a.!!!.c") is None
