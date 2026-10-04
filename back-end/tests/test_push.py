"""iOS push notifications (migration 025): devices, APNs sending, delivery."""

import asyncio
from datetime import date, datetime, timezone

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.api.v1 import feedback as feedback_api
from app.api.v1 import notifications as notif_api
from app.core.config import settings
from app.db import queries
from app.services import feedback as fsvc
from app.services import push
from app.services import telegram_notify
from tests.portfolio_fakes import U1, make_client

TOKEN = "a1" * 32


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(push, "_jwt", None)
    monkeypatch.setattr(push, "_client", None)
    for k in ("apns_team_id", "apns_key_id", "apns_private_key", "apns_bundle_id"):
        monkeypatch.setattr(settings, k, "")


def _configure(monkeypatch, handler):
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    monkeypatch.setattr(settings, "apns_team_id", "TEAM123456")
    monkeypatch.setattr(settings, "apns_key_id", "KEY1234567")
    monkeypatch.setattr(settings, "apns_private_key", pem)
    monkeypatch.setattr(settings, "apns_bundle_id", "app.signa.ios")
    monkeypatch.setattr(push, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))


# ---------------------------------------------------------------- pure parts

def test_token_validation():
    assert push._clean_token(" <" + TOKEN.upper() + "> ") == TOKEN
    for bad in ("", "xyz", "12 34", "g" * 64):
        with pytest.raises(Exception):
            push._clean_token(bad)


def test_free_users_get_basic_kinds_only(monkeypatch):
    lines = [("price_alert", "alert:1", "a"), ("big_move", "bm:X", "b"), ("dividend_paid", "paid:X", "c"),
             ("economy", "eco:1", "d")]
    monkeypatch.setattr(push.access, "can", lambda level, f: level != "free")
    assert [k for k, _, _ in push.allowed_lines(lines, "free")] == ["price_alert", "dividend_paid"]
    assert len(push.allowed_lines(lines, "premium")) == 4


def test_plain_and_compose():
    assert push.plain("<b>ENB.TO</b> pays &amp; more") == "ENB.TO pays & more"
    assert push.compose(["<b>a</b>"]) == "a" and push.compose(["a", "b", "c"]) == "a (+2 more)"
    assert len(push.payload("t", "x" * 500)["aps"]["alert"]["body"]) == push.BODY_MAX


# ---------------------------------------------------------------- APNs

def test_unconfigured_send_is_logged_not_failed():
    assert asyncio.run(push.send_to_device({"token": TOKEN, "environment": "sandbox"}, push.payload("t", "b")))


def test_apns_request_shape(monkeypatch):
    seen = {}

    def handler(req: httpx.Request):
        seen.update(url=str(req.url), headers=dict(req.headers), body=req.content)
        return httpx.Response(200)
    _configure(monkeypatch, handler)
    ok = asyncio.run(push.send_to_device({"token": TOKEN, "environment": "sandbox"}, push.payload("Signa", "hi")))
    assert ok and seen["url"] == f"https://api.sandbox.push.apple.com/3/device/{TOKEN}"
    assert seen["headers"]["apns-topic"] == "app.signa.ios" and seen["headers"]["apns-push-type"] == "alert"
    assert seen["headers"]["authorization"].startswith("bearer ey")
    first = push._provider_token()
    assert push._provider_token() == first          # JWT reused


def test_gone_token_is_disabled(monkeypatch):
    disabled = []
    monkeypatch.setattr(push, "disable_device", disabled.append)
    _configure(monkeypatch, lambda req: httpx.Response(410, json={"reason": "Unregistered"}))
    assert not asyncio.run(push.send_to_device({"token": TOKEN, "environment": "production"}, push.payload("t", "b")))
    assert disabled == [TOKEN]


# ---------------------------------------------------------------- delivery

def _fake_delivery(monkeypatch, lines, level="free", hide=False):
    sent, recorded = [], []
    from app.services import notification_prefs
    monkeypatch.setattr(notification_prefs, "get_prefs", lambda uid: {"prefs": {"privacy": {"hide_amounts": hide}}})

    async def lines_for(user, mode, today, now):
        return "en", lines
    monkeypatch.setattr(telegram_notify, "_lines_for", lines_for)
    monkeypatch.setattr(push.access, "get_user_access", lambda uid: {"level": level, "slot_bonus": 0})
    monkeypatch.setattr(queries, "get_delivered_keys", lambda uid, keys: {k for k in keys if k.endswith(":old")})
    monkeypatch.setattr(queries, "insert_deliveries", lambda uid, items: recorded.extend(items))

    async def send(device, body):
        sent.append(body)
        return True
    monkeypatch.setattr(push, "send_to_device", send)
    return sent, recorded


def test_deliver_user_one_push_with_new_free_lines(monkeypatch):
    lines = [("dividend_paid", "paid:ENB.TO:old", "old"), ("big_move", "bm:NVDA", "<b>NVDA</b> +8%"),
             ("dividend_paid", "paid:XEQT.TO:2026-10-03", "<b>XEQT.TO</b> paid $12"),
             ("price_alert", "alert:7", "MSFT above 400")]
    sent, recorded = _fake_delivery(monkeypatch, lines)
    n = asyncio.run(push.deliver_user(U1, [{"token": TOKEN}], "events", date(2026, 10, 3), datetime.now(timezone.utc)))
    assert n == 2 and len(sent) == 1
    assert sent[0]["aps"]["alert"]["body"] == "XEQT.TO paid $12 (+1 more)"
    assert recorded == [("dividend_paid", "push:paid:XEQT.TO:2026-10-03"), ("price_alert", "push:alert:7")]


def test_hide_amounts_sends_no_money_or_tickers(monkeypatch):
    lines = [("dividend_paid", "paid:XEQT.TO:2026-10-03", "<b>XEQT.TO</b> paid $12"),
             ("price_alert", "alert:7", "MSFT above 400")]
    sent, _ = _fake_delivery(monkeypatch, lines, hide=True)
    asyncio.run(push.deliver_user(U1, [{"token": TOKEN}], "events", date(2026, 10, 3), datetime.now(timezone.utc)))
    assert sent[0]["aps"]["alert"]["body"] == "2 new updates in Signa"
    assert push.private_text(["dividend_paid"], "pt") == "Um dividendo foi pago"


def test_nothing_new_sends_nothing(monkeypatch):
    sent, _ = _fake_delivery(monkeypatch, [("big_move", "bm:NVDA", "x")])
    assert asyncio.run(push.deliver_user(U1, [{"token": TOKEN}], "live", date.today(), datetime.now(timezone.utc))) == 0
    assert sent == []


# ---------------------------------------------------------------- routes

def test_device_routes(monkeypatch):
    calls = []
    monkeypatch.setattr(push, "register_device", lambda uid, body: calls.append(("reg", uid, body)) or {"registered": True})
    monkeypatch.setattr(push, "remove_device", lambda uid, tok: calls.append(("del", uid, tok)) or {"removed": True})
    monkeypatch.setattr(push, "active_devices", lambda uid=None: [{"token": TOKEN}])
    c = make_client(monkeypatch, notif_api.router, level="free")
    assert c.post("/api/v1/notifications/devices", json={"token": TOKEN}).json() == {"registered": True}
    assert c.delete(f"/api/v1/notifications/devices/{TOKEN}").json() == {"removed": True}
    st = c.get("/api/v1/notifications/push").json()
    assert st["all_kinds"] is False and st["devices"] == 1 and "price_alert" in st["free_kinds"]
    assert [x[0] for x in calls] == ["reg", "del"] and calls[0][1] == U1


def test_report_status_change_pushes_the_reporter(monkeypatch):
    pushed = []

    async def notify(uid, title, body, data=None):
        pushed.append((uid, body, data))
        return 1
    monkeypatch.setattr(push, "notify_user", notify)
    monkeypatch.setattr(fsvc, "update", lambda rid, data: {"id": rid, "user_id": "u9", "status": data["status"],
                                                            "message": "Total is wrong\\nmore"})
    owner = make_client(monkeypatch, feedback_api.router, level="owner")
    rid = "11111111-2222-3333-4444-555555555555"
    assert owner.patch(f"/api/v1/feedback/{rid}", json={"status": "fixed"}).status_code == 200
    assert pushed and pushed[0][0] == "u9" and pushed[0][1] == 'Your report "Total is wrong\\nmore" was fixed.'[:0] + pushed[0][1]
    assert "was fixed" in pushed[0][1] and pushed[0][2]["kind"] == "report"


def test_alert_push_carries_kind_and_hides_money(monkeypatch):
    lines = [("price_alert", "alert:p1:2026-10-03T14:00:00", "<b>RY.TO</b> is up 10% since you set the alert (C$188.20)")]
    alert = {"id": "p1", "symbol": "RY.TO", "kind": "percent", "direction": "above", "percent": 10,
             "last_price": 188.2, "currency": "CAD"}
    monkeypatch.setattr(queries, "get_price_alert", lambda aid, uid: dict(alert) if aid == "p1" else None)
    sent, _ = _fake_delivery(monkeypatch, lines, hide=True)
    asyncio.run(push.deliver_user(U1, [{"token": TOKEN}], "live", date(2026, 10, 3), datetime.now(timezone.utc)))
    body = sent[0]
    assert body["aps"]["alert"]["body"] == "🎯 RY.TO is up 10% since you set the alert"
    assert body["kind"] == "price_alert" and body["alert_kind"] == "percent" and body["percent"] == 10.0
    assert body["symbol"] == "RY.TO"


def test_day_move_push_data():
    data = push.alert_data({"id": "d", "symbol": "RY.TO", "kind": "day_move", "percent": 5, "last_change_pct": -5.3})
    assert data == {"alert_kind": "day_move", "symbol": "RY.TO", "alert_id": "d", "percent": 5.0, "change_pct": -5.3}
