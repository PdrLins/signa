"""Access levels: who can see which area and use which button.

Every user has an `access_level` in the `users` table (migration 011):

    free < premium < owner

Every area (a page) and action (a button / API operation) has a feature key
with a minimum level, e.g. `area.holdings` -> free, `feature.full_history`
-> premium. The catalog below is the list of features and their defaults;
rows in the `access_features` table override a catalog key's level, so a
feature can move between levels with one SQL update, without a deploy. DB
rows for keys not in the catalog (e.g. the brain's, now in Signa Advisor)
are ignored.

Enforcement happens on the server:
  * `require_feature(key)` is a FastAPI dependency on the routes (or whole
    routers) that belong to a feature -> 403 {"code": "upgrade_required"}.

The front-end gets the same keys from GET /auth/me and hides what the user
cannot use; hiding is a convenience, the server is the gate.

The level is read from the DB per request (cached 60s), so a change in the
database applies within a minute without logging out.
"""

from __future__ import annotations

import threading
import time
from contextvars import ContextVar
from typing import Callable, Optional

from fastapi import HTTPException, Request, status
from loguru import logger

from app.core.cache import TTLCache

LEVELS: tuple[str, ...] = ("free", "premium", "owner")
LEVEL_RANK: dict[str, int] = {lvl: i for i, lvl in enumerate(LEVELS)}
DEFAULT_LEVEL = "free"

# key -> (min level, description). Areas are pages; actions are buttons /
# API operations; system keys are internal capabilities.
FEATURE_CATALOG: dict[str, tuple[str, str]] = {
    # --- Areas (pages) ---
    "area.holdings": ("free", "My holdings"),
    "area.stock": ("free", "Stock page: price, dividends, events, Signa checks"),
    "area.dividends": ("free", "Dividend calendar and expected income"),
    "area.watchlist": ("free", "Watchlist"),
    "area.settings": ("free", "Settings"),
    "area.home": ("free", "Home: portfolio overview"),
    "area.insights": ("free", "Portfolio insights (allocation, performance)"),
    "area.coming_up": ("free", "Coming up: dividends, earnings and events"),
    "area.profile": ("free", "Profile, preferences and notifications"),
    "area.admin": ("owner", "Admin: data usage"),
    # --- Actions (buttons / operations) ---
    "action.holdings.edit": ("free", "Add, edit and remove holdings"),
    "action.watchlist.edit": ("free", "Add and remove watchlist stocks"),
    "action.accounts.edit": ("free", "Create, edit and delete accounts and people"),
    "action.accounts.type": ("free", "Tag accounts with a tax type (TFSA, RRSP, IRA ...)"),
    "action.transactions.edit": ("free", "Add, edit and delete transactions"),
    "action.alerts.edit": ("free", "Create, edit and delete price alerts"),
    "action.import.csv": ("free", "Import transactions from a CSV file"),
    # --- Features (behaviour inside an area) ---
    "feature.tax_view": ("premium", "After-tax dividend view"),
    "feature.intraday_chart": ("free", "5-minute intraday chart"),
    "feature.full_history": ("premium", "Full portfolio history (ALL range; free: up to 1 year)"),
    "feature.unlimited_alerts": ("premium", "No limit on active price alerts (free: FREE_ALERT_LIMIT)"),
    "feature.extended_hours": ("premium", "Pre-market and after-hours prices (US stocks)"),
    "feature.telegram_alerts": ("premium", "Notifications on Telegram (connect a chat, receive alerts)"),
    "feature.allocation_plan": ("premium", "Target allocation and deposit plan"),
    "feature.income_quality": ("premium", "Income quality of option-income / covered-call ETFs"),
    "feature.similar_funds": ("premium", "Similar funds compared (fee, yield, return)"),
    "feature.all_widgets": ("premium", "Every home-screen and lock-screen widget (free: 1)"),
    "feature.unlimited_goals": ("premium", "Unlimited goals (free: 1)"),
    "feature.suggestions_all": ("premium", "Every suggestion (free: 3 similar stocks and 3 also-followed)"),
    "feature.portfolio_gaps": ("premium", "Gaps in your portfolio, with ideas to look at"),
    "feature.push_all": ("premium", "Every push notification type (free: price alerts, dividends, earnings, report updates)"),
    # --- System capabilities ---
    "system.unlimited_slots": ("premium", "No limit on followed stocks"),
}

# Slots = stocks a user follows (holdings + watchlist). None = unlimited.
# Business rule: followed symbols are what users pay for. Free follows
# FREE_SLOT_LIMIT (15) + REFERRAL_SLOTS_PER_FRIEND (5) per rewarded referral,
# at most +REFERRAL_SLOTS_MAX (25) — migration 019, app/services/referrals.py.
# Premium and owner are unlimited (system.unlimited_slots, migration 015).
# `users.slot_bonus` is kept in the DB but ignored: the bonus is counted from
# the referrals table. slot_limit() is the ONLY place the limit is computed
# (slots.limit_for feeds it the rewarded count for /auth/me and every 403).
FREE_SLOT_LIMIT = 15
REFERRAL_SLOTS_PER_FRIEND = 5
REFERRAL_SLOTS_MAX = 25
SLOT_BASE: dict[str, Optional[int]] = {"free": FREE_SLOT_LIMIT, "premium": None, "owner": None}

# Active price alerts (app/services/price_alerts.py). None = unlimited
# (feature.unlimited_alerts, premium).
FREE_ALERT_LIMIT = 3


# What a 403 slot_limit / alert_limit body carries so a client can open
# its upgrade screen: {"feature": key that lifts the limit, "plan": level}.
def upgrade_hint(feature: str) -> dict:
    return {"feature": feature, "plan": "premium"}


_level_cache = TTLCache(max_size=10000, default_ttl=60)

# Access level of the user behind the current request; None outside a
# request (scheduler jobs, scripts). Set by AuthMiddleware; copied into
# tasks the request spawns (background checks keep their caller's level).
_request_level: ContextVar[Optional[str]] = ContextVar("signa_request_level", default=None)


def normalize_level(level: object) -> str:
    return level if isinstance(level, str) and level in LEVEL_RANK else DEFAULT_LEVEL


def level_allows(level: str, min_level: str) -> bool:
    return LEVEL_RANK[normalize_level(level)] >= LEVEL_RANK.get(min_level, LEVEL_RANK["owner"])


def _is_missing_column(err: Exception, column: str) -> bool:
    text = str(err).lower()
    return column in text and ("does not exist" in text or "could not find" in text or "42703" in text
                               or "pgrst204" in text)


FEATURES_TTL_S = 60
_features_last: tuple[dict[str, str], float] | None = None   # (levels, loaded at)
_features_refreshing = threading.Event()


def _load_feature_levels() -> dict[str, str]:
    """Blocking: catalog defaults overridden by DB rows."""
    global _features_last
    levels = {k: v[0] for k, v in FEATURE_CATALOG.items()}
    try:
        from app.db.supabase import get_client
        rows = get_client().table("access_features").select("key,min_level").execute().data or []
        for r in rows:
            key, lvl = r.get("key"), r.get("min_level")
            if key in levels and lvl in LEVEL_RANK:
                levels[key] = lvl
    except Exception as e:  # table missing (before 011) or DB down: defaults
        logger.debug(f"access_features unavailable, using defaults: {e}")
        if _features_last is not None:
            levels = _features_last[0]   # keep the last good levels through an outage
    _features_last = (levels, time.time())
    return levels


def _refresh_in_background() -> None:
    if _features_refreshing.is_set():
        return
    _features_refreshing.set()

    def run():
        try:
            _load_feature_levels()
        finally:
            _features_refreshing.clear()
    threading.Thread(target=run, name="access-features", daemon=True).start()


def get_feature_levels() -> dict[str, str]:
    """Feature key -> min level: catalog defaults overridden by DB rows.

    Read on every protected request, so it never waits on the database after
    the first load: older than FEATURES_TTL_S, the last levels are served while
    one background thread reloads them."""
    last = _features_last
    if last is None:
        return _load_feature_levels()
    if time.time() - last[1] > FEATURES_TTL_S:
        _refresh_in_background()
    return last[0]


_last_level = TTLCache(max_size=20000, default_ttl=24 * 3600)   # outage fallback, see below


def get_user_access(user_id: str) -> dict:
    """{"level", "slot_bonus"} for a user, cached 60s.

    On a database error: the user's last known level (kept 24 h), else free.
    Never owner.
    """
    if not user_id:
        return {"level": DEFAULT_LEVEL, "slot_bonus": 0}
    cached = _level_cache.get(user_id)
    if cached is not None:
        return cached
    try:
        from app.db.supabase import get_client
        rows = (get_client().table("users").select("access_level")
                .eq("id", user_id).limit(1).execute().data or [])
        row = rows[0] if rows else {}
        access = {"level": normalize_level(row.get("access_level")), "slot_bonus": 0}
    except Exception as e:
        # Never fail OPEN: an error can't make anyone owner. A known user keeps
        # their last level through an outage (no upgrade screen for Premium);
        # an unknown one is free until the database answers.
        last = _last_level.get(user_id)
        fallback = last or {"level": DEFAULT_LEVEL, "slot_bonus": 0}
        logger.error(f"Access level lookup failed for {user_id}: {type(e).__name__} — using "
                     f"{'the last known level' if last else 'free'}")
        _level_cache.set(user_id, fallback, ttl=5)   # brief: an outage doesn't hit the DB per request
        return fallback
    _level_cache.set(user_id, access)
    _last_level.set(user_id, access)
    return access


def clear_access_cache() -> None:
    global _features_last
    _level_cache.clear()
    _last_level.clear()
    _features_last = None


def allowed_features(level: str) -> list[str]:
    return sorted(k for k, lvl in get_feature_levels().items() if level_allows(level, lvl))


def can(level: str, feature: str) -> bool:
    """Unknown features require owner (fail closed)."""
    return level_allows(level, get_feature_levels().get(feature, "owner"))


def referral_bonus(rewarded_referrals: int) -> int:
    """Extra free slots from rewarded referrals: 5 each, at most 25."""
    return min(REFERRAL_SLOTS_PER_FRIEND * max(0, int(rewarded_referrals or 0)), REFERRAL_SLOTS_MAX)


def slot_limit(level: str, slot_bonus: int = 0, rewarded_referrals: int = 0) -> Optional[int]:
    """Followed-stock limit; None = unlimited. `slot_bonus` (users.slot_bonus)
    is accepted for old callers and ignored."""
    level = normalize_level(level)
    if can(level, "system.unlimited_slots"):
        return None
    base = SLOT_BASE.get(level)
    if base is None:
        return None
    return base + referral_bonus(rewarded_referrals)


def alert_limit(level: str) -> Optional[int]:
    """Max ACTIVE price alerts; None = unlimited (feature.unlimited_alerts)."""
    return None if can(normalize_level(level), "feature.unlimited_alerts") else FREE_ALERT_LIMIT


# ---------------------------------------------------------------- request API

def set_request_level(level: Optional[str]):
    return _request_level.set(level)


def reset_request_level(token) -> None:
    _request_level.reset(token)


def current_request_level() -> Optional[str]:
    return _request_level.get()


def upgrade_required(feature: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "upgrade_required", "feature": feature,
                "message": "This part of Signa isn't available on your plan."},
    )


def require_feature(feature: str) -> Callable:
    """FastAPI dependency: 403 unless the current user can use `feature`."""
    async def _dep(request: Request) -> None:
        user = getattr(request.state, "user", None)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        level = user.get("access_level") or get_user_access(user.get("user_id"))["level"]
        if not can(level, feature):
            raise upgrade_required(feature)
    _dep.__name__ = f"require_{feature.replace('.', '_')}"
    return _dep
