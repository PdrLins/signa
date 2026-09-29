"""Brain unlock: Telegram code when Telegram is configured, fallback code otherwise."""

import pytest

from app.api.v1 import brain
from app.core.config import settings


@pytest.fixture
def telegram(monkeypatch):
    def set_(token="7123456789:AAHrealLookingToken_abcdefghij", chat="987654321", enabled=True):
        monkeypatch.setattr(settings, "telegram_bot_token", token)
        monkeypatch.setattr(settings, "telegram_chat_id", chat)
        monkeypatch.setattr(settings, "brain_otp_enabled", enabled)
    return set_


def test_configured_telegram_is_used(telegram):
    telegram()
    assert brain.brain_otp_via_telegram() is True


@pytest.mark.parametrize("token,chat", [
    ("", "987654321"),                 # no token
    ("123456:ABC-DEF", "123456789"),   # .env.example placeholders
    ("7123456789:AAHreal", ""),        # no chat id
])
def test_unconfigured_telegram_uses_fallback(telegram, token, chat):
    telegram(token=token, chat=chat)
    assert brain.brain_otp_via_telegram() is False


def test_switch_off_uses_fallback_even_when_configured(telegram):
    telegram(enabled=False)
    assert brain.brain_otp_via_telegram() is False


def test_fallback_code_default():
    assert settings.brain_otp_fallback_code == "123456"
