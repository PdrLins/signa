"""AI Budget Service — runaway-cost protection for paid AI providers.

============================================================
WHAT THIS MODULE IS
============================================================

Signa uses paid AI APIs (Claude, Grok). Without limits, a bug in the
scanner could blow through hundreds of dollars in a single afternoon —
imagine an infinite retry loop on a 500 error, or a regex bug that
sends 50K-character prompts. This module is the spending circuit
breaker.

It enforces TWO independent caps per provider:
  • DAILY     — default $1.00 across all providers
  • MONTHLY   — default $5.00 per provider (Claude=$5, Grok=$5,
                Gemini=$0/unlimited because it's free tier)

Every paid AI call goes through `can_call()` BEFORE being made. If
the call would push spending over either limit, it returns False and
`provider.synthesize_signal` (or `analyze_sentiment`) skips that
provider and falls through to the next in the chain.

After each successful call, `record_call()` updates the running totals,
fires Telegram alerts at 70/90/100% thresholds, and persists the call
to the `ai_usage` DB table for audit / dashboard reporting.

============================================================
TIERED ALERT SYSTEM
============================================================

Each threshold (70%, 90%, 100%) fires AT MOST ONCE per provider per
month. The dedup is in-memory (`_alert_sent`), so a process restart
could cause one duplicate alert per month per threshold (acceptable
trade-off for avoiding DB writes on the hot path).

The alerts say:
  •  70% — "Heads up — budget at 70%. Plan ahead before it runs out."
  •  90% — "Approaching limit. Consider increasing budget or reducing scans."
  • 100% — "Provider blocked. Brain will fall back to next provider in chain."

100% is the most important: that's when the brain effectively goes
blind on this provider until the user takes action.

============================================================
STORAGE MODEL
============================================================

  In-memory dicts (`_daily_usage`, `_monthly_usage`, `_daily_calls`):
    Fast O(1) read for `can_call`. Loaded from DB on startup, updated
    on every `record_call`. Daily entries are pruned to the last 7
    days to prevent unbounded growth.

  DB (`ai_usage` table):
    One row per call: provider, call_type, ticker, estimated_cost,
    success, created_at. Used for the dashboard's "AI Cost Today"
    widget and for audit / debugging.

  Singleton pattern:
    `BudgetService.get_instance()` returns the one shared instance.
    The instance is created on first call and persists for the
    lifetime of the process. The async lock prevents two coroutines
    from each creating their own instance during cold start.

============================================================
COST ESTIMATES
============================================================

Estimated per-call costs (validated against real usage):

  Claude synthesis (Sonnet 4):  $0.012  (1200 in + 800 out tokens)
  Gemini synthesis (2.0-flash): $0.000  (free tier)
  Grok sentiment (grok-3-mini): $0.0002 (400 in + 600 out tokens)
  Gemini sentiment (2.0-flash): $0.000  (free tier)

If actual usage diverges from these, update COST_ESTIMATES at the
top of this file. The dashboard's "AI Cost Today" reflects these
estimates, not real billing — cross-check with provider invoices
monthly.
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
        "synthesis": 0.012,   # Sonnet 4: $3/M in + $15/M out → ~$0.012/call (validated: $0.99 for ~85 calls)
    },
    "gemini": {
        "synthesis": 0.0,     # Free tier (2.0-flash, 1500 req/day)
        "sentiment": 0.0,     # Free tier
    },
    "grok": {
        "sentiment": 0.0002,  # Grok-3-mini: ~$0.0002/call (validated: $0.0045 for ~30 calls)
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
        # Track which budget alert thresholds have already been sent this month
        # so we don't spam Telegram on every call. Resets at start of new month.
        # Format: {f"{provider}:{month_str}": set([70, 90, 100])}
        self._alert_sent: dict[str, set[int]] = {}
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

        # Tiered budget alerts: log warning + Telegram at 70%, 90%, 100%.
        # Each threshold fires at most once per provider per month.
        monthly_spend = self.get_monthly_spend(provider)
        provider_limit = getattr(settings, f"budget_{provider}_monthly_usd", settings.budget_monthly_limit_usd)
        if provider_limit > 0:
            pct = (monthly_spend / provider_limit) * 100
            await self._maybe_send_threshold_alert(provider, monthly_spend, provider_limit, pct)

    async def _maybe_send_threshold_alert(
        self, provider: str, monthly_spend: float, provider_limit: float, pct: float
    ) -> None:
        """Send a Telegram alert when budget crosses 70%, 90%, or 100% — once per month."""
        thresholds_crossed = [t for t in (70, 90, 100) if pct >= t]
        if not thresholds_crossed:
            return
        highest_crossed = max(thresholds_crossed)

        month_key = f"{provider}:{self._month()}"
        sent = self._alert_sent.setdefault(month_key, set())
        if highest_crossed in sent:
            return  # Already alerted for this threshold this month

        sent.add(highest_crossed)
        # Also mark all lower thresholds as sent (in case we jumped past them)
        for t in thresholds_crossed:
            sent.add(t)

        logger.warning(
            f"Budget alert: {provider} at {pct:.0f}% of monthly limit "
            f"(${monthly_spend:.3f}/${provider_limit:.2f})"
        )

        # Send Telegram alert (best-effort, don't block the call recording)
        try:
            from app.notifications.messages import msg
            from app.notifications.telegram_bot import enqueue
            if highest_crossed >= 100:
                threshold_msg = "Provider blocked. Brain will fall back to next provider in chain."
            elif highest_crossed >= 90:
                threshold_msg = "Approaching limit. Consider increasing budget or reducing scans."
            else:
                threshold_msg = "Heads up — budget at 70%. Plan ahead before it runs out."
            enqueue(
                settings.telegram_chat_id,
                msg(
                    "budget_threshold",
                    provider=provider,
                    pct=str(int(pct)),
                    spend=f"{monthly_spend:.2f}",
                    limit=f"{provider_limit:.2f}",
                    threshold=str(highest_crossed),
                    threshold_msg=threshold_msg,
                ),
            )
        except Exception as e:
            logger.debug(f"Failed to send budget alert: {e}")

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
