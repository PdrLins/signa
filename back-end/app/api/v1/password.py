"""Forgot password (public, rate-limited like sign-in; app/services/identity.py).

  POST /api/v1/auth/password/forgot   {"identifier": username or email}
       200 {"session_token", "message"}   always the same answer (no account
       enumeration). The 6-digit code goes to the account's verified email,
       else to its Telegram two-step chat; an account with neither can't
       reset by itself (support). At most 3 codes an hour per account.
  POST /api/v1/auth/password/reset    {"session_token", "code", "new_password"}
       200 {"message"}: password changed, every device signed out (sign in
       again). Wrong, expired or used code: the same errors as sign-in codes (401 / 422) ·
       422 password_too_short | password_too_long.
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.api_errors import run_db_for
from app.services import identity

router = APIRouter(prefix="/auth/password", tags=["Authentication"])


class ForgotBody(BaseModel):
    identifier: str = Field(..., min_length=1, max_length=254)


class ResetBody(BaseModel):
    session_token: str = Field(..., min_length=10, max_length=200)
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")
    new_password: str = Field(..., min_length=1, max_length=256)


@router.post("/forgot")
async def forgot(body: ForgotBody):
    result, telegram = await run_db_for(identity.MIGRATION, identity.start_reset, body.identifier)
    if telegram:
        from app.notifications.messages import msg_for
        from app.notifications.telegram_bot import enqueue
        chat_id, code, lang = telegram
        enqueue(chat_id, msg_for(lang, "user_reset_code", code=code), urgent=True)
    return result


@router.post("/reset")
async def reset(body: ResetBody):
    await run_db_for(identity.MIGRATION, identity.finish_reset, body.session_token, body.code, body.new_password)
    return {"message": "Password changed. Sign in again on every device."}
