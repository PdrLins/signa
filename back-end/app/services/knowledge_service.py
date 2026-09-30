"""Knowledge service — reads investment rules and signal knowledge from DB.

Used by the signal engine to build AI prompts with current rules.
Caches results for 5 minutes to avoid hammering the DB during scans.
"""

from typing import Optional

from loguru import logger

from app.core.cache import TTLCache
from app.core.config import settings
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


# ============================================================
# PROMPT KNOWLEDGE — the ONE source of truth for what Claude reads
# ============================================================
#
# The synthesis prompt (scan_service + stock_check, Sonnet and the Opus
# BUY re-check) injects exactly these signal_knowledge rows, in this order.
# They are stored in the DB (topic PROMPT_CORE, source_type
# curated_2026_09) by scripts/curate_brain_knowledge.py so the owner can
# edit them in the Brain Editor. Until that script runs (or if a row is
# deactivated/missing) the built-in text below is used instead, so the
# prompt never falls back to the old stale 10-row list.

PROMPT_CORE_TOPIC = "PROMPT_CORE"
PROMPT_CORE_SOURCE_TYPE = "curated_2026_09"

PROMPT_KNOWLEDGE_CONCEPTS = [
    "prompt_horizon",
    "prompt_enforced_by_code",
    "prompt_evidence_2021_2026",
    "prompt_factor_independence",
    "prompt_momentum_crash_caution",
]


def _fmt_money(v: float) -> str:
    return f"${v / 1_000_000:g}M" if v >= 1_000_000 else f"${v:,.0f}"


def build_prompt_core_rows() -> list[dict]:
    """The curated PROMPT_CORE rows (~350 tokens total), with live thresholds
    read from settings. Hardcoded values (RSI 75 / SMA200 +50% blockers) mirror
    `signal_engine.check_blockers`."""
    s = settings
    texts = {
        "prompt_horizon": (
            "Signa trades a 5-20 trading-day horizon; positions auto-close after at most "
            f"{s.virtual_trade_max_days} days. p_win means the probability that the price is higher "
            f"{s.ai_pwin_horizon_days} trading days after entry. Judge the next 1-4 weeks, not the long-term story."
        ),
        "prompt_enforced_by_code": (
            "Code already enforces these; do not penalize them again. Judge what code cannot see. "
            "Blocked: RSI(14) > 75, price > 50% above SMA200, cited material red flags, hostile macro; "
            f"BUY downgraded to HOLD within {s.earnings_blackout_trading_days} trading days of earnings. Technical filter: price > SMA200, "
            f"SMA50 > SMA200, <= {s.tech_filter_max_ext_sma50_pct:g}% above SMA50, 20-day dollar volume >= "
            f"{_fmt_money(s.tech_filter_min_dollar_volume)} ({_fmt_money(s.tech_filter_min_dollar_volume_crypto)} crypto). "
            f"Entry needs reward:risk >= {s.brain_min_rr:g} from final levels. Sizing risks "
            f"{s.brain_risk_per_trade_pct:g}% of equity per trade (<= {s.brain_max_position_pct:g}% per position); "
            f"the {s.brain_stop_atr_mult:g}xATR stop is always hard. Max {s.brain_max_open_positions} positions, "
            f"{s.brain_max_per_sector} per sector, {s.brain_max_crypto_pct:g}% crypto; correlation gate blocks "
            f">= {s.brain_corr_max_pairwise:g} to one holding or >= {s.brain_corr_cluster_threshold:g} to "
            f"{s.brain_corr_cluster_max} holdings."
        ),
        "prompt_evidence_2021_2026": (
            "A 2021-2026 backtest of the technical layer (8,996 trades, survivorship-biased universe) found "
            "no edge vs SPY from the technical score or the technical filter: about 40% of trades beat SPY in "
            "every score band. Names failing the filter on RSI > 75 did best (+2.4pp vs SPY, n=104, small sample). "
            "Most setups have no edge: HOLD unless independent, cited evidence agrees. No dated catalyst "
            "is needed: strong recent fundamentals (earnings beat, rising estimates, insider buying) in an "
            "intact uptrend can justify BUY. Missing news is a data gap, not evidence against."
        ),
        "prompt_factor_independence": (
            "RSI, MACD, moving-average trend and short-term momentum all come from the same price series: "
            "count them as one piece of evidence, not three. Conviction needs independent sources, such as "
            "company news or fundamentals, analyst estimate revisions, or a dated catalyst, each cited."
        ),
        "prompt_momentum_crash_caution": (
            "After a sharp market rebound from a deep drawdown (the RECOVERY regime), recent losers tend to "
            "rally hardest and recent momentum leaders can fall sharply. In RECOVERY, be skeptical of chasing "
            "extended winners and require independent evidence."
        ),
    }
    return [
        {
            "topic": PROMPT_CORE_TOPIC,
            "key_concept": key,
            "explanation": texts[key],
            "formula": None,
            "example": None,
            "is_active": True,
            "source_name": "Signa curated prompt knowledge (2026-09 audit)",
            "source_type": PROMPT_CORE_SOURCE_TYPE,
        }
        for key in PROMPT_KNOWLEDGE_CONCEPTS
    ]


def get_live_thresholds_block() -> str:
    """Live decision thresholds (from settings) as prompt text. These, not the
    investment_rules table, are what the code actually enforces."""
    s = settings
    return "\n".join([
        f"- brain_entry_mode={s.brain_entry_mode}; AI BUY needs confidence >= {s.ai_validated_min_confidence}",
        f"- tech_filter_max_rsi={s.tech_filter_max_rsi:g}, tech_filter_max_ext_sma50_pct={s.tech_filter_max_ext_sma50_pct:g}, "
        f"tech_filter_min_dollar_volume={s.tech_filter_min_dollar_volume:,.0f} (crypto {s.tech_filter_min_dollar_volume_crypto:,.0f})",
        f"- earnings_blackout_trading_days={s.earnings_blackout_trading_days}; brain_min_rr={s.brain_min_rr:g}",
        f"- brain_risk_per_trade_pct={s.brain_risk_per_trade_pct:g}, brain_max_position_pct={s.brain_max_position_pct:g}, "
        f"brain_max_open_positions={s.brain_max_open_positions}, brain_max_per_sector={s.brain_max_per_sector}, "
        f"brain_max_crypto_pct={s.brain_max_crypto_pct:g}",
        f"- brain_stop_atr_mult={s.brain_stop_atr_mult:g}, brain_target_r_mult={s.brain_target_r_mult:g}, "
        f"brain_trail_atr_mult={s.brain_trail_atr_mult:g} after +{s.brain_trail_activate_r:g}R, "
        f"virtual_trade_max_days={s.virtual_trade_max_days}",
        f"- correlation gate: pairwise >= {s.brain_corr_max_pairwise:g}, or >= {s.brain_corr_cluster_max} holdings "
        f">= {s.brain_corr_cluster_threshold:g}; brain_max_drawdown_pct={s.brain_max_drawdown_pct:g}",
        "- hardcoded blockers (signal_engine.check_blockers): RSI > 75, > 50% above SMA200, hostile macro, "
        "cited material red flags, avg volume < 50K",
    ])


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
            Formatted text block suitable for embedding in a prompt. Now also
            appends a "Working Hypotheses" section listing active thinking
            entries (low-confidence observations under test) so Claude sees
            the brain's tentative learnings alongside its proven knowledge.
        """
        all_knowledge = self.get_active_knowledge()
        selected = [k for k in all_knowledge if k.get("key_concept") in key_concepts]

        lines = []
        for k in selected:
            lines.append(f"## {k.get('key_concept', '')}")
            lines.append(k.get("explanation", ""))
            if k.get("formula"):
                lines.append(f"Formula: {k['formula']}")
            if k.get("example"):
                lines.append(f"Example: {k['example']}")
            lines.append("")

        thinking_block = self.get_active_thinking_block()
        if thinking_block:
            lines.append(thinking_block)

        return "\n".join(lines).strip()

    def get_prompt_knowledge_text(self) -> str:
        """The PROMPT_CORE rows (DB text when present and active, else the
        built-in text), in PROMPT_KNOWLEDGE_CONCEPTS order. No hypotheses."""
        try:
            db_rows = {k.get("key_concept"): k for k in self.get_active_knowledge()}
        except Exception as e:
            logger.warning(f"Prompt knowledge DB read failed, using built-in text: {e}")
            db_rows = {}
        defaults = {r["key_concept"]: r for r in build_prompt_core_rows()}
        lines = []
        for key in PROMPT_KNOWLEDGE_CONCEPTS:
            row = db_rows.get(key) or defaults[key]
            lines.append(f"## {key}")
            lines.append((row.get("explanation") or defaults[key]["explanation"]).strip())
            lines.append("")
        return "\n".join(lines).strip()

    async def get_prompt_knowledge_block(self) -> str:
        """The knowledge block for every synthesis prompt: PROMPT_CORE rows
        plus the working-hypotheses block (only hypotheses with enough
        observations). Single source of truth for scan + stock check."""
        text = self.get_prompt_knowledge_text()
        thinking_block = self.get_active_thinking_block()
        if thinking_block:
            text = f"{text}\n\n{thinking_block}"
        return text

    def get_active_thinking(self) -> list[dict]:
        """Get all active thinking entries (hypotheses under observation).

        Returns an empty list if the signal_thinking table doesn't exist
        yet (forward-compatible with environments where the migration
        hasn't been applied).
        """
        cached = _get_cached("thinking_active")
        if cached is not None:
            return cached

        client = get_client()
        try:
            result = (
                client.table("signal_thinking")
                .select("*")
                .eq("status", "active")
                .order("created_at", desc=True)
                .execute()
            )
            entries = result.data or []
        except Exception as e:
            # Table may not exist yet — log once and return empty
            if "signal_thinking" in str(e).lower():
                logger.debug("signal_thinking table not present yet — returning no hypotheses")
            else:
                logger.warning(f"Failed to load active thinking entries: {e}")
            entries = []

        _set_cached("thinking_active", entries)
        return entries

    def get_active_thinking_block(self) -> str:
        """Format active thinking entries as a 'Working Hypotheses' markdown block.

        Only hypotheses with at least hypothesis_prompt_min_observations
        observed trades are included. Returns an empty string if none
        qualify. The framing
        is intentional: Claude is told these are LOW CONFIDENCE observations
        under test, not validated truth. The supporting/contradicting counts
        are exposed so Claude can weigh each hypothesis appropriately.
        """
        def _observed(h: dict) -> int:
            return sum(
                h.get(k) or 0
                for k in ("observations_supporting", "observations_contradicting", "observations_neutral")
            )

        min_n = settings.hypothesis_prompt_min_observations
        entries = [h for h in self.get_active_thinking() if _observed(h) >= min_n]
        if not entries:
            return ""

        lines = ["## Working Hypotheses (under observation — low confidence)"]
        lines.append(
            "These are tentative patterns the brain has observed but NOT yet validated. "
            "Treat them as data to consider, not as rules to follow."
        )
        lines.append("")
        for h in entries:
            lines.append(f"### {h.get('hypothesis', '(no hypothesis)')}")
            if h.get("prediction"):
                lines.append(f"**Prediction:** {h['prediction']}")
            supporting = h.get("observations_supporting") or 0
            contradicting = h.get("observations_contradicting") or 0
            neutral = h.get("observations_neutral") or 0
            total = supporting + contradicting + neutral
            lines.append(
                f"**Evidence so far:** {supporting} supporting, "
                f"{contradicting} contradicting, {neutral} neutral "
                f"(total observed: {total})"
            )
            if h.get("notes"):
                lines.append(f"**Notes:** {h['notes']}")
            lines.append(
                "_This is a hypothesis under test — weigh accordingly._"
            )
            lines.append("")
        return "\n".join(lines).rstrip()

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
