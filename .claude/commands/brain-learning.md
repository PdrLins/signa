Show how the Signa brain learns: thinking, knowledge, thesis tracking, pattern stats, and the audit log.

## The Principle

**AI is the decider, not one witness among three.** Claude (synthesis) and Grok (sentiment) are the brain's portfolio manager. Math (formulas) and knowledge (rules, hypotheses, lessons) are the *dossier* the decider reads. The brain's job is to make the dossier complete and honest, not to override Claude after the fact.

The original architecture treated `_eval_brain_trust_tier` as a hard gate keyed only on `ai_status × score`. That's still in place, but the learning loop layered above it gives Claude four independent context streams that all flow into one prompt. Plus a thesis tracker that re-asks Claude after every scan whether the original reason for owning still holds.

## The 4 Evidence Layers Claude Sees

Every brain BUY decision and every thesis re-evaluation runs against a prompt that includes ALL of these:

| Section in prompt | Source | Confidence | Built by |
|---|---|---|---|
| `## Investment Knowledge` | `signal_knowledge` table — proven, validated patterns | HIGH (validated) | `KnowledgeService.get_knowledge_block()` |
| `## Working Hypotheses` | `signal_thinking` table — patterns under observation | LOW (under test) | `KnowledgeService.get_active_thinking_block()` |
| `## Pattern Stats` | `trade_outcomes` (closed) + `virtual_trades` WHERE OPEN, combined per (bucket, regime) | DATA-DRIVEN | `pattern_stats.get_pattern_warning()` |
| `## Warning Signs` | `signal_breakdown.RULES` filtered to `tone == TONE_NEGATIVE`, formatted via `KEY_TO_PROMPT_TEXT` | DATA-DRIVEN | `danger_signals.format_warning_signs()` |

The 4 sections are concatenated into the synthesis prompt at `app/ai/prompts.py:CLAUDE_SYNTHESIS_PROMPT`. The `## Warning Signs` section is placed JUST BEFORE `## Your Task` to exploit LLM recency bias — danger signs are the last thing Claude reads before deciding.

## Thinking → Knowledge Graduation

Hypotheses live in `signal_thinking`. Validated patterns live in `signal_knowledge`. They're separate tables because **N=2 is not knowledge**.

```
observation → THINKING (active) → graduates → KNOWLEDGE
                ↓
            (counter-evidence wins) → REJECTED (kept as history)
                ↓
            (no observations for X days) → STALE (kept as history)
```

| | `signal_thinking` | `signal_knowledge` |
|---|---|---|
| Confidence | LOW — under observation | HIGH — proven |
| How AI sees it | "Working Hypothesis (low confidence)" | "Investment Knowledge" |
| Schema highlights | `pattern_match` JSONB, `prediction`, `observations_*` counters, `status`, `graduation_threshold`, `graduated_to` FK | `key_concept`, `explanation`, `source_type`, `learned_from_thinking_id` FK back, `invalidation_conditions` |
| Lifecycle | `active` → `graduated` / `rejected` / `stale` | Generally permanent (deactivate via `is_active`) |

**Graduation rules** (post-Stage-6 work, currently MANUAL):
- `observations_supporting >= graduation_threshold` (default 5) AND `observations_contradicting < supporting / 3` → graduate
- `observations_contradicting >= graduation_threshold` → reject
- The auto-graduation logic itself ships in a future stage; today, transitions are manual and the schema supports them

**The bidirectional link:**
- `signal_thinking.graduated_to → signal_knowledge.id` (forward — when a hypothesis becomes proven)
- `signal_knowledge.learned_from_thinking_id → signal_thinking.id` (reverse — to query "knowledge that came from observation" with the original evidence trail)
- `signal_knowledge.source_type` distinguishes `'seed'` / `'manual'` / `'learned_from_thinking'` / `'auto_extracted'`

**Win-rate framing, not loss counting.** Pattern stats track BOTH wins and losses. The graduation/rejection decision uses a rolling-window win rate (last 30 matching trades or last 90 days). A pattern that fails twice then wins three times never becomes a permanent boogeyman — its counters update and the warning fades automatically. The 40-65% win-rate band is the dead zone where we report nothing because there's no edge to teach.

**Never delete.** Rejected and stale entries are kept as historical record. *"How good are my hypotheses?"* is itself a learning question.

## Thesis Tracking (Stage 6)

Every brain entry captures the REASON for owning (not just the score). The thesis tracker re-asks Claude at every scan whether the reason still holds.

```
brain BUY → captures entry_thesis (Claude's reasoning) +
            entry_thesis_keywords (machine-checkable snapshot)
   ↓
every scan → reevaluate_open_theses() in PARALLEL via asyncio.gather
              (semaphore=3, ~10s × 5 positions / 3 = ~17s instead of 50s)
   ↓
Claude returns {status: 'valid'|'weakening'|'invalid', confidence, reason}
   ↓
if status == 'invalid' AND confidence >= 60:
    → close with exit_reason='THESIS_INVALIDATED'
       regardless of P&L direction (the oil-barrel exit:
       sell at +50% when the war ends)
```

**The HUM Day-1 fix.** All 6 existing exit paths (SIGNAL, STOP_HIT, TARGET_HIT, PROFIT_TAKE, TIME_EXPIRED, ROTATION) now read `thesis_last_status` and SUPPRESS themselves when the thesis is still valid (with carve-outs).

**The exit gating matrix** (`virtual_portfolio._exit_is_thesis_protected`):

| Exit type | Gated by thesis check? |
|---|---|
| SIGNAL flip | ✅ Yes — HUM Day-1 fix |
| STOP_HIT | ✅ Yes (UNLESS catastrophic) |
| TARGET_HIT | ✅ Yes (let it run if thesis strong) |
| PROFIT_TAKE | ✅ Yes (let it run) |
| TIME_EXPIRED | ✅ Yes (extend the window) |
| ROTATION | ❌ Never (relative comparison) |
| THESIS_INVALIDATED | ❌ Never (it IS the thesis exit) |
| WATCHDOG_FORCE_SELL | ❌ Never (real-time brake, fresher data than cached thesis) |
| WATCHDOG_EXIT | ❌ Never (same reason) |
| Catastrophic stop (`pnl_pct <= settings.brain_thesis_hard_stop_pct`, default -8%) | ❌ Never (carve-out — never let a wrong AI call blow up the position) |

**Confidence floor on `THESIS_INVALIDATED`:** Claude's `status='invalid'` AND `confidence >= 60` are both required before closing. Without this floor, a parser glitch or hallucinated `should_exit=true` could close arbitrary winning positions.

## Pattern Stats (Stage 4)

When the brain considers a new candidate, `pattern_stats.get_pattern_warning()` looks up the brain's TRACK RECORD on similar setups and surfaces it to Claude in the prompt as additional context.

**Reads BOTH closed and open positions.** Closed-only learning has slow feedback (a bleeding META wouldn't contribute anything until it actually exits) AND survivorship bias (fast-closing trades dominate the data, slow bleeders are rare in `trade_outcomes`). The fix: read both tables and combine the evidence.

```
combined_n = closed_n + open_n
combined_wins = closed_wins + open_winners_now
combined_wr = combined_wins / combined_n

N >= 5 AND wr < 40%  → ⚠ PATTERN WARNING in prompt
N >= 5 AND wr > 65%  → ✓ PATTERN GREEN LIGHT in prompt
40-65%               → silent (dead zone)
```

**Granularity:** intentionally coarse — `(bucket, market_regime)` only, 6 cells total (2 buckets × 3 regimes). Refines later when data justifies it. Don't add `score_band` until any one cell has N > 20 trades.

**Per-scan dedupe cache:** plain dict cleared at the start of every scan by `scan_service.run_scan` calling `pattern_stats.invalidate_cache()`. With 15 candidates per scan and only 6 possible cells, the cache hit rate is high.

## The Audit Log: `knowledge_events`

Append-only. Never UPDATE, never DELETE. Every mutation to `signal_thinking` or `signal_knowledge` — and every observation that updates a hypothesis's evidence counters, every thesis re-evaluation, every thesis-driven exit — appends a row here.

**Event types:**

| Event | When | Triggered by |
|---|---|---|
| `thinking_created` | New hypothesis proposed | journal analysis, user manual, future auto_extractor |
| `thinking_observation_added` | A closed brain trade matched the pattern, counter incremented | `_match_thinking_observations` (called from `_record_brain_outcome`) |
| `thinking_graduated` | Hypothesis became validated knowledge | graduation_logic (post-Stage-6) |
| `thinking_rejected` | Counter-evidence won | graduation_logic |
| `thinking_stale` | Aged out (no observations for X days) | graduation_logic |
| `thinking_edited` | Hypothesis text changed | brain editor, user manual |
| `knowledge_created` | New `signal_knowledge` row inserted | seed scripts, brain editor, graduation |
| `knowledge_edited` | Existing knowledge row updated | brain editor |
| `knowledge_deactivated` | `is_active` flipped to false | brain editor |
| `thesis_evaluated` | Claude re-evaluated an open position's thesis | `thesis_tracker.reevaluate_open_theses` |
| `thesis_invalidated_exit` | Position closed via THESIS_INVALIDATED | `thesis_tracker.execute_thesis_invalidation_exits` |

**FKs:** `thinking_id`, `knowledge_id`, `trade_id` are all nullable — which one is set depends on the event type.

**Queries this enables:**
```sql
-- Full history of one hypothesis
SELECT * FROM knowledge_events WHERE thinking_id = X ORDER BY created_at;

-- Show me the trades that graduated this hypothesis
SELECT trade_id, payload FROM knowledge_events
WHERE thinking_id = X AND event_type = 'thinking_observation_added'
  AND observation_outcome = 'supporting' ORDER BY created_at;

-- Why did the brain start avoiding META-class signals last Tuesday?
SELECT * FROM knowledge_events
WHERE knowledge_id = (SELECT id FROM signal_knowledge WHERE key_concept = 'X')
ORDER BY created_at;
```

## The Worked Example: META Day 3

What WOULD have been different on 2026-04-08 if all 7 stages had been live:

1. **Stage 1 (working hypothesis):** The PYPL Day 2 lesson was promoted to `signal_thinking` with `pattern_match = {bucket: SAFE_INCOME, regime: VOLATILE, score_min: 72, score_max: 79, macd_histogram_lt: 0}` and 1 supporting observation (PYPL itself). Claude's prompt for META would have shown a `## Working Hypotheses` section with this pattern listed at LOW confidence.
2. **Stage 2 (warning signs):** META's `macd_histogram=-19.66` would have fired the new `macd_strongly_negative` rule, surfacing as `⚠ MACD histogram is -19.66 (strongly negative, scaled to price) — momentum has reversed` in the prompt RIGHT BEFORE the "Your Task" question. Claude couldn't have plausibly missed it.
3. **Stage 4 (pattern stats):** No closed history yet (Day 2 only had PYPL closed) but the `## Pattern Stats` section would have surfaced *"1 closed @ 0/1 winners"* — below the N=5 threshold so silent. After Day 3, with PYPL closed AND 4 open SAFE_INCOME/VOLATILE positions in the red, the threshold would trip on Day 4.
4. **Stage 6 (thesis re-eval):** The brain captures META's entry thesis at insert. Within 1 hour the next scan re-evaluates: Claude reads the prompt with the warning sign + the working hypothesis + (eventually) pattern stats, and might return `status='weakening'`. If META's MACD continues collapsing, status flips to `'invalid'` with confidence ≥ 60 and the position closes via THESIS_INVALIDATED — instead of waiting for the watchdog slow-bleed at -3%.

The brain would still have made the SAME initial pick. But it would have either NOT bought it (Claude weighs the warning + hypothesis + history and downgrades to HOLD), or it would have exited within 1-2 scans instead of bleeding for hours.

## Critical Files

- **Schema:** `back-end/app/db/schema.sql` (sections 14, 14b, 14c — signal_knowledge, signal_thinking, knowledge_events)
- **Hypothesis loading into prompt:** `back-end/app/services/knowledge_service.py:get_active_thinking_block`
- **Pattern matching + classification:** `back-end/app/services/virtual_portfolio.py` (`_trade_matches_pattern`, `_classify_observation`, `_match_thinking_observations`, `_record_brain_outcome`)
- **Thesis re-eval orchestration:** `back-end/app/services/thesis_tracker.py` (`reevaluate_open_theses`, `execute_thesis_invalidation_exits`)
- **Thesis re-eval AI call:** `back-end/app/ai/provider.py:re_evaluate_thesis` + prompt at `back-end/app/ai/prompts.py:THESIS_REEVAL_PROMPT`
- **Pattern stats query:** `back-end/app/services/pattern_stats.py:get_pattern_warning`
- **Warning signs builder:** `back-end/app/ai/danger_signals.py:format_warning_signs` (reuses `signal_breakdown.RULES`)
- **Audit log helper:** `back-end/app/services/knowledge_events.py:log_event`
- **Exit gate:** `back-end/app/services/virtual_portfolio.py:_exit_is_thesis_protected`
- **Config flags:** `back-end/app/core/config.py:brain_thesis_gate_enabled` (default True), `brain_thesis_hard_stop_pct` (default -8.0)

## Implementation Plan (full detail)

`back-end/docs/learning-loop-implementation-plan.md` — the 7-stage build plan with rationale for every decision.
