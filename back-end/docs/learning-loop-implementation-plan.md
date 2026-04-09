# Self-Learning Knowledge Loop — Implementation Plan

## Context

**Why we're building this:** On 2026-04-08 the brain auto-bought META at score 78 (validated by Claude) and it bled -2.41% within 3 hours. The previous day (Day 2), PYPL — same pattern (SAFE_INCOME, VOLATILE regime, marginal score 72-78, negative MACD histogram) — also closed at -3.0%. Same failure twice in a row. **The lesson from PYPL was written into the journal but never reached Claude's prompt for the META decision.** Each day the brain starts blind to its own recent losses.

**The principle (saved as `feedback_three_witness_consensus.md`):** AI is the *decider*, not one witness among three. Math (formulas) and Knowledge (rules, lessons) exist to *serve the AI* by making the dossier complete and honest. We don't override Claude with parallel voting — we make sure Claude sees what it needs to make the right call.

**Intended outcome:** Closed-loop learning. When a brain trade closes, the outcome gets recorded; recurring failure (or success) patterns get surfaced to Claude in the next scan's prompt as *context*, not as a veto. Plus: technical danger signs that Claude is currently glossing over (negative MACD histogram, extreme SMA200 distance) get pulled out of the JSON dump and named explicitly in the prompt.

**Out of scope (explicitly NOT building):**
- The 3-witness parallel-voting "consensus engine" I originally proposed. The user corrected this — AI stays the decider.
- Hard math vetoes that override AI BUYs. We're feeding the AI better, not second-guessing it.
- Replacing `_eval_brain_trust_tier` (`virtual_portfolio.py:884`). The tier gate stays as-is.
- A new database table for pattern stats. We use existing `trade_outcomes` + `signal_knowledge`.
- A frontend UI for promoting lessons. Stage 1 ships as a single hand-written DB row tonight.

## Architecture — 4 Stages, Build in Order

```
                                ┌─────────────────────┐
                                │  CLAUDE SYNTHESIS   │ <— the decider (unchanged)
                                │  (validates BUY)    │
                                └─────────▲───────────┘
                                          │
              ┌───────────────────────────┴───────────────────────────┐
              │                                                       │
      ┌───────┴────────┐                                    ┌─────────┴────────┐
      │ DOSSIER (in)   │                                    │  GATE (after)    │
      │ - technicals   │                                    │  _eval_brain_    │
      │ - fundamentals │                                    │  trust_tier      │
      │ - sentiment    │                                    │  (unchanged)     │
      │ - macro        │                                    └──────────────────┘
      │ - knowledge ◄──┼─── Stage 1 (NEW): pattern_stats inline warning
      │ - DANGER SIGS◄─┼─── Stage 2 (NEW): salience pass on technicals
      └────────────────┘
                                          ▲
                                          │
                                ┌─────────┴───────────┐
                                │  trade_outcomes     │ <— Stage 3 (NEW): wired
                                │  (existing table)   │     from virtual_portfolio
                                └─────────▲───────────┘     + watchdog close hooks
                                          │
                                ┌─────────┴───────────┐
                                │  brain trade close  │
                                │  (6 hooks in vp.py  │
                                │   + 1 in watchdog)  │
                                └─────────────────────┘
```

The four stages, in build order:

| # | Stage | Effort | What it does |
|---|---|---|---|
| 1 | Manual entry tonight | 15 min | Hand-write the PYPL→META **hypothesis** into a new `signal_thinking` table (NOT `signal_knowledge` — it's N=2, not validated yet). Add the table schema. The new entry is loaded into Claude's prompt as a "Working Hypothesis", not as proven knowledge. Buys time to build the rest. |
| 2 | Prompt salience pass | 1-2 hrs | Add 3-4 new `signal_breakdown.py` rules + a backend `KEY_TO_PROMPT_TEXT` map + a `## Warning Signs` section in `CLAUDE_SYNTHESIS_PROMPT` (placed just before "Your Task"). Claude sees META's negative MACD as a flagged warning, not as one number in a blob. |
| 3 | Wire close hooks → `trade_outcomes` | 1 hr | The brain has been losing trades for 3 days and **none** of it has reached `trade_outcomes` because virtual_portfolio never calls `learning_service.record_outcome()`. Wire it. Snapshot `market_regime` on virtual_trades at insert so we have it at close. |
| 4 | Inline pattern stats query | 2 hrs | New `app/services/pattern_stats.py::get_pattern_warning(signal)` queries BOTH `trade_outcomes` (closed history) AND open `virtual_trades` (in-flight evidence) filtered by (bucket, regime). If N≥5 combined and win rate <40% or >65%, returns a warning/green-light string injected into the prompt. Starts coarse (6 cells: 2 buckets × 3 regimes), refines later. |
| 5 | thinking + knowledge schemas | 30 min | Create `signal_thinking` table. Add `invalidation_conditions` JSONB to both tables. NO automatic graduation logic yet — manual transitions only until data justifies the auto loop. |
| 6 | Thesis tracking + invalidation exits | 3-4 hrs | Capture every entry's thesis. Re-evaluate every open position's thesis at every scan via Claude. New exit reason `THESIS_INVALIDATED` for "the reason for owning is gone, sell regardless of P&L." Existing exits gated by thesis check (carve-out: catastrophic stops at -8% bypass). The HUM-Day-1 fix. |
| 7 | Lock the architecture into docs/memory/skills | 1 hr | After Stages 1-6 ship and verify, persist the principles so they survive context resets. New memory entries for the 4 architectural principles. New `/brain-learning` skill explaining the thinking/knowledge/thesis system. Updates to `/scan-pipeline`, `/database`. Update the frontend "How It Works" page. **Skills > CLAUDE.md** — bias new content toward skills, only touch CLAUDE.md for the minimum delta. |

## Critical Files (read these before editing)

| File | Why | Touched in Stage |
|---|---|---|
| `back-end/app/services/signal_breakdown.py` | Existing rules engine. Returns i18n keys + label_value dicts. RULES list at lines 130-279. New rules added here. | 2 |
| `back-end/app/ai/prompts.py` | `CLAUDE_SYNTHESIS_PROMPT` template (lines 33-95) and `format_technicals` (98-120). New `format_warning_signs()` helper added here. New `## Warning Signs` section added to template. | 2 |
| `back-end/app/ai/claude_client.py:130-140` | Synthesis call site — formats prompt with `format_technicals(...)` etc. New `format_warning_signs(...)` injection here. Also `gemini_client.py:132`, `claude_local_client.py:123`. | 2 |
| `back-end/app/services/learning_service.py:20-75` | **`record_outcome()` already exists.** Takes signal_id, symbol, action, score, bucket, signal_date, entry/exit price, days_held, target, stop, market_regime, catalyst_type, notes. Just needs to be called. | 3 |
| `back-end/app/services/virtual_portfolio.py` | The 6 close hooks where trades transition to CLOSED: lines 802 (SIGNAL), 940 (ROTATION), 1189 (STOP_HIT), 1192 (TARGET_HIT), 1196 (PROFIT_TAKE), 1207 (TIME_EXPIRED). Brain insert at 981-996 — add `market_regime` snapshot. | 3 |
| `back-end/app/services/watchdog_service.py:486-495` | 7th close hook. Same wiring. | 3 |
| `back-end/app/services/knowledge_service.py:126-151` | `get_knowledge_block()` already loads markdown from `signal_knowledge` with a 5-min TTLCache. Stage 4 leaves it untouched (pattern stats inject separately). | 4 (read only) |
| `back-end/app/services/scan_service.py:309-325` | Hardcoded list of `key_concept` names loaded per scan. **Stage 1 adds the new key here.** Stage 4 injects pattern stats per ticker around line 806 where `_knowledge_block` is set on `grok_data`. | 1, 4 |
| `back-end/app/db/schema.sql:256-271` (`signal_knowledge`), `:231-253` (`investment_rules`) | Read-only — confirm column names before Stage 1's hand-written entry. | 1 |

## Stage 1 — Manual Entry as a Hypothesis (tonight, 15 minutes)

**Goal:** Get the PYPL→META lesson into Claude's prompt for tomorrow's first scan — but as a *hypothesis under observation*, not as proven knowledge. N=2 is not knowledge.

### 1a. Create `signal_thinking` table (Stage 5 schema, brought forward to unblock Stage 1)

```sql
CREATE TABLE IF NOT EXISTS signal_thinking (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  hypothesis TEXT NOT NULL,
  prediction TEXT NOT NULL,
  pattern_match JSONB NOT NULL,
  invalidation_conditions JSONB,
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  observations_supporting INT DEFAULT 0,
  observations_contradicting INT DEFAULT 0,
  observations_neutral INT DEFAULT 0,
  status TEXT DEFAULT 'active',  -- 'active' | 'graduated' | 'rejected' | 'stale'
  graduation_threshold INT DEFAULT 5,
  graduated_to UUID REFERENCES signal_knowledge(id),
  last_evaluated_at TIMESTAMPTZ,
  notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_signal_thinking_status ON signal_thinking(status);
```

### 1b. Insert the PYPL→META hypothesis as ONE row

```python
{
  "hypothesis": "SAFE_INCOME picks scoring 72-79 in VOLATILE regimes with negative MACD histogram bleed within 3 days, regardless of how strong other indicators look.",
  "prediction": "Such trades will print negative P&L within 3 days of entry, with avg loss ~-2.5% to -3.0%",
  "pattern_match": {
    "bucket": "SAFE_INCOME",
    "regime": "VOLATILE",
    "score_min": 72,
    "score_max": 79,
    "macd_histogram_lt": 0
  },
  "invalidation_conditions": {
    "regime_changes_to": ["TRENDING"],
    "OR_macd_histogram_gt": 0,
    "OR_vix_drops_below": 20
  },
  "created_by": "journal_day3_analysis",
  "observations_supporting": 2,  # PYPL + META
  "observations_contradicting": 0,
  "status": "active",
  "notes": "Promoted from learning-journal Day 3. Examples: PYPL Apr 7 entry at score 73 → exited -3.0% via watchdog. META Apr 8 entry at score 78 with macd_hist=-19.66 → currently -2.4%, watchdog firing."
}
```

### 1c. Modify `knowledge_service.get_knowledge_block()` to ALSO load active thinking entries

The existing function currently loads from `signal_knowledge`. Add a parallel section that loads from `signal_thinking WHERE status='active'` and renders them under a separate header:

```markdown
## Working Hypotheses (under observation — low confidence)
### {hypothesis}
**Prediction:** {prediction}
**Currently observed:** {observations_supporting} supporting, {observations_contradicting} contradicting
**This is a hypothesis under test — weigh accordingly.**
```

This makes the confidence level explicit in the prompt. Claude reads "low confidence" and treats it as data to consider, not gospel.

### 1d. Verify

Run the next scan and check the AI debug log. The `## Working Hypotheses` section should appear, listing the PYPL→META entry with the supporting/contradicting counts. The existing `## Investment Knowledge` section should still contain the 10 hardcoded validated concepts.

**Why this is Stage 1:** Highest leverage, lowest risk. Ships in ~15 minutes. Honest framing — no lying about confidence. Buys days of breathing room while Stages 2-6 are built.

## Stage 2 — Prompt Salience Pass (1-2 hours)

**Goal:** Make sure technical danger signs are *named* in Claude's prompt with prominence, not buried in a JSON-style line.

### 2a. Add new rules to `signal_breakdown.py`

Append to `RULES` list (after line 152, before volume rules):

```python
_rule(
    "macd_strongly_negative", TONE_NEGATIVE,
    fires=lambda s, t, f, o: (
        _safe_float(t.get("macd_histogram")) is not None
        and (_safe_float(t.get("macd_histogram")) or 0) < -5
        and (_safe_float(t.get("current_price")) or 0) > 50
    ),
    label_value=lambda s, t, f, o: {
        "hist": round(_safe_float(t.get("macd_histogram")) or 0, 2),
    },
),
_rule(
    "vs_sma200_extended", TONE_NEGATIVE,
    fires=lambda s, t, f, o: abs(_safe_float(t.get("vs_sma200")) or 0) > 25,
    label_value=lambda s, t, f, o: {"pct": round(_safe_float(t.get("vs_sma200")) or 0, 1)},
),
_rule(
    "momentum_collapse", TONE_NEGATIVE,
    fires=lambda s, t, f, o: (
        (_safe_float(t.get("vs_sma200")) or 0) < 0
        and (_safe_float(t.get("macd_histogram")) or 0) < 0
        and (_safe_float(t.get("momentum_5d")) or 0) < -2
    ),
),
```

The thresholds (`-5` for macd_hist, `25%` for sma200, `-2%` for momentum_5d) are tuned for liquid mid/large caps. They WILL fire on META's data (`macd_hist=-19.66`, `vs_sma200=-8`, falling momentum). Verify against the Day 3 META row in `signals` table before merging.

### 2b. Build the backend prompt template map

New file: `back-end/app/ai/danger_signals.py`

```python
"""Plain-English templates for signal_breakdown rules → Claude prompt.

Source of truth for English-language warning text. Lives separately from the
frontend i18n store (which has EN+PT for the UI). When a new TONE_NEGATIVE
rule is added to signal_breakdown.RULES, add a matching entry here.
"""

KEY_TO_PROMPT_TEXT: dict[str, str] = {
    "macd_strongly_negative":
        "⚠ MACD histogram is {hist} (strongly negative — momentum has reversed; price is decelerating into a downtrend)",
    "vs_sma200_extended":
        "⚠ Price is {pct}% from the 200-day SMA (extreme distance — mean reversion risk is high)",
    "momentum_collapse":
        "⚠ Momentum collapse: price is below SMA200, MACD histogram negative, AND 5-day momentum negative (multi-timeframe weakness)",
    "macd_bearish_divergence":
        "⚠ MACD bearish divergence (price up, MACD down — common precursor to a top)",
    "death_cross":
        "⚠ Death cross detected (50-day SMA crossed below 200-day SMA — bearish trend confirmation)",
    "volume_dry":
        "⚠ Volume drying up (z-score {z} — low participation; rallies on thin volume rarely sustain)",
    "pe_rich":
        "⚠ Stretched valuation (P/E {pe} — limited margin of safety)",
    "eps_growth_negative":
        "⚠ EPS growth is negative (earnings deteriorating)",
    "high_debt":
        "⚠ High leverage (debt/equity {de} — sensitive to rate or earnings shocks)",
    "rr_weak":
        "⚠ Weak risk/reward ({rr}:1 — even if right, the upside doesn't justify the risk)",
    "regime_crisis":
        "⚠ Market is in CRISIS regime — only the highest-conviction defensive plays should be considered",
    "iv_complacency":
        "⚠ Options IV at {pct}th percentile (extreme complacency — historically precedes vol expansion)",
}


def format_warning_signs(signal: dict) -> str:
    """Build the '## Warning Signs' section of the synthesis prompt.

    Filters the signal_breakdown rule output to TONE_NEGATIVE rules only,
    looks up each key's English template, and interpolates the label_value
    dict. Returns an empty string if nothing fires (which is the right
    no-op — a clean signal has no warnings to flag).
    """
    from app.services.signal_breakdown import compute_signal_breakdown

    rows = compute_signal_breakdown(signal)
    lines = []
    for row in rows:
        if row.get("tone") != "negative":
            continue
        template = KEY_TO_PROMPT_TEXT.get(row["key"])
        if not template:
            continue
        try:
            text = template.format(**(row.get("label_value") or {}))
            lines.append(f"- {text}")
        except Exception:
            lines.append(f"- {template}")
    return "\n".join(lines) if lines else ""
```

### 2c. Add the section to the prompt template

In `app/ai/prompts.py`, modify `CLAUDE_SYNTHESIS_PROMPT` to add a new section **just before "## Your Task"** (recency bias: the closer to the decision question, the more weight Claude gives it):

```
## Investment Knowledge (from Signa Brain)
{knowledge_block}

## Warning Signs (from technical/fundamental analysis)
{warning_signs}

## Your Task
...
```

When `warning_signs` is empty string, the section header will look bare. Either:
- Conditionally include the section (template-level), OR
- Always include with text "None detected." when empty

Prefer the conditional approach: build the prompt as a list of sections in `claude_client.py:130-140` and skip empty ones, OR keep the template static and pass `"None detected."` when empty.

### 2d. Wire through the AI clients

`claude_client.py:130-140`, `gemini_client.py:132`, `claude_local_client.py:123` — all three call `CLAUDE_SYNTHESIS_PROMPT.format(...)`. Each needs to pass `warning_signs=format_warning_signs(signal_dict)` where `signal_dict` is reconstructed from the function's args (technical_data, fundamental_data, grok_data, etc.) — wrapped into a `{"technical_data": tech, "fundamental_data": fund, "grok_data": grok, "market_regime": ...}` dict that `compute_signal_breakdown` expects.

The signal dict shape that `compute_signal_breakdown` expects (from `signal_breakdown.py:299-302`):
```python
{
    "technical_data": {...},
    "fundamental_data": {...},
    "grok_data": {"_options_flow": {...}, ...},
    "market_regime": "VOLATILE",
    "risk_reward": ...,
}
```

## Stage 3 — Wire Brain Trade Closes into `trade_outcomes` (1 hour)

**Goal:** Stop losing closed-trade history. Every brain close must reach `trade_outcomes` so Stage 4's *historical* half has ground truth to query.

**Important framing:** Stage 3 alone does NOT close the learning loop — it only feeds the historical half. The live half (currently-open positions) is read directly from `virtual_trades` by Stage 4 and does not need a separate recorder. Together they cover both ends.

### 3a. Snapshot `market_regime` on virtual_trades at insert

Add a column:
```sql
ALTER TABLE virtual_trades ADD COLUMN IF NOT EXISTS market_regime TEXT;
```

In `virtual_portfolio.py` at the brain track insert (lines 981-996), add:
```python
"market_regime": (sig.get("macro_data") or {}).get("regime") or sig.get("market_regime"),
```

Also for the watchlist track insert at lines 857-870 — same field, same source.

### 3b. Single helper that records on every close

New helper in `virtual_portfolio.py` (top of the close-handling section):

```python
def _record_brain_outcome(closed_row: dict, exit_price: float, exit_action: str | None) -> None:
    """Forward a closed virtual trade to learning_service.record_outcome().

    Called from EVERY close path: SIGNAL, ROTATION, STOP_HIT, TARGET_HIT,
    PROFIT_TAKE, TIME_EXPIRED, watchdog. Failures are logged but never
    propagated — recording outcomes must NEVER block a real exit.
    """
    if closed_row.get("source") != "brain":
        return  # Only learn from brain track for now (watchlist is exploratory)
    try:
        from app.services import learning_service
        from datetime import datetime
        entry_dt = datetime.fromisoformat((closed_row["entry_date"] or "").replace("Z", "+00:00"))
        exit_dt = datetime.now(timezone.utc)
        days_held = max(0, (exit_dt - entry_dt).days)
        learning_service.record_outcome(
            signal_id=closed_row.get("signal_id") or "virtual",
            symbol=closed_row["symbol"],
            action="BUY",  # all brain entries are BUYs
            score=int(closed_row.get("entry_score") or 0),
            bucket=closed_row.get("bucket") or "UNKNOWN",
            signal_date=closed_row["entry_date"],
            entry_price=float(closed_row["entry_price"]),
            exit_price=float(exit_price),
            days_held=days_held,
            target_price=closed_row.get("target_price"),
            stop_loss=closed_row.get("stop_loss"),
            market_regime=closed_row.get("market_regime"),
            catalyst_type=None,  # not snapshotted yet, deferred
            notes=closed_row.get("exit_reason"),
        )
    except Exception as e:
        logger.warning(f"Failed to record brain outcome for {closed_row.get('symbol')}: {e}")
```

### 3c. Call the helper at every close path

All 7 sites pass the freshly-fetched row (the dict that was just UPDATEd to status=CLOSED) and the exit price/action:

| File:Line | Path | Hook |
|---|---|---|
| `virtual_portfolio.py:802` | SIGNAL exit | After the `update().execute()` succeeds, call `_record_brain_outcome(pos, price, action)` |
| `virtual_portfolio.py:940` | ROTATION exit | Same — pass the closed-out weakest row |
| `virtual_portfolio.py:1189` | STOP_HIT (in `check_virtual_exits`) | Same |
| `virtual_portfolio.py:1192` | TARGET_HIT | Same |
| `virtual_portfolio.py:1196` | PROFIT_TAKE | Same |
| `virtual_portfolio.py:1207` | TIME_EXPIRED | Same |
| `watchdog_service.py:486` | Watchdog slow-bleed exit (`_close_virtual_trade`) | Inside `_close_virtual_trade`, after the update succeeds |

### 3d. Backfill is OPTIONAL

The 5 currently-open positions have no historical close data, so backfill is moot — they'll be recorded when they actually close. We don't have prior closed trades in the DB (the wipe between Day 2 and Day 3 took them). Skip backfill.

## Stage 4 — Inline Pattern Stats Query (2 hours)

**Goal:** When the brain considers a new candidate, query BOTH closed history AND live open positions for matching brain trades, combine the evidence, and inject a warning/green-light line into the prompt's knowledge_block.

**Why both tables (and not just `trade_outcomes`):** A trade is data the moment it's open, not the moment it closes. If we only learn from closes, we delay feedback by days or weeks (META as of Day 3 wouldn't contribute *anything* until it eventually exits) AND we bias the data toward fast-closing trades (stop hits, target hits) at the expense of slow bleeders (which are usually the lessons we need most). Open positions are in-flight evidence — lower weight than closes, but real. The brain reads both.

### 4a. New file `app/services/pattern_stats.py`

```python
"""Compute pattern stats from BOTH closed history AND live open positions.

A "pattern" is initially just (bucket, market_regime) — 6 cells total
(SAFE_INCOME/HIGH_RISK × TRENDING/VOLATILE/CRISIS). Granularity is intentionally
coarse: it has to follow data density. Once any cell hits >20 trades, finer
dimensions (score band, MACD direction) can be layered in.

EVIDENCE COMBINATION:
  - Closed trades from `trade_outcomes` (rolling 90 days, max 30) — ground truth
  - Open brain trades from `virtual_trades` (status='OPEN', source='brain')
    that match the same (bucket, regime) — in-flight evidence, live P&L
  - The two are combined into a single sample. Open positions count toward N
    and toward win count when they're currently in the green.

Rationale for including open: a position is data the moment it's open, not the
moment it closes. Closed-only learning has slow feedback AND survivorship bias
toward fast-closing trades. The bleeders we hold patiently are the most valuable
data, and they're the slowest to arrive at "closed."

Surface thresholds: N>=5 combined sample, WR<40% (warning) or WR>65% (green).
"""

from datetime import datetime, timedelta, timezone
from app.db.supabase import get_client
from app.services.price_cache import _fetch_prices_batch


def get_pattern_warning(signal: dict) -> str | None:
    """Return a one-paragraph pattern stat string, or None if no warning/light.

    Called per-ticker from scan_service._process_candidate. Output is appended
    to the knowledge_block markdown that goes into Claude's prompt.
    """
    bucket = signal.get("bucket")
    regime = (signal.get("macro_data") or {}).get("regime") or signal.get("market_regime")
    if not bucket or not regime:
        return None

    db = get_client()

    # ── Closed history ──
    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    closed_rows = (
        db.table("trade_outcomes")
        .select("pnl_pct, signal_date, symbol")
        .eq("bucket", bucket)
        .eq("market_regime", regime)
        .gte("signal_date", cutoff)
        .order("signal_date", desc=True)
        .limit(30)
        .execute()
    ).data or []

    closed_n = len(closed_rows)
    closed_wins = sum(1 for r in closed_rows if (r.get("pnl_pct") or 0) > 0)
    closed_avg = (sum((r.get("pnl_pct") or 0) for r in closed_rows) / closed_n) if closed_n else 0.0

    # ── Live open positions matching this pattern ──
    open_rows = (
        db.table("virtual_trades")
        .select("symbol, entry_price, bucket, market_regime")
        .eq("status", "OPEN")
        .eq("source", "brain")
        .eq("bucket", bucket)
        .eq("market_regime", regime)
        .execute()
    ).data or []

    open_n = len(open_rows)
    open_winners = 0
    open_avg = 0.0
    if open_n:
        symbols = [r["symbol"] for r in open_rows]
        prices = _fetch_prices_batch(symbols)  # existing helper, batched
        live_pnls = []
        for r in open_rows:
            sym = r["symbol"]
            entry = float(r.get("entry_price") or 0)
            now_px, _ = prices.get(sym, (None, None))
            if not now_px or not entry:
                continue
            live_pnl = (now_px - entry) / entry * 100
            live_pnls.append(live_pnl)
            if live_pnl > 0:
                open_winners += 1
        if live_pnls:
            open_avg = sum(live_pnls) / len(live_pnls)
        # If we couldn't price any open positions, treat as no open evidence
        # (don't double-penalize a price feed outage)
        if not live_pnls:
            open_n = 0

    # ── Combined ──
    combined_n = closed_n + open_n
    if combined_n < 5:
        return None
    combined_wins = closed_wins + open_winners
    combined_wr = combined_wins / combined_n

    # Sample symbols for context (up to 6, prefer recent closed + currently open)
    sample = []
    sample.extend(r["symbol"] for r in open_rows[:3])
    sample.extend(r["symbol"] for r in closed_rows[:3])
    sample_symbols = ", ".join(sorted(set(sample)))

    breakdown = (
        f"({closed_n} closed @ {closed_wins}/{closed_n} winners, avg {closed_avg:+.1f}%; "
        f"{open_n} currently open @ {open_winners}/{open_n} in green, avg {open_avg:+.1f}%)"
    )

    if combined_wr < 0.40:
        return (
            f"⚠ PATTERN WARNING: This setup ({bucket} in {regime} regime) has "
            f"a {combined_wr:.0%} positive rate across {combined_n} brain trades "
            f"{breakdown}. Recent examples: {sample_symbols}. Be skeptical — "
            f"require a fresh catalyst or stronger conviction than the score "
            f"alone suggests. Open positions in this pattern are bleeding."
        )
    if combined_wr > 0.65:
        return (
            f"✓ PATTERN GREEN LIGHT: This setup ({bucket} in {regime} regime) has "
            f"a {combined_wr:.0%} positive rate across {combined_n} brain trades "
            f"{breakdown}. Historically favorable — the score is more reliable here."
        )
    return None
```

**Note on the open-positions contribution:** an open position currently up +0.1% counts as a "winner" with the same weight as a closed +20% winner. This is intentional for v1 — we're after a *signal*, not a precise win-rate measurement. If it turns out to be too noisy, the next refinement is to require a magnitude threshold (e.g., a position only counts as a soft win if it's up >+1%, soft loss if it's down >-1%, abstain if in the noise band). Defer until we see how it behaves in practice.

### 4b. Inject at the per-ticker scan_service site

In `scan_service.py` near line 806 where `grok_data["_knowledge_block"] = knowledge_block` is set, append the per-ticker pattern warning:

```python
if isinstance(grok_data, dict):
    grok_data["_market_regime"] = market_regime
    # ... existing lines ...
    if knowledge_block:
        grok_data["_knowledge_block"] = knowledge_block
        # NEW: append per-ticker pattern stats if any
        from app.services.pattern_stats import get_pattern_warning
        sig_for_stats = {
            "bucket": bucket,
            "market_regime": market_regime,
            "macro_data": macro_data,
        }
        pat = get_pattern_warning(sig_for_stats)
        if pat:
            grok_data["_knowledge_block"] = (
                grok_data["_knowledge_block"] + "\n\n## Pattern Stats (your own track record)\n" + pat
            )
```

This means the static knowledge_block (Stage 1's hand-written entry + the existing 10 hardcoded entries) is loaded once per scan, but the per-ticker pattern stat gets appended after — keeping the per-ticker work to one small DB query and one string concat.

## Stage 6 — Thesis Tracking + Invalidation Exits (3-4 hours)

**Goal:** Capture the *reason* for every brain entry, re-evaluate that reason at every scan, and exit positions whose reason has died — regardless of P&L direction. A winning position with a dead thesis should be sold; a losing position with an intact thesis should be held.

**The principle (saved as a memory after exit):** Knowledge is conditional, not absolute. Every pattern needs (a) entry conditions, (b) prediction, (c) invalidation conditions. The most important exit is `THESIS_INVALIDATED` — when the reason for entry no longer holds, exit regardless of P&L. The oil-barrel example: buy at $100 on a war thesis, hold through $120 and $150 as the thesis plays out, then SELL at $150 when peace is announced (thesis dead), even though the position is up +50%.

### 6a. Schema migrations

```sql
-- Capture the thesis at entry time
ALTER TABLE virtual_trades ADD COLUMN IF NOT EXISTS entry_thesis TEXT;
ALTER TABLE virtual_trades ADD COLUMN IF NOT EXISTS entry_thesis_keywords JSONB;
ALTER TABLE virtual_trades ADD COLUMN IF NOT EXISTS thesis_last_checked_at TIMESTAMPTZ;
ALTER TABLE virtual_trades ADD COLUMN IF NOT EXISTS thesis_last_status TEXT;  -- 'valid' | 'weakening' | 'invalid'
ALTER TABLE virtual_trades ADD COLUMN IF NOT EXISTS thesis_last_reason TEXT;

-- Knowledge entries describe state transitions, not static rules
ALTER TABLE signal_knowledge ADD COLUMN IF NOT EXISTS invalidation_conditions JSONB;
-- And the new signal_thinking table from Stage 5 also gets it (set in its CREATE statement)
```

### 6b. Capture the thesis at insert time

In `virtual_portfolio.py` at the brain track insert (lines 981-996), add:

```python
"entry_thesis": (sig.get("reasoning") or "")[:500],  # Claude's reasoning field
"entry_thesis_keywords": _extract_thesis_keywords(sig),  # see below
```

`_extract_thesis_keywords(sig)` is a small helper that pulls structured signal attributes that any future re-evaluation needs to compare against:

```python
def _extract_thesis_keywords(sig: dict) -> dict:
    """Snapshot the structured conditions that justified this entry.

    These are the *machine-checkable* parts of the thesis. Claude's
    free-text reasoning is captured separately in entry_thesis. The
    re-evaluation prompt uses both: the keywords for fast diff, and the
    prose for nuance.
    """
    td = sig.get("technical_data") or {}
    md = sig.get("macro_data") or {}
    gd = sig.get("grok_data") or {}
    return {
        "regime": md.get("regime") or sig.get("market_regime"),
        "score_at_entry": sig.get("score"),
        "macd_histogram": td.get("macd_histogram"),
        "rsi": td.get("rsi"),
        "vs_sma200": td.get("vs_sma200"),
        "sentiment_score": gd.get("score"),
        "sentiment_label": gd.get("label"),
        "catalyst": sig.get("catalyst"),
        "catalyst_type": sig.get("catalyst_type"),
        "fear_greed": md.get("fear_greed"),
    }
```

### 6c. New AI prompt for thesis re-evaluation

New constant in `app/ai/prompts.py`:

```python
THESIS_REEVAL_PROMPT = """You are an AI investment analyst re-evaluating an OPEN brain position.

The brain bought {symbol} on {entry_date} ({days_held} days ago) at ${entry_price}.
Current price: ${current_price} (P&L: {pnl_pct:+.2f}%).

## Original Entry Thesis (verbatim from when we bought)
{entry_thesis}

## Conditions at Entry
{entry_conditions}

## Current Conditions
{current_conditions}

## Your Task
Determine whether the original thesis is still valid TODAY.

Return JSON:
{{
  "status": "valid" | "weakening" | "invalid",
  "confidence": <0-100>,
  "reason": "<one paragraph: what changed (or didn't), and why>",
  "should_exit": <true if status is "invalid", else false>,
  "current_thesis": "<if still valid: the updated thesis given today's data; if invalid: null>"
}}

## Rules
- "valid": the conditions and reasoning that justified entry are still in place
- "weakening": some conditions have degraded but the core reason still holds (HOLD, monitor closely)
- "invalid": the reason for owning is gone — even if the position is currently winning, the EDGE is gone
- A winning position with a dead thesis should be EXITED. We sold not because we're losing but because we no longer have a reason to be long.
- A losing position with an intact thesis should be HELD. The drawdown is noise.
- Be especially alert to:
  • Catalysts that have already played out (earnings beat, FDA approval, deal closed)
  • Macro shifts that change the regime (war ends, Fed pivots, recession averted)
  • Sentiment flips (bullish → bearish without our position recovering)
  • The thesis itself becoming the consensus (everyone's already long, no incremental buyers)

Return JSON only."""
```

### 6d. New module `app/services/thesis_tracker.py`

```python
"""Thesis re-evaluation: re-check the reason for every open brain position.

Runs once per scan, AFTER process_virtual_trades and BEFORE check_virtual_exits.
The result is cached on the position row (thesis_last_status, thesis_last_reason)
and read by the existing exit paths to gate their own decisions.
"""

from datetime import datetime, timezone
from loguru import logger
from app.db.supabase import get_client
from app.ai.provider import re_evaluate_thesis  # new function in provider.py
from app.services.price_cache import _fetch_prices_batch


async def reevaluate_open_theses(signals: list[dict]) -> dict[str, dict]:
    """Re-evaluate every open brain position's thesis. Returns {symbol: ThesisResult}.

    The signals list (from the current scan) is used to look up CURRENT conditions
    for each open position. If a position's symbol isn't in this scan's signals,
    we skip the re-eval (no fresh data) and the cached status from the last scan
    remains in effect.
    """
    db = get_client()
    open_positions = (
        db.table("virtual_trades")
        .select("id, symbol, entry_price, entry_date, entry_score, "
                "entry_thesis, entry_thesis_keywords, market_regime, bucket")
        .eq("status", "OPEN")
        .eq("source", "brain")
        .execute()
    ).data or []
    if not open_positions:
        return {}

    # Index fresh signals by symbol for O(1) lookup
    sig_by_sym = {s.get("symbol"): s for s in signals}

    # Batch live prices
    symbols = [p["symbol"] for p in open_positions]
    prices = _fetch_prices_batch(symbols)

    results: dict[str, dict] = {}
    for pos in open_positions:
        sym = pos["symbol"]
        fresh = sig_by_sym.get(sym)
        if not fresh:
            logger.debug(f"Thesis re-eval skipped for {sym}: no fresh signal in this scan")
            continue
        if not pos.get("entry_thesis"):
            logger.debug(f"Thesis re-eval skipped for {sym}: no entry_thesis recorded (pre-Stage 6 trade)")
            continue
        try:
            result = await re_evaluate_thesis(pos, fresh, prices.get(sym))
        except Exception as e:
            logger.warning(f"Thesis re-eval failed for {sym}: {e}")
            continue
        results[sym] = result
        # Persist the result on the position row
        try:
            db.table("virtual_trades").update({
                "thesis_last_checked_at": datetime.now(timezone.utc).isoformat(),
                "thesis_last_status": result.get("status"),
                "thesis_last_reason": (result.get("reason") or "")[:500],
            }).eq("id", pos["id"]).execute()
        except Exception as e:
            logger.warning(f"Failed to persist thesis result for {sym}: {e}")
    return results


async def execute_thesis_invalidation_exits(
    thesis_results: dict[str, dict],
    notifications,  # BrainNotificationQueue
) -> int:
    """Close any brain position whose thesis re-evaluated to 'invalid'.

    Returns the count of closed positions. Exits at the live price from the
    fresh signal (same source the regular SELL path uses). The exit_reason
    is set to 'THESIS_INVALIDATED' so the journal can distinguish these from
    price-based exits later.

    IMPORTANT: This runs BEFORE check_virtual_exits (the price-based exit
    sweep). A position with an invalid thesis will be closed here, so any
    subsequent stop/target trigger on the same scan will simply skip it.
    """
    # ... implementation: for each invalid result, fetch the position,
    # update status=CLOSED with exit_reason='THESIS_INVALIDATED', record
    # outcome via _record_brain_outcome, queue Telegram notification.
    ...
```

### 6e. Wire into the scan loop

In `scan_service.py` `run_scan`, between `process_virtual_trades` and `check_virtual_exits`:

```python
# Re-evaluate the thesis on every open brain position using this scan's data
from app.services import thesis_tracker
thesis_results = await thesis_tracker.reevaluate_open_theses(signals)
await thesis_tracker.execute_thesis_invalidation_exits(thesis_results, brain_notifications)
```

### 6f. Gate existing exits with the thesis check

The 6 existing exit paths in `virtual_portfolio.py` (SIGNAL, ROTATION, STOP_HIT, TARGET_HIT, PROFIT_TAKE, TIME_EXPIRED) get a new pre-check. If the position's `thesis_last_status == 'valid'` AND the exit is NOT a catastrophic loss, the exit is suppressed and logged as "thesis-protected hold."

```python
def _exit_is_thesis_protected(pos: dict, exit_reason: str, pnl_pct: float) -> bool:
    """Return True if a normal exit should be SUPPRESSED because the thesis is still valid.

    Catastrophic exits ALWAYS fire — we never let an "intact thesis" call
    blow us up beyond -8%. The thesis check is for noise filtering, not for
    overriding hard risk limits.
    """
    HARD_STOP_PCT = -8.0
    if pnl_pct <= HARD_STOP_PCT:
        return False  # Catastrophic — bypass thesis check, exit unconditionally
    if exit_reason == "ROTATION":
        return False  # Rotation is a relative comparison, doesn't depend on thesis
    if exit_reason == "THESIS_INVALIDATED":
        return False  # Already a thesis-driven exit
    return pos.get("thesis_last_status") == "valid"
```

Each exit site gains an early-return:

```python
if _exit_is_thesis_protected(pos, "STOP_HIT", pnl_pct):
    logger.info(f"Virtual STOP_HIT suppressed for {symbol} — thesis still valid: {pos.get('thesis_last_reason')}")
    notifications.append(("brain_thesis_hold", {
        "symbol": symbol, "exit_type": "STOP_HIT", "pnl": f"{pnl_pct:+.1f}",
        "reason": pos.get("thesis_last_reason") or "Thesis intact",
    }))
    continue
# ... existing close code
```

This is exactly the HUM-Day-1 fix the journal asked for: a SELL-signal-triggered close gets suppressed when the thesis says "still valid, this is noise."

### 6g. Provider function

`app/ai/provider.py` gains:

```python
async def re_evaluate_thesis(
    position: dict,
    fresh_signal: dict,
    current_price_tuple: tuple | None,
) -> dict:
    """Call Claude (or fallback chain) with THESIS_REEVAL_PROMPT.

    Returns the parsed JSON dict: {status, confidence, reason, should_exit, current_thesis}.
    Cost: ~$0.012 per call (one Claude synthesis-equivalent call). With 5 open
    positions and 8 scans/day = 40 calls/day = $0.48/day. Affordable.
    """
    # Build entry_conditions and current_conditions sections from
    # position.entry_thesis_keywords vs fresh_signal's current values.
    # Fill the prompt template, send via the provider chain, parse JSON.
    ...
```

### 6h. Verification for Stage 6

1. **Fake an invalidation:** Pick an open brain position. Manually set its `entry_thesis` to "Bought because XYZ catalyst is upcoming next week." In a fresh scan, the catalyst date passes. Confirm Claude returns `status: invalid` and the position closes with `exit_reason='THESIS_INVALIDATED'`.

2. **Fake a noise exit:** Pick an open brain position with a clearly intact thesis. Manually feed it a SELL signal in the next scan. Confirm:
   - Thesis re-eval runs first, returns `status: valid`
   - The SELL exit path is suppressed (logged as "thesis-protected hold")
   - The position stays open
   - A `brain_thesis_hold` Telegram alert fires

3. **Verify catastrophic bypass:** Take an open position currently at -8.5% with `thesis_last_status='valid'`. Trigger a stop hit. Confirm the position closes regardless of the thesis check (the catastrophic carve-out works).

4. **Cost check:** After 24 hours, query the AI cost log. Expected: ~$0.48/day for thesis re-evals on top of existing scan costs. If much higher, investigate batching.

5. **Pre-Stage-6 trades:** Old positions (without `entry_thesis` populated) must be silently skipped by the re-eval, not crash. Verify by querying for any virtual_trade with `entry_thesis IS NULL` and confirming the re-eval logs `"no entry_thesis recorded (pre-Stage 6 trade)"`.

### 6i. Feature flag

Add `BRAIN_THESIS_GATE_ENABLED` to `app/core/config.py` (default `True`) so we can revert the gating behavior in seconds if it misbehaves on the first day. The thesis re-evaluation itself always runs (cheap, useful for telemetry); only the exit-suppression gate is flag-controlled.

## Stage 7 — Lock the Architecture Into Docs, Memory, and Skills (1 hr, runs LAST)

**Goal:** After Stages 1-6 are shipped and verified, persist the principles into places they will survive context resets, model upgrades, and future development. This is non-negotiable — without Stage 7, the next conversation that touches the brain will re-litigate the same decisions.

**Bias toward skills, not CLAUDE.md.** User preference: skills are the right place for capability documentation; CLAUDE.md should only get the minimum needed to point at the skills. Don't bloat CLAUDE.md.

### 7a. Memory entries (write to `~/.claude/projects/.../memory/`)

These persist across all future Claude Code sessions. Use the `feedback` type because they are guiding principles, not project status.

1. **UPDATE** `feedback_three_witness_consensus.md` — currently describes a 3-witness voting model. **Rewrite** to reflect the corrected framing: AI is the *decider*, math + knowledge are the *dossier* the decider reads. The "consensus engine" idea was wrong; what we built is dossier enrichment + thesis tracking. Reference Stage 6 of this plan as the implementation.

2. **NEW** `feedback_thinking_vs_knowledge.md` — *"Distinguish thinking (hypothesis, low confidence, under observation) from knowledge (validated, proven, repeatable). Hypotheses graduate to knowledge through N successful confirmations (default 5); counter-evidence rejects them. Bad patterns also become knowledge once proven. Never store guesses as knowledge — that is lying about confidence."* Why: User insight on Day 3 — the thinking/knowledge split is the honest model; storing N=2 lessons as 'knowledge' deceives the AI about confidence levels.

3. **NEW** `feedback_knowledge_is_conditional.md` — *"Knowledge is never absolute, always conditional. Every pattern needs three parts: (a) entry conditions — when does this fire?, (b) prediction — what happens?, (c) invalidation conditions — when does it stop applying? The most important exit type is THESIS_INVALIDATED: when the reason for owning a position is gone, exit regardless of P&L. A winning position with a dead thesis must be sold; a losing position with an intact thesis must be held. Example: oil bought at $100 on a war thesis, sold at $150 when peace is announced, even though +50%."* Why: The oil-barrel example on Day 3 — pinpoints why static "avoid X" rules are wrong.

4. **NEW** `feedback_open_trades_are_data.md` — *"A position is data the moment it is open, not the moment it closes. Closed trades are ground truth (high weight). Open trades are in-flight evidence (lower weight, still real). Pattern stats and learning loops MUST read both — closed-only learning has slow feedback and survivorship bias toward fast-closing trades. Slow bleeders are usually the most valuable lesson and the slowest to arrive at 'closed.'"* Why: User caught this gap in the original Stage 4 design.

5. **NEW** `feedback_skills_over_claudemd.md` — *"For documenting capabilities, features, and architectural patterns: prefer adding/extending skills over editing CLAUDE.md files. CLAUDE.md should stay minimal and point at skills. Reason: skills are loaded on demand (don't bloat every conversation's context), have richer formatting, and are easier to discover via slash commands."* Why: Explicit user preference stated during Day 3 plan review.

6. Update `MEMORY.md` index with the 5 new/updated entries.

### 7b. New skill: `/brain-learning` (or similar name — confirm with user before creating)

This is the most important deliverable of Stage 7. A single skill that explains the brain's full reasoning architecture so any future Claude can understand it without re-deriving it.

Sections (proposed):

1. **The principle** — AI is the decider; math + knowledge serve the AI; thesis tracking gives forward-looking exits
2. **The 4 evidence layers** Claude sees in every prompt — Investment Knowledge (validated), Working Hypotheses (under observation), Pattern Stats (your live track record), Warning Signs (technical danger flags)
3. **The thinking → knowledge graduation pipeline** — schemas, graduation rules, where thinking entries come from (auto-extracted, journal, user)
4. **Thesis tracking** — entry capture, re-evaluation cadence, the THESIS_INVALIDATED exit, the catastrophic-stop carve-out
5. **The 7 exit reasons** with the gating matrix — which exits defer to the thesis check, which bypass it
6. **Pattern stats query** — closed + open evidence combination, the (bucket, regime) coarse start, how granularity expands as data grows
7. **Worked example** — walk through the META Day 3 loss with Stages 1-6 in place, showing what would have been different
8. **File pointers** — the critical paths an implementer needs to know

### 7c. Updates to existing skills

- **`/scan-pipeline`** — add the new "thesis re-evaluation" step in the scan flow diagram between `process_virtual_trades` and `check_virtual_exits`. Document the new exit reason. Document the catastrophic-stop carve-out.
- **`/database`** — add `signal_thinking` table, the new `virtual_trades` columns (`market_regime`, `entry_thesis`, `entry_thesis_keywords`, `thesis_last_*`), the new `signal_knowledge.invalidation_conditions` column. Document the indexes added in Stage 4.
- **`/conventions`** — add a note about the thinking/knowledge confidence framing if conventions doc covers data modeling.

### 7d. Frontend "How It Works" page

The user-facing page that explains Signa to humans (the user themselves, plus anyone they share Signa with). Add a new section: *"How the brain learns from its mistakes"* — explain in plain English (no code) the thinking/knowledge split, the thesis tracking, and the META→thesis-invalidation example. This is also a marketing surface — it shows that Signa is a *learning* system, not just an AI black box.

File: probably `front-end/src/app/(dashboard)/how-it-works/` or wherever the existing page lives. Match the existing tone and i18n pattern — bilingual EN/PT, all text from the i18n store.

### 7e. CLAUDE.md (minimum delta only)

`back-end/CLAUDE.md` already lists key thresholds and skill pointers. The only additions needed:

1. Under "Key Thresholds": add `THESIS_HARD_STOP_PCT = -8.0` (the catastrophic-stop carve-out)
2. Under "Skills": add a one-line pointer to the new `/brain-learning` skill
3. Under "Key Thresholds": add the `BRAIN_THESIS_GATE_ENABLED` config flag

Three lines total. Resist the urge to copy detail from the skill into CLAUDE.md — leave the detail in the skill where it belongs.

### 7f. Verification of Stage 7

1. Read `MEMORY.md` after the edits — confirm 5 new/updated entries listed
2. Invoke the new `/brain-learning` skill in a fresh Claude Code session and verify it loads cleanly
3. Visit the "How It Works" page in the front-end dev server — confirm the new section renders bilingually
4. Grep `back-end/CLAUDE.md` for the new flag and threshold — confirm only the 3 minimum lines were added
5. **The acid test:** start a NEW Claude Code session with no context, ask it to "explain how the Signa brain learns from losing trades." It should be able to answer correctly using only the skill + memory entries, with no need to re-derive anything from this conversation.

## What We're Deliberately NOT Doing (yet)

These were considered and explicitly deferred:

1. **JSONB `signal_pattern` column on `signal_knowledge` for entry-level pattern matching.** Useful, but Stage 1 (hand-written entry) + Stage 4 (inline pattern stats) cover the META-class problem without it. Add when the auto-extractor (Stage 5, future) needs it.

2. **Auto-extractor that writes/deactivates `signal_knowledge` entries based on N≥5 outcomes.** Requires hysteresis design (to avoid flapping at the 40-65% boundary), provenance audit table, and a deactivation policy. Worth building, but Stage 4 already gives Claude the same information (the warning) without the write loop. Defer until Stages 1-4 prove the pattern is real.

3. **The 3-witness consensus engine.** Killed by user direction. AI is the decider; we feed it better, we don't override it.

4. **Hard math vetoes (e.g., `macd_hist < -10` blocks BUY regardless of AI).** Same reason. The Stage 2 warning rule does flag the same condition — but as *information*, not as a veto. Claude can still decide to buy if the rest of the dossier overrules it.

5. **Snapshotting `catalyst_type` on virtual_trades.** Listed as a `record_outcome` parameter; we pass `None` for now. Add when we have a use case.

6. **Backfilling closed trades into `trade_outcomes`.** None exist after the Day 2→3 wipe.

7. **Backfilling thesis on the 5 currently-open positions.** They were entered before Stage 6 ships, so their `entry_thesis` is NULL. The re-eval silently skips them. They will exit through the existing 6 paths with no thesis protection. Once they close and new positions open, those new positions will have theses captured.

8. **Watchdog-triggered thesis re-evals between scans.** Currently the re-eval only runs at scan time (every ~1-4 hours). Fast-moving news could break a thesis between scans. Could add a watchdog hook, but defer until we see whether the gap matters in practice.

9. **The thinking → knowledge graduation pipeline (Stage 5 in the conversation).** The schema is described above and the `signal_thinking` table is needed for Stage 1's honest hypothesis insert. But the *automatic graduation logic* (count supporting outcomes per scan, promote when N ≥ 5) is deferred until we have data to graduate. For now, all entries go in as `status='active'` and stay there until manual promotion or rejection.

## Verification Plan

Each stage must pass these checks before moving to the next.

### Stage 1 verification
1. Run a manual scan: `venv/bin/python -m scripts._oneoff_test_scan` (or trigger via the API).
2. Check the AI debug logs (Claude/Gemini clients log full prompts at debug level) for any signal in the top-15 — confirm the new key_concept text appears in the `## Investment Knowledge` section.
3. Spot-check that the existing 10 entries also still appear (no regression).

### Stage 2 verification
1. **Unit-level:** Write a small ad-hoc Python that constructs a fake signal dict with `macd_histogram=-19.66, current_price=627, vs_sma200=-8, momentum_5d=-3` (META's actual numbers from Day 3). Call `format_warning_signs(sig)`. Expect at least: `macd_strongly_negative` and `momentum_collapse` to fire.
2. **Integration:** Run a manual scan after the rule + template + prompt changes. Inspect the AI debug log for a SAFE_INCOME ticker with negative MACD and confirm the `## Warning Signs` section is present and lists the danger signs in plain English.
3. **Regression:** Confirm no existing rule output changes — `compute_signal_breakdown(sig)` should still return the same i18n keys for the same input. Frontend signal detail page should look identical.

### Stage 3 verification
1. After deploying, force-close any test position (use `/forcesell` from Telegram or insert a SELL signal manually).
2. Query `trade_outcomes` for that symbol — expect a new row with bucket, market_regime, pnl_pct, signal_date, days_held all populated.
3. Confirm the brain Telegram alert still fires (the recorder must NOT block the close path even if it errors).
4. Tail logs for `Failed to record brain outcome` warnings — should be zero on the happy path.

### Stage 4 verification

The verification needs to exercise BOTH the closed and open evidence paths.

**Test A — closed-only path**
1. Insert ~6 fake closed brain trades into `trade_outcomes` with bucket=SAFE_INCOME, market_regime=VOLATILE, mostly negative pnl_pct (e.g. 4 losses, 2 wins → 33% WR).
2. Make sure no OPEN brain positions exist for that pattern (or set them all to a different bucket/regime temporarily).
3. Trigger a scan with at least one SAFE_INCOME signal in VOLATILE regime.
4. Check the AI prompt — expect the `## Pattern Stats (your own track record)` block at the end of the knowledge section with a `⚠ PATTERN WARNING` line. The breakdown should show `(6 closed @ 2/6 winners, ...; 0 currently open @ 0/0 in green, ...)`.

**Test B — open-only path (the most important one — proves the user's insight)**
1. Clear `trade_outcomes` of fake rows.
2. Make sure ~5 OPEN brain positions exist with bucket=SAFE_INCOME, market_regime=VOLATILE — and most are currently underwater (use today's actual state if it matches, otherwise insert test rows with entry_price set high enough that current price < entry).
3. Trigger a scan with a SAFE_INCOME / VOLATILE signal.
4. Expect the AI prompt to STILL contain a pattern warning, even though there are zero closed trades. The breakdown should show `(0 closed @ 0/0 winners, ...; 5 currently open @ 1/5 in green, ...)`. **This is the test that closes the user's META→PYPL loop in real time**, before any trade has actually closed.

**Test C — combined path**
1. With the open positions from Test B still in place, add 3 closed losers and 2 closed winners to `trade_outcomes` (5 closed: 40% WR, on the edge).
2. Combined: 5 closed (2W/3L) + 5 open (1W/4L) = 10 trades with 3 winners = 30% WR. Expect a warning.
3. Add 3 more closed winners (8 closed: 5W/3L = 62% WR). Combined: 13 trades with 6 winners = 46%. Should be in dead zone — no warning, no green light.
4. Add 3 more closed winners (11 closed: 8W/3L = 73% WR). Combined: 16 trades with 9 winners = 56%. Still dead zone.
5. Verify the warning correctly appears and disappears as the combined number crosses thresholds.

**Test D — price-feed outage**
1. With ~3 closed losers in `trade_outcomes` and 2 OPEN brain positions, simulate a price feed outage (mock `_fetch_prices_batch` to return empty).
2. Verify the open positions are silently skipped (open_n becomes 0) instead of being treated as zero-winners. This prevents a price outage from flipping a green light to a warning.

**Cleanup**
6. Clean up fake rows after each test.

### End-to-end
After all 4 stages: trigger a scan. For a SAFE_INCOME ticker with negative MACD in VOLATILE regime, the AI prompt should now contain:

1. The PYPL/META lesson (Stage 1, in `## Investment Knowledge`)
2. The per-ticker pattern stat (Stage 4, in `## Pattern Stats`) — once `trade_outcomes` has real data from Stage 3
3. The plain-English warning signs (Stage 2, in `## Warning Signs`)

Three layers of *context for Claude*, none of which override Claude's decision. Then re-evaluate META's setup tomorrow and see whether Claude's reasoning differs.
