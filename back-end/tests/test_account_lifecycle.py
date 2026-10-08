"""Delete my account (30-day grace / now), restore at sign-in, export
(migration 030, app/services/account.py)."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.core.security import hash_password
from app.services import account

UID = "11111111-1111-1111-1111-111111111111"


class _Res:
    def __init__(self, data):
        self.data = data


class MemDB:
    """users / push_devices / audit_logs / feedback_reports / reserved_usernames in memory."""

    def __init__(self):
        self.tables = {"users": [], "push_devices": [], "audit_logs": [], "feedback_reports": [],
                       "reserved_usernames": [], "auth_sessions": [], "holdings": []}
        self.deleted_users = []

    def table(self, name):
        return _Q(self, name)


class _Q:
    def __init__(self, db, name):
        self.db, self.name, self.op, self.payload, self.filters = db, name, "select", None, []

    def select(self, *a, **k):
        return self

    def update(self, payload, **k):
        self.op, self.payload = "update", payload
        return self

    def delete(self, **k):
        self.op = "delete"
        return self

    def upsert(self, payload, **k):
        self.op, self.payload = "upsert", payload
        return self

    def eq(self, k, v):
        self.filters.append(lambda r: str(r.get(k)) == str(v))
        return self

    def lt(self, k, v):
        self.filters.append(lambda r: r.get(k) is not None and str(r[k]) < str(v))
        return self

    def gt(self, k, v):
        self.filters.append(lambda r: r.get(k) is not None and str(r[k]) > str(v))
        return self

    def is_(self, *a):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a):
        return self

    def range(self, *a):
        return self

    def execute(self):
        rows = self.db.tables[self.name]
        match = [r for r in rows if all(f(r) for f in self.filters)]
        if self.op == "update":
            for r in match:
                r.update(self.payload)
        elif self.op == "delete":
            for r in match:
                rows.remove(r)
            if self.name == "users":
                self.db.deleted_users += [r["id"] for r in match]
        elif self.op == "upsert":
            rows.append(dict(self.payload))
        return _Res([dict(r) for r in match])


@pytest.fixture
def db(monkeypatch):
    mem = MemDB()
    mem.tables["users"].append({"id": UID, "username": "ana", "password_hash": hash_password("correct horse"),
                                "access_level": "free", "deletion_scheduled_at": None})
    mem.tables["push_devices"].append({"user_id": UID, "token": "a" * 64})
    mem.tables["audit_logs"].append({"user_id": UID, "event_type": "LOGIN"})
    mem.tables["feedback_reports"].append({"user_id": UID, "diagnostics": {"x": 1}, "device_model": "iPhone"})
    monkeypatch.setattr(account, "_db", lambda: mem)
    monkeypatch.setattr("app.services.sessions.revoke_others", lambda uid, keep, reason="others": 2)
    monkeypatch.setattr(account, "_audit", lambda *a, **k: None)
    return mem


def test_delete_with_grace_signs_out_and_removes_devices(db):
    out = account.request_deletion(UID, "correct horse")
    assert out["status"] == "pending_deletion"
    when = datetime.fromisoformat(db.tables["users"][0]["deletion_scheduled_at"])
    assert 29 <= (when - datetime.now(timezone.utc)).days <= 30
    assert db.tables["push_devices"] == [] and db.deleted_users == []
    assert account.pending_deletion_date(db.tables["users"][0]) == out["deletion_date"]


def test_delete_now_anonymizes_and_holds_the_username(db):
    assert account.request_deletion(UID, "correct horse", now=True) == {"status": "deleted"}
    assert db.deleted_users == [UID]
    assert db.tables["audit_logs"][0]["user_id"] is None
    assert db.tables["feedback_reports"][0]["diagnostics"] is None
    assert db.tables["feedback_reports"][0]["device_model"] is None
    assert db.tables["reserved_usernames"][0]["username"] == "ana"


def test_wrong_password_and_owner_refused(db):
    with pytest.raises(HTTPException) as e:
        account.request_deletion(UID, "nope")
    assert e.value.status_code == 403 and e.value.detail["code"] == "wrong_password"
    db.tables["users"][0]["access_level"] = "owner"
    with pytest.raises(HTTPException) as e:
        account.request_deletion(UID, "correct horse")
    assert e.value.detail["code"] == "owner_cannot_delete"


def test_restore_and_purge_due(db):
    account.request_deletion(UID, "correct horse")
    account.restore(UID)
    assert db.tables["users"][0]["deletion_scheduled_at"] is None
    db.tables["users"][0]["deletion_scheduled_at"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert account.purge_due() == {"deleted": 1, "failed": 0} and db.deleted_users == [UID]


# ---------------------------------------------------------------- sign-in

@pytest.mark.asyncio
async def test_sign_in_asks_before_restoring(monkeypatch):
    from app.core.config import settings
    from app.services import auth_service
    from tests.test_sec_auth import KNOWN_HASH, KNOWN_PASSWORD, FakeClient, FakeQueries
    from app.db import supabase as supa
    when = (datetime.now(timezone.utc) + timedelta(days=20)).isoformat()
    user = {"id": "u1", "username": "pedro", "password_hash": KNOWN_HASH, "telegram_chat_id": "1",
            "login_attempts": 0, "locked_until": None, "deletion_scheduled_at": when}
    fq = FakeQueries()
    fq.get_user_by_username = lambda u: dict(user)
    fq.update_user_last_login = lambda uid: None
    monkeypatch.setattr(auth_service, "queries", fq)
    monkeypatch.setattr(supa, "get_client", lambda: FakeClient([]))
    monkeypatch.setattr(settings, "login_otp_enabled", False)
    restored = []
    monkeypatch.setattr(account, "restore", lambda uid: restored.append(uid))
    auth_service._device_failures.clear()
    with pytest.raises(HTTPException) as e:
        await auth_service.login("pedro", KNOWN_PASSWORD, "1.2.3.4", "ua")
    assert e.value.status_code == 403 and e.value.detail["code"] == "account_pending_deletion"
    assert e.value.detail["deletion_date"] == when[:10]
    res = await auth_service.login("pedro", KNOWN_PASSWORD, "1.2.3.4", "ua", restore_account=True)
    assert res["access_token"] and restored == ["u1"]


# ---------------------------------------------------------------- export

def test_export_has_everything_and_no_user_ids(db, monkeypatch):
    db.tables["users"][0].update({"account_id": "ABCDEFGH", "created_at": "2026-10-01"})
    db.tables["holdings"].append({"id": "h1", "user_id": UID, "symbol": "ENB.TO", "shares": 10})
    for t in ("user_settings", "notification_prefs", "signup_sources", "portfolio_people", "accounts",
              "transactions", "watchlist", "price_alerts", "goals"):
        db.tables[t] = []
    out = account.export(UID)
    assert out["format"] == "signa-export-1" and out["account"]["username"] == "ana"
    assert out["holdings"] == [{"id": "h1", "symbol": "ENB.TO", "shares": 10}]
    assert "password_hash" not in str(out)


def test_export_includes_fixed_income_and_says_what_is_left_out(db, monkeypatch):
    for t in ("user_settings", "notification_prefs", "signup_sources", "portfolio_people", "accounts",
              "transactions", "watchlist", "price_alerts", "goals", "telegram_links"):
        db.tables[t] = []
    db.tables["fixed_income"] = [{"id": "f1", "user_id": UID, "name": "CDB Inter", "kind": "cdb", "rate": 110},
                                 {"id": "f2", "user_id": "someone-else", "name": "LCI", "kind": "lci"}]
    db.tables["auto_dividend_dismissed"] = [{"user_id": UID, "auto_ref": "auto:a1:ENB.TO:2026-09-20",
                                             "created_at": "2026-10-01"}]
    db.tables["referrals"] = [{"referrer_id": UID, "referred_id": "friend-uuid", "status": "rewarded",
                               "created_at": "2026-09-01", "rewarded_at": "2026-09-10"}]
    db.tables["user_activity_days"] = [{"user_id": UID, "day": "2026-10-06"}]
    out = account.export(UID)
    assert out["fixed_income"] == [{"id": "f1", "name": "CDB Inter", "kind": "cdb", "rate": 110}]
    assert out["dismissed_auto_dividends"] == [{"auto_ref": "auto:a1:ENB.TO:2026-09-20", "created_at": "2026-10-01"}]
    assert out["active_days"] == [{"day": "2026-10-06"}]
    assert out["invites_sent"] and out["telegram"] == []
    assert "IP addresses, browser/app user agents, audit logs" in out["left_out"]
    assert all(name in out for name, *_ in account.EXPORT_TABLES)


# Per-user tables that stay out of the export (see account.EXPORT_LEFT_OUT); a new one must be added here or
# to account.EXPORT_TABLES.
NOT_EXPORTED = {"users", "otp_codes", "token_blacklist", "audit_logs", "portfolio", "portfolio_snapshots",
                "income_forecast_snapshots", "telegram_link_codes", "notification_deliveries", "two_factor_setup",
                "push_devices"}


def test_every_per_user_table_is_exported_or_listed():
    import re
    from pathlib import Path
    schema = (Path(__file__).parent.parent / "app/db/schema.sql").read_text()
    per_user = {m.group(1) for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", schema, re.S)
                if re.search(r"\b(user_id|referrer_id)\b", m.group(2))}
    exported = {table for _, table, *_ in account.EXPORT_TABLES}
    assert per_user - exported - NOT_EXPORTED == set()
