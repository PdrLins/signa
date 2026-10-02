"""Incoming Telegram messages: one handler for the webhook and for polling.

process_update(update) handles:
  /start 2fa_<code>   a user setting up two-step sign-in (app/services/two_factor.py)
  /start <code>       a user connecting a notification chat (telegram_notify)
  /<command>          the owner's bot commands (owner chat only)
Everything else is ignored.

Polling (settings.telegram_polling): the webhook needs a public HTTPS
address, which a Mac running Signa locally doesn't have, so "Start" in the
bot would never reach Signa. When polling is on, a background task asks
Telegram for new messages (getUpdates, long poll 25 s). Telegram refuses
getUpdates while a webhook is registered (409): polling then stops by itself
and the webhook keeps working.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx
from loguru import logger

from app.core.config import settings

_poll_task: Optional[asyncio.Task] = None


async def _handle_2fa_start(start_code: str, chat: dict, sender: dict) -> bool:
    from app.services import two_factor

    if (chat or {}).get("type") != "private" or not chat.get("id"):
        return False
    chat_id = str(chat["id"])
    uname = sender.get("username")
    label = f"@{uname}" if uname else (sender.get("first_name") or "Telegram")
    try:
        found = await asyncio.to_thread(two_factor.chat_pressed_start, start_code, chat_id, label)
    except Exception as e:  # before migration 020, or DB down
        logger.warning(f"two-step: start failed: {type(e).__name__}")
        found = None
    if found:
        user_id, code = found
        return await two_factor.send(chat_id, "user_2fa_code", user_id, code=code)
    from app.notifications.messages import msg_for
    from app.services.telegram_notify import send
    lang = "pt" if str(sender.get("language_code") or "").startswith("pt") else "en"
    return await send(chat_id, msg_for(lang, "user_2fa_link_expired"))


async def process_update(data: dict[str, Any]) -> None:
    """Handle one Telegram update. Never raises."""
    from app.notifications.telegram_bot import handle_command, send_message

    try:
        message = data.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        text = message.get("text") or ""
        if not isinstance(text, str):
            return

        if text.startswith("/start "):
            code = text.split(maxsplit=1)[1].strip()
            if code.startswith("2fa_"):
                await _handle_2fa_start(code[4:], message.get("chat") or {}, message.get("from") or {})
                return
            # a user connecting their notification chat (telegram_notify)
            from app.services.telegram_notify import handle_start
            if await handle_start(code, message.get("chat") or {}, message.get("from") or {}):
                return

        # Only the bot owner may run commands
        if str(chat_id) != settings.telegram_chat_id:
            return
        if text.startswith("/"):
            parts = text.split(maxsplit=1)
            command = parts[0].lstrip("/").split("@")[0]
            args = parts[1] if len(parts) > 1 else ""
            from app.db import queries as db_queries
            tg_user = db_queries.get_user_by_telegram_chat_id(str(chat_id))
            user_id = tg_user["id"] if tg_user else ""
            response_text = await handle_command(command, args, user_id=user_id)
            if chat_id and response_text:
                await send_message(str(chat_id), response_text)
    except Exception:
        logger.exception("Telegram update error")


async def _poll_loop() -> None:
    from app.notifications.telegram_bot import _telegram_url

    offset: Optional[int] = None
    backoff = 2
    async with httpx.AsyncClient(timeout=httpx.Timeout(35.0, connect=10.0)) as client:
        while True:
            try:
                params: dict[str, Any] = {"timeout": 25, "allowed_updates": '["message"]'}
                if offset is not None:
                    params["offset"] = offset
                resp = await client.get(_telegram_url("getUpdates"), params=params)
                if resp.status_code == 409:
                    logger.info("telegram: a webhook is set, so polling stops (the webhook receives messages)")
                    return
                if resp.status_code == 401:
                    logger.warning("telegram: polling stopped, TELEGRAM_BOT_TOKEN is not valid (401)")
                    return
                if resp.status_code != 200:
                    raise httpx.HTTPStatusError(f"HTTP {resp.status_code}", request=resp.request, response=resp)
                for upd in resp.json().get("result") or []:
                    offset = int(upd["update_id"]) + 1
                    await process_update(upd)
                backoff = 2
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.debug(f"telegram: poll failed ({type(e).__name__}), retrying in {backoff}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)


def start_polling() -> bool:
    """Start polling when it's on and a bot token is set. True when started."""
    global _poll_task
    if not settings.telegram_polling or not settings.telegram_bot_token:
        return False
    if _poll_task is not None and not _poll_task.done():
        return True
    _poll_task = asyncio.ensure_future(_poll_loop())
    logger.info("telegram: polling for messages (no public webhook needed)")
    return True


async def stop_polling() -> None:
    global _poll_task
    if _poll_task is None or _poll_task.done():
        return
    _poll_task.cancel()
    try:
        await _poll_task
    except asyncio.CancelledError:
        pass
    _poll_task = None
