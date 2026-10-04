"""Where users come from and whether they stay (migration 029). No AI.

Sign-up source (signup_sources, one row per user, first touch wins)
  Written at sign-up (POST /auth/register "source": {...}) or right after it
  (POST /api/v1/attribution, only empty fields are filled):
    utm_source / utm_medium / utm_campaign / utm_content / utm_term
                    campaign tags from the link the person came from
    heard_from      "How did you hear about Signa?" (HEARD_FROM), optional:
                    the only signal for ads Apple can't attribute (Instagram,
                    YouTube, TikTok ...) and for word of mouth
    asa_token       Apple Search Ads: the app's AdServices attribution token
                    (AAAttribution.attributionToken()). A job (every 10 min)
                    sends it to Apple and stores campaign / ad group / keyword
                    ids, or "organic". Apple keeps a token valid for 24 h.
  plus platform (ios | web), country and invite (friend | none).

Activity (user_activity_days)
  One row per user per US/Eastern day they used the app, written by the auth
  middleware at most once a day per user.

Funnel (GET /api/v1/admin/growth, owner)
  For users who signed up in [from, to], grouped by channel / campaign /
  heard_from / country / platform / week:
    signups
    activated     added at least one holding within 7 days
    activated_3   at least three holdings within 7 days
    week2         used the app on a day 7-13 days after sign-up
                  (out of week2_eligible: users who signed up >= 14 days ago)
    premium       access level premium today
  and each rate. Channel: Apple Search Ads when Apple attributed it, else
  the utm_source, else heard_from, else "friend_invite" / "unknown".
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from loguru import logger

from app.core.cache import TTLCache

from zoneinfo import ZoneInfo

MIGRATION = "029_growth.sql"
_ET = ZoneInfo("America/New_York")
HEARD_FROM = ("app_store", "instagram", "youtube", "tiktok", "facebook", "google", "reddit", "x",
              "friend", "creator", "podcast", "news", "other")
UTM_FIELDS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")
GROUPS = ("channel", "campaign", "heard_from", "country", "platform", "week")
ASA_URL = "https://api-adservices.apple.com/api/v1/"
ASA_TOKEN_HOURS = 24
ASA_RUN_BUDGET_S = 120
ACTIVATION_DAYS = 7
MAX_RANGE_DAYS = 366
_SAFE = re.compile(r"[^a-z0-9_.\-]+")

_activity_written = TTLCache(max_size=50000, default_ttl=24 * 3600)


def _clean(v: Any, n: int) -> str | None:
    s = _SAFE.sub("_", str(v or "").strip().lower())[:n].strip("_")
    return s or None


def clean_source(body: dict | None) -> dict:
    """Allowed, trimmed fields of a client "source" object. Pure. Unknown
    keys and bad values are dropped (never an error: sign-up must not fail)."""
    body = body if isinstance(body, dict) else {}
    out: dict = {}
    for f, n in zip(UTM_FIELDS, (64, 64, 100, 100, 100)):
        v = _clean(body.get(f), n)
        if v:
            out[f] = v
    hf = _clean(body.get("heard_from"), 24)
    if hf in HEARD_FROM:
        out["heard_from"] = hf
    tok = str(body.get("asa_token") or "").strip()
    if 20 <= len(tok) <= 4096 and re.fullmatch(r"[A-Za-z0-9+/=_\-.]+", tok):
        out["asa_token"] = tok
        out["asa_status"] = "pending"
    return out


def record_signup(user_id: str, source: dict | None, platform: str | None, country: str | None,
                  invite: str) -> None:
    """The user's signup_sources row. Never raises (before 029: skipped)."""
    row = {"user_id": user_id, **clean_source(source),
           "platform": platform if platform in ("ios", "web") else None,
           "country": (str(country).upper()[:8] if country else None), "invite": invite}
    try:
        from app.db import queries
        queries.insert_signup_source(row)
    except Exception as e:
        logger.debug(f"growth: sign-up source not saved for {user_id} ({type(e).__name__})")


def add_attribution(user_id: str, body: dict | None) -> dict:
    """POST /attribution: fill the fields still empty (first touch wins)."""
    from app.db import queries
    new = clean_source(body)
    cur = queries.get_signup_source(user_id)
    if cur is None:
        queries.insert_signup_source({"user_id": user_id, **new})
        return {"saved": sorted(new)}
    patch = {k: v for k, v in new.items() if not cur.get(k)}
    if "asa_token" in patch and cur.get("asa_status") in ("attributed", "organic"):
        patch.pop("asa_token")
        patch.pop("asa_status", None)
    elif "asa_token" in patch:   # a fresh token after a failed one is worth another try
        patch["asa_status"] = "pending"
    if patch:
        queries.update_signup_source(user_id, {**patch, "updated_at": datetime.now(timezone.utc).isoformat()})
    return {"saved": sorted(patch)}


def record_activity(user_id: str, day: date) -> None:
    """Once a day per user. Blocking; the auth middleware runs it in the background."""
    key = f"{user_id}|{day.isoformat()}"
    if _activity_written.get(key):
        return
    try:
        from app.db import queries
        queries.add_activity_day(user_id, day.isoformat())
        _activity_written.set(key, True)   # only once it's saved: a failure is retried
    except Exception as e:
        logger.debug(f"growth: activity not saved ({type(e).__name__})")


# ============================================================
# Apple Search Ads (AdServices)
# ============================================================

def parse_asa(payload: dict) -> dict:
    """Apple's attribution answer -> signup_sources fields. Pure."""
    if not payload.get("attribution"):
        return {"asa_status": "organic", "asa_token": None}

    def num(k):
        try:
            return int(payload[k]) if payload.get(k) is not None else None
        except (TypeError, ValueError):
            return None
    click = payload.get("clickDate")
    return {"asa_status": "attributed", "asa_token": None, "asa_campaign_id": num("campaignId"),
            "asa_ad_group_id": num("adGroupId"), "asa_keyword_id": num("keywordId"),
            "asa_country": (str(payload.get("countryOrRegion") or "")[:4] or None),
            "asa_click_date": click if isinstance(click, str) and click else None}


def resolve_asa(now: datetime | None = None, post=None) -> dict:
    """Job: send pending tokens to Apple. 404 = not ready yet (retried next
    run); after ASA_TOKEN_HOURS the token is dead -> failed. Blocking."""
    import httpx

    from app.db import queries

    now = now or datetime.now(timezone.utc)
    rows = queries.get_pending_asa()
    post = post or (lambda tok: httpx.post(ASA_URL, content=tok, headers={"Content-Type": "text/plain"},
                                           timeout=10))
    out = {"pending": len(rows), "attributed": 0, "organic": 0, "failed": 0, "waiting": 0}
    import time as _time
    budget_end = _time.time() + ASA_RUN_BUDGET_S
    for r in rows:
        if _time.time() > budget_end:   # the rest waits for the next run
            out["waiting"] += 1
            continue
        try:
            created = _d(r.get("created_at")) or now
            if now - created > timedelta(hours=ASA_TOKEN_HOURS):
                queries.update_signup_source(r["user_id"], {"asa_status": "failed", "asa_token": None})
                out["failed"] += 1
                continue
            resp = post(r["asa_token"])
            if resp.status_code == 200:
                try:
                    fields = parse_asa(resp.json())
                except ValueError:   # not JSON: treat like "not ready yet"
                    out["waiting"] += 1
                    continue
                queries.update_signup_source(r["user_id"], fields)
                out[fields["asa_status"]] += 1
            elif resp.status_code == 400:   # invalid token: never resolvable
                queries.update_signup_source(r["user_id"], {"asa_status": "failed", "asa_token": None})
                out["failed"] += 1
            else:   # 404: Apple doesn't have it yet; 5xx: try again later
                out["waiting"] += 1
        except Exception as e:   # one bad row never stops the others
            logger.debug(f"growth: Apple attribution for one sign-up failed ({type(e).__name__})")
            out["waiting"] += 1
    return out


# ============================================================
# Funnel (pure core + loader)
# ============================================================

def channel_of(src: dict | None) -> str:
    src = src or {}
    if src.get("asa_status") == "attributed":
        return "apple_search_ads"
    if src.get("utm_source"):
        return src["utm_source"]
    if src.get("heard_from"):
        return src["heard_from"]
    return "friend_invite" if src.get("invite") == "friend" else "unknown"


def campaign_of(src: dict | None) -> str:
    src = src or {}
    if src.get("asa_status") == "attributed":
        return f"apple_search_ads:{src.get('asa_campaign_id')}"
    if src.get("utm_campaign"):
        return f"{src.get('utm_source') or 'unknown'}:{src['utm_campaign']}"
    return channel_of(src)


def _d(v: Any) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def build_funnel(users: list[dict], sources: dict[str, dict], holdings: list[dict],
                 activity: list[dict], group: str, today: date) -> list[dict]:
    """Rows per group key, largest first. Pure."""
    first_holdings: dict[str, list[datetime]] = defaultdict(list)
    for h in holdings:
        t = _d(h.get("created_at"))
        if t:
            first_holdings[str(h["user_id"])].append(t)
    days: dict[str, set[date]] = defaultdict(set)
    for a in activity:
        try:
            days[str(a["user_id"])].add(date.fromisoformat(str(a["day"])[:10]))
        except ValueError:
            continue
    agg: dict[str, dict] = defaultdict(lambda: {"signups": 0, "activated": 0, "activated_3": 0,
                                                "week2": 0, "week2_eligible": 0, "premium": 0})
    for u in users:
        uid = str(u["id"])
        created = _d(u.get("created_at"))
        if not created:
            continue
        src = sources.get(uid) or {}
        signup_day = created.astimezone(_ET).date()   # same day boundary as activity days (New York)
        if group == "channel":
            key = channel_of(src)
        elif group == "campaign":
            key = campaign_of(src)
        elif group == "heard_from":
            key = src.get("heard_from") or "not_answered"
        elif group == "country":
            key = src.get("country") or "unknown"
        elif group == "platform":
            key = src.get("platform") or "unknown"
        else:   # week: Monday of the sign-up week
            key = (signup_day - timedelta(days=signup_day.weekday())).isoformat()
        g = agg[key]
        g["signups"] += 1
        window = created + timedelta(days=ACTIVATION_DAYS)
        early = sum(1 for t in first_holdings.get(uid, []) if t <= window)
        g["activated"] += 1 if early >= 1 else 0
        g["activated_3"] += 1 if early >= 3 else 0
        if (today - signup_day).days >= 14:
            g["week2_eligible"] += 1
            if any(7 <= (d - signup_day).days <= 13 for d in days.get(uid, ())):
                g["week2"] += 1
        g["premium"] += 1 if u.get("access_level") == "premium" else 0

    def rate(a, b):
        return round(a / b * 100, 1) if b else None
    rows = []
    for key, g in agg.items():
        rows.append({"key": key, **g,
                     "activated_pct": rate(g["activated"], g["signups"]),
                     "activated_3_pct": rate(g["activated_3"], g["signups"]),
                     "week2_pct": rate(g["week2"], g["week2_eligible"]),
                     "premium_pct": rate(g["premium"], g["signups"])})
    key_sort = (lambda r: r["key"]) if group == "week" else (lambda r: (-r["signups"], r["key"]))
    return sorted(rows, key=key_sort)


def funnel_body(start: date, end: date, group: str, today: date | None = None) -> dict:
    """GET /admin/growth. Blocking."""
    from app.core.api_errors import api_error
    from app.db import queries
    from app.services.dividends import today_et

    today = today or today_et()
    if group not in GROUPS:
        raise api_error("invalid_group", f"group must be one of {', '.join(GROUPS)}.", 422, field="group")
    if end < start or (end - start).days > MAX_RANGE_DAYS:
        raise api_error("invalid_range", f"from must be before to, at most {MAX_RANGE_DAYS} days.", 422)
    def et_midnight(d: date) -> str:
        return datetime(d.year, d.month, d.day, tzinfo=_ET).isoformat()
    users = queries.get_users_created(et_midnight(start), et_midnight(end + timedelta(days=1)))
    ids = [str(u["id"]) for u in users]
    sources = {str(r["user_id"]): r for r in queries.get_signup_sources(ids)} if ids else {}
    holdings = queries.get_holding_times(ids) if ids else []
    activity = queries.get_activity_days(ids, start.isoformat(),
                                         (end + timedelta(days=14)).isoformat()) if ids else []
    rows = build_funnel(users, sources, holdings, activity, group, today)
    total = build_funnel(users, sources, holdings, activity, "platform", today)
    totals = {k: sum(r[k] for r in total) for k in ("signups", "activated", "activated_3", "week2",
                                                    "week2_eligible", "premium")}
    return {"from": start.isoformat(), "to": end.isoformat(), "group": group, "rows": rows,
            "totals": totals,
            "definitions": {"activated": f"added a holding within {ACTIVATION_DAYS} days",
                            "activated_3": f"3+ holdings within {ACTIVATION_DAYS} days",
                            "week2": "used the app 7-13 days after sign-up (of users who signed up 14+ days ago)",
                            "premium": "Premium today"}}
