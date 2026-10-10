"""TELEGRAM_ENABLED=false (the default): nobody can connect or use Telegram,
nothing is sent, two-step via Telegram and Telegram reset codes are off."""

import asyncio

import pytest
from fastapi import HTTPException

from app.core.config import Settings, settings
from app.notifications import telegram_bot
from app.services import identity, telegram_notify, two_factor
from tests import test_password_reset as pr

UID = pr.UID
db = pr.db   # the in-memory users / codes fixture


@pytest.fixture
def off(monkeypatch):
    monkeypatch.setattr(settings, "telegram_enabled", False)
    monkeypatch.setattr(settings, "telegram_bot_token", "123:token")


def test_off_by_default_and_needs_a_token(monkeypatch):
    assert Settings.model_fields["telegram_enabled"].default is False
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    assert not settings.telegram_active   # on, but no bot token
    monkeypatch.setattr(settings, "telegram_bot_token", "123:token")
    assert settings.telegram_active


def test_nothing_is_sent(off, monkeypatch):
    def no_http():
        raise AssertionError("Telegram called while off")
    monkeypatch.setattr(telegram_bot, "_get_http_client", no_http)
    monkeypatch.setattr(telegram_bot, "_get_queue", no_http)
    telegram_bot.enqueue("777", "hi")
    assert asyncio.run(telegram_bot.send_message("777", "hi", urgent=True)) is False
    assert asyncio.run(telegram_bot.send_otp_message("777", "123456")) is False
    assert asyncio.run(telegram_notify.bot_username()) is None


def test_two_step_and_linking_are_unavailable(off):
    # an account that turned two-step on signs in with the password only
    assert not two_factor.is_enabled({"telegram_chat_id": "1", "two_factor_method": "telegram"})
    for call in (lambda: two_factor.start_telegram(UID, "SignaBot", False, "pw"),
                 lambda: telegram_notify.create_link({"user_id": UID}, "SignaBot")):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 503 and e.value.detail["code"] == "telegram_not_configured"


def test_no_reset_code_by_telegram(off, db):
    result, telegram = identity.start_reset("ana")   # Telegram chat only, no email
    assert telegram is None and result["message"] == identity.RESET_MESSAGE


def test_webhook_is_closed(off):
    from fastapi.testclient import TestClient

    import main
    r = TestClient(main.app).post("/api/v1/telegram/webhook", json={},
                                  headers={"X-Telegram-Bot-Api-Secret-Token": "x"})
    assert r.status_code == 404
