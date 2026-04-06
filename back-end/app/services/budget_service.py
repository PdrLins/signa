"""AI Budget Service — tracks spending per provider with daily/monthly limits.

Stores usage in-memory (fast checks) and persists to Supabase (survives restarts).
When a provider's budget is exhausted, calls are blocked and fallback kicks in.
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from app.core.config import settings

# ─── Estimated cost per call (USD) ───────────────────────────
# These are conservative estimates for typical Signa prompts.
# Synthesis: ~1200 input tokens + ~800 output tokens
# Sentiment: ~400 input tokens + ~600 output tokens
COST_ESTIMATES: dict[str, dict[str, float]] = {
    "claude": {
        "synthesis": 0.012,   # Sonnet 4: $3/M in + $15/M out → ~$0.012/call
    },
    "gemini": {
        "synthesis": 0.0,     # Free tier (2.0-flash, 1500 req/day)
        "sentiment": 0.0,     # Free tier
    },
    "grok": {
        "sentiment": 0.008,   # Grok-2: $2/M in + $10/M out → ~$0.008/call
    },
}

# Only keep this many days of daily data in memory
_MAX_DAILY_HISTORY = 7


class BudgetService:
    """Singleton that tracks AI spending and enforces budget limits."""

    _instance: Optional["BudgetService"] = None
    _lock = asyncio.Lock()

    def __init__(self):
        # {provider: {date_str: cost_usd}}
        self._daily_usage: dict[str, dict[str, float]] = {}
        # {provider: {month_str: cost_usd}}
        self._monthly_usage: dict[str, dict[str, float]] = {}
        # {provider: {date_str: call_count}}
        self._daily_calls: dict[str, dict[str, int]] = {}
        self._data_lock = asyncio.Lock()
        self._initialized = False

    @classmethod
    async def get_instance(cls) -> "BudgetService":
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = BudgetService()
                    await cls._instance._load_from_db()
        return cls._instance

    async def _load_from_db(self):
        """Load current month's usage from Supabase on startup."""
        if self._initialized:
            return
        try:
            from app.db.supabase import get_client
            client = get_client()
            now = datetime.now(timezone.utc)
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

            result = client.table("ai_usage").select("*").gte(
                "created_at", month_start.isoformat()
            ).execute()

            for row in result.data or []:
                provider = row["provider"]
                cost = float(row.get("estimated_cost", 0))
                created = row["created_at"][:10]  # YYYY-MM-DD
                month = row["created_at"][:7]      # YYYY-MM

                # Daily
                if provider not in self._daily_usage:
                    self._daily_usage[provider] = {}
                self._daily_usage[provider][created] = (
                    self._daily_usage[provider].get(created, 0) + cost
                )

                # Monthly
                if provider not in self._monthly_usage:
                    self._monthly_usage[provider] = {}
                self._monthly_usage[provider][month] = (
                    self._monthly_usage[provider].get(month, 0) + cost
                )

                # Call count
                if provider not in self._daily_calls:
                    self._daily_calls[provider] = {}
                self._daily_calls[provider][created] = (
                    self._daily_calls[provider].get(created, 0) + 1
                )

            self._initialized = True
            logger.info(f"Budget service loaded — {len(result.data or [])} usage records this month")
        except Exception as e:
            logger.warning(f"Budget service failed to load from DB: {e}")
            self._initialized = True  # Don't block on DB failure

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _month(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m")

    def get_daily_spend(self, provider: str) -> float:
        """Get today's spend for a provider in USD."""
        return self._daily_usage.get(provider, {}).get(self._today(), 0.0)

    def get_monthly_spend(self, provider: str) -> float:
        """Get this month's spend for a provider in USD."""
        return self._monthly_usage.get(provider, {}).get(self._month(), 0.0)

    def get_daily_calls(self, provider: str) -> int:
        """Get today's call count for a provider."""
        return self._daily_calls.get(provider, {}).get(self._today(), 0)

    async def can_call(self, provider: str, call_type: str = "synthesis") -> tuple[bool, str]:
        """Check if a provider call is within budget. Thread-safe."""
        async with self._data_lock:
            daily_limit = settings.budget_daily_limit_usd
            monthly_limit = settings.budget_monthly_limit_usd

            # Per-provider monthly limit (0 = unlimited, e.g. Gemini free tier)
            provider_limit = getattr(settings, f"budget_{provider}_monthly_usd", monthly_limit)

            daily_spend = self.get_daily_spend(provider)
            monthly_spend = self.get_monthly_spend(provider)

            # Free tier providers — always allow
            cost = COST_ESTIMATES.get(provider, {}).get(call_type, 0.01)
            if cost == 0:
                return True, "free_tier"

            # Check daily limit
            if daily_limit > 0 and daily_spend + cost > daily_limit:
                return False, f"Daily budget exceeded (${daily_spend:.3f}/${daily_limit:.2f})"

            # Check provider monthly limit (0 = unlimited)
            if provider_limit > 0 and monthly_spend + cost > provider_limit:
                return False, f"Monthly budget exceeded for {provider} (${monthly_spend:.3f}/${provider_limit:.2f})"

            return True, "ok"

    async def record_call(self, provider: str, call_type: str, ticker: str = "", success: bool = True):
        """Record an AI call and its estimated cost. Thread-safe."""
        cost = COST_ESTIMATES.get(provider, {}).get(call_type, 0.01)
        today = self._today()
        month = self._month()

        async with self._data_lock:
            # Update in-memory
            if provider not in self._daily_usage:
                self._daily_usage[provider] = {}
            self._daily_usage[provider][today] = (
                self._daily_usage[provider].get(today, 0) + cost
            )

            if provider not in self._monthly_usage:
                self._monthly_usage[provider] = {}
            self._monthly_usage[provider][month] = (
                self._monthly_usage[provider].get(month, 0) + cost
            )

            if provider not in self._daily_calls:
                self._daily_calls[provider] = {}
            self._daily_calls[provider][today] = (
                self._daily_calls[provider].get(today, 0) + 1
            )

            # Cleanup old daily entries to prevent unbounded growth
            self._cleanup_old_daily(provider)

        # Persist to DB (fire-and-forget via to_thread to not block)
        try:
            from app.db.supabase import get_client
            client = get_client()
            client.table("ai_usage").insert({
                "provider": provider,
                "call_type": call_type,
                "ticker": ticker,
                "estimated_cost": cost,
                "success": success,
            }).execute()
        except Exception as e:
            logger.debug(f"Failed to persist AI usage: {e}")

        # Log warning when approaching limits
        monthly_spend = self.get_monthly_spend(provider)
        provider_limit = getattr(settings, f"budget_{provider}_monthly_usd", settings.budget_monthly_limit_usd)
        if provider_limit > 0 and monthly_spend / provider_limit > 0.8:
            logger.warning(
                f"Budget alert: {provider} at {monthly_spend/provider_limit:.0%} "
                f"of monthly limit (${monthly_spend:.3f}/${provider_limit:.2f})"
            )

    def _cleanup_old_daily(self, provider: str):
        """Remove daily entries older than _MAX_DAILY_HISTORY days."""
        for store in (self._daily_usage, self._daily_calls):
            if provider in store and len(store[provider]) > _MAX_DAILY_HISTORY:
                # Sort keys and keep only recent ones
                sorted_keys = sorted(store[provider].keys())
                for old_key in sorted_keys[:-_MAX_DAILY_HISTORY]:
                    del store[provider][old_key]

    def get_budget_summary(self) -> dict:
        """Return budget summary for all providers."""
        providers = ["claude", "gemini", "grok"]

        summary = {
            "daily_limit_usd": settings.budget_daily_limit_usd,
            "monthly_limit_usd": settings.budget_monthly_limit_usd,
            "providers": {},
        }

        for p in providers:
            provider_limit = getattr(settings, f"budget_{p}_monthly_usd", settings.budget_monthly_limit_usd)
            daily_spend = self.get_daily_spend(p)
            monthly_spend = self.get_monthly_spend(p)
            daily_calls = self.get_daily_calls(p)

            summary["providers"][p] = {
                "daily_spend_usd": round(daily_spend, 4),
                "monthly_spend_usd": round(monthly_spend, 4),
                "monthly_limit_usd": provider_limit,
                "daily_calls": daily_calls,
                "budget_remaining_usd": round(max(0, provider_limit - monthly_spend), 4),
                "budget_pct_used": round(monthly_spend / provider_limit * 100, 1) if provider_limit > 0 else 0.0,
                "is_free_tier": all(v == 0 for v in COST_ESTIMATES.get(p, {}).values()),
            }

        total_monthly = sum(
            s["monthly_spend_usd"] for s in summary["providers"].values()
        )
        summary["total_monthly_spend_usd"] = round(total_monthly, 4)

        return summary
