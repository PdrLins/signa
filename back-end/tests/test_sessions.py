"""Sessions and rotating refresh tokens (migration 017): app/services/sessions.py,
the auth middleware check and the /auth/token/refresh + /auth/sessions routes."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.services import sessions


# ---------------------------------------------------------------- in-memory PostgREST

class _Result:
    def __init__(self, data):
        self.data = data


class MemDB:
    """Just enough of supabase-py for sessions.py: select/insert/update with
    eq / neq / is_(col, "null") filters, order, limit."""

    def __init__(self):
        self.tables = {"auth_sessions": [], "auth_refresh_tokens": []}

    def table(self, name):
        if name not in self.tables:
            raise RuntimeError(f'relation "{name}" does not exist (42P01)')
        return _Q(self, name)


class _Q:
    def __init__(self, db, name):
        self.db, self.name, self.op, self.payload, self.filters = db, name, None, None, []

    def select(self, *_a, **_k):
        self.op = "select"
        return self

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def eq(self, k, v):
        self.filters.append(lambda r, k=k, v=v: str(r.get(k)) == str(v))
        return self

    def neq(self, k, v):
        self.filters.append(lambda r, k=k, v=v: str(r.get(k)) != str(v))
        return self

    def is_(self, k, v):
        assert v == "null"
        self.filters.append(lambda r, k=k: r.get(k) is None)
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a):
        return self

    def execute(self):
        rows = self.db.tables[self.name]
        match = [r for r in rows if all(f(r) for f in self.filters)]
        if self.op == "select":
            return _Result([dict(r) for r in match])
        if self.op == "update":
            for r in match:
                r.update(self.payload)
            return _Result([dict(r) for r in match])
        now = datetime.now(timezone.utc).isoformat()
        row = {"created_at": now, **self.payload}
        if self.name == "auth_sessions":
            row = {"id": str(uuid.uuid4()), "last_used_at": now, "revoked_at": None, "revoked_reason": None, **row}
        else:
            row = {"used_at": None, **row}
        rows.append(row)
        return _Result([dict(row)])


@pytest.fixture
def db(monkeypatch):
    mem = MemDB()
    monkeypatch.setattr(sessions, "_db", lambda: mem)
    monkeypatch.setattr(sessions, "_level", lambda uid: "free")
    sessions._active_cache._store.clear()
    sessions._grace_used._store.clear()
    return mem


USER = {"id": "11111111-1111-1111-1111-111111111111", "username": "ana", "access_level": "free"}


# ---------------------------------------------------------------- pure helpers

def test_device_label():
    mac = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
    assert sessions.device_label("web", None, mac) == "Chrome on macOS"
    assert sessions.device_label("ios", "  Pedro's   iPhone ", "Signa/1.0") == "Pedro's iPhone"
    assert sessions.device_label("ios", None, "Signa/1.0 CFNetwork Darwin") == "iPhone"
    assert sessions.device_label("web", None, "") == "Web browser"


def test_lifetimes_by_client_and_level():
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    exp, absolute = sessions.lifetimes("ios", "free", now)
    assert exp == now + timedelta(days=settings.session_refresh_days)
    assert absolute == now + timedelta(days=settings.session_absolute_days)
    assert sessions.lifetimes("ios", "owner", now) == (now + timedelta(days=30), now + timedelta(days=30))
    web = now + timedelta(hours=settings.jwt_max_session_hours)
    assert sessions.lifetimes("web", "free", now) == (web, web)
    # sliding never passes the absolute cap
    assert sessions.slide(now + timedelta(days=10), "free", now) == now + timedelta(days=10)
    assert sessions.access_minutes("ios") == 15


# ---------------------------------------------------------------- create / rotate

def test_ios_session_gets_hashed_refresh_token(db):
    out = sessions.create(USER, "ios", "Ana's iPhone", "1.2.3.4", "Signa/1.0")
    assert out["session_id"] and out["refresh_token"]
    stored = db.tables["auth_refresh_tokens"][0]
    assert stored["token_hash"] == sessions.hash_token(out["refresh_token"])
    assert out["refresh_token"] not in str(db.tables)          # only the hash is stored
    assert db.tables["auth_sessions"][0]["device_name"] == "Ana's iPhone"


def test_web_session_has_no_refresh_token(db):
    out = sessions.create(USER, "web", None, "1.2.3.4", "Firefox/130")
    assert out["session_id"] and out["refresh_token"] is None
    assert db.tables["auth_refresh_tokens"] == []


def test_rotate_returns_new_token_and_old_one_is_spent(db):
    first = sessions.create(USER, "ios", None, "ip", "ua")["refresh_token"]
    r = sessions.rotate(first, "ip2", "ua2")
    second = r["refresh_token"]
    assert second != first
    assert sessions.rotate(second, "ip", "ua")["refresh_token"]   # the new one works


def test_reused_refresh_token_revokes_the_session(db):
    out = sessions.create(USER, "ios", None, "ip", "ua")
    first = out["refresh_token"]
    second = sessions.rotate(first, "ip", "ua")["refresh_token"]
    _age_used(db, first, seconds=settings.session_refresh_grace_seconds + 5)   # past the retry window
    with pytest.raises(sessions.SessionError) as e:
        sessions.rotate(first, "ip", "ua")                        # stolen copy presented
    assert e.value.code == "reuse_detected"
    assert db.tables["auth_sessions"][0]["revoked_reason"] == "reuse_detected"
    with pytest.raises(sessions.SessionError) as e:
        sessions.rotate(second, "ip", "ua")                       # the legit one is dead too
    assert e.value.code == "session_revoked"
    assert sessions.is_active(out["session_id"]) is False


def _age_used(db, token, seconds):
    h = sessions.hash_token(token)
    row = next(r for r in db.tables["auth_refresh_tokens"] if r["token_hash"] == h)
    row["used_at"] = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def test_retry_within_grace_returns_the_same_pair_once(db):
    out = sessions.create(USER, "ios", None, "ip", "ua")
    first = out["refresh_token"]
    r1 = sessions.rotate(first, "ip", "ua")                       # response lost on the way
    r2 = sessions.rotate(first, "ip", "ua")                       # the app retries with the old token
    assert r2["refresh_token"] == r1["refresh_token"] and r2.get("retry") is True
    assert str(r2["session"]["id"]) == out["session_id"]
    assert len(db.tables["auth_refresh_tokens"]) == 2             # nothing new issued
    assert sessions.is_active(out["session_id"]) is True
    with pytest.raises(sessions.SessionError) as e:               # only once per rotation
        sessions.rotate(first, "ip", "ua")
    assert e.value.code == "reuse_detected"


def test_retry_after_grace_window_is_reuse(db):
    out = sessions.create(USER, "ios", None, "ip", "ua")
    first = out["refresh_token"]
    sessions.rotate(first, "ip", "ua")
    _age_used(db, first, seconds=settings.session_refresh_grace_seconds + 1)
    with pytest.raises(sessions.SessionError) as e:
        sessions.rotate(first, "ip", "ua")
    assert e.value.code == "reuse_detected"
    assert db.tables["auth_sessions"][0]["revoked_reason"] == "reuse_detected"


def test_older_than_predecessor_is_reuse_even_inside_window(db):
    out = sessions.create(USER, "ios", None, "ip", "ua")
    first = out["refresh_token"]
    second = sessions.rotate(first, "ip", "ua")["refresh_token"]
    sessions.rotate(second, "ip", "ua")                           # current = third
    with pytest.raises(sessions.SessionError) as e:
        sessions.rotate(first, "ip", "ua")                        # 2 rotations back, a few ms ago
    assert e.value.code == "reuse_detected"
    assert sessions.is_active(out["session_id"]) is False


def test_retry_after_successor_was_used_is_reuse(db):
    first = sessions.create(USER, "ios", None, "ip", "ua")["refresh_token"]
    second = sessions.rotate(first, "ip", "ua")["refresh_token"]
    sessions.rotate(second, "ip", "ua")
    with pytest.raises(sessions.SessionError) as e:
        sessions.rotate(first, "ip", "ua")
    assert e.value.code == "reuse_detected"


def test_grace_off_and_successor_is_derived(db, monkeypatch):
    monkeypatch.setattr(settings, "session_refresh_grace_seconds", 0)
    first = sessions.create(USER, "ios", None, "ip", "ua")["refresh_token"]
    second = sessions.rotate(first, "ip", "ua")["refresh_token"]
    assert second == sessions.successor_token(first) and len(second) == len(first)
    with pytest.raises(sessions.SessionError) as e:
        sessions.rotate(first, "ip", "ua")
    assert e.value.code == "reuse_detected"


def test_unknown_and_expired_tokens(db):
    with pytest.raises(sessions.SessionError) as e:
        sessions.rotate("x" * 40, "ip", "ua")
    assert e.value.code == "invalid_refresh"
    tok = sessions.create(USER, "ios", None, "ip", "ua")["refresh_token"]
    db.tables["auth_sessions"][0]["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    with pytest.raises(sessions.SessionError) as e:
        sessions.rotate(tok, "ip", "ua")
    assert e.value.code == "session_expired"


def test_revoke_only_own_sessions_and_revoke_others(db):
    a = sessions.create(USER, "ios", "A", "ip", "ua")["session_id"]
    b = sessions.create(USER, "web", "B", "ip", "ua")["session_id"]
    c = sessions.create(USER, "ios", "C", "ip", "ua")["session_id"]
    assert sessions.revoke(a, "someone-else", "user") is False
    assert sessions.revoke(a, USER["id"], "user") is True
    assert sessions.revoke(a, USER["id"], "user") is False       # already ended
    assert sessions.revoke_others(USER["id"], b) == 1             # only C was still active
    listed = sessions.list_for_user(USER["id"], b)
    assert [s["id"] for s in listed] == [b] and listed[0]["current"] is True
    assert not sessions.is_active(c) and sessions.is_active(b)


def test_create_without_migration_degrades(monkeypatch):
    class NoTables:
        def table(self, name):
            raise RuntimeError('relation "auth_sessions" does not exist (42P01)')
    monkeypatch.setattr(sessions, "_db", lambda: NoTables())
    assert sessions.create(USER, "ios", None, "ip", "ua") == {"session_id": None, "refresh_token": None, "expires_at": None}
    assert sessions.is_active("whatever") is True                 # fail open, token expiry still applies


# ---------------------------------------------------------------- API

@pytest.fixture
def api(db, monkeypatch):
    from fastapi.testclient import TestClient

    import main
    from app.db import queries
    from app.middleware import rate_limit
    monkeypatch.setattr(queries, "insert_audit_log", lambda **k: None)
    monkeypatch.setattr(queries, "get_user_by_id", lambda uid: {**USER} if uid == USER["id"] else None)
    monkeypatch.setattr("app.middleware.auth.insert_audit_log", lambda **k: None)
    monkeypatch.setattr("app.middleware.auth.is_token_blacklisted", lambda jti: False)
    monkeypatch.setattr("app.middleware.auth.get_user_access", lambda uid: {"level": "free", "slot_bonus": 0})
    monkeypatch.setattr("app.middleware.auth._touch_last_seen", lambda uid: None)
    for store in rate_limit._attempts.values():
        store.clear()
    rate_limit._blocked.clear()
    return TestClient(main.app)


def _signed_in(client_kind="ios"):
    from app.core.security import create_access_token
    out = sessions.create(USER, client_kind, None, "ip", "ua")
    token = create_access_token(USER["id"], USER["username"], session_id=out["session_id"], client=client_kind)
    return out, {"Authorization": f"Bearer {token}"}


def test_refresh_endpoint_rotates_and_reports_reuse(api, db):
    out, _ = _signed_in()
    r = api.post("/api/v1/auth/token/refresh", json={"refresh_token": out["refresh_token"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["refresh_token"] and body["refresh_token"] != out["refresh_token"]
    assert body["expires_in"] == 15 * 60 and body["session_id"] == out["session_id"]
    retry = api.post("/api/v1/auth/token/refresh", json={"refresh_token": out["refresh_token"]})
    assert retry.status_code == 200 and retry.json()["refresh_token"] == body["refresh_token"]   # lost response
    assert retry.json()["session_id"] == out["session_id"] and retry.json()["access_token"]
    again = api.post("/api/v1/auth/token/refresh", json={"refresh_token": out["refresh_token"]})
    assert again.status_code == 401 and again.json()["detail"]["code"] == "reuse_detected"


def test_revoked_session_blocks_its_access_token(api):
    out, headers = _signed_in()
    me = api.get("/api/v1/auth/sessions", headers=headers)
    assert me.status_code == 200 and me.json()[0]["current"] is True
    other, other_headers = _signed_in("web")
    assert api.delete(f"/api/v1/auth/sessions/{out['session_id']}", headers=other_headers).status_code == 204
    assert api.get("/api/v1/auth/sessions", headers=headers).status_code == 401   # signed out within the cache window
    assert api.delete(f"/api/v1/auth/sessions/{out['session_id']}", headers=other_headers).status_code == 404


def test_revoke_others_keeps_current(api):
    _a, headers = _signed_in()
    _signed_in("web")
    _signed_in("ios")
    r = api.post("/api/v1/auth/sessions/revoke-others", headers=headers)
    assert r.status_code == 200 and r.json() == {"revoked": 2}
    assert len(api.get("/api/v1/auth/sessions", headers=headers).json()) == 1


def test_sign_in_issues_session_bound_tokens(db, monkeypatch):
    from app.core.security import decode_token
    from app.db import queries
    from app.services import auth_service
    monkeypatch.setattr(queries, "update_user_last_login", lambda uid: None)
    monkeypatch.setattr(queries, "insert_audit_log", lambda **k: None)
    ios = auth_service._issue_access_token({**USER}, "ip", "Signa/1.0", "ios", "Ana's iPhone")
    claims = decode_token(ios["access_token"])
    assert claims["sid"] == ios["session_id"] and claims["cli"] == "ios"
    assert ios["refresh_token"] and ios["expires_in"] == 15 * 60
    web = auth_service._issue_access_token({**USER}, "ip", "Firefox/130", "web", None)
    assert web["refresh_token"] is None and decode_token(web["access_token"])["cli"] == "web"
    assert web["expires_in"] == settings.jwt_access_token_expire_minutes * 60
