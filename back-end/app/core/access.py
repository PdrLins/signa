"""Access levels: who can see which area and use which button.

Every user has an `access_level` in the `users` table (migration 011):

    free < premium < owner

Every area (a page) and action (a button / API operation) has a feature key
with a minimum level, e.g. `area.holdings` -> free, `action.check.run` ->
owner. The catalog below holds the defaults; rows in the `access_features`
table override them, so a feature can move between levels with one SQL
update, without a deploy.

Enforcement happens on the server:
  * `require_feature(key)` is a FastAPI dependency on the routes (or whole
    routers) that belong to a feature -> 403 {"code": "upgrade_required"}.
  * The AI layer calls `assert_ai_allowed()`: a request whose user lacks
    `system.ai` cannot trigger a paid (or owner-subscription) AI call, even
    if a route forgot its check. Scheduled jobs run without a request and
    are allowed.

The front-end gets the same keys from GET /auth/me and hides what the user
cannot use; hiding is a convenience, the server is the gate.

The level is read from the DB per request (cached 60s), so a change in the
database applies within a minute without logging out.
"""

from __future__ import annotations

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
    "area.today": ("owner", "Today: brain dashboard"),
    "area.signals": ("owner", "Signals from the brain's scans"),
    "area.check": ("owner", "Check a stock (AI)"),
    "area.positions": ("owner", "Paper-trading positions and wallet"),
    "area.performance": ("owner", "Is it working? (brain track record)"),
    "area.brain": ("owner", "Brain rules, knowledge and learning"),
    "area.holdings": ("free", "My holdings"),
    "area.stock": ("free", "Stock page: price, dividends, events, Signa checks"),
    "area.dividends": ("free", "Dividend calendar and expected income"),
    "area.watchlist": ("free", "Watchlist"),
    "area.how_it_works": ("free", "How it works"),
    "area.settings": ("free", "Settings"),
    "area.home": ("free", "Home: portfolio overview"),
    "area.insights": ("free", "Portfolio insights (allocation, performance)"),
    "area.coming_up": ("free", "Coming up: dividends, earnings and events"),
    "area.profile": ("free", "Profile, preferences and notifications"),
    "area.integrations": ("owner", "Integrations, AI config and budgets"),
    "area.logs": ("owner", "Live logs"),
    # --- Actions (buttons / operations) ---
    "action.scan.trigger": ("owner", "Start a scan"),
    "action.check.run": ("owner", "Run an AI stock check"),
    "action.check.compare": ("owner", "Compare 2-3 stocks with AI"),
    "action.holdings.edit": ("free", "Add, edit and remove holdings"),
    "action.holdings.refresh": ("owner", "Refresh holdings monitor (may use Grok)"),
    "action.holdings.review": ("owner", "AI review of holdings"),
    "action.holdings.allocate": ("owner", "Where could new cash go? (AI)"),
    "action.watchlist.edit": ("free", "Add and remove watchlist stocks"),
    "action.accounts.edit": ("free", "Create, edit and delete accounts and people"),
    "action.accounts.type": ("premium", "Tag accounts with a tax type (TFSA, RRSP, IRA ...)"),
    "action.transactions.edit": ("free", "Add, edit and delete transactions"),
    "action.import.csv": ("free", "Import transactions from a CSV file"),
    "action.positions.manage": ("owner", "Open, edit and close positions"),
    "action.wallet.manage": ("owner", "Deposit to / withdraw from the paper wallet"),
    "action.brain.edit": ("owner", "Edit brain rules and knowledge"),
    "action.learning.manage": ("owner", "Approve / apply learning suggestions"),
    "action.settings.ai": ("owner", "Change AI config and budgets"),
    # --- Features (behaviour inside an area) ---
    "feature.tax_view": ("premium", "After-tax dividend view"),
    # --- System capabilities ---
    "system.ai": ("owner", "Trigger AI calls (Grok, Claude, Codex)"),
    "system.unlimited_slots": ("owner", "No limit on followed stocks"),
}

# Slots = stocks a user follows (holdings + watchlist). None = unlimited.
SLOT_BASE: dict[str, Optional[int]] = {"free": 5, "premium": 50, "owner": None}
SLOT_MAX: dict[str, Optional[int]] = {"free": 25, "premium": 100, "owner": None}

_level_cache = TTLCache(max_size=500, default_ttl=60)
_features_cache = TTLCache(max_size=1, default_ttl=60)

# Access level of the user behind the current request; None outside a
# request (scheduler jobs, scripts). Set by AuthMiddleware; copied into
# tasks the request spawns (background checks keep their caller's level).
_request_level: ContextVar[Optional[str]] = ContextVar("signa_request_level", default=None)


class AIAccessDenied(PermissionError):
    """An AI call was attempted on behalf of a user without system.ai."""


def normalize_level(level: object) -> str:
    return level if isinstance(level, str) and level in LEVEL_RANK else DEFAULT_LEVEL


def level_allows(level: str, min_level: str) -> bool:
    return LEVEL_RANK[normalize_level(level)] >= LEVEL_RANK.get(min_level, LEVEL_RANK["owner"])


def _is_missing_column(err: Exception, column: str) -> bool:
    text = str(err).lower()
    return column in text and ("does not exist" in text or "could not find" in text or "42703" in text
                               or "pgrst204" in text)


def get_feature_levels() -> dict[str, str]:
    """Feature key -> min level: catalog defaults overridden by DB rows."""
    cached = _features_cache.get("features")
    if cached is not None:
        return cached
    levels = {k: v[0] for k, v in FEATURE_CATALOG.items()}
    try:
        from app.db.supabase import get_client
        rows = get_client().table("access_features").select("key,min_level").execute().data or []
        for r in rows:
            key, lvl = r.get("key"), r.get("min_level")
            if isinstance(key, str) and lvl in LEVEL_RANK:
                levels[key] = lvl
    except Exception as e:  # table missing (before 011) or DB down: defaults
        logger.debug(f"access_features unavailable, using defaults: {e}")
    _features_cache.set("features", levels)
    return levels


def get_user_access(user_id: str) -> dict:
    """{"level", "slot_bonus"} for a user, cached 60s.

    Before migration 011 there is no access_level column; Signa then had a
    single user (the owner), so every account is treated as owner. Any other
    failure fails closed to free.
    """
    if not user_id:
        return {"level": DEFAULT_LEVEL, "slot_bonus": 0}
    cached = _level_cache.get(user_id)
    if cached is not None:
        return cached
    try:
        from app.db.supabase import get_client
        rows = (get_client().table("users").select("access_level,slot_bonus")
                .eq("id", user_id).limit(1).execute().data or [])
        row = rows[0] if rows else {}
        access = {"level": normalize_level(row.get("access_level")),
                  "slot_bonus": int(row.get("slot_bonus") or 0)}
    except Exception as e:
        if _is_missing_column(e, "access_level") or _is_missing_column(e, "slot_bonus"):
            logger.warning("users.access_level missing — apply migration 011; treating user as owner")
            access = {"level": "owner", "slot_bonus": 0}
        else:
            logger.error(f"Access level lookup failed for {user_id}: {e} — failing closed to free")
            return {"level": DEFAULT_LEVEL, "slot_bonus": 0}  # not cached: retry next request
    _level_cache.set(user_id, access)
    return access


def clear_access_cache() -> None:
    _level_cache.clear()
    _features_cache.clear()


def allowed_features(level: str) -> list[str]:
    return sorted(k for k, lvl in get_feature_levels().items() if level_allows(level, lvl))


def can(level: str, feature: str) -> bool:
    """Unknown features require owner (fail closed)."""
    return level_allows(level, get_feature_levels().get(feature, "owner"))


def slot_limit(level: str, slot_bonus: int = 0) -> Optional[int]:
    level = normalize_level(level)
    if can(level, "system.unlimited_slots"):
        return None
    base, cap = SLOT_BASE.get(level), SLOT_MAX.get(level)
    if base is None:
        return None
    total = base + max(0, slot_bonus)
    return min(total, cap) if cap is not None else total


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


def assert_ai_allowed(what: str = "AI call") -> None:
    """Hard stop in the AI layer. Outside a request (scheduler) -> allowed."""
    level = _request_level.get()
    if level is not None and not can(level, "system.ai"):
        logger.warning(f"Blocked {what}: requesting user's level '{level}' lacks system.ai")
        raise AIAccessDenied(f"{what} is not available on this plan")


def ai_guarded(what: str) -> Callable:
    """Decorator for async AI entry points: assert_ai_allowed() first."""
    import functools

    def wrap(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def inner(*args, **kwargs):
            assert_ai_allowed(what)
            return await fn(*args, **kwargs)
        return inner
    return wrap
