"""iOS push notifications (migration 025): devices, APNs sending, delivery.

Devices
  The app registers its APNs token after sign-in (register_device) and
  removes it on sign-out (remove_device). A token belongs to one user.

Sending (APNs, token auth)
  HTTP/2 POST https://api.push.apple.com/3/device/<token> (sandbox host for
  development builds), a JWT signed with the team's .p8 key (ES256, reused
  for 50 minutes), topic = the app's bundle id. 410 Unregistered or 400
  BadDeviceToken disables the token. Without APNs settings, pushes are only
  logged (development), like the console email sender.

Delivery (scheduler, same runs as Telegram)
  The lines come from the Telegram builders (telegram_notify._lines_for), so
  both channels say the same thing. Free users get the basic kinds (FREE_KINDS:
  dividends, earnings, price alerts); feature.push_all (Premium) gets every
  kind. One push per user per run: the first line as the body and "+N more".
  Deduped per user in notification_deliveries with keys prefixed "push:", so
  Telegram and push don't block each other. notify_user() sends a single
  immediate push (e.g. a problem report changed status).
"""

from __future__ import annotations

import asyncio
import html
import re
import time
from datetime import date, datetime, timezone
from typing import Any

import httpx
from loguru import logger

from app.core import access
from app.core.api_errors import api_error
from app.core.config import settings
from app.db.supabase import get_client

MIGRATION = "025_push_devices.sql"
FEATURE_ALL = "feature.push_all"
FREE_KINDS = {"exdiv_reminder", "dividend_paid", "earnings", "price_alert"}
KEY_PREFIX = "push:"
HOSTS = {"production": "https://api.push.apple.com", "sandbox": "https://api.sandbox.push.apple.com"}
JWT_TTL_S = 50 * 60
TITLE = "Signa"
BODY_MAX = 240

_jwt: tuple[str, float] | None = None
_client: httpx.AsyncClient | None = None


# ---------------------------------------------------------------- devices (blocking)

def _clean_token(token: Any) -> str:
    t = re.sub(r"[\s<>]", "", str(token or "")).lower()
    if not re.fullmatch(r"[0-9a-f]{32,200}", t):
        raise api_error("invalid_token", "That is not an APNs device token.", 422)
    return t


def register_device(user_id: str, body: dict) -> dict:
    token = _clean_token(body.get("token"))
    env = body.get("environment") or "production"
    if env not in HOSTS:
        raise api_error("invalid_environment", "environment must be sandbox or production.", 422)
    row = {"token": token, "user_id": user_id, "platform": "ios", "environment": env,
           "app_version": (str(body["app_version"])[:32] if body.get("app_version") else None),
           "device_name": (str(body["device_name"])[:80] if body.get("device_name") else None),
           "disabled_at": None}
    get_client().table("push_devices").upsert(row, on_conflict="token").execute()
    return {"registered": True, "token": token, "environment": env}


def remove_device(user_id: str, token: str) -> dict:
    t = _clean_token(token)
    get_client().table("push_devices").delete().eq("token", t).eq("user_id", user_id).execute()
    return {"removed": True}


def active_devices(user_id: str | None = None) -> list[dict]:
    from app.db.queries import _select_all_pages

    def build():
        q = get_client().table("push_devices").select("token, user_id, environment").is_("disabled_at", "null")
        return (q.eq("user_id", user_id) if user_id else q).order("token")
    return _select_all_pages(build)


def disable_device(token: str) -> None:
    get_client().table("push_devices").update(
        {"disabled_at": datetime.now(timezone.utc).isoformat()}).eq("token", token).execute()


# ---------------------------------------------------------------- APNs

def configured() -> bool:
    return bool(settings.apns_team_id and settings.apns_key_id and settings.apns_private_key
                and settings.apns_bundle_id)


def _provider_token() -> str:
    global _jwt
    now = time.time()
    if _jwt and now - _jwt[1] < JWT_TTL_S:
        return _jwt[0]
    import jwt as pyjwt

    key = settings.apns_private_key.replace("\\n", "\n")
    tok = pyjwt.encode({"iss": settings.apns_team_id, "iat": int(now)}, key, algorithm="ES256",
                       headers={"kid": settings.apns_key_id})
    _jwt = (tok, now)
    return tok


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(http2=True, timeout=httpx.Timeout(10.0, connect=5.0))
    return _client


def payload(title: str, body: str, data: dict | None = None, badge: int | None = None) -> dict:
    aps: dict = {"alert": {"title": title, "body": body[:BODY_MAX]}, "sound": "default"}
    if badge is not None:
        aps["badge"] = badge
    return {"aps": aps, **(data or {})}


async def send_to_device(device: dict, body: dict) -> bool:
    """True when Apple accepted it. Disables tokens Apple rejects as gone."""
    if not configured():
        logger.info(f"push (not configured, logged only) to {device['token'][:8]}…: {body['aps']['alert']}")
        return True
    url = f"{HOSTS.get(device.get('environment'), HOSTS['production'])}/3/device/{device['token']}"
    headers = {"authorization": f"bearer {_provider_token()}", "apns-topic": settings.apns_bundle_id,
               "apns-push-type": "alert", "apns-priority": "10"}
    try:
        r = await _http().post(url, json=body, headers=headers)
    except Exception as e:
        logger.warning(f"push: APNs request failed: {type(e).__name__}")
        return False
    if r.status_code == 200:
        return True
    reason = ""
    try:
        reason = r.json().get("reason", "")
    except Exception:
        pass
    if r.status_code == 410 or reason in ("BadDeviceToken", "Unregistered", "DeviceTokenNotForTopic"):
        await asyncio.to_thread(disable_device, device["token"])
    logger.warning(f"push: APNs refused ({r.status_code} {reason})")
    return False


async def notify_user(user_id: str, title: str, body: str, data: dict | None = None) -> int:
    """Immediate push to every active device of a user. Never raises; returns devices reached."""
    if not settings.push_notifications_enabled:
        return 0
    try:
        devices = await asyncio.to_thread(active_devices, user_id)
    except Exception as e:
        logger.debug(f"push: devices unavailable ({type(e).__name__})")
        return 0
    sent = 0
    for d in devices:
        sent += 1 if await send_to_device(d, payload(title, body, data)) else 0
    return sent


# ---------------------------------------------------------------- delivery (scheduler)

def plain(text: str) -> str:
    """Telegram HTML line -> plain push text."""
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def allowed_lines(lines: list[tuple[str, str, str]], level: str) -> list[tuple[str, str, str]]:
    if access.can(level, FEATURE_ALL):
        return lines
    return [ln for ln in lines if ln[0] in FREE_KINDS]


def compose(lines: list[str]) -> str:
    first = plain(lines[0])
    return first if len(lines) == 1 else f"{first} (+{len(lines) - 1} more)"


async def deliver_user(user_id: str, devices: list[dict], mode: str, today: date, now: datetime) -> int:
    from app.db import queries
    from app.services import telegram_notify

    level = access.get_user_access(user_id)["level"]
    _lang, lines = await telegram_notify._lines_for({"user_id": user_id, "access_level": level}, mode, today, now)
    lines = allowed_lines(lines, level)
    if not lines:
        return 0
    seen: set[str] = set()
    unique = [ln for ln in lines if not (ln[1] in seen or seen.add(ln[1]))]
    keys = [KEY_PREFIX + k for _, k, _ in unique]
    done = await asyncio.to_thread(queries.get_delivered_keys, user_id, keys)
    fresh = [ln for ln in unique if KEY_PREFIX + ln[1] not in done]
    if not fresh:
        return 0
    body = payload(TITLE, compose([t for _, _, t in fresh]), {"kind": fresh[0][0]})
    ok = False
    for d in devices:
        ok = await send_to_device(d, body) or ok
    if not ok:
        return 0
    await asyncio.to_thread(queries.insert_deliveries, user_id, [(k, KEY_PREFIX + key) for k, key, _ in fresh])
    return len(fresh)


async def run_delivery(mode: str, today: date | None = None, now: datetime | None = None) -> dict:
    """mode "events" (digest) or "live" (price alerts, big moves). Never raises."""
    from app.core.api_errors import is_missing_schema
    from app.services import dividends

    if not settings.push_notifications_enabled:
        return {"status": "disabled"}
    now = now or datetime.now(timezone.utc)
    today = today or dividends.today_et()
    try:
        devices = await asyncio.to_thread(active_devices)
    except Exception as e:
        if is_missing_schema(e):
            return {"status": "migration_required"}
        logger.warning(f"push: could not load devices: {type(e).__name__}")
        return {"status": "failed"}
    by_user: dict[str, list[dict]] = {}
    for d in devices:
        by_user.setdefault(str(d["user_id"]), []).append(d)
    users = lines = errors = 0
    for uid, devs in by_user.items():
        try:
            n = await deliver_user(uid, devs, mode, today, now)
            users += 1 if n else 0
            lines += n
        except Exception as e:
            errors += 1
            logger.warning(f"push: delivery for {uid} failed: {type(e).__name__}: {e}")
    return {"status": "ok", "mode": mode, "devices": len(devices), "users": users, "lines": lines, "errors": errors}
