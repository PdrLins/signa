"""Per-user Telegram notifications (migration 016, feature.telegram_alerts = premium).

A Premium (or owner) user connects their own Telegram chat — separate from
users.telegram_chat_id, which stays the login / OTP chat — and receives the
notifications switched on in Profile -> Notifications (notification_prefs)
plus their price alerts that fired. No AI anywhere.

Linking
  POST /notifications/telegram/link issues a one-time code (10 min, only its
  SHA-256 stored) and the URL https://t.me/<bot>?start=<code>. The user taps
  Start in Telegram; the webhook sees "/start <code>" from that private chat
  (handle_start) and links the chat. A chat belongs to one user (linking it
  from a second account moves it). A new code invalidates older unused ones.

Delivery (run_delivery, scheduler)
  "events"  08:30 ET daily + 18:30 ET weekdays: ex-dividend reminders (ex-date
            in 1-2 days, held shares), dividends paid today (announced pay
            dates only), dividend raises / cuts (newest payment in the last 3
            days vs the previous regular one, >= 1 %), earnings (within 2
            trading days), analyst actions on held stocks (last 2 days), Signa
            check changes (last 2 days), economy events (tomorrow).
  "live"    every 5 min after prices moved on any exchange (only today's quotes count): price alerts that fired in
            the last 24 h, and held stocks whose day move >= the user's
            big_move.threshold_pct (once per symbol per day).
  Each user gets at most one message per run (lines grouped), in their profile
  language, deduped through notification_deliveries (a line is recorded only
  after Telegram accepted the message, so a failed send retries next run).
  The feature is re-checked every run: a downgraded user stops receiving.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from datetime import date, datetime, timedelta, timezone
from html import escape
from typing import Any

import httpx
from fastapi import status
from loguru import logger

from app.core import access
from app.core.api_errors import api_error
from app.core.config import settings
from app.notifications.messages import msg_for

MIGRATION = "016_telegram_notifications.sql"
FEATURE = "feature.telegram_alerts"
CODE_TTL = timedelta(minutes=10)
KINDS = ("exdiv_reminder", "dividend_paid", "dividend_change", "check_changed",
         "earnings", "big_move", "analyst_ratings", "economy")
RECENT_DAYS = 2
DIV_CHANGE_MIN_PCT = 1.0

_bot_username: str | None = None


# ============================================================
# Helpers
# ============================================================

def _now() -> datetime:
    return datetime.now(timezone.utc)


def hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x not in (float("inf"), float("-inf")) else None


def _d(v: Any) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


CURRENCY_SYMBOLS = {"CAD": "C$", "USD": "US$", "BRL": "R$", "EUR": "€", "GBP": "£", "JPY": "¥", "CHF": "CHF ",
                    "AUD": "A$", "NZD": "NZ$", "MXN": "MX$", "HKD": "HK$", "SGD": "S$", "INR": "₹", "KRW": "₩"}


def money(v: float | None, ccy: str | None, lang: str = "en") -> str:
    """"C$1,234.56" (en) / "R$ 1.234,56" (pt): the currency's symbol, the
    language's separators. Unknown codes are written in front ("SEK 12.00")."""
    if v is None:
        return ""
    ccy = (ccy or "").upper()
    prefix = CURRENCY_SYMBOLS.get(ccy, f"{ccy} " if ccy else "$")
    digits = 0 if ccy in ("JPY", "KRW") else 2
    num = f"{v:,.{digits}f}"
    if lang == "pt":
        num = num.replace(",", "\u0000").replace(".", ",").replace("\u0000", ".")
        if not prefix.endswith(" "):
            prefix += " "
    return f"{prefix}{num}"


def pct(v: float, digits: int = 1) -> str:
    return f"{'+' if v > 0 else '−' if v < 0 else ''}{abs(v):.{digits}f}%"


def _et_date(iso: Any) -> date | None:
    """Calendar date in New York of an ISO timestamp."""
    from zoneinfo import ZoneInfo
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(ZoneInfo("America/New_York")).date()


def short_date(d: date, lang: str) -> str:
    if lang == "pt":
        return d.strftime("%d/%m")
    return f"{d.strftime('%b')} {d.day}"


def user_language(user_id: str) -> str:
    from app.db import queries
    from app.services import profile_service
    from app.core import user_cache
    try:
        lang = profile_service.merged_settings(
            user_cache.get(user_id, "settings", lambda: queries.get_profile_settings(user_id))).get("language")
    except Exception:
        lang = None
    return lang if lang in ("en", "pt") else (settings.language if settings.language in ("en", "pt") else "en")


BOT_LOOKUP_RETRY_S = 300
_bot_lookup_retry_at = 0.0


async def bot_username() -> str | None:
    """settings.telegram_bot_username, else read once via getMe (a failure is
    retried after BOT_LOOKUP_RETRY_S)."""
    global _bot_username, _bot_lookup_retry_at
    if settings.telegram_bot_username:
        return settings.telegram_bot_username.lstrip("@")
    if _bot_username:
        return _bot_username
    if not settings.telegram_bot_token or time.time() < _bot_lookup_retry_at:
        return None   # a failed getMe isn't retried on every call (the app polls)
    try:
        from app.notifications.telegram_bot import _get_http_client, _telegram_url
        resp = await _get_http_client().get(_telegram_url("getMe"))
        name = (resp.json().get("result") or {}).get("username") if resp.status_code == 200 else None
    except (httpx.HTTPError, ValueError) as e:
        logger.warning(f"telegram: getMe failed: {type(e).__name__}")
        name = None
    _bot_username = name or None
    if not _bot_username:
        _bot_lookup_retry_at = time.time() + BOT_LOOKUP_RETRY_S
    return _bot_username


async def send(chat_id: str, text: str) -> bool:
    """Send now. urgent=True: the owner's quiet hours / scan switches are for
    the owner's brain alerts, not a user's own notifications."""
    from app.notifications.telegram_bot import send_message
    return await send_message(chat_id, text, urgent=True)


# ============================================================
# API (sync parts run via run_db_for(MIGRATION, ...))
# ============================================================

def status_payload(user: dict, bot: str | None) -> dict:
    """GET /notifications/telegram."""
    from app.db import queries
    level = user.get("access_level") or access.get_user_access(user["user_id"])["level"]
    link = queries.get_telegram_link(user["user_id"])
    pending = None if link else queries.get_pending_telegram_link_code(user["user_id"], _now().isoformat())
    return {
        "available": access.can(level, FEATURE),
        "linked": link is not None,
        "username": (link or {}).get("username"),
        "linked_at": (link or {}).get("linked_at"),
        "bot_username": bot,
        "pending": {"expires_at": pending["expires_at"]} if pending else None,
    }


def create_link(user: dict, bot: str | None) -> dict:
    """POST /notifications/telegram/link."""
    from app.db import queries
    if not settings.telegram_bot_token or not bot:
        raise api_error("telegram_not_configured", "Telegram isn't set up on this server yet.",
                        status.HTTP_503_SERVICE_UNAVAILABLE)
    code = secrets.token_urlsafe(18)  # 24 URL-safe chars (Telegram start param allows A-Z a-z 0-9 _ -)
    expires = (_now() + CODE_TTL).isoformat()
    queries.replace_telegram_link_code(user["user_id"], hash_code(code), expires)
    return {"code": code, "url": f"https://t.me/{bot}?start={code}", "expires_at": expires}


def linked_chat(user_id: str) -> str | None:
    from app.db import queries
    link = queries.get_telegram_link(user_id)
    return str(link["chat_id"]) if link else None


def unlink(user: dict) -> dict:
    from app.db import queries
    queries.delete_telegram_link(user["user_id"])
    return {"unlinked": True}


async def send_test(user: dict) -> dict:
    """POST /notifications/telegram/test (chat looked up by the route)."""
    from app.core.api_errors import run_db_for
    chat = await run_db_for(MIGRATION, linked_chat, user["user_id"])
    if not chat:
        raise api_error("not_linked", "Connect Telegram first.", status.HTTP_409_CONFLICT)
    lang = await run_db_for(MIGRATION, user_language, user["user_id"])
    if not await send(chat, msg_for(lang, "user_tg_test")):
        raise api_error("telegram_send_failed", "Telegram didn't accept the message. Try again.",
                        status.HTTP_502_BAD_GATEWAY)
    return {"sent": True}


# ============================================================
# Webhook: /start <code>
# ============================================================

def _link_from_code(code: str, chat_id: str, username: str | None) -> str | None:
    """Spend the code and link the chat. Returns the user_id, or None."""
    from app.db import queries
    if not code or len(code) > 64:
        return None
    user_id = queries.consume_telegram_link_code(hash_code(code), _now().isoformat())
    if not user_id:
        return None
    queries.upsert_telegram_link(user_id, chat_id, username)
    return user_id


async def handle_start(code: str, chat: dict, sender: dict) -> bool:
    """Handle "/start <code>" from a private chat. Replies in the chat; True
    when a reply was sent. Never raises (webhook)."""
    import asyncio

    if (chat or {}).get("type") != "private" or not chat.get("id"):
        return False
    chat_id = str(chat["id"])
    uname = sender.get("username")
    display = f"@{uname}" if uname else (sender.get("first_name") or None)
    try:
        user_id = await asyncio.to_thread(_link_from_code, code.strip(), chat_id, display)
    except Exception as e:  # table missing (before 016) or DB down
        logger.warning(f"telegram: link failed: {type(e).__name__}")
        user_id = None
    if user_id:
        lang = await asyncio.to_thread(user_language, user_id)
        logger.info(f"telegram: user {user_id} connected a notification chat")
        return await send(chat_id, msg_for(lang, "user_tg_connected"))
    lang = "pt" if str(sender.get("language_code") or "").startswith("pt") else "en"
    return await send(chat_id, msg_for(lang, "user_tg_link_expired"))


# ============================================================
# Delivery — line builders (pure)
# ============================================================

def _when(d: date, today: date, lang: str) -> str:
    if d == today:
        return msg_for(lang, "user_tg_today")
    if d == today + timedelta(days=1):
        return msg_for(lang, "user_tg_tomorrow")
    return msg_for(lang, "user_tg_on_date", date=short_date(d, lang))


def _amount(it: dict, home: str, lang: str = "en") -> str:
    if it.get("cash_home") is not None:
        return f" · {money(_f(it['cash_home']), home, lang)}"
    if it.get("cash") is not None:
        return f" · {money(_f(it['cash']), it.get('currency'), lang)}"
    return ""


def event_lines(items: list[dict], prefs: dict, today: date, lang: str, home: str) -> list[tuple[str, str, str]]:
    """(kind, dedupe_key, line) for /events/upcoming items worth a message."""
    out: list[tuple[str, str, str]] = []
    on = lambda k: bool((prefs.get(k) or {}).get("enabled"))  # noqa: E731
    since = today - timedelta(days=RECENT_DAYS)
    for it in items or []:
        t, d, sym = it.get("type"), _d(it.get("date")), it.get("symbol")
        if d is None:
            continue
        s = escape(str(sym or ""))
        if t == "ex_dividend" and on("exdiv_reminder") and it.get("owned") and it.get("shares") \
                and today < d <= today + timedelta(days=2):
            out.append(("exdiv_reminder", f"exdiv:{sym}:{d}",
                        msg_for(lang, "user_tg_exdiv", symbol=s, when=_when(d, today, lang), amount=_amount(it, home, lang))))
        elif t == "dividend_payment" and on("dividend_paid") and it.get("owned") and it.get("shares") \
                and d == today and not it.get("estimated"):
            out.append(("dividend_paid", f"paid:{sym}:{d}",
                        msg_for(lang, "user_tg_paid", symbol=s, amount=_amount(it, home, lang))))
        elif t == "earnings" and on("earnings") and it.get("owned"):
            td = it.get("trading_days")
            td = int(td) if isinstance(td, (int, float)) else (d - today).days
            if 0 <= td <= 2:
                avg = _f(it.get("avg_abs_move_pct"))
                move = msg_for(lang, "user_tg_earnings_move", pct=f"{avg:.1f}%") if avg else ""
                out.append(("earnings", f"earnings:{sym}:{d}",
                            msg_for(lang, "user_tg_earnings", symbol=s, when=_when(d, today, lang), move=move)))
        elif t == "analyst" and on("analyst_ratings") and since <= d <= today:
            action = str(it.get("action") or "").lower()
            word = {"up": "user_tg_analyst_up", "down": "user_tg_analyst_down",
                    "init": "user_tg_analyst_init"}.get(action, "user_tg_analyst_other")
            frm, to = it.get("from_grade"), it.get("to_grade")
            grades = f" ({escape(str(frm))} → {escape(str(to))})" if frm and to and frm != to \
                else (f" ({escape(str(to))})" if to else "")
            firm = escape(str(it.get("firm") or "—"))
            out.append(("analyst_ratings", f"analyst:{sym}:{d}:{it.get('firm')}:{to}",
                        msg_for(lang, "user_tg_analyst", symbol=s, firm=firm, action=msg_for(lang, word),
                                grades=grades)))
        elif t == "check_changed" and on("check_changed") and it.get("owned") and since <= d <= today:
            out.append(("check_changed", f"check:{sym}:{d}",
                        msg_for(lang, "user_tg_check", symbol=s, n=len(it.get("changes") or []) or 1)))
        elif t == "economy" and on("economy") and d == today + timedelta(days=1):
            code = it.get("code") or ""
            title = msg_for(lang, f"user_tg_economy_{code}")
            if title == f"user_tg_economy_{code}":
                title = escape(str(it.get("title") or ""))
            out.append(("economy", f"economy:{code}:{d}", msg_for(lang, "user_tg_economy", title=title)))
    return out


def dividend_change_lines(profiles: dict[str, dict | None], held: set[str], prefs: dict, today: date,
                          lang: str) -> list[tuple[str, str, str]]:
    """Raise / cut: newest payment (last 3 days) vs the previous regular one."""
    if not (prefs.get("dividend_change") or {}).get("enabled"):
        return []
    out = []
    for sym in sorted(held):
        prof = profiles.get(sym) or {}
        pays = [p for p in (prof.get("last_payments") or []) if not p.get("special") and _f(p.get("amount"))]
        if len(pays) < 2:
            continue
        new, old = pays[0], pays[1]
        nd = _d(new.get("ex_date"))
        if nd is None or not (today - timedelta(days=3) <= nd <= today):
            continue
        a, b = _f(new["amount"]), _f(old["amount"])
        change = (a / b - 1) * 100
        if abs(change) < DIV_CHANGE_MIN_PCT:
            continue
        ccy = prof.get("currency")
        out.append(("dividend_change", f"divchange:{sym}:{nd}",
                    msg_for(lang, "user_tg_raise" if change > 0 else "user_tg_cut", symbol=escape(sym),
                            pct=pct(change), old=money(b, ccy, lang), new=money(a, ccy, lang))))
    return out


def big_move_lines(positions: list[dict], prefs: dict, today: date, lang: str) -> list[tuple[str, str, str]]:
    bm = prefs.get("big_move") or {}
    if not bm.get("enabled"):
        return []
    threshold = _f(bm.get("threshold_pct")) or 5.0
    out = []
    for p in positions or []:
        ch = _f(p.get("change_pct"))
        if not p.get("shares") or ch is None or abs(ch) < threshold or p.get("price_source") != "quote":
            continue
        if _et_date(p.get("as_of")) != today:  # yesterday's quote = yesterday's move
            continue
        out.append(("big_move", f"bigmove:{p['symbol']}:{today}",
                    msg_for(lang, "user_tg_big_move", symbol=escape(p["symbol"]), pct=pct(ch))))
    return out


def _num_text(v: float, lang: str, signed: bool = False) -> str:
    """5 -> "5", 2.5 -> "2.5" / "2,5"; signed: "+5.3" / "−5.3" (true minus sign). Pure."""
    t = f"{abs(v):.1f}".rstrip("0").rstrip(".") if not float(v).is_integer() else f"{abs(v):.0f}"
    if lang == "pt":
        t = t.replace(".", ",")
    if signed:
        return ("+" if v >= 0 else "−") + t
    return ("−" if v < 0 else "") + t


def alert_message(r: dict, lang: str, hide_amounts: bool = False) -> str:
    """One triggered alert as a line (Telegram HTML; push strips the tags).
    hide_amounts drops money (lock screens) but keeps the ticker and percent. Pure."""
    sym = escape(str(r.get("symbol") or ""))
    kind = r.get("kind") or "price"
    ccy = r.get("currency")
    price = _f(r.get("last_price"))
    if kind == "day_move":
        change = _f(r.get("last_change_pct"))
        return msg_for(lang, "user_tg_alert_day_move", symbol=sym,
                       change=_num_text(change, lang, signed=True) if change is not None else "?")
    if kind == "percent" and _f(r.get("percent")) is not None:
        key = "user_tg_alert_pct_up" if r.get("direction") == "above" else "user_tg_alert_pct_down"
        text = msg_for(lang, key, symbol=sym, pct=_num_text(_f(r["percent"]), lang))
        return text if hide_amounts or price is None else f"{text} ({money(price, ccy, lang)})"
    if hide_amounts:
        key = "user_tg_alert_pct_up" if r.get("direction") == "above" else "user_tg_alert_pct_down"
        word = {"en": "reached your alert price", "pt": "chegou ao preço do seu alerta"}["pt" if lang == "pt" else "en"]
        return f"🎯 <b>{sym}</b> {word}"
    key = "user_tg_alert_above" if r.get("direction") == "above" else "user_tg_alert_below"
    return msg_for(lang, key, symbol=sym, target=money(_f(r.get("target_price")), ccy, lang),
                   price=money(price, ccy, lang))


def alert_key(r: dict) -> str:
    """One delivery per firing: a day_move alert fires once a day, a re-armed
    price alert can fire again, so the firing time is part of the key."""
    return f"alert:{r.get('id')}:{str(r.get('triggered_at') or '')[:19]}"


def alert_lines(rows: list[dict], lang: str, now: datetime) -> list[tuple[str, str, str]]:
    """Price alerts that fired in the last 24 h (always on: the user set them)."""
    out = []
    for r in rows or []:
        at = r.get("triggered_at")
        try:
            when = datetime.fromisoformat(str(at).replace("Z", "+00:00"))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if now - when > timedelta(hours=24):
            continue
        out.append(("price_alert", alert_key(r), alert_message(r, lang)))
    return out


def compose(lang: str, lines: list[str]) -> str:
    return msg_for(lang, "user_tg_header") + "\n\n" + "\n".join(lines)


# ============================================================
# Delivery — job
# ============================================================

async def _lines_for(user: dict, mode: str, today: date, now: datetime) -> tuple[str, list[tuple[str, str, str]]]:
    import asyncio

    from app.services import events_feed, notification_prefs, portfolio_context, price_alerts

    uid = user["user_id"]
    prefs = (await asyncio.to_thread(notification_prefs.get_prefs, uid))["prefs"]
    lang = await asyncio.to_thread(user_language, uid)
    scope = await asyncio.to_thread(portfolio_context.load_scope, user, None, None, False, True)
    home = scope["home_currency"]
    lines: list[tuple[str, str, str]] = []
    if mode == "events":
        feed = await events_feed.build_upcoming(scope, None, 3, today=today)
        lines += event_lines(feed.get("items") or [], prefs, today, lang, home)
        held = {str(h.get("symbol") or "").upper() for h in scope["holdings"] if h.get("symbol")}
        if held and (prefs.get("dividend_change") or {}).get("enabled"):
            profiles = await events_feed.fetch_profiles(sorted(held))
            lines += dividend_change_lines(profiles, held, prefs, today, lang)
    else:
        positions = portfolio_context.merge_positions_by_symbol(
            portfolio_context.value_positions(scope["holdings"], scope.get("quotes") or {}, home, scope.get("usdcad")))
        lines += big_move_lines(positions, prefs, today, lang)
        try:
            rows = await asyncio.to_thread(price_alerts.recent_triggered, uid, now)
        except Exception:
            rows = []
        lines += alert_lines(rows, lang, now)
    return lang, lines


MESSAGE_MAX_CHARS = 4000   # Telegram's limit is 4,096
DELIVERY_CONCURRENCY = 8   # users prepared at once per run (DB reads + Yahoo, bounded)


def live_candidates(today: date, now: datetime) -> set[str] | None:
    """Users who could get a "live" line this run: holders of a stock that
    moved past the lowest big-move threshold today, or users whose price
    alert fired in the last 24 h. Everyone else is skipped without reading
    their settings or portfolio. None (process everyone) if this fails."""
    from app.db import queries
    from app.services.notification_prefs import THRESHOLD_MIN

    try:
        movers = [r["symbol"] for r in queries.get_mover_quotes(THRESHOLD_MIN)
                  if r.get("symbol") and _et_date(r.get("as_of")) == today]
        out = queries.get_holder_ids(movers) if movers else set()
        return out | queries.get_recent_alert_user_ids((now - timedelta(hours=24)).isoformat())
    except Exception as e:
        logger.debug(f"notifications: live candidates unavailable ({type(e).__name__}), checking everyone")
        return None


async def deliver_user(link: dict, mode: str, today: date, now: datetime) -> int:
    """Send one user's new lines for this run; returns how many were sent."""
    import asyncio

    from app.db import queries

    uid = str(link["user_id"])
    level = (await asyncio.to_thread(access.get_user_access, uid))["level"]
    if not access.can(level, FEATURE):
        return 0
    user = {"user_id": uid, "access_level": level}
    lang, lines = await _lines_for(user, mode, today, now)
    if not lines:
        return 0
    seen: set[str] = set()
    unique = [ln for ln in lines if not (ln[1] in seen or seen.add(ln[1]))]
    done = await asyncio.to_thread(queries.get_delivered_keys, uid, [k for _, k, _ in unique])
    fresh = [ln for ln in unique if ln[1] not in done]
    if not fresh:
        return 0
    # Telegram rejects messages over 4,096 characters: send what fits, the
    # rest goes out on the next run (only sent lines are recorded).
    while len(fresh) > 1 and len(compose(lang, [t for _, _, t in fresh])) > MESSAGE_MAX_CHARS:
        fresh = fresh[:max(1, len(fresh) * 2 // 3)]
    chat = str(link["chat_id"])
    if not await send(chat, compose(lang, [t for _, _, t in fresh])):
        from app.notifications.telegram_bot import blocked_chats
        if chat in blocked_chats:   # the user blocked the bot: stop trying every run
            blocked_chats.discard(chat)
            await asyncio.to_thread(queries.delete_telegram_link, uid)
            logger.info(f"telegram: {uid} blocked the bot, notification chat unlinked")
            return 0
        logger.warning(f"telegram: delivery to {uid} failed — will retry next run")
        return 0
    await asyncio.to_thread(queries.insert_deliveries, uid, [(kind, key) for kind, key, _ in fresh])
    return len(fresh)


async def run_delivery(mode: str, today: date | None = None, now: datetime | None = None) -> dict:
    """mode "events" (digest) or "live" (price alerts + big moves). Never raises."""
    import asyncio

    from app.core.api_errors import is_missing_schema
    from app.db import queries
    from app.services import dividends

    if not settings.telegram_notifications_enabled or not settings.telegram_bot_token:
        return {"status": "disabled"}
    now = now or _now()
    today = today or dividends.today_et()
    try:
        links = await asyncio.to_thread(queries.get_telegram_links)
    except Exception as e:
        if is_missing_schema(e):
            logger.debug(f"telegram: notifications skipped (apply {MIGRATION})")
            return {"status": "migration_required"}
        logger.warning(f"telegram: could not load linked chats: {type(e).__name__}")
        return {"status": "failed"}
    pending = await asyncio.to_thread(queries.pending_deletion_ids)   # accounts waiting for deletion
    links = [ln for ln in links if str(ln.get("user_id")) not in pending]
    if mode == "live":
        wanted = await asyncio.to_thread(live_candidates, today, now)
        if wanted is not None:
            links = [ln for ln in links if str(ln.get("user_id")) in wanted]
    sem = asyncio.Semaphore(DELIVERY_CONCURRENCY)

    async def one(link: dict) -> int | None:
        async with sem:
            try:
                return await deliver_user(link, mode, today, now)
            except Exception as e:
                logger.warning(f"telegram: delivery for {link.get('user_id')} failed: {type(e).__name__}: {e}")
                return None
    results = await asyncio.gather(*(one(ln) for ln in links))
    users = sum(1 for n in results if n)
    sent = sum(n for n in results if n)
    errors = sum(1 for n in results if n is None)
    return {"status": "ok", "mode": mode, "linked": len(links), "users": users, "lines": sent, "errors": errors}
