"""In-memory fakes for referrals / invite-only sign-up (migration 019).

`ReferralDB` is just enough of supabase-py for app/services/referrals.py and
app/services/registration.py (users + referrals: select / insert / update
with eq filters, UNIQUE username / account_id / referred_id). `missing=True`
makes every call fail like a database without migration 019.

`register_client(monkeypatch, db)` returns a TestClient on the real app with
sessions (migration 017) faked in memory, audit/last-login writes stubbed
and the rate limiter reset.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import bcrypt

from app.services import referrals

REFERRER_ID = "33333333-3333-3333-3333-333333333333"
REFERRER_CODE = "K7M2QX9A"


class _Result:
    def __init__(self, data):
        self.data = data


class ReferralDB:
    UNIQUE = {"users": ("username", "account_id"), "referrals": ("referred_id",)}

    def __init__(self):
        self.tables: dict[str, list[dict]] = {"users": [], "referrals": []}
        self.missing = False

    def table(self, name):
        if self.missing:
            raise RuntimeError('column users.account_id does not exist (42703)')
        if name not in self.tables:
            raise RuntimeError(f'relation "{name}" does not exist (42P01)')
        return _Q(self, name)

    # ---- seeding helpers
    def add_user(self, username: str, account_id: str | None = None, uid: str | None = None,
                 is_active: bool = True, **extra) -> dict:
        row = {"id": uid or str(uuid.uuid4()), "username": username, "password_hash": "x",
               "telegram_chat_id": None, "access_level": "free", "is_active": is_active,
               "account_id": account_id or referrals.new_account_id(), "referred_by": None,
               "last_login": None, "created_at": datetime.now(timezone.utc).isoformat(), **extra}
        self.tables["users"].append(row)
        return row

    def add_referral(self, referrer_id: str, referred_id: str, status: str = "pending") -> dict:
        row = {"id": str(uuid.uuid4()), "referrer_id": referrer_id, "referred_id": referred_id,
               "status": status, "created_at": datetime.now(timezone.utc).isoformat(),
               "rewarded_at": datetime.now(timezone.utc).isoformat() if status == "rewarded" else None}
        self.tables["referrals"].append(row)
        return row

    def user(self, username: str) -> dict | None:
        return next((u for u in self.tables["users"] if u["username"] == username), None)


class _Q:
    def __init__(self, db: ReferralDB, name: str):
        self.db, self.name, self.op, self.payload, self.filters, self._limit = db, name, None, None, [], None

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

    def limit(self, n):
        self._limit = n
        return self

    def order(self, *_a, **_k):
        return self

    def execute(self):
        rows = self.db.tables[self.name]
        match = [r for r in rows if all(f(r) for f in self.filters)]
        if self.op == "select":
            out = [dict(r) for r in match]
            return _Result(out[: self._limit] if self._limit else out)
        if self.op == "update":
            for r in match:
                r.update(self.payload)
            return _Result([dict(r) for r in match])
        row = dict(self.payload)
        for col in self.UNIQUE_COLS():
            if row.get(col) is not None and any(r.get(col) == row[col] for r in rows):
                raise RuntimeError(f'duplicate key value violates unique constraint "{self.name}_{col}_key" (23505)')
        now = datetime.now(timezone.utc).isoformat()
        if self.name == "users":
            row = {"id": str(uuid.uuid4()), "last_login": None, "created_at": now, **row}
        else:
            row = {"id": str(uuid.uuid4()), "created_at": now, "rewarded_at": None, **row}
        rows.append(row)
        return _Result([dict(row)])

    def UNIQUE_COLS(self):
        return ReferralDB.UNIQUE.get(self.name, ())


def use(monkeypatch, db: ReferralDB | None = None) -> ReferralDB:
    """Point app/services/referrals.py (and registration) at an in-memory DB."""
    db = db or ReferralDB()
    monkeypatch.setattr(referrals, "_db", lambda: db)
    referrals.clear_caches()
    return db


def register_client(monkeypatch, db: ReferralDB, sessions_db=None):
    """TestClient on main.app for /auth/register + /auth/referral/{code}."""
    from fastapi.testclient import TestClient

    import main
    from app.db import queries
    from app.middleware import rate_limit
    from app.services import sessions
    from tests.test_sessions import MemDB

    use(monkeypatch, db)
    sdb = sessions_db or MemDB()
    monkeypatch.setattr(sessions, "_db", lambda: sdb)
    monkeypatch.setattr(sessions, "_level", lambda uid: "free")
    monkeypatch.setattr(queries, "insert_audit_log", lambda **k: None)
    monkeypatch.setattr(queries, "update_user_last_login", lambda uid: None)
    monkeypatch.setattr("app.middleware.rate_limit.insert_audit_log", lambda **k: None)
    monkeypatch.setattr("app.middleware.auth.insert_audit_log", lambda **k: None)
    fast = bcrypt.gensalt  # cheap hashes in tests (same $2b$ format)
    monkeypatch.setattr(bcrypt, "gensalt", lambda rounds=12, prefix=b"2b": fast(4, prefix))
    for store in rate_limit._attempts.values():
        store.clear()
    rate_limit._blocked.clear()
    return TestClient(main.app)
