"""Two-step sign-in (migration 020): app/services/two_factor.py and the
Telegram update router (app/notifications/telegram_updates.py)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.core.security import hash_password
from app.services import two_factor


class _Result:
    def __init__(self, data):
        self.data = data


class MemDB:
    def __init__(self):
        self.tables = {"users": [], "two_factor_setup": [], "telegram_links": []}

    def table(self, name):
        return _Q(self, name)


class _Q:
    def __init__(self, db, name):
        self.db, self.name, self.op, self.payload, self.filters, self.conflict = db, name, "select", None, [], None

    def select(self, *_a, **_k):
        self.op = "select"
        return self

    def update(self, p):
        self.op, self.payload = "update", p
        return self

    def upsert(self, p, on_conflict=None):
        self.op, self.payload, self.conflict = "upsert", p, on_conflict
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, k, v):
        self.filters.append(lambda r, k=k, v=v: str(r.get(k)) == str(v))
        return self

    def neq(self, k, v):
        self.filters.append(lambda r, k=k, v=v: str(r.get(k)) != str(v))
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
        if self.op == "delete":
            self.db.tables[self.name] = [r for r in rows if r not in match]
            return _Result([dict(r) for r in match])
        key = self.conflict
        existing = [r for r in rows if str(r.get(key)) == str(self.payload.get(key))]
        if existing:
            existing[0].update(self.payload)
            return _Result([dict(existing[0])])
        rows.append(dict(self.payload))
        return _Result([dict(self.payload)])


UID = str(uuid.uuid4())
OWNER = str(uuid.uuid4())


@pytest.fixture
def db(monkeypatch):
    mem = MemDB()
    mem.tables["users"] = [
        {"id": UID, "username": "ana", "password_hash": hash_password("correct horse"), "access_level": "free",
         "telegram_chat_id": None, "two_factor_method": None},
        {"id": OWNER, "username": "pedro", "password_hash": hash_password("owner pass 1"), "access_level": "owner",
         "telegram_chat_id": "999", "two_factor_method": "telegram"},
    ]
    monkeypatch.setattr(two_factor, "_db", lambda: mem)
    monkeypatch.setattr(settings, "telegram_bot_token", "123:abc")
    return mem


def _code_from_start(url: str) -> str:
    return url.split("start=2fa_", 1)[1]


def test_is_enabled_rules():
    assert two_factor.is_enabled({"telegram_chat_id": "1", "two_factor_method": "telegram"})
    assert not two_factor.is_enabled({"telegram_chat_id": "1", "two_factor_method": None})
    assert not two_factor.is_enabled({"telegram_chat_id": None, "two_factor_method": "telegram"})
    assert two_factor.is_enabled({"telegram_chat_id": "1"})               # before 020: chat = on
    assert not two_factor.is_enabled({"telegram_chat_id": None})


def test_full_setup_with_link(db):
    view, target = two_factor.start_telegram(UID, "SignaBot", False, "correct horse")
    assert view["step"] == "open_telegram" and target is None
    assert view["url"].startswith("https://t.me/SignaBot?start=2fa_")
    st = two_factor.status_payload(UID, "SignaBot")
    assert st["enabled"] is False and st["setup"]["step"] == "open_telegram" and st["sms"] == {"available": False}

    user_id, code = two_factor.chat_pressed_start(_code_from_start(view["url"]), "555", "@ana")
    assert user_id == UID and len(code) == 6
    assert two_factor.chat_pressed_start(_code_from_start(view["url"]), "555", "@ana") is None   # link is single use
    assert two_factor.status_payload(UID, "SignaBot")["setup"]["step"] == "enter_code"

    with pytest.raises(HTTPException) as e:
        two_factor.confirm(UID, "000000" if code != "000000" else "111111")
    assert e.value.status_code == 422 and e.value.detail["attempts_remaining"] == 2

    assert two_factor.confirm(UID, code) == "555"
    u = db.tables["users"][0]
    assert u["telegram_chat_id"] == "555" and u["two_factor_method"] == "telegram"
    assert db.tables["two_factor_setup"] == []
    st = two_factor.status_payload(UID, "SignaBot")
    assert st["enabled"] and st["can_disable"] and st["setup"] is None


def test_use_connected_notification_chat(db):
    db.tables["telegram_links"].append({"user_id": UID, "chat_id": "777", "username": "@ana"})
    assert two_factor.status_payload(UID, "SignaBot")["telegram"]["connected_chat"] == "@ana"
    view, (chat, code) = two_factor.start_telegram(UID, "SignaBot", True, "correct horse")
    assert view["step"] == "enter_code" and chat == "777"
    assert two_factor.confirm(UID, code) == "777"


def test_three_wrong_codes_end_setup(db):
    view, _ = two_factor.start_telegram(UID, "SignaBot", False, "correct horse")
    _, code = two_factor.chat_pressed_start(_code_from_start(view["url"]), "555", None)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(2):
        with pytest.raises(HTTPException):
            two_factor.confirm(UID, wrong)
    with pytest.raises(HTTPException) as e:
        two_factor.confirm(UID, wrong)
    assert e.value.status_code == 410
    with pytest.raises(HTTPException) as e:
        two_factor.confirm(UID, code)                                      # even the right one is gone
    assert e.value.status_code == 410


def test_expired_link_and_chat_in_use(db):
    view, _ = two_factor.start_telegram(UID, "SignaBot", False, "correct horse")
    db.tables["two_factor_setup"][0]["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    assert two_factor.chat_pressed_start(_code_from_start(view["url"]), "555", None) is None
    view, _ = two_factor.start_telegram(UID, "SignaBot", False, "correct horse")
    _, code = two_factor.chat_pressed_start(_code_from_start(view["url"]), "999", None)   # the owner's chat
    with pytest.raises(HTTPException) as e:
        two_factor.confirm(UID, code)
    assert e.value.detail["code"] == "chat_in_use"


def test_disable_rules(db):
    with pytest.raises(HTTPException) as e:
        two_factor.disable(OWNER, "owner pass 1")
    assert e.value.detail["code"] == "owner_cannot_disable"
    db.tables["users"][0].update({"telegram_chat_id": "555", "two_factor_method": "telegram"})
    with pytest.raises(HTTPException) as e:
        two_factor.disable(UID, "nope")
    assert e.value.detail["code"] == "wrong_password"
    assert two_factor.disable(UID, "correct horse") == "555"
    assert db.tables["users"][0]["two_factor_method"] is None and db.tables["users"][0]["telegram_chat_id"] is None


def test_start_needs_a_bot(db, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    with pytest.raises(HTTPException) as e:
        two_factor.start_telegram(UID, None, False)
    assert e.value.detail["code"] == "telegram_not_configured"
    assert two_factor.status_payload(UID, None)["telegram"]["available"] is False


@pytest.mark.asyncio
async def test_update_router_sends_2fa_code(db, monkeypatch):
    from app.notifications import telegram_updates
    sent = []

    async def fake_send(chat_id, key, user_id, **kw):
        sent.append((chat_id, key, kw.get("code")))
        return True
    monkeypatch.setattr(two_factor, "send", fake_send)
    view, _ = two_factor.start_telegram(UID, "SignaBot", False, "correct horse")
    await telegram_updates.process_update({"message": {
        "text": f"/start 2fa_{_code_from_start(view['url'])}",
        "chat": {"id": 555, "type": "private"}, "from": {"username": "ana"}}})
    assert sent and sent[0][0] == "555" and sent[0][1] == "user_2fa_code" and len(sent[0][2]) == 6
    assert two_factor.status_payload(UID, "SignaBot")["setup"]["chat_label"] == "@ana"


def test_start_needs_the_password(db):
    with pytest.raises(HTTPException) as e:
        two_factor.start_telegram(UID, "SignaBot", False)
    assert e.value.detail["code"] == "password_required"
    with pytest.raises(HTTPException) as e:
        two_factor.start_telegram(UID, "SignaBot", False, "wrong")
    assert e.value.status_code == 403 and e.value.detail["code"] == "wrong_password"


def test_resend_cooldown_and_keeps_attempts(db):
    two_factor._resend_last.clear()
    two_factor._resend_hour.clear()
    view, _ = two_factor.start_telegram(UID, "SignaBot", False, "correct horse")
    two_factor.chat_pressed_start(_code_from_start(view["url"]), "555", None)
    two_factor.resend(UID)
    with pytest.raises(HTTPException) as e:
        two_factor.resend(UID)                      # within 60 s
    assert e.value.status_code == 429 and e.value.detail["code"] == "resend_too_soon"
    two_factor._resend_last.clear()
    two_factor._resend_hour.clear()
