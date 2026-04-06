"""Knowledge service — reads investment rules and signal knowledge from DB.

Used by the signal engine to build AI prompts with current rules.
Caches results for 5 minutes to avoid hammering the DB during scans.
"""

from typing import Optional

from loguru import logger

from app.core.cache import TTLCache
from app.db.supabase import get_client

_cache = TTLCache(max_size=200, default_ttl=300)


def _get_cached(key: str):
    return _cache.get(key)


def _set_cached(key: str, value):
    _cache.set(key, value)


def invalidate_cache():
    """Clear all cached knowledge. Called after brain edits."""
    _cache.clear()
    logger.info("Knowledge cache invalidated")


class KnowledgeService:
    """Reads rules and knowledge from Supabase."""

    def get_active_rules(self, rule_type: Optional[str] = None) -> list[dict]:
        """Get all active investment rules, optionally filtered by type."""
        cached = _get_cached(f"rules_{rule_type}")
        if cached is not None:
            return cached

        client = get_client()
        query = client.table("investment_rules").select("*").eq("is_active", True)
        if rule_type:
            query = query.eq("rule_type", rule_type)
        query = query.order("rule_type").order("name")
        result = query.execute()
        rules = result.data or []
        _set_cached(f"rules_{rule_type}", rules)
        return rules

    def get_all_rules(self) -> list[dict]:
        """Get ALL rules (active + inactive) for the brain editor."""
        client = get_client()
        result = (
            client.table("investment_rules")
            .select("*")
            .order("rule_type")
            .order("name")
            .limit(500)
            .execute()
        )
        return result.data or []

    def get_rule_by_id(self, rule_id: str) -> dict | None:
        client = get_client()
        result = (
            client.table("investment_rules")
            .select("*")
            .eq("id", rule_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def update_rule(self, rule_id: str, data: dict) -> dict:
        client = get_client()
        result = client.table("investment_rules").update(data).eq("id", rule_id).execute()
        invalidate_cache()
        return result.data[0] if result.data else {}

    def get_active_knowledge(self, topic: Optional[str] = None) -> list[dict]:
        """Get all active signal knowledge, optionally filtered by topic."""
        cached = _get_cached(f"knowledge_{topic}")
        if cached is not None:
            return cached

        client = get_client()
        query = client.table("signal_knowledge").select("*").eq("is_active", True)
        if topic:
            query = query.eq("topic", topic)
        query = query.order("topic").order("key_concept")
        result = query.execute()
        knowledge = result.data or []
        _set_cached(f"knowledge_{topic}", knowledge)
        return knowledge

    def get_all_knowledge(self) -> list[dict]:
        """Get ALL knowledge (active + inactive) for the brain editor."""
        client = get_client()
        result = (
            client.table("signal_knowledge")
            .select("*")
            .order("topic")
            .order("key_concept")
            .limit(500)
            .execute()
        )
        return result.data or []

    def get_knowledge_by_id(self, knowledge_id: str) -> dict | None:
        client = get_client()
        result = (
            client.table("signal_knowledge")
            .select("*")
            .eq("id", knowledge_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def update_knowledge(self, knowledge_id: str, data: dict) -> dict:
        client = get_client()
        result = client.table("signal_knowledge").update(data).eq("id", knowledge_id).execute()
        invalidate_cache()
        return result.data[0] if result.data else {}

    async def get_knowledge_block(self, key_concepts: list[str]) -> str:
        """Format specific knowledge entries into a text block for AI prompts.

        Args:
            key_concepts: List of key_concept values to include.

        Returns:
            Formatted text block suitable for embedding in a prompt.
        """
        all_knowledge = self.get_active_knowledge()
        selected = [k for k in all_knowledge if k.get("key_concept") in key_concepts]

        if not selected:
            return ""

        lines = []
        for k in selected:
            lines.append(f"## {k.get('key_concept', '')}")
            lines.append(k.get("explanation", ""))
            if k.get("formula"):
                lines.append(f"Formula: {k['formula']}")
            if k.get("example"):
                lines.append(f"Example: {k['example']}")
            lines.append("")

        return "\n".join(lines)

    def get_blocker_rules(self) -> list[dict]:
        """Get all active blocker rules."""
        rules = self.get_active_rules()
        return [r for r in rules if r.get("is_blocker")]

    def get_sell_rules(self) -> list[dict]:
        """Get all active SELL-type rules."""
        return self.get_active_rules(rule_type="SELL")

    def get_highlights(self) -> dict:
        """Get non-sensitive summary for the brain locked state."""
        all_rules = self.get_all_rules()
        all_knowledge = self.get_all_knowledge()

        active_rules = [r for r in all_rules if r.get("is_active")]

        rules_by_type: dict[str, int] = {}
        for r in active_rules:
            rt = r.get("rule_type", "OTHER")
            rules_by_type[rt] = rules_by_type.get(rt, 0) + 1

        blocker_count = sum(1 for r in active_rules if r.get("is_blocker"))
        safe_rules = sum(1 for r in active_rules if r.get("bucket") in ("SAFE_INCOME", "BOTH"))
        risk_rules = sum(1 for r in active_rules if r.get("bucket") in ("HIGH_RISK", "BOTH"))

        last_rule = max(
            (r.get("updated_at", r.get("created_at", "")) for r in all_rules),
            default=None,
        )
        last_knowledge = max(
            (k.get("updated_at", k.get("created_at", "")) for k in all_knowledge),
            default=None,
        )

        return {
            "total_rules": len(all_rules),
            "active_rules": len(active_rules),
            "total_knowledge": len(all_knowledge),
            "rules_by_type": rules_by_type,
            "last_rule_updated": last_rule,
            "last_knowledge_updated": last_knowledge,
            "blocker_count": blocker_count,
            "safe_income_rules": safe_rules,
            "high_risk_rules": risk_rules,
        }
