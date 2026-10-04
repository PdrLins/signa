"""Forgot password: by username or email, code by verified email or Telegram,
no account enumeration, 3 an hour, every device signed out after the reset."""

import asyncio

import pytest

from app.core.security import hash_password, verify_password
from app.db import queries
from app.services import identity

UID = "11111111-1111-1111-1111-111111111111"


class _Res:
    def __init__(self, data):
        self.data = data


class MemDB:
    def __init__(self):
        self.otps: dict[str, dict] = {}
        self.users = {UID: {"id": UID, "username": "ana", "password_hash": hash_password("old password"),
                            "is_active": True, "email": None, "email_verified_at": None,
                            "telegram_chat_id": "777"}}

    def table(self, name):
        return _Q(self, name)


class _Q:
    def __init__(self, db, name):
        self.db, self.name, self.payload, self.op, self.filters = db, name, None, None, {}

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def eq(self, k, v):
        self.filters[k] = v
        return self

    def execute(self):
        if self.name == "otp_codes" and self.op == "insert":
            row = {"id": str(len(self.db.otps)), "used_at": None, **self.payload}
            self.db.otps[row["session_token"]] = row
        if self.name == "users" and self.op == "update":
            self.db.users[self.filters["id"]].update(self.payload)
        return _Res([])


@pytest.fixture
def db(monkeypatch):
    mem = MemDB()
    monkeypatch.setattr(identity, "_db", lambda: mem)
    monkeypatch.setattr(identity, "_language", lambda uid, fallback="en": "en")
    monkeypatch.setattr(queries, "get_user_by_username", lambda u: dict(mem.users[UID]) if u == "ana" else None)
    monkeypatch.setattr(queries, "get_user_by_email", lambda e: next(
        (dict(u) for u in mem.users.values() if u.get("email") == e), None))
    monkeypatch.setattr(queries, "get_otp_by_session_token", lambda t: dict(mem.otps[t]) if t in mem.otps else None)

    def used(oid):
        for r in mem.otps.values():
            if r["id"] == oid and not r["used_at"]:
                r["used_at"] = "now"
                return True
        return False
    monkeypatch.setattr(queries, "mark_otp_used", used)
    monkeypatch.setattr(queries, "increment_otp_attempts", lambda oid: None)
    monkeypatch.setattr(queries, "insert_audit_log", lambda **k: None)
    revoked = []
    monkeypatch.setattr("app.services.sessions.revoke_others", lambda uid, keep, reason="": revoked.append(uid) or 1)
    mem.revoked = revoked
    identity._resets.clear()
    return mem


def test_telegram_reset_then_new_password_signs_out_everyone(db):
    res, telegram = identity.start_reset("Ana")
    assert res["message"] == identity.RESET_MESSAGE and telegram[0] == "777"
    code = telegram[1]
    identity.finish_reset(res["session_token"], code, "new password 1")
    assert verify_password("new password 1", db.users[UID]["password_hash"])
    assert db.revoked == [UID]
    with pytest.raises(Exception):   # a code works once
        identity.finish_reset(res["session_token"], code, "another password")


def test_same_answer_for_unknown_and_unreachable_accounts(db):
    unknown, t1 = identity.start_reset("nobody")
    db.users[UID]["telegram_chat_id"] = None
    unreachable, t2 = identity.start_reset("ana")
    assert unknown["message"] == unreachable["message"] == identity.RESET_MESSAGE
    assert t1 is None and t2 is None and db.otps == {}


def test_verified_email_gets_the_code_by_email(db, monkeypatch):
    sent = []
    monkeypatch.setattr("app.services.email_sender.send_code", lambda to, purpose, code, lang: sent.append((to, purpose)))
    db.users[UID].update(email="ana@example.com", email_verified_at="2026-10-01")
    res, telegram = identity.start_reset("ana@example.com")
    assert telegram is None and sent == [("ana@example.com", "reset")]


def test_three_codes_an_hour(db):
    for _ in range(3):
        assert identity.start_reset("ana")[1] is not None
    res, telegram = identity.start_reset("ana")
    assert telegram is None and res["message"] == identity.RESET_MESSAGE   # same answer, no 4th code


def test_short_password_refused(db):
    res, (chat, code, _) = identity.start_reset("ana")
    with pytest.raises(Exception) as e:
        identity.finish_reset(res["session_token"], code, "short")
    assert e.value.detail["code"] == "password_too_short"


def test_forgot_route_is_public_and_sends_telegram(monkeypatch, db):
    from fastapi.testclient import TestClient

    import main
    sent = []
    monkeypatch.setattr("app.notifications.telegram_bot.enqueue", lambda chat, text, urgent=False, **k: sent.append(chat))
    r = TestClient(main.app).post("/api/v1/auth/password/forgot", json={"identifier": "ana"})
    assert r.status_code == 200 and r.json()["session_token"] and sent == ["777"]
