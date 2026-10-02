"""Two-step sign-in (migration 020) — app/services/two_factor.py.

  GET    /api/v1/auth/2fa
         {"enabled": bool, "method": "telegram" | "sms" | null, "can_disable": bool,
          "telegram": {"available": bool, "bot_username": str | null,
                       "connected_chat": str | null},   # notification chat label, offer "Use @name"
          "sms": {"available": false},                    # no provider yet
          "setup": null | Setup}
  POST   /api/v1/auth/2fa/telegram/start   {"use_connected_chat": bool = false} → Setup
  POST   /api/v1/auth/2fa/telegram/resend  → Setup (a new code to the same chat)
  POST   /api/v1/auth/2fa/telegram/confirm {"code": "123456"} → {"enabled": true, "method": "telegram"}
  DELETE /api/v1/auth/2fa/setup            → 204 (cancel a setup)
  POST   /api/v1/auth/2fa/disable          {"password"} → {"enabled": false}

  Setup = {"step": "open_telegram" | "enter_code", "url": str | null,
           "chat_label": str | null, "expires_at": ISO}
    open_telegram: open `url` (t.me/<bot>?start=2fa_<code>), press Start;
      clients poll GET /auth/2fa (every ~3 s) until step is "enter_code".
      `url` is only returned by /telegram/start (single use, never stored).
    enter_code: the bot sent a 6-digit code to `chat_label`.

Errors {"detail": {"code", "message", ...}}: 503 telegram_not_configured
(no bot on this server) | migration_required; 409 already_enabled |
not_connected | chat_in_use | owner_cannot_disable; 410 setup_expired;
422 invalid_code (+ attempts_remaining); 403 wrong_password.
All routes: area.profile (every signed-in user).
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Response, status
from pydantic import BaseModel, Field

from app.core.access import require_feature
from app.core.api_errors import api_error, run_db_for
from app.core.dependencies import get_current_user
from app.services import telegram_notify, two_factor

router = APIRouter(prefix="/auth/2fa", tags=["Two-step sign-in"],
                   dependencies=[Depends(require_feature("area.profile"))])


class StartBody(BaseModel):
    use_connected_chat: bool = False


class ConfirmBody(BaseModel):
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class DisableBody(BaseModel):
    password: str = Field(..., min_length=1, max_length=128)


async def _db(fn, *args):
    return await run_db_for(two_factor.MIGRATION, fn, *args)


@router.get("")
async def get_status(user: dict = Depends(get_current_user)):
    bot = await telegram_notify.bot_username()
    return await _db(two_factor.status_payload, user["user_id"], bot)


async def _send_code(target, user_id: str) -> None:
    if not target:
        return
    chat_id, code = target
    if not await two_factor.send(chat_id, "user_2fa_code", user_id, code=code):
        raise api_error("telegram_send_failed", "Telegram didn't accept the message. Try again.",
                        status.HTTP_502_BAD_GATEWAY)


@router.post("/telegram/start")
async def start(body: StartBody = Body(default_factory=StartBody), user: dict = Depends(get_current_user)):
    bot = await telegram_notify.bot_username()
    view, target = await _db(two_factor.start_telegram, user["user_id"], bot, body.use_connected_chat)
    await _send_code(target, user["user_id"])
    return view


@router.post("/telegram/resend")
async def resend(user: dict = Depends(get_current_user)):
    view, target = await _db(two_factor.resend, user["user_id"])
    await _send_code(target, user["user_id"])
    return view


@router.post("/telegram/confirm")
async def confirm(body: ConfirmBody, user: dict = Depends(get_current_user)):
    chat_id = await _db(two_factor.confirm, user["user_id"], body.code)
    await two_factor.send(chat_id, "user_2fa_on", user["user_id"])
    return {"enabled": True, "method": "telegram"}


@router.delete("/setup", status_code=status.HTTP_204_NO_CONTENT)
async def cancel(user: dict = Depends(get_current_user)):
    await _db(two_factor.cancel, user["user_id"])
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/disable")
async def disable(body: DisableBody, user: dict = Depends(get_current_user)):
    old_chat = await _db(two_factor.disable, user["user_id"], body.password)
    if old_chat:
        await two_factor.send(old_chat, "user_2fa_off", user["user_id"])
    return {"enabled": False}
