"""Virtual Portfolio — the brain (Signa's autonomous trading engine).

============================================================
WHAT THIS MODULE IS
============================================================

The "brain" is an autonomous decision engine that opens and closes virtual
positions based on the signals produced by `scan_service`. It operates with
no human input — every buy and sell is evaluated against strict rules and
recorded to the `virtual_trades` table for later performance analysis.

There is no real money at stake. The brain's purpose is to:

  1. Validate the signal scoring model with real trade outcomes (win rate,
     P&L, time-to-target).
  2. Surface high-conviction opportunities to the user via Telegram alerts
     (so they can mirror the brain's decisions in their real broker if they
     choose to).
  3. Provide a self-learning feedback loop: the brain's wins and losses
     feed back into the signal scoring rules over time.

The brain is intentionally CONSERVATIVE. It refuses to act on incomplete
data, refuses to act outside market hours, refuses to act on signals where
the AI failed, and refuses to act on positions that have lost the AI's
confirmation. False negatives (missed opportunities) are preferable to
false positives (bad trades).

============================================================
THE TWO TRACKS
============================================================

Each scan can produce two parallel sets of virtual trades:

  WATCHLIST TRACK (`source = "watchlist"`)
  ----------------------------------------
  Tracks what would happen if you bought every BUY signal on a ticker you
  added to your watchlist. The brain doesn't pick the tickers — you do —
  but the brain executes the trades on your behalf in the virtual ledger.
  This is your "what-if-I-had-followed-my-own-list" experiment.

  BRAIN TRACK (`source = "brain"`)
  --------------------------------
  Fully autonomous. The brain picks its own tickers from the scan results
  using the tiered trust model below. It can hold up to `brain_max_open`
  positions at once and rotates the weakest position out when a stronger
  signal arrives.

After 1-2 weeks of running both tracks, you can compare them via the
`get_virtual_summary()` and `get_brain_tier_breakdown()` reports to see
which approach performs better.

============================================================
THE TIERED TRUST MODEL  (the brain's auto-buy gate)
============================================================

The brain only auto-buys signals that meet ONE of these tiers:

  TIER 1 — full position size  (trust_multiplier = 1.0)
  -----------------------------------------------------
    Requires:
      • ai_status == "validated" (AI synthesis succeeded with confidence ≥ 50)
      • score >= 75  (BRAIN_MIN_SCORE)
    Rationale: This is the high-conviction default. The AI ran cleanly,
    blockers were checked, the composite score is strong. Buy at full Kelly.

  TIER 2 — half position size  (trust_multiplier = 0.5)
  -----------------------------------------------------
    Requires:
      • ai_status == "low_confidence" (AI ran, but confidence < 50)
      • score >= 80  (BRAIN_TIER2_MIN_SCORE)
      • implicit: blockers passed (otherwise action would be AVOID, which
        is caught by the SELL/AVOID branch before tier evaluation)
    Rationale: AI is uncertain but the rest of the signal (tech, fundamentals,
    macro) all agree at score ≥ 80. The higher score bar compensates for
    AI uncertainty. Half-size to manage risk.

  TIER 3 — half position size  (trust_multiplier = 0.5)
  -----------------------------------------------------
    Requires:
      • ai_status == "skipped" (tech-only signal, AI never ran because the
        ticker was below the top-15 by pre-score)
      • score >= 82  (BRAIN_TIER3_MIN_SCORE)
      • At least 3 of 4 technical confirmations:
          - RSI in sweet spot (50-65)
          - MACD histogram positive
          - Volume z-score in [1.0, 2.5]
          - Within 30% of SMA200
      • Macro environment != "hostile" (re-checked here because tech-only
        signals skip the regular blocker pass)
    Rationale: AI never validated this signal, so we substitute pristine
    technicals + a macro check + a higher score bar. Strict criteria let
    the brain catch real opportunities the AI quota missed without taking
    on noise.

  TIER 0 — never auto-buy
  -----------------------
    • ai_status == "failed" (AI tried but errored — added to retry queue
      and re-attempted on the next scan, never auto-bought directly)
    • Any signal that doesn't meet a tier above

The tier evaluation runs INDEPENDENTLY of the user-facing `action` field.
Tier 2 and Tier 3 signals will already have been downgraded from BUY to
HOLD by the AI quality guard in `scan_service` (because their AI status
isn't "validated"). The brain bypasses that downgrade and applies its
own stricter criteria — the user-facing UI stays conservative, the brain
is allowed to act with its tier-aware position sizing.

============================================================
FILTER D ADMISSION GATES (Day 20, Apr 30)
============================================================

Independent of the tier model above, every brain entry (long or short)
must clear two structural admission gates derived from the historical
backtest (`scripts/backtest_filters.py`, see `docs/Day-19-overnight-analysis.md`):

  1. Sector exclusion: signals where fundamental_data.sector ∈
     {"Financial Services", "Industrials"} are rejected at the tier
     evaluator. See `FILTER_D_BLOCKED_SECTORS` for the rationale and
     invalidation criteria.

  2. LONG-horizon suspension: BUY signals whose computed trade_horizon
     would be "LONG" (i.e., not crypto, not HIGH_RISK bucket, no near-term
     catalyst within 7 days) are rejected at the BUY entry path AFTER
     horizon computation. Every LONG trade in 52-trade history was
     SAFE_INCOME bucket and the cohort was -14.9% total. See the inline
     comment in `process_virtual_trades` for invalidation criteria.

Both gates are TEMPORARY safety rails, not eternal vetoes. They live in
code (rather than in Claude's dossier) because the dossier path doesn't
yet carry "trades like this have lost us 5/9 times" to Claude's prompt.
When pattern-stats injection (Stage 4) makes Claude aware of these
cohorts, the gates become redundant and should be removed. Until then,
re-run the backtest weekly and remove a gate when its underlying cohort
recovers — see each constant's docstring for the precise threshold.

============================================================
MARKET HOURS DISCIPLINE
============================================================

The brain only buys/sells equities during the US regular session:
  Monday-Friday, 9:30am - 4:00pm ET.

Outside these hours:
  • New BUY signals on equities are SKIPPED (the trade wouldn't fill).
  • SELL signals on held equities are FLAGGED FOR REVIEW (see below)
    instead of being executed.
  • The watchdog skips equity positions and only monitors crypto.

Crypto is exempt and trades 24/7.

This makes virtual trades realistic — you can compare brain P&L to what
you'd actually achieve in your broker because every fill price is a real
in-hours price.

============================================================
PRE-MARKET REVIEW SYSTEM
============================================================

Pre-market scans (e.g. the 6am scan) can produce SELL signals on positions
the brain holds. We can't actually sell at 6am, so:

  1. The position is FLAGGED with `pending_review_at`, `pending_review_action`
     (SELL or AVOID), `pending_review_score`, `pending_review_reason`.
  2. An immediate Telegram alert fires: "⚠ Brain Flagged for Review".
  3. At the first scan after market open (9:30am+ ET), `process_pending_reviews`
     re-evaluates each flagged position against the FRESH signal:
       • Still SELL/AVOID → execute the sell, send "Brain SELL" alert.
       • Recovered to BUY/HOLD → clear the flag, send "Review Cleared" alert.
       • No fresh signal yet → leave the flag, retry next scan.

The user can also override from Telegram with /forcesell, /keep, /review.
A /forcesell sets `pending_review_action = "FORCE_SELL"` (a sentinel value)
which makes the next in-hours scan execute the sell unconditionally,
bypassing the score-drop guard.

============================================================
SCORE-DROP GUARD
============================================================

If a held position's score drops 25+ points to below 50 in a single scan,
the brain REFUSES to auto-sell. This usually means the AI failed to
analyze the ticker on this scan (tech-only fallback) rather than a real
deterioration. The watchdog will catch genuine danger within 15 minutes.

Exception: a user-forced sell from /forcesell bypasses this guard since
the user has explicitly accepted the risk.

============================================================
CONCURRENCY MODEL
============================================================

The brain notification queue is SCAN-LOCAL. Each scan creates a fresh
`BrainNotificationQueue` via `new_notification_queue()` and threads it
through every brain function in this module. There is NO module-level
notification state, so concurrent scans (manual + scheduled overlap)
cannot mix notifications between scans.

The flow is:

  1. scan_service.run_scan creates `brain_notifications = new_notification_queue()`
  2. process_pending_reviews(signals, brain_notifications)
  3. process_virtual_trades(signals, watchlist_symbols, brain_notifications)
  4. check_virtual_exits(brain_notifications)
  5. await flush_brain_notifications(brain_notifications)  # drains the queue

Step 5 is the only place that sends Telegram messages — it batches all
brain alerts at the end of the scan.

============================================================
STATE OWNERSHIP
============================================================

  Database (Supabase, source of truth):
    • virtual_trades — open + closed positions
    • virtual_snapshots — daily equity curve

  In-memory (per-scan, ephemeral):
    • BrainNotificationQueue — Telegram alerts queued for the end of scan
    • _vp_cache — TTL cache for the dashboard summary endpoints (5 min)

There is no in-memory state that survives process restarts. The brain
fully recovers its state from `virtual_trades` on every scan.
"""

from collections import Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from loguru import logger

from app.core.cache import TTLCache
from app.core.config import settings
from app.core.dates import days_since, parse_iso_utc
from app.db import queries
from app.db.supabase import get_client, with_retry
from app.services.knowledge_events import (
    EVENT_THINKING_OBSERVATION_ADDED,
    OUTCOME_CONTRADICTING,
    OUTCOME_NEUTRAL,
    OUTCOME_SUPPORTING,
    log_event,
)
from app.services.price_cache import _fetch_prices_batch


# ============================================================
# CONSTANTS — brain auto-pick score thresholds
# ============================================================
#
# These three constants define the score floor for each brain trust tier.
# See the file header for the full tier model. Tuned from the backtest
# (Oct 2024 - Apr 2025) — raising any of these reduces buy frequency but
# increases per-trade win rate. Lowering them does the reverse.

BRAIN_MIN_SCORE = 75
"""Tier 1 floor — validated AI signals must clear this score to be bought.

Day 13 (Apr 21): raised 72 → 75 after every losing rotation/churn over
Days 11-13 came from score 72-74 entries (JD, REI-UN.TO, CAR-UN.TO,
HR-UN.TO). Patience over slot-filling.

Day 19 (Apr 29): raised 75 → 80 after the bucketing fix shifted the
universe HIGH_RISK-heavy. The Day-19 reasoning was based on 4 wallet-era
trades at score 75-79 all closing losses. That sample was too small.

Day 20 (Apr 30): rolled back 80 → 75 as part of the Filter D ship.
The full 52-trade backtest (`scripts/backtest_filters.py`) showed:
  - Score 75-79 across all history: 8W / 11L, 42.1% win rate, -9.7% total
  - Score 80+ across all history: 7W / 10L, 41.2% win rate, +1.7% total
The 80-only rule cuts trade volume in half (36 → 17) for a marginal
+0.6pp/trade gain. Filter D (75 + SHORT-horizon + drop Fin/Industrials)
delivers +5.4% historical with n=23 — the same number of trades survive
as score 80 + sector add-on, with a stronger win rate (47.8% vs 46.2%).
Score is a quality FILTER, not a quality RANKER (Day-19 lesson from
ONDS at 91 being the biggest loser). The discriminating axes are
horizon and sector, not score.

Invalidation: revert to 80 if next monthly backtest shows the 75-79
band has a win rate < 35% across n >= 15 wallet-era trades."""

BRAIN_TIER2_MIN_SCORE = 80
"""Tier 2 floor — low-confidence AI signals need a higher score bar (80+)
to compensate for the AI's uncertainty. The 8-point premium over Tier 1
is what makes the brain comfortable acting at half-size despite low AI
conviction."""

BRAIN_TIER3_MIN_SCORE = 82
"""Tier 3 floor — tech-only signals (AI never ran) need an even higher
score bar (82+) AND must pass technical confirmation checks AND must not
be in a hostile macro regime. The 10-point premium over Tier 1 reflects
the absence of any AI validation."""


# ============================================================
# CONSTANTS — Filter D admission gates (Day 20)
# ============================================================
#
# Filter D is the historical winner from the 52-trade backtest
# (`scripts/backtest_filters.py`). Two structurally independent recipes
# (D and G) collapse to the same 23-trade subset and produce the same
# +5.4% total historical P&L (47.8% win rate) vs the unfiltered baseline
# of -17.6% / 40.4% — a +23.1pp improvement.
#
# The two gates below implement the structural pieces of Filter D:
#   1. FILTER_D_BLOCKED_SECTORS — the sector exclusion
#   2. The LONG-horizon suspension — implemented inline at the BUY path
#      (horizon is computed there, not on the signal)
#
# These are NOT meant to be permanent vetoes. Per the "Knowledge is
# Conditional" principle, every gate carries explicit invalidation
# criteria. Re-run `scripts/backtest_filters.py` weekly and remove the
# gate when its underlying cohort recovers.

FILTER_D_BLOCKED_SECTORS: frozenset[str] = frozenset({
    "Financial Services",
    "Industrials",
})
"""Sectors blocked from brain entry as of Day 20 (Apr 30).

Backtest evidence (52 closed brain trades):
  - "Drop Financial Services + Industrials" alone: n=43 surviving,
    46.5% win rate, +0.2% total (vs baseline 40.4% / -17.6%).
  - +17.8pp improvement from a 9-trade exclusion → those 9 trades
    averaged ~ -2% per trade. Structurally negative-EV in our sample.

Why these two specifically: they are the two highest-frequency,
lowest-EV sector cohorts in the data. Financial Services is dominated
by Canadian REITs and bank stocks that have been bleeding through the
sample period; Industrials is dominated by cyclical names that the
brain has been catching at the wrong end of their cycles.

Why this is OK as a gate (and not a violation of "AI is the Decider"):
the AI does not currently see "trades like this have lost us 5/9 times"
in its dossier. Until pattern-stats injection (Stage 4) carries this
signal to Claude's prompt, this gate is a temporary capacity rail
analogous to the per-day entry cap, not a quality veto.

Invalidation criteria: remove a sector from this set if the next
monthly backtest shows that sector's cohort has:
  - win rate >= 45% AND
  - n >= 10 trades in the rolling 30-day window AND
  - sum_pct >= 0% (not a net loser)

Audit cadence: weekly via `scripts/backtest_filters.py`. Log every
block via the tier_reason `"filter_d_sector_excluded_<sector>"` so
the cost of being wrong is visible in the database."""


# ============================================================
# TYPES
# ============================================================

BrainNotificationQueue = list[tuple[str, dict]]
"""A scan-local queue of brain Telegram notifications.

Format: list of (template_key, kwargs_dict) tuples.

Each scan creates a fresh queue via `new_notification_queue()` and threads
it through every brain function for that scan run. `flush_brain_notifications()`
drains it at the end of the scan and sends each entry as a Telegram message.

We DO NOT use a module-level singleton for this state because:
  1. Concurrent scans (manual + scheduled overlap) would mix notifications
     between scans, causing duplicates, lost messages, or wrong-ticker alerts.
  2. Explicit queue passing makes the data flow visible from the function
     signature instead of relying on hidden global state.
  3. It makes the brain functions independently testable.
"""


def new_notification_queue() -> BrainNotificationQueue:
    """Create a fresh brain notification queue for a single scan run.

    Called once per scan by `scan_service.run_scan` BEFORE any other brain
    function. The same queue is then passed to `process_pending_reviews`,
    `process_virtual_trades`, `check_virtual_exits`, and finally drained
    by `flush_brain_notifications` at the end of the scan.

    Returns an empty list. The functions append `(template_key, kwargs)`
    tuples; the flush coroutine sends each one via Telegram.
    """
    return []


def _is_us_market_open() -> bool:
    """Return True if the US equity regular session is currently open.

    Regular session: Monday-Friday, 9:30am-4:00pm ET (no holidays check —
    a closed-on-holiday scan would just generate no fills, which is
    correct behavior anyway since real markets would also reject the order).

    The brain uses this to gate equity buy/sell decisions:
      • Outside hours: equity BUYs are skipped, equity SELLs are flagged
        for review at the next open.
      • Crypto is exempt (24/7 market) and ignores this check.

    The watchdog also calls this to skip equity monitoring outside hours.
    """
    now_et = datetime.now(ZoneInfo("America/New_York"))
    if now_et.weekday() >= 5:  # 5=Saturday, 6=Sunday
        return False
    minutes = now_et.hour * 60 + now_et.minute
    # 9:30am = 9*60 + 30 = 570; 4:00pm = 16*60 = 960
    return 570 <= minutes < 960


def _eval_brain_trust_tier(sig: dict, portfolio_heat: int = 0) -> tuple[int, float, str]:
    """Decide which brain trust tier (if any) a signal qualifies for.

    This is the brain's GATE. Every brain auto-buy goes through this function.
    See the file header for the full tier model and rationale.

    Args:
        sig: A signal dict from the current scan (the same dict shape that
            `scan_service` builds for `signals` table inserts). The fields
            we read are: `score`, `ai_status`, `technical_data`, `macro_data`.

    Returns:
        (tier, trust_multiplier, reason)

        tier: 0, 1, 2, or 3. Tier 0 means "do not auto-buy".
        trust_multiplier: Position size scaling. 1.0 for tier 1, 0.5 for
            tiers 2/3, 0.0 for tier 0. Recorded on the virtual_trade so
            you can analyze per-tier returns later.
        reason: A short human-readable string explaining the decision.
            Logged with every brain buy and stored for diagnostics.

    Why this is called BEFORE the user-facing action check:
        Tier 2 and 3 signals will have already been downgraded from BUY to
        HOLD by the AI quality guard in `scan_service._process_candidate`
        (because their `ai_status` is not "validated"). The brain bypasses
        that downgrade because its tier model has stricter criteria that
        compensate. The user-facing UI stays conservative (HOLD), the
        brain is allowed to act (with reduced position size).

    Implicit blocker protection:
        Tier 1 + Tier 2: protected by `check_blockers` from `signal_engine`,
            because the AI path runs that check and sets action="AVOID" if
            anything fires. AVOID is caught earlier in `process_virtual_trades`
            (the SELL/AVOID branch), so it never reaches this function.

        Tier 3: NOT protected by `check_blockers`, because the tech-only
            signal path in `scan_service` skips that check entirely. We
            re-check the most critical blockers here:
                • Hostile macro environment (explicit check below)
                • Overbought RSI (excluded by the RSI 50-65 sweet-spot filter)
                • Low volume (excluded by the volume z-score 1.0-2.5 filter)
                • SMA200 overextension (excluded by the < 30% filter)
            Fraud blockers don't apply because tech-only signals have empty
            grok_data, so there's no sentiment text to scan for fraud keywords.
    """
    score = sig.get("score", 0) or 0
    ai_status = sig.get("ai_status", "skipped")
    technical_data = sig.get("technical_data") or {}

    # Failed AI is never auto-bought — it's a transient failure that should retry
    if ai_status == "failed":
        return 0, 0.0, "ai_failed"

    # ── Filter D: sector exclusion (Day 20) ──
    # Backtest evidence: Financial Services + Industrials cohorts together
    # account for the largest concentrated source of loss in the 52-trade
    # history. Block at the gate. See FILTER_D_BLOCKED_SECTORS for the
    # invalidation criteria — re-run scripts/backtest_filters.py weekly.
    fund = sig.get("fundamental_data") or {}
    sector = (fund.get("sector") or "").strip()
    if sector in FILTER_D_BLOCKED_SECTORS:
        return 0, 0.0, f"filter_d_sector_excluded_{sector.lower().replace(' ', '_')}"

    # ── Portfolio heat gating ──
    # heat=3 (locked): no new entries at all — protect existing gains
    if portfolio_heat >= 3:
        return 0, 0.0, "portfolio_locked"

    # heat=2 (defensive): only score 80+ at half size
    if portfolio_heat >= 2 and score < 80:
        return 0, 0.0, f"portfolio_defensive_score{score}"

    # heat=1 (cautious): only score 76+
    if portfolio_heat >= 1 and score < 76:
        return 0, 0.0, f"portfolio_cautious_score{score}"

    # ── SMA50 trend filter ──
    # Week 1 data (Apr 8-13) showed a clean pattern: ALL winners
    # (PBR-A +4.47%, AVGO +3.01%, ASML +1.30%, RRX +2.47%) were above
    # SMA50 at entry. ALL counter-trend losers (VZ -5.2% 5d, LB -5.5%
    # 5d, TPL -7.3% 5d) were below SMA50 at entry. "Cheap and falling"
    # is not "cheap and recovering."
    #
    # When price is below SMA50, the short-term trend is DOWN regardless
    # of fundamentals. The brain still enters (fundamentals might be
    # right) but at REDUCED SIZE — Tier 1 is downgraded to Tier 2 (50%
    # size) to limit exposure to counter-trend entries.
    vs_sma50 = technical_data.get("vs_sma50")
    below_sma50 = vs_sma50 is not None and vs_sma50 < 0

    # ── Bollinger Band ceiling + MACD divergence filter ──
    # Week 1-2 data: entries at BB > 95% with negative MACD had a 45%
    # win rate vs 69% overall. Price at the Bollinger ceiling with fading
    # momentum is a "buying the top" pattern — not bad enough to block
    # (AVGO +3.29% and ASML +2.52% entered this way) but risky enough
    # to halve the position size. Same principle as the SMA50 filter:
    # reduce, don't block.
    #
    # Real cases: VSEC -3.18%, BF-B -2.29%, LTM -1.24%, BLK -1.40%
    # all entered at BB=1.00 with negative MACD.
    bb_position = technical_data.get("bb_position")
    macd_hist = technical_data.get("macd_histogram")
    overextended = (
        bb_position is not None and bb_position > 0.95
        and macd_hist is not None and macd_hist < 0
    )

    # Heat=2 forces half size on all entries that pass the score gate
    heat_halve = portfolio_heat >= 2

    # Tier 1: validated AI + standard score threshold
    if ai_status == "validated" and score >= BRAIN_MIN_SCORE:
        if below_sma50:
            return 2, 0.5, "validated_below_sma50"
        if overextended:
            return 2, 0.5, "validated_overextended_bb"
        if heat_halve:
            return 2, 0.5, "validated_heat_defensive"
        return 1, 1.0, "validated"

    # Tier 2: low confidence AI + higher score bar
    # The AI ran (so we know it didn't blow up on red flags) but isn't sure.
    # Score >= 80 means tech/fund/macro all agree, compensating for low AI conviction.
    if ai_status == "low_confidence" and score >= BRAIN_TIER2_MIN_SCORE:
        return 2, 0.5, "low_confidence_high_score"

    # Tier 3: tech-only signal + very high score + technical confirmation
    # AI was never run (below top 15), so we require pristine technicals as a
    # substitute AND re-check the macro blocker (which the tech-only path
    # skips). Other blockers (RSI overbought, low volume, SMA overextension)
    # are implicitly enforced by the technical confirmation thresholds below.
    if ai_status == "skipped" and score >= BRAIN_TIER3_MIN_SCORE:
        # Hostile macro is a hard blocker — never auto-buy in a bad regime,
        # regardless of how good the technicals look on the individual ticker.
        macro_data = sig.get("macro_data") or {}
        if macro_data.get("environment") == "hostile":
            return 0, 0.0, "tier3_blocked_hostile_macro"

        rsi = technical_data.get("rsi")
        macd_hist = technical_data.get("macd_histogram")
        volume_zscore = technical_data.get("volume_zscore")
        vs_sma200 = technical_data.get("vs_sma200")
        sma_cross = technical_data.get("sma_cross")

        # Required technical confirmation:
        # 1. RSI in sweet spot (50-65) — not overbought, not falling
        # 2. MACD histogram positive — momentum building
        # 3. Volume confirmation (z-score 1.0-2.5) — real participation, not panic
        # 4. Not extremely overextended above SMA200 (< 30% gap)
        rsi_ok = rsi is not None and 50 <= rsi <= 65
        macd_ok = macd_hist is not None and macd_hist > 0
        volume_ok = volume_zscore is not None and 1.0 <= volume_zscore <= 2.5
        sma_ok = vs_sma200 is not None and vs_sma200 < 30
        # Bonus: golden cross within window (not strictly required but boosts confidence)

        confirmations = sum([rsi_ok, macd_ok, volume_ok, sma_ok])
        if confirmations >= 3:
            reason = f"tech_only_confirmed_{confirmations}of4"
            if sma_cross == "golden_cross":
                reason += "_goldencross"
            return 3, 0.5, reason

    return 0, 0.0, f"no_tier_{ai_status}_score{score}"


# ============================================================
# LEARNING LOOP — record outcomes + update hypothesis evidence
# ============================================================
#
# Every brain trade close MUST flow through `_record_brain_outcome` so that:
#   1. `trade_outcomes` gets a row (feeds Stage 4 pattern stats and the
#      existing weekly Claude analysis in `learning_service.run_weekly_analysis`)
#   2. Active hypotheses in `signal_thinking` whose `pattern_match` matches
#      the closed trade get their evidence counters incremented and the
#      mutation is logged to `knowledge_events`
#
# Failures NEVER block the close path. Audit/learning is best-effort.
# Watchlist trades are recorded too (under `record_outcome`'s existing
# track) but only BRAIN trades drive hypothesis evidence — watchlist is
# the user's exploratory list, not the brain's autonomous decisions.

def _eval_brain_short_tier(sig: dict) -> tuple[int, float, str]:
    """Decide whether a signal qualifies as a SHORT (sell) entry.

    Only AI-validated bearish signals with score <= brain_short_max_score
    qualify. No tech-only shorts — too risky without AI confirmation.

    Returns (tier, trust_multiplier, reason). tier=0 means rejected.
    """
    score = sig.get("score", 100) or 100
    ai_status = sig.get("ai_status", "skipped")
    action = sig.get("action")

    # Must be AI-validated AVOID with low score
    if ai_status != "validated":
        return 0, 0.0, "short_requires_validated_ai"
    if action != "AVOID":
        return 0, 0.0, "short_requires_avoid_action"
    if score > settings.brain_short_max_score:
        return 0, 0.0, f"short_score_too_high_{score}"

    # Filter D: sector exclusion (Day 20) — same rationale as the long
    # path. The backtest didn't cleanly separate long-vs-short for these
    # sectors, but the structural drag was symmetric enough to warrant
    # blocking at both gates. See FILTER_D_BLOCKED_SECTORS for invalidation.
    fund = sig.get("fundamental_data") or {}
    sector = (fund.get("sector") or "").strip()
    if sector in FILTER_D_BLOCKED_SECTORS:
        return 0, 0.0, f"short_filter_d_sector_excluded_{sector.lower().replace(' ', '_')}"

    # Must have target and stop defined
    price = float(sig.get("price_at_signal") or 0)
    target_p = sig.get("target_price")
    stop_p = sig.get("stop_loss")
    if not target_p or not stop_p or not price:
        return 0, 0.0, "short_missing_levels"

    target_p = float(target_p)
    stop_p = float(stop_p)

    # For a valid short: target < current price < stop
    # (target is lower = where we take profit, stop is higher = where we cut loss)
    if not (target_p < price < stop_p):
        return 0, 0.0, f"short_levels_wrong_direction"

    # Check bearish sentiment if available (Grok only runs for HIGH_RISK)
    gd = sig.get("grok_data") or {}
    if isinstance(gd, dict) and gd.get("score") is not None:
        if gd["score"] > 40:  # not bearish enough
            return 0, 0.0, f"short_sentiment_not_bearish_{gd['score']}"

    return 1, 1.0, "short_validated_bearish"


def _extract_thesis_keywords(sig: dict) -> dict:
    """Snapshot the structured conditions that justified an entry.

    The keywords are the *machine-checkable* parts of the thesis (numbers
    and labels), captured at insert time so the thesis re-evaluator can
    diff entry vs current state. Claude's free-text reasoning is captured
    separately in `entry_thesis`. The re-eval prompt uses both: keywords
    for fast field-by-field diff, prose for the WHY behind the entry.
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
        "sentiment_score": gd.get("score") if isinstance(gd, dict) else None,
        "sentiment_label": gd.get("label") if isinstance(gd, dict) else None,
        "catalyst": sig.get("catalyst"),
        "catalyst_type": sig.get("catalyst_type"),
        "fear_greed": md.get("fear_greed"),
    }


def _exit_is_thesis_protected(pos: dict, exit_reason: str, pnl_pct: float) -> bool:
    """Return True when an existing exit path should be SUPPRESSED because
    the thesis re-evaluator says the position is still valid.

    Catastrophic exits ALWAYS fire — we never let an "intact thesis" call
    blow us up beyond `settings.brain_thesis_hard_stop_pct`. The thesis
    check is for noise filtering, not for overriding hard risk limits.

    The 6 existing exit paths gate themselves through this function:
      • SIGNAL/AVOID flip → suppress if thesis still valid (HUM Day-1 fix)
      • STOP_HIT → suppress if thesis still valid AND not catastrophic
      • TARGET_HIT → suppress if thesis still valid (let it run)
      • PROFIT_TAKE → suppress if thesis still valid (let it run)
      • TIME_EXPIRED → suppress if thesis still valid (extend the window)
      • ROTATION → NEVER suppressed (rotation is a relative comparison
        between competing signals, doesn't depend on the absolute thesis)
      • THESIS_INVALIDATED → N/A (this IS the thesis-driven exit)
    """
    if not settings.brain_thesis_gate_enabled:
        return False
    # Defensive None guard — a null pnl_pct shouldn't happen (all call sites
    # compute from non-null floats) but if it ever does, fail-open so the
    # exit fires rather than crashing the scan.
    if pnl_pct is None:
        return False
    # Catastrophic carve-out: always exit, regardless of thesis. A wrong
    # Claude call must never blow up the position past the hard limit.
    # Direction-aware threshold: shorts use brain_short_hard_stop_pct
    # (semantically identical to long at -8.0 today, but configurable).
    direction = pos.get("direction") or "LONG"
    hard_stop_threshold = (
        settings.brain_short_hard_stop_pct if direction == "SHORT"
        else settings.brain_thesis_hard_stop_pct
    )
    if pnl_pct <= hard_stop_threshold:
        return False
    if exit_reason == "ROTATION":
        return False
    if exit_reason == "THESIS_INVALIDATED":
        return False
    if exit_reason == "TRAILING_STOP":
        return False  # trailing stop protects gains — never suppress it
    if exit_reason == "QUALITY_PRUNE":
        return False  # pruning dead weight — the thesis IS the reason we're selling
    return (pos.get("thesis_last_status") or "").lower() == "valid"


def _record_brain_outcome(
    closed_trade: dict,
    exit_price: float,
    exit_score: int | None,
    exit_reason: str,
    pnl_pct: float,
) -> None:
    """Forward a closed virtual trade to learning_service.record_outcome().

    Called from EVERY close path (SIGNAL, ROTATION, STOP_HIT, TARGET_HIT,
    PROFIT_TAKE, TIME_EXPIRED, watchdog). Failures are caught and logged,
    never raised — recording outcomes must NEVER block a real exit.

    For brain trades, also runs `_match_thinking_observations` which checks
    every active hypothesis and increments the supporting/contradicting
    counter on any whose `pattern_match` matches this closed trade.
    """
    if closed_trade.get("source") != "brain":
        # We could record watchlist outcomes too, but for v1 the learning
        # loop only studies the brain track — the user's watchlist picks
        # are exploratory and shouldn't shape the brain's learned patterns.
        return
    # Defensive guard: a brain trade without an entry_date shouldn't exist,
    # but if it ever does, skip learning rather than stamping the outcome
    # with today's date. That fallback would pollute pattern_stats's 90-day
    # rolling window (trade from 6 months ago counted as "today").
    entry_date_raw = closed_trade.get("entry_date")
    if not entry_date_raw:
        logger.warning(
            f"Skipping brain outcome for {closed_trade.get('symbol')}: "
            f"entry_date is null (pre-Stage-3 trade or data corruption)"
        )
        return
    try:
        from app.services import learning_service
        entry_dt = parse_iso_utc(entry_date_raw)
        if entry_dt is None:
            logger.warning(
                f"Skipping brain outcome for {closed_trade.get('symbol')}: "
                f"unparseable entry_date {entry_date_raw!r}"
            )
            return
        exit_dt = datetime.now(timezone.utc)
        days_held = max(0, (exit_dt - entry_dt).days)
        learning_service.record_outcome(
            signal_id=None,  # virtual trades aren't tied to one specific signal_id
            symbol=closed_trade["symbol"],
            action="BUY",  # all brain entries are BUYs
            score=int(closed_trade.get("entry_score") or 0),
            bucket=closed_trade.get("bucket") or "UNKNOWN",
            signal_date=entry_date_raw,
            entry_price=float(closed_trade["entry_price"]),
            exit_price=float(exit_price),
            days_held=days_held,
            target_price=closed_trade.get("target_price"),
            stop_loss=closed_trade.get("stop_loss"),
            market_regime=closed_trade.get("market_regime"),
            catalyst_type=None,  # not snapshotted yet (Stage 6 entry_thesis_keywords will carry it)
            notes=exit_reason,
        )
    except Exception as e:
        logger.warning(
            f"Failed to record brain outcome for {closed_trade.get('symbol')}: {e}"
        )

    # Hypothesis evidence update — separate try so a failure here doesn't
    # cancel the record_outcome above. Both are best-effort.
    try:
        _match_thinking_observations(closed_trade, exit_reason, pnl_pct)
    except Exception as e:
        logger.warning(
            f"Failed to update hypothesis observations for {closed_trade.get('symbol')}: {e}"
        )

    # Bust the Track Record by Score cache so the dashboard reflects the
    # new close immediately. Without this, the closed trade is in the DB
    # but the Track Record table shows stale data until the 15-min TTL
    # expires (the bug Pedro caught after WING closed at 13:06).
    try:
        from app.services.signal_service import invalidate_track_record_cache
        invalidate_track_record_cache()
    except Exception as e:
        logger.debug(f"Track record cache invalidation skipped: {e}")


def _trade_matches_pattern(trade: dict, pattern_match: dict) -> bool:
    """Best-effort match of a closed trade against a hypothesis pattern_match.

    Today we can only check (bucket, regime, score band) because that's all
    we snapshot on virtual_trades. Other pattern keys (e.g., macd_histogram_lt)
    are silently ignored — they'll become checkable once entry_thesis_keywords
    starts carrying technicals.

    Returns False if any CHECKABLE key fails, True otherwise. An empty
    pattern_match returns False (refuse to match against everything — a
    hypothesis with no pattern is unverifiable and would otherwise grab
    every closed trade).

    Score-band semantics:
        score_min and score_max are INCLUSIVE bounds.
        Non-integer/None values for score_min/score_max are silently
        skipped rather than crashing — this guards against bad data in
        pattern_match JSONB without raising on every closed trade.
    """
    if not pattern_match:
        return False
    # Defensive type check — pattern_match comes from JSONB and could
    # theoretically be a list/string if a bad insert sneaks through.
    # A non-dict here would crash .get() and kill ALL hypothesis updates
    # for this close (the outer try/except catches it but loses the good
    # hypotheses too). Return False for the bad entry, continue processing.
    if not isinstance(pattern_match, dict):
        return False
    bucket = pattern_match.get("bucket")
    if bucket and trade.get("bucket") != bucket:
        return False
    regime = pattern_match.get("regime")
    if regime and trade.get("market_regime") != regime:
        return False
    score = trade.get("entry_score") or 0
    score_min = pattern_match.get("score_min")
    if isinstance(score_min, (int, float)) and score < score_min:
        return False
    score_max = pattern_match.get("score_max")
    if isinstance(score_max, (int, float)) and score > score_max:
        return False
    score_eq = pattern_match.get("score_eq")
    if isinstance(score_eq, (int, float)) and score != score_eq:
        return False
    return True


def _classify_observation(prediction: str, pnl_pct: float) -> str:
    """Decide whether a closed trade SUPPORTS or CONTRADICTS a hypothesis.

    ⚠ V1 LIMITATION — READ BEFORE ADDING NEW HYPOTHESIS TYPES ⚠

    This function assumes EVERY hypothesis predicts a NEGATIVE outcome (a
    loss). The PYPL/META hypothesis from Stage 1 predicts losses, so a
    losing trade is "supporting" and a winning trade is "contradicting."
    This is correct for warning-style hypotheses but **inverted** for
    bullish hypotheses like "post-earnings-drift winners" or "momentum
    setups in TRENDING regime tend to win."

    If you add a hypothesis that predicts WINS instead of losses, this
    function will silently mis-classify every observation — winning trades
    will increment `observations_contradicting` (wrong) and losers will
    increment `observations_supporting` (also wrong). The brain's
    graduation logic would then learn the opposite of reality.

    The fix when needed: parse `prediction` text for keywords ("will gain",
    "will win", "favors") OR add a structured `expected_direction` column
    to `signal_thinking` ('loss' | 'win' | 'either') and switch on it here.
    Until that fix lands, ONLY add hypotheses that predict losses to
    `signal_thinking`.

    The 1% deadband around zero filters out trades that closed near
    breakeven — those don't really confirm or disprove a directional
    prediction in either direction.
    """
    if -1.0 < pnl_pct < 1.0:
        return OUTCOME_NEUTRAL
    # V1: hypothesis predicts a LOSS. Loss confirms it; win disproves it.
    if pnl_pct < 0:
        return OUTCOME_SUPPORTING
    return OUTCOME_CONTRADICTING


def _match_thinking_observations(
    closed_trade: dict,
    exit_reason: str,
    pnl_pct: float,
) -> None:
    """For every active hypothesis whose pattern matches this closed trade,
    increment the relevant evidence counter and log a knowledge_event.

    Best-effort matching — see `_trade_matches_pattern` for the limits of
    what we can check today vs what becomes checkable when entry_thesis_keywords
    carries the technical fields.

    PERF NOTE: this loads active hypotheses on every call. With ~5 closes/scan
    that's ~5 small queries (~50ms total). Acceptable today; if the brain
    starts closing many trades per scan, batch-load active hypotheses once
    in `process_virtual_trades` and pass them in.

    RACE CONDITION (acceptable for v1):
    The increment is read-modify-write, which is non-atomic. If a SCAN and
    a WATCHDOG TICK both close trades matching the same hypothesis at
    almost the same instant, both will read counter=N, both will write N+1,
    and one increment will be lost. The scan_service has a concurrency
    guard (rejects scans while another is RUNNING/QUEUED), so two SCANS
    can't race. But the watchdog runs on its own APScheduler timer and
    CAN overlap a long-running scan. Fix when needed: switch to a Postgres
    atomic increment via raw SQL, OR add an updated_at-based optimistic
    concurrency check. Until then, expect to lose ~1 counter increment per
    year — irrelevant for graduation thresholds in single digits.
    """
    db = get_client()
    active = (
        db.table("signal_thinking")
        .select("id, hypothesis, prediction, pattern_match, "
                "observations_supporting, observations_contradicting, observations_neutral")
        .eq("status", "active")
        .execute()
    ).data or []
    if not active:
        return

    for hypothesis in active:
        pattern = hypothesis.get("pattern_match") or {}
        if not _trade_matches_pattern(closed_trade, pattern):
            continue
        outcome = _classify_observation(hypothesis.get("prediction") or "", pnl_pct)
        # Map the outcome to the column we increment
        if outcome == OUTCOME_SUPPORTING:
            field = "observations_supporting"
        elif outcome == OUTCOME_CONTRADICTING:
            field = "observations_contradicting"
        else:
            field = "observations_neutral"
        before = hypothesis.get(field) or 0
        after = before + 1
        try:
            db.table("signal_thinking").update({
                field: after,
                "last_evaluated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", hypothesis["id"]).execute()
        except Exception as e:
            logger.warning(
                f"Failed to bump {field} on hypothesis {hypothesis['id']}: {e}"
            )
            continue
        # Append an audit event for the increment
        log_event(
            EVENT_THINKING_OBSERVATION_ADDED,
            triggered_by="brain_close_hook",
            thinking_id=hypothesis["id"],
            trade_id=closed_trade.get("id"),
            observation_outcome=outcome,
            payload={
                "symbol": closed_trade.get("symbol"),
                "bucket": closed_trade.get("bucket"),
                "market_regime": closed_trade.get("market_regime"),
                "entry_score": closed_trade.get("entry_score"),
                "pnl_pct": round(pnl_pct, 2),
                "exit_reason": exit_reason,
                "counter_field": field,
                "counter_before": before,
                "counter_after": after,
            },
            reason=(
                f"Trade {closed_trade.get('symbol')} closed {pnl_pct:+.2f}% "
                f"({exit_reason}) — matches pattern_match for hypothesis "
                f"\"{(hypothesis.get('hypothesis') or '')[:60]}...\" — "
                f"{field}: {before} → {after}"
            ),
        )


def _flag_positions_for_review(
    db, all_open: list, symbol: str, action: str, score: int,
    reason: str, now_iso: str, notifications: BrainNotificationQueue,
) -> None:
    """Tag held positions of `symbol` as pending review at next market open.

    Called from the SELL/AVOID branch of `process_virtual_trades` when the
    market is closed and the held position is an equity (so the trade
    cannot actually fill). The flag tells `process_pending_reviews` to
    re-evaluate this position the next time the market is open.

    Args:
        db: Supabase client (passed in to avoid re-fetching).
        all_open: All currently-open virtual_trades, loaded once at the
            start of `process_virtual_trades` for in-memory iteration.
        symbol: Ticker symbol of the position to flag.
        action: The deteriorated action that triggered the flag — usually
            "SELL" or "AVOID".
        score: The fresh signal score that triggered the flag.
        reason: Human-readable reason (the signal's `reasoning` field).
            Truncated to 500 chars when stored, 200 when sent over Telegram.
        now_iso: Current UTC timestamp as ISO-8601 string. Stored in
            `pending_review_at`.
        notifications: Scan-local notification queue. A "brain_pending_review"
            entry is appended for each newly-flagged BRAIN position
            (watchlist positions are tracked silently — they're data
            collection only, not actionable).

    Idempotency: positions that ALREADY have a pending_review_at flag are
    skipped. This prevents alert spam if the user has multiple pre-market
    scans flag the same position twice in a row (e.g. 6am and 7am scans).
    """
    for pos in all_open:
        if pos["symbol"] != symbol:
            continue
        if pos.get("pending_review_at"):
            continue  # Already flagged, don't spam alerts
        entry_score = pos.get("entry_score", 0) or 0
        try:
            db.table("virtual_trades").update({
                "pending_review_at": now_iso,
                "pending_review_action": action,
                "pending_review_score": score,
                "pending_review_reason": (reason or "")[:500],
            }).eq("id", pos["id"]).execute()
        except Exception as e:
            logger.warning(f"Failed to flag {symbol} for review: {e}")
            continue
        logger.warning(
            f"Virtual REVIEW FLAGGED: {symbol} signal turned {action} "
            f"({entry_score}->{score}) — will re-check at market open"
        )
        # Only notify for brain positions (watchlist track is just data collection)
        if pos.get("source") == "brain":
            notifications.append(("brain_pending_review", {
                "symbol": symbol,
                "action": action,
                "entry_score": str(entry_score),
                "exit_score": str(score),
                "reason": reason[:200] if reason else "Signal deteriorated overnight",
            }))


def process_pending_reviews(
    signals: list[dict],
    notifications: BrainNotificationQueue,
) -> dict:
    """Re-evaluate positions flagged for review at a previous pre-market scan.

    This function implements step 3 of the pre-market review system (see
    file header). It runs at the START of every in-hours scan, BEFORE
    `process_virtual_trades`, on the same `signals` list reference.

    For each position with `pending_review_at` set:

      • The fresh signal for that ticker is looked up in `signals`.
      • If no fresh signal exists, the flag is left in place (retry next scan).
      • If `pending_review_action == "FORCE_SELL"` (user override via
        /forcesell), the fresh signal's `action` is mutated to "SELL"
        and a `_review_forced` marker is set so the score-drop guard
        in `process_virtual_trades` knows to bypass itself.
      • If the fresh signal is still SELL/AVOID → CONFIRMED. The flag is
        cleared. Because we operate on the SAME `signals` list reference
        that `process_virtual_trades` will iterate next, the SELL action
        propagates naturally and the sell executes in the same scan run.
      • If the fresh signal recovered to BUY/HOLD → CLEARED. The flag is
        cleared and a "brain_review_cleared" notification is queued.

    Args:
        signals: Fresh signals from the current scan. THIS FUNCTION MUTATES
            the signal dicts for forced-sell cases (sets `action` and
            `_review_forced`). The mutation is intentional — the same list
            reference is then iterated by `process_virtual_trades` which
            sees the mutated values.
        notifications: Scan-local queue. Appends `brain_review_cleared`
            entries for recovered brain positions (deduped by symbol so
            multiple positions for the same ticker only generate one alert).

    Returns:
        Dict with two counters:
            cleared: positions whose flag was cleared due to recovery.
            confirmed: positions whose flag was cleared due to confirmed
                deterioration (these will be sold by `process_virtual_trades`
                later in the same scan).

    Returns immediately with zero counts if the market is closed —
    pending reviews can only be processed during market hours.
    """
    if not _is_us_market_open():
        return {"cleared": 0, "confirmed": 0}

    db = get_client()
    flagged_result = (
        db.table("virtual_trades")
        .select("id, symbol, entry_score, source, pending_review_action, "
                "pending_review_score, pending_review_reason, target_price, stop_loss, "
                "bucket, signal_style")
        .eq("status", "OPEN")
        .not_.is_("pending_review_at", "null")
        .execute()
    )
    flagged = flagged_result.data or []
    if not flagged:
        return {"cleared": 0, "confirmed": 0}

    # Index fresh signals by symbol for O(1) lookup
    by_symbol: dict[str, dict] = {}
    for sig in signals:
        sym = sig.get("symbol")
        if sym:
            by_symbol[sym] = sig

    cleared = 0
    confirmed = 0
    notified_recovered: set[str] = set()  # Dedupe per-symbol "review cleared" notifications
    for pos in flagged:
        symbol = pos["symbol"]
        fresh = by_symbol.get(symbol)
        if not fresh:
            # No fresh signal for this ticker — leave the flag, retry next scan
            continue

        fresh_action = fresh.get("action")
        fresh_score = fresh.get("score", 0)
        entry_score = pos.get("entry_score", 0) or 0
        # Detect a user-forced sell via the sentinel value set by /forcesell.
        # This is more robust than parsing the reason text.
        forced = pos.get("pending_review_action") == "FORCE_SELL"

        # User-forced sell from /forcesell command: override the fresh signal
        # so process_virtual_trades sees a SELL action this scan and executes.
        # Also flag _review_forced so the SELL flow's score-drop guard
        # (which protects against AI methodology change false-AVOIDs)
        # doesn't accidentally block the user's explicit override.
        if forced:
            fresh["action"] = "SELL"
            fresh["_review_forced"] = True
            fresh_action = "SELL"
            logger.warning(
                f"Virtual REVIEW FORCED SELL: {symbol} (user override via /forcesell) "
                f"— executing this scan"
            )

        if fresh_action in ("SELL", "AVOID"):
            # Confirmed: clear the review flag. The regular SELL flow in
            # process_virtual_trades (which runs right after this on the same
            # scan, on the SAME `signals` list reference) will see the SELL
            # action and execute the sell since market is now open. We clear
            # the flag here so a future scan doesn't see a stale flag and
            # skip the SELL flow with another flagging operation.
            try:
                db.table("virtual_trades").update({
                    "pending_review_at": None,
                    "pending_review_action": None,
                    "pending_review_score": None,
                    "pending_review_reason": None,
                }).eq("id", pos["id"]).execute()
            except Exception as e:
                logger.warning(f"Failed to clear review flag for {symbol}: {e}")
            confirmed += 1
            logger.warning(
                f"Virtual REVIEW CONFIRMED: {symbol} still {fresh_action} "
                f"at open ({entry_score}->{fresh_score}) — will sell this scan"
            )
        else:
            # Recovered: clear the flag and notify
            try:
                db.table("virtual_trades").update({
                    "pending_review_at": None,
                    "pending_review_action": None,
                    "pending_review_score": None,
                    "pending_review_reason": None,
                }).eq("id", pos["id"]).execute()
            except Exception as e:
                logger.warning(f"Failed to clear review flag for {symbol}: {e}")
                continue
            cleared += 1
            logger.info(
                f"Virtual REVIEW CLEARED: {symbol} recovered to {fresh_action} "
                f"({entry_score}->{fresh_score}) — keeping position"
            )
            if pos.get("source") == "brain" and symbol not in notified_recovered:
                notified_recovered.add(symbol)
                notifications.append(("brain_review_cleared", {
                    "symbol": symbol,
                    "action": fresh_action,
                    "entry_score": str(entry_score),
                    "exit_score": str(fresh_score),
                }))

    return {"cleared": cleared, "confirmed": confirmed}


def process_virtual_trades(
    signals: list[dict],
    watchlist_symbols: set[str],
    notifications: BrainNotificationQueue,
) -> dict:
    """Run the brain's buy/sell decision loop over a scan's fresh signals.

    This is the heart of the brain. For every signal in `signals`, this
    function decides:
      • Should we close any existing positions for this symbol? (SELL/AVOID)
      • Should we open a new watchlist-track position? (action == BUY +
        symbol on watchlist + score >= 62)
      • Should we open a new brain-track position? (tier evaluator returns
        tier > 0; the brain bypasses the user-facing action field)
      • If the brain wants to open a new position but is at max capacity,
        should we rotate out the weakest existing brain position?

    The decision rules are documented in the file header. The most
    important constraints:

      MARKET HOURS GATE
        • Equity BUYs and SELLs are skipped/flagged when market is closed.
        • Crypto BUYs and SELLs proceed regardless (24/7 markets).

      SCORE-DROP GUARD
        • If a held position's score drops 25+ points to below 50 in a
          single scan, refuse to auto-sell. Likely AI methodology change,
          not real deterioration. The watchdog will catch genuine danger.
        • A user-forced sell (via /forcesell, marked with `_review_forced`
          on the signal) bypasses this guard.

      BRAIN ROTATION
        • If `brain_open_count >= settings.brain_max_open` and a stronger
          signal arrives, the weakest existing brain position is closed
          to make room IF the new signal is at least 5 points better.
        • Below the 5-point margin, no rotation happens (avoids churn
          on small score differences).

      TIER-AWARE BUYS
        • Tier 1 (validated AI, score >= 72): full position size.
        • Tier 2 (low_confidence AI, score >= 80): half position size.
        • Tier 3 (skipped AI tech-only, score >= 82, technical confirmation,
          non-hostile macro): half position size.
        • Tier and trust_multiplier are recorded on the virtual_trade row
          for per-tier performance analysis.

    Args:
        signals: Fresh signals from the current scan. The signal dicts may
            have been mutated by `process_pending_reviews` (e.g. forced
            sells). Read-only otherwise.
        watchlist_symbols: Symbols currently on the user's watchlist. Used
            to gate the watchlist track (only symbols here are considered
            for watchlist-source positions).
        notifications: Scan-local queue. Brain BUY/SELL events append
            entries here that `flush_brain_notifications` later sends.

    Returns:
        Dict with two counters:
            buys: number of positions opened this scan (sum of watchlist + brain).
            sells: number of positions closed this scan (signal-driven SELLs;
                rotations and watchdog closes are NOT counted here).

    Side effects:
        • DB inserts/updates to virtual_trades.
        • Appends to the notifications queue.
        • Auto-upserts discovered tickers to the tickers table when the
          brain buys a ticker that's not in the universe (so it keeps
          getting scanned in future runs).
    """
    db = get_client()
    buys = 0
    sells = 0

    # ──────────────────────────────────────────────────────────
    # PHASE 1 — Snapshot current open positions
    # ──────────────────────────────────────────────────────────
    # We load all open virtual_trades ONCE and iterate against the in-memory
    # snapshot. This avoids N+1 queries inside the per-signal loop. The
    # snapshot is read-only for lookups; mutations to the DB happen via
    # targeted updates by row id.
    # process_virtual_trades also needs pending_review_at (pre-market
    # review flow) and consecutive_avoid_count (Day-14 LONG exit delay),
    # so we extend the shared close-field list.
    open_result = (
        db.table("virtual_trades")
        .select(VIRTUAL_TRADES_CLOSE_FIELDS + ", pending_review_at, consecutive_avoid_count")
        .eq("status", "OPEN")
        .execute()
    )
    all_open = open_result.data or []

    # Two parallel sets keep O(1) "is this symbol already held?" checks for
    # both tracks. The rotation block recomputes the weakest brain position
    # JUST IN TIME from `open_brain` (rather than caching it upfront), so a
    # SELL or rotation earlier in the same scan can't leave us with a stale
    # reference pointing at an already-closed row. The previous design
    # cached `weakest_brain` here and tried to keep it in sync — that's the
    # bug that allowed the rotation logic to overwrite already-closed rows
    # with new is_win values computed from a fresh live price.
    open_watchlist: set[str] = set()
    open_brain: set[str] = set()         # all brain (long + short)
    open_brain_long: set[str] = set()    # brain LONG positions only
    open_brain_short: set[str] = set()   # brain SHORT positions only
    brain_open_count = 0
    brain_long_count = 0
    brain_short_count = 0
    brain_entry_prices: list[float] = []
    for r in all_open:
        if r.get("source") == "brain":
            open_brain.add(r["symbol"])
            brain_open_count += 1
            brain_entry_prices.append(float(r.get("entry_price", 0)))
            if r.get("direction") == "SHORT":
                open_brain_short.add(r["symbol"])
                brain_short_count += 1
            else:
                open_brain_long.add(r["symbol"])
                brain_long_count += 1
        else:
            open_watchlist.add(r["symbol"])

    # ── Portfolio heat score ──
    # Computed once per scan. Controls how aggressively the brain adds
    # new positions. The goal: PROTECT existing gains. When the portfolio
    # is fat (high unrealized P&L), concentrated (many positions), or the
    # market is complacent (low VIX), the brain gets more selective.
    #
    # Pedro's principle (Day 8): "we cannot lose whatever we make. if so
    # what is the point?" Making money and then losing it is worse than
    # never making it. The heat score ensures the brain shifts from
    # "grow" to "protect" as profits accumulate.
    #
    # heat=0: normal (score >= 72, full size)
    # heat=1: cautious (score >= 76, full size)
    # heat=2: defensive (score >= 80, half size)
    # heat=3: locked (no new entries, let existing positions ride)
    portfolio_heat = 0

    # Factor 1: Portfolio size as a proxy for unrealized gains.
    # Position-count heuristic — a mid-scan live-price fetch over all
    # brain positions caused DNS thread exhaustion against the scan's own
    # yfinance calls, so we use count instead: 8+ positions usually means
    # meaningful gains to protect (the brain only buys winners).
    if brain_open_count >= 8:
        portfolio_heat += 1

    # Factor 2: Concentration (too many open positions)
    if brain_open_count > 12:
        portfolio_heat += 1

    # Factor 3: Market complacency (VIX too low = shock risk)
    # Use the macro_data from the first signal if available
    first_macro = None
    for sig_item in signals:
        if sig_item.get("macro_data"):
            first_macro = sig_item["macro_data"]
            break
    if first_macro:
        vix = first_macro.get("vix")
        if vix is not None and vix < 16:
            portfolio_heat += 1

    if portfolio_heat > 0:
        heat_labels = {1: "cautious", 2: "defensive", 3: "locked"}
        logger.info(
            f"Portfolio heat: {portfolio_heat} ({heat_labels.get(portfolio_heat, 'max')}) — "
            f"positions={brain_open_count}, "
            f"vix={first_macro.get('vix') if first_macro else '?'}"
        )

    # Re-buy cooldown snapshot: any brain symbol recently closed via
    # THESIS_INVALIDATED or TARGET_HIT is blocked from re-entry this scan.
    #
    # THESIS_INVALIDATED: prevents the buy → invalidate → re-buy loop
    # caused by Claude's non-determinism. Real case (2026-04-09): WING #1
    # closed at 17:06:04, WING #2 opened 54 min later and bled -0.95%.
    #
    # TARGET_HIT: prevents selling at target then immediately re-buying
    # at the same price. Real case (2026-04-10): ASML #1 sold at $1489
    # (target hit, +5.09%), ASML #2 re-entered same day at $1480.96 with
    # a bearish entry thesis. The sell + re-buy creates a taxable event
    # in Canada with no strategic benefit. Better to wait for a pullback
    # before re-entering.
    cooldown_minutes = settings.brain_thesis_rebuy_cooldown_minutes
    cooldown_brain_symbols: set[str] = set()
    if cooldown_minutes > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)).isoformat()
        cooldown_rows = (
            db.table("virtual_trades")
            .select("symbol, exit_date")
            .eq("source", "brain")
            .eq("status", "CLOSED")
            .in_("exit_reason", ["THESIS_INVALIDATED", "TARGET_HIT"])
            .gte("exit_date", cutoff)
            .execute()
        ).data or []
        cooldown_brain_symbols = {r["symbol"] for r in cooldown_rows if r.get("symbol")}
        if cooldown_brain_symbols:
            logger.info(
                f"Brain re-buy cooldown active on {len(cooldown_brain_symbols)} symbols "
                f"({cooldown_minutes}min): {sorted(cooldown_brain_symbols)}"
            )

    # Resolve once: brain runs single-tenant, every insert is stamped with
    # this user_id so the rows are correctly attributed and queryable.
    brain_user_id = queries.get_brain_user_id()

    # Load wallet once; `running_balance` tracks decrements locally so a
    # second BUY in the same scan sizes off the post-first-BUY balance.
    # `get_wallet` lazy-creates a zeroed row on first access — until the
    # user deposits, running_balance is 0 and every entry is skipped.
    from app.services import wallet as wallet_svc
    _wlt_initial = wallet_svc.get_wallet(brain_user_id) if settings.wallet_enabled else None
    running_balance: float = float(_wlt_initial["balance"]) if _wlt_initial else 0.0

    # Per-day entry cap (Day 19 learning). Count today's already-opened
    # wallet entries from the audit ledger so the cap is enforced
    # *across* scans, not just within one scan. Counts BUY + SHORT_OPEN
    # (both deploy capital). Tracking variable below increments locally
    # as we open new ones during this scan.
    wallet_entries_today = 0
    # Day 21: per-SYMBOL per-day cap. SEZL hit Filter D 3 times in one
    # day (May 1) — the same name re-appearing across consecutive scans.
    # Without a per-symbol gate, the per-day cap (3) could be entirely
    # consumed by one ticker and concentrate ~$1.2k there. Build a
    # Counter of today's wallet-entry symbols so we can clip on the
    # second attempt of the same name.
    wallet_entries_by_symbol_today: Counter = Counter()
    if settings.wallet_max_entries_per_day > 0 or settings.wallet_max_entries_per_symbol_per_day > 0:
        try:
            today_utc_start = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            ).isoformat()
            day_count_result = (
                db.table("wallet_transactions")
                .select("symbol", count="exact")
                .gte("created_at", today_utc_start)
                .in_("transaction_type", ["BUY", "SHORT_OPEN"])
                .execute()
            )
            wallet_entries_today = int(day_count_result.count or 0)
            for row in (day_count_result.data or []):
                _sym = row.get("symbol")
                if _sym:
                    wallet_entries_by_symbol_today[_sym] += 1
        except Exception as e:
            logger.warning(f"Couldn't count today's wallet entries: {e}")
    wallet_entries_this_scan = 0

    now = datetime.now(timezone.utc).isoformat()
    market_open = _is_us_market_open()

    # Pre-sort signals by score DESC so when we hit the daily cap the
    # surviving slots go to the highest-conviction signals, not whatever
    # happened to come first in the iteration order. SELL/AVOID logic
    # is symbol-keyed (matches by `pos["symbol"] == sig["symbol"]`) so
    # the order doesn't matter for closes. Only entries benefit.
    signals = sorted(signals, key=lambda s: -(s.get("score") or 0))

    # ──────────────────────────────────────────────────────────
    # PHASE 2 — Per-signal decision loop
    # ──────────────────────────────────────────────────────────
    # For each fresh signal we decide:
    #   1. SELL/AVOID branch: close held positions for this symbol
    #      (or flag for review if equity + market closed).
    #   2. BUY branch (watchlist track): open if explicit BUY + watchlisted.
    #   3. BUY branch (brain track): open if tier evaluator returns tier > 0.
    # Each branch is gated by independent rules (market hours, score-drop
    # guard, tier eval) — see the file header for the full rule set.

    for sig in signals:
        symbol = sig.get("symbol")
        action = sig.get("action")
        price = sig.get("price_at_signal")
        score = sig.get("score", 0)

        if not price:
            continue
        price = float(price)

        is_watchlisted = symbol in watchlist_symbols
        is_crypto = sig.get("asset_type") == "CRYPTO" or (symbol or "").endswith("-USD")

        # Reset consecutive_avoid_count on any open LONG position for this
        # symbol when the fresh signal is NOT AVOID/SELL. This prevents a
        # stale counter from 2 days ago from triggering an immediate close
        # on the next AVOID.
        if action not in ("SELL", "AVOID"):
            for pos in all_open:
                if (
                    pos["symbol"] == symbol
                    and pos.get("source") == "brain"
                    and int(pos.get("consecutive_avoid_count") or 0) > 0
                ):
                    db.table("virtual_trades").update(
                        {"consecutive_avoid_count": 0}
                    ).eq("id", pos["id"]).eq("status", "OPEN").execute()
                    pos["consecutive_avoid_count"] = 0
                    logger.info(
                        f"Virtual AVOID counter RESET for {symbol} — "
                        f"fresh signal is {action}, trend intact"
                    )

        # ── SELL: close all open positions for this symbol ──
        if action in ("SELL", "AVOID"):
            # Pre-market SELLs on equities can't fill — flag the position for
            # review at market open instead. The first scan after 9:30am ET
            # re-checks: still bad → execute, recovered → clear flag.
            if not is_crypto and not market_open:
                _flag_positions_for_review(
                    db, all_open, symbol, action, score,
                    sig.get("reasoning") or f"Pre-market signal turned {action}",
                    now, notifications,
                )
                continue
            for pos in all_open:
                if pos["symbol"] != symbol:
                    continue

                entry_score = pos.get("entry_score", 0) or 0
                score_drop = entry_score - score

                # Guard: if score dropped 25+ points, don't auto-close.
                # This usually means the ticker lost AI analysis (tech-only fallback)
                # rather than a real deterioration. Wait for next scan to confirm.
                # Exception: user-forced sells from /forcesell bypass this guard
                # since the user has explicitly accepted the risk.
                if score_drop >= 25 and score < 50 and not sig.get("_review_forced"):
                    source = pos.get("source", "watchlist")
                    logger.warning(
                        f"Virtual SELL BLOCKED [{source}]: {symbol} score dropped "
                        f"{entry_score} -> {score} (-{score_drop}pts). "
                        f"Likely methodology change, not real signal. Waiting for confirmation."
                    )
                    continue
                if sig.get("_review_forced"):
                    logger.warning(
                        f"Virtual SELL [user-forced]: {symbol} bypassing score-drop guard "
                        f"({entry_score} -> {score}, -{score_drop}pts)"
                    )

                entry_price = float(pos["entry_price"])
                # Direction-aware P&L (Day 14 audit fix): a SHORT position
                # hit by a BUY→AVOID signal (which means the short signal
                # got stronger) uses inverted P&L. Hardcoding long-side
                # logic inverts learning-loop + notification P&L for shorts.
                _pos_dir = pos.get("direction") or "LONG"
                pnl_pct = _calc_pnl_pct(entry_price, price, _pos_dir)
                pnl_amount = _calc_pnl_amount(entry_price, price, _pos_dir)
                is_win = pnl_pct > 0
                source = pos.get("source", "watchlist")

                # Stage 6 gate: if the thesis is still valid, this SIGNAL
                # flip is treated as noise and the position is held. The
                # HUM Day-1 incident: HUM hit a SELL signal but the thesis
                # was still intact (just an AI-quality issue), and we sold
                # at +0.77% leaving 15% on the table. The thesis gate
                # fixes that class of false-positive sell.
                if source == "brain" and _exit_is_thesis_protected(pos, "SIGNAL", pnl_pct):
                    logger.info(
                        f"Virtual SIGNAL exit SUPPRESSED for {symbol} — thesis still valid "
                        f"(P&L {pnl_pct:+.1f}%, action was {action}, holding through)"
                    )
                    continue

                # LONG/LONG exit-delay gate (Day 14 fix): a LONG-direction
                # position with LONG trade_horizon needs N consecutive
                # AVOID/SELL signals before closing. This prevents
                # single-signal shake-outs where Claude's "AVOID" on one
                # scan is just noise (morning volume lull, one-off RSI
                # print) and the trend is actually intact. CCO.TO on
                # Day 14 opened at PRE_CLOSE, closed on next MORNING at
                # +1.49% — a win, but the trend had room to run.
                pos_direction = pos.get("direction") or "LONG"
                pos_horizon = pos.get("trade_horizon") or "SHORT"
                if (
                    source == "brain"
                    and pos_direction == "LONG"
                    and pos_horizon == "LONG"
                    and not sig.get("_review_forced")
                ):
                    new_count = int(pos.get("consecutive_avoid_count") or 0) + 1
                    threshold = settings.brain_long_signal_exit_threshold
                    if new_count < threshold:
                        db.table("virtual_trades").update(
                            {"consecutive_avoid_count": new_count}
                        ).eq("id", pos["id"]).eq("status", "OPEN").execute()
                        logger.info(
                            f"Virtual SIGNAL exit DELAYED for {symbol} (LONG) — "
                            f"avoid count {new_count}/{threshold}, P&L {pnl_pct:+.1f}%. "
                            f"Holding through first flip, waiting for confirmation."
                        )
                        continue
                    # count reached threshold — close normally, counter doesn't matter after close
                    logger.info(
                        f"Virtual SIGNAL exit CONFIRMED for {symbol} (LONG) — "
                        f"{threshold} consecutive AVOIDs, closing at P&L {pnl_pct:+.1f}%"
                    )

                # Route through close_virtual_trade so wallet settlement +
                # learning loop fire for every close, and the pnl math is
                # computed once regardless of which path triggered the exit.
                # If another path (watchdog / earlier scan) already closed
                # this row, the helper returns skipped=True so we don't
                # double-count or send a duplicate Telegram alert.
                close_res = close_virtual_trade(
                    pos, price, "SIGNAL", score,
                    exit_action=action, exit_date_iso=now,
                )
                if close_res.get("skipped"):
                    continue
                sells += 1

                # Refresh in-memory state so the rotation block later in this
                # scan doesn't pick this just-closed position as a rotation
                # target. Without this, `weakest_brain` (now recomputed lazily)
                # would still see the row in `open_brain` and could re-update
                # the closed row.
                if source == "brain":
                    open_brain.discard(symbol)
                    brain_open_count = max(0, brain_open_count - 1)
                else:
                    open_watchlist.discard(symbol)

                emoji = "✅" if is_win else "❌"
                logger.info(
                    f"Virtual SELL [{source}]: {emoji} {symbol} @ ${price:.2f} "
                    f"(entry ${entry_price:.2f}, P&L {pnl_pct:+.1f}%, score {entry_score}->{score})"
                )

                # Queue Telegram notification for brain sells
                if source == "brain":
                    verdict = f"{emoji} {'Win' if is_win else 'Loss'} -- brain learning from this outcome."
                    notifications.append(("brain_sell", {
                        "symbol": symbol, "price": f"{price:.2f}",
                        "pnl": f"{pnl_pct:+.1f}", "reason": f"Signal changed to {action}",
                        "entry_score": str(entry_score), "exit_score": str(score),
                        "verdict": verdict,
                    }))
            continue

        # ── COVER: close SHORT positions when signal turns bullish ──
        # If we're short a stock and the signal flips to BUY (or strong HOLD
        # with score >= 65), the bearish thesis is dead — cover the short.
        if action == "BUY" and symbol in open_brain_short:
            for pos in all_open:
                if pos["symbol"] != symbol or pos.get("direction") != "SHORT":
                    continue
                entry_price_pos = float(pos["entry_price"])
                cover_pnl_pct = _calc_pnl_pct(entry_price_pos, price, "SHORT")
                close_res = close_virtual_trade(
                    pos, price, "SIGNAL", score,
                    exit_action=action, exit_date_iso=now,
                )
                if close_res.get("skipped"):
                    continue
                sells += 1
                brain_short_count = max(0, brain_short_count - 1)
                brain_open_count = max(0, brain_open_count - 1)
                open_brain_short.discard(symbol)
                open_brain.discard(symbol)
                logger.info(
                    f"Virtual COVER [brain]: {symbol} @ ${price:.2f} "
                    f"(signal flipped to BUY, P&L {cover_pnl_pct:+.1f}%)"
                )
                notifications.append(("brain_sell", {
                    "symbol": symbol, "price": f"{price:.2f}",
                    "pnl": f"{cover_pnl_pct:+.1f}",
                    "reason": f"SHORT covered — signal flipped to BUY (score {score})",
                    "entry_score": str(pos.get("entry_score", 0)),
                    "exit_score": str(score),
                    "verdict": f"Bearish thesis invalidated by bullish signal.",
                }))

        # By here, action is not SELL/AVOID (handled above with continue).
        # It can be BUY, HOLD, or anything else. Brain will evaluate via tier logic.

        # Skip BUYs on equities when US market is closed — the trade wouldn't
        # actually fill at the scan price (e.g. 6am pre-market scan). Crypto
        # trades 24/7 so it's always allowed.
        if not is_crypto and not market_open:
            logger.debug(f"Virtual BUY skipped for {symbol}: US market closed")
            continue

        # Track 1: Watchlist picks (score 62+) — only on explicit BUY action.
        # Dedup against BOTH tracks so a symbol opened by either track in a
        # previous scan (or earlier in this scan) blocks the other from also
        # opening it. Previously the two tracks were independent, which is
        # why PNC and SLF.TO ended up with two rows each (watchlist + brain)
        # on the same Apr 6 scan.
        if (
            action == "BUY"
            and is_watchlisted
            and score >= 62
            and symbol not in open_watchlist
            and symbol not in open_brain
        ):
            db.table("virtual_trades").insert({
                "user_id": brain_user_id,
                "symbol": symbol,
                "action": "BUY",
                "entry_price": price,
                "entry_date": now,
                "entry_score": score,
                "status": "OPEN",
                "bucket": sig.get("bucket"),
                "signal_style": sig.get("signal_style"),
                "source": "watchlist",
                "target_price": sig.get("target_price"),
                "stop_loss": sig.get("stop_loss"),
                # Snapshot for the learning loop — see _record_brain_outcome
                "market_regime": sig.get("market_regime"),
            }).execute()
            buys += 1
            open_watchlist.add(symbol)  # block any further inserts this scan
            logger.info(f"Virtual BUY [watchlist]: {symbol} @ ${price:.2f} (score {score})")

        # ── Track 2: Brain auto-picks via the tiered trust model ──
        # The brain evaluates the signal INDEPENDENTLY of the user-facing
        # `action` field. Tier 2/3 signals were downgraded BUY → HOLD by
        # the AI quality guard in scan_service, but the brain bypasses
        # that downgrade because its tier model has stricter criteria
        # (higher score bar + technical confirmation + macro check) that
        # compensate for the AI uncertainty.
        #
        # See `_eval_brain_trust_tier` and the file header for the rules.
        brain_tier, trust_multiplier, tier_reason = _eval_brain_trust_tier(sig, portfolio_heat)
        if (
            brain_tier > 0
            and symbol not in open_brain
            and symbol not in open_watchlist  # dedup with watchlist track
            and symbol not in cooldown_brain_symbols  # post-THESIS_INVALIDATED cooldown
        ):
            # ── Rotation: brain at max capacity, only rotate if the new
            # ── signal is meaningfully better (+5 points) than the weakest
            # ── currently-held brain position.
            #
            # The +5 margin avoids constant churn on small score differences.
            # We use entry_score as the tie-breaker; higher entry_score
            # implied a more confident initial decision.
            if brain_long_count >= settings.brain_max_open_long:
                # Recompute the weakest brain position from the LIVE state
                # of `open_brain` (which reflects any SELLs and rotations
                # that happened earlier in this scan). The previous design
                # cached `weakest_brain` upfront and tried to keep it in
                # sync, which was bug-prone — a SELL flow earlier in the
                # scan could leave a stale reference pointing at a
                # just-closed row, and the rotation would then overwrite
                # the closed row's pnl/is_win with new values.
                weakest = None
                weakest_score = 999
                for r in all_open:
                    if r.get("source") != "brain":
                        continue
                    if r.get("symbol") not in open_brain:
                        continue  # already closed earlier this scan
                    es = r.get("entry_score", 0) or 0
                    if es < weakest_score:
                        weakest_score = es
                        weakest = r

                if weakest and score >= weakest_score + 5:
                    w_symbol = weakest["symbol"]
                    w_entry = float(weakest["entry_price"])
                    # Use the LIVE price for the rotated-out position so the
                    # recorded P&L is realistic. Fall back to the new signal's
                    # price only if the live fetch fails (rare).
                    w_prices = _fetch_prices_batch([w_symbol])
                    w_current, _ = w_prices.get(w_symbol, (None, None))
                    w_exit_price = w_current if w_current else price
                    # Direction-aware P&L for the rotated-out position (kept
                    # as a local for the logger + notification below; the
                    # close helper computes the stored version itself).
                    w_direction = weakest.get("direction") or "LONG"
                    w_pnl = _calc_pnl_pct(w_entry, w_exit_price, w_direction) if w_entry > 0 else 0
                    close_res = close_virtual_trade(
                        weakest, w_exit_price, "ROTATION", score,
                        exit_date_iso=now,
                    )
                    if close_res.get("skipped"):
                        # Another path (watchdog/parallel scan) already closed
                        # the weakest. Our local counters are now stale and
                        # capacity may or may not be free. Skip inserting the
                        # new position this round — next scan will reassess.
                        continue
                    open_brain.discard(w_symbol)
                    brain_open_count -= 1
                    logger.info(
                        f"Virtual ROTATION: closed {w_symbol} (score {weakest_score}, P&L {w_pnl:+.1f}%) "
                        f"to make room for {symbol} (score {score})"
                    )
                    notifications.append(("brain_sell", {
                        "symbol": w_symbol, "price": f"{w_exit_price:.2f}",
                        "pnl": f"{w_pnl:+.1f}", "reason": f"Rotated out for {symbol} (score {score})",
                        "entry_score": str(weakest_score), "exit_score": str(score),
                        "verdict": f"Replaced by stronger pick {symbol}.",
                    }))
                else:
                    continue  # No room and new signal isn't strong enough
            # ── Compute target & stop for the new position ──
            # AI-validated signals (Tier 1, sometimes Tier 2) come with
            # AI-generated target_price and stop_loss from the synthesis.
            # Tier 3 (tech-only) signals don't — synthesize the levels from
            # the ATR (Average True Range) instead. ATR-based levels give
            # a 1.33 R/R ratio (target = price + 2 ATR, stop = price - 1.5 ATR)
            # which is conservative but workable.
            target = sig.get("target_price")
            stop = sig.get("stop_loss")
            if not target or not stop:
                atr = (sig.get("technical_data") or {}).get("atr")
                if atr and price:
                    target = round(price + 2 * float(atr), 2)
                    stop = round(price - 1.5 * float(atr), 2)

            if target and stop:
                # Crypto risk cap: floor the stop at -8% from entry. Without
                # this, an AI-generated stop could be far wider than is safe
                # for crypto's volatility, leading to catastrophic losses
                # before the stop triggers.
                if sig.get("asset_type") == "CRYPTO" or symbol.endswith("-USD"):
                    max_crypto_stop = price * 0.92  # 8% max drawdown
                    if float(stop) < max_crypto_stop:
                        stop = round(max_crypto_stop, 2)

                # Classify trade horizon. LONG positions get daily thesis
                # re-eval (AFTER_CLOSE only), wider trailing stop (8%), and
                # 60-day expiry — letting winners compound instead of being
                # killed by 5x/day conservative thesis re-evals.
                # SHORT: crypto (24/7 volatile), HIGH_RISK (momentum), or
                # near-term catalyst <= 7 days.
                _is_crypto = sig.get("asset_type") == "CRYPTO" or symbol.endswith("-USD")
                _catalyst_days = sig.get("catalyst_days") or 999
                _bucket = sig.get("bucket") or ""
                if _is_crypto or _bucket == "HIGH_RISK" or _catalyst_days <= 7:
                    _horizon = "SHORT"
                else:
                    _horizon = "LONG"

                # Filter D: LONG-horizon suspension (Day 20).
                # Backtest evidence: every LONG-horizon trade in the 52-trade
                # history was bucket=SAFE_INCOME (zero HIGH_RISK × LONG ever
                # existed). The cohort: n=15, 33.3% win rate, -14.9% total —
                # the single worst slice of the data. Block here, after the
                # horizon has been computed, so the log is informative.
                #
                # Invalidation: re-enable when the next monthly backtest shows
                # the LONG cohort has win rate >= 50% across n >= 10 trades
                # in the rolling 30-day window OR a HIGH_RISK × LONG entry
                # appears in the data with a positive outcome. Until then,
                # SAFE_INCOME with no near-term catalyst is structurally
                # negative-EV in our sample.
                if _horizon == "LONG":
                    logger.info(
                        f"Virtual BUY skipped for {symbol} (score {score}): "
                        f"filter_d_long_horizon_suspended (bucket={_bucket}, "
                        f"catalyst_days={_catalyst_days}). Historical LONG "
                        f"cohort: 33% win rate, -14.9% total over n=15."
                    )
                    continue

                # Per-symbol per-day cap (Day 21): block re-entry of a
                # name we already entered today. Without this gate, a
                # repeatedly-flagged ticker (May 1: SEZL hit Filter D
                # 3 times in one day) could consume the per-day cap
                # entirely on a single name. Sector exclusion catches
                # this for Fin/Industrials but a Tech name in the same
                # situation would still concentrate.
                sym_cap = settings.wallet_max_entries_per_symbol_per_day
                if sym_cap > 0 and wallet_entries_by_symbol_today[symbol] >= sym_cap:
                    logger.info(
                        f"Virtual BUY skipped for {symbol} (score {score}): per-symbol "
                        f"cap reached ({wallet_entries_by_symbol_today[symbol]}/{sym_cap}). "
                        f"Brain already entered this name today; preventing concentration."
                    )
                    continue

                # Per-day cap (Day 19): if we've already opened the
                # configured max number of wallet entries today (across
                # all scans), skip. Highest-score signals are processed
                # first because we sorted at function entry, so the cap
                # naturally clips marginal entries.
                cap = settings.wallet_max_entries_per_day
                if cap > 0 and (wallet_entries_today + wallet_entries_this_scan) >= cap:
                    logger.info(
                        f"Virtual BUY skipped for {symbol} (score {score}): daily entry cap "
                        f"reached ({wallet_entries_today + wallet_entries_this_scan}/{cap}). "
                        f"Conserving capital for higher-conviction signals tomorrow."
                    )
                    continue

                sizing = _compute_wallet_fields(
                    running_balance, brain_tier, trust_multiplier, price, symbol, kind="BUY",
                )
                if sizing is None:
                    continue
                allocation_usd, shares, wallet_fields = sizing

                ins_result = db.table("virtual_trades").insert({
                    "user_id": brain_user_id,
                    "symbol": symbol,
                    "action": "BUY",
                    "entry_price": price,
                    "entry_date": now,
                    "entry_score": score,
                    "status": "OPEN",
                    "bucket": sig.get("bucket"),
                    "signal_style": sig.get("signal_style"),
                    "source": "brain",
                    "target_price": target,
                    "stop_loss": stop,
                    "entry_tier": brain_tier,
                    "trust_multiplier": trust_multiplier,
                    "tier_reason": tier_reason,
                    "trade_horizon": _horizon,
                    # Snapshot for the learning loop — see _record_brain_outcome.
                    # We snapshot at insert because the regime can shift between
                    # entry and close, and pattern_stats matches on the regime
                    # we ENTERED in (the conditions that justified the trade),
                    # not the one we exited in.
                    "market_regime": sig.get("market_regime"),
                    # Stage 6: capture the THESIS for this entry. The thesis
                    # tracker re-evaluates this every scan and triggers
                    # THESIS_INVALIDATED exits when the reason is gone.
                    "entry_thesis": (sig.get("reasoning") or "")[:500],
                    "entry_thesis_keywords": _extract_thesis_keywords(sig),
                    **wallet_fields,
                }).execute()

                new_trade_id = ins_result.data[0]["id"] if ins_result.data else None
                # Settle the wallet AFTER insert — we need the trade_id on
                # the audit ledger row. Only runs when the wallet is enabled
                # AND allocation is positive (disabled path skips wallet math
                # entirely). If this fails after the insert succeeded, the
                # error log names the orphan so it can be reconciled; we do
                # NOT roll back the trade because the brain's autonomy
                # depends on the trade being open even if wallet errored.
                if settings.wallet_enabled and allocation_usd > 0:
                    try:
                        wallet_svc.debit_for_long_buy(
                            user_id=brain_user_id,
                            allocation_usd=allocation_usd,
                            trade_id=new_trade_id,
                            symbol=symbol,
                            shares=shares,
                            price=price,
                        )
                        running_balance = max(0.0, running_balance - allocation_usd)
                    except Exception as e:
                        logger.error(
                            f"Wallet debit FAILED for {symbol} (trade {new_trade_id}, "
                            f"allocation ${allocation_usd:.2f}): {e}. Trade row exists; "
                            f"wallet balance is NOT deducted — reconcile manually."
                        )

                buys += 1
                brain_open_count += 1
                brain_long_count += 1
                wallet_entries_this_scan += 1
                wallet_entries_by_symbol_today[symbol] += 1
                open_brain.add(symbol)
                open_brain_long.add(symbol)
                logger.info(
                    f"Virtual BUY [brain] T{brain_tier}: {symbol} @ ${price:.2f} "
                    f"(score {score}, tier={tier_reason}, trust={trust_multiplier:.0%})"
                )

                # Queue Telegram notification (sent after function returns)
                rr = round(float(target - price) / float(price - stop), 1) if stop and price > stop else 0
                notifications.append(("brain_buy", {
                    "symbol": symbol, "score": str(score),
                    "bucket": sig.get("bucket", ""),
                    "price": f"{price:.2f}", "target": f"{float(target):.2f}",
                    "stop": f"{float(stop):.2f}", "rr": f"{rr}",
                    "tier": str(brain_tier),
                    "trust": f"{int(trust_multiplier * 100)}",
                }))

                # Auto-add discovered tickers to the tickers table
                # so they keep getting scanned in future scans
                from app.db import queries as db_queries
                from app.scanners.universe import get_exchange
                try:
                    db_queries.upsert_ticker(
                        symbol,
                        name=sig.get("company_name", ""),
                        exchange=get_exchange(symbol),
                        bucket=sig.get("bucket"),
                    )
                except Exception:
                    pass

    # ── Track 3: Brain SHORT entries (bearish bets) ──────────────
    # Evaluate AVOID signals as potential short positions. This runs
    # AFTER the BUY track so we never short a symbol we just bought,
    # and AFTER the SELL track so symbols that flipped to AVOID are
    # already closed on the long side before we consider shorting.
    shorts_opened = 0
    for sig in signals:
        symbol = sig.get("symbol")
        action = sig.get("action")
        score = sig.get("score", 100) or 100
        price = sig.get("price_at_signal")

        if not symbol or not price or action != "AVOID":
            continue
        # Don't short something we hold long, or already short
        if symbol in open_brain_long or symbol in open_brain_short:
            continue
        if brain_short_count >= settings.brain_max_open_short:
            continue

        short_tier, short_mult, short_reason = _eval_brain_short_tier(sig)
        if short_tier == 0:
            continue

        target = sig.get("target_price")
        stop = sig.get("stop_loss")
        if not target or not stop:
            continue

        # Per-symbol per-day cap (Day 21) — same gate as the BUY path,
        # applied to SHORT entries. Prevents the brain from re-shorting
        # the same name across consecutive scans.
        sym_cap = settings.wallet_max_entries_per_symbol_per_day
        if sym_cap > 0 and wallet_entries_by_symbol_today[symbol] >= sym_cap:
            logger.info(
                f"Virtual SHORT skipped for {symbol} (score {score}): per-symbol "
                f"cap reached ({wallet_entries_by_symbol_today[symbol]}/{sym_cap})."
            )
            continue

        # Per-day cap (Day 19) — applies to SHORTs too. Both wallet
        # entries deploy capital; rate-limit them together.
        cap = settings.wallet_max_entries_per_day
        if cap > 0 and (wallet_entries_today + wallet_entries_this_scan) >= cap:
            logger.info(
                f"Virtual SHORT skipped for {symbol} (score {score}): daily entry cap "
                f"reached ({wallet_entries_today + wallet_entries_this_scan}/{cap})."
            )
            continue

        # Horizon for shorts: default SHORT (momentum), but stable
        # bearish thesis could be LONG (held up to 14 days either way).
        _horizon = "SHORT"

        # Shorts use Tier-1 sizing (10% of balance) scaled by short_mult;
        # 100% of the allocation gets reserved as collateral when
        # reserve_for_short_open runs below.
        sizing = _compute_wallet_fields(
            running_balance, 1, short_mult, float(price), symbol, kind="SHORT",
        )
        if sizing is None:
            continue
        short_allocation_usd, short_shares, short_wallet_fields = sizing

        ins_result = db.table("virtual_trades").insert({
            "user_id": brain_user_id,
            "symbol": symbol,
            "action": "SHORT_SELL",
            "entry_price": float(price),
            "entry_date": now,
            "entry_score": score,
            "status": "OPEN",
            "bucket": sig.get("bucket"),
            "signal_style": sig.get("signal_style"),
            "source": "brain",
            "target_price": float(target),
            "stop_loss": float(stop),
            "entry_tier": 1,
            "trust_multiplier": short_mult,
            "tier_reason": short_reason,
            "trade_horizon": _horizon,
            "direction": "SHORT",
            "trough_price": float(price),  # initial trough = entry price
            "market_regime": sig.get("market_regime"),
            "entry_thesis": (sig.get("reasoning") or "")[:500],
            "entry_thesis_keywords": _extract_thesis_keywords(sig),
            **short_wallet_fields,
        }).execute()

        new_short_id = ins_result.data[0]["id"] if ins_result.data else None
        if settings.wallet_enabled and short_allocation_usd > 0:
            try:
                wallet_svc.reserve_for_short_open(
                    user_id=brain_user_id,
                    allocation_usd=short_allocation_usd,
                    trade_id=new_short_id,
                    symbol=symbol,
                    shares=short_shares,
                    price=float(price),
                )
                running_balance = max(0.0, running_balance - short_allocation_usd)
            except Exception as e:
                logger.error(
                    f"Wallet reserve FAILED for SHORT {symbol} (trade {new_short_id}, "
                    f"allocation ${short_allocation_usd:.2f}): {e}. Trade row exists; "
                    f"collateral NOT reserved — reconcile manually."
                )

        shorts_opened += 1
        brain_short_count += 1
        brain_open_count += 1
        wallet_entries_this_scan += 1
        wallet_entries_by_symbol_today[symbol] += 1
        open_brain_short.add(symbol)
        open_brain.add(symbol)
        logger.info(
            f"Virtual SHORT [brain]: {symbol} @ ${float(price):.2f} "
            f"(score {score}, target ${float(target):.2f}, stop ${float(stop):.2f})"
        )
        notifications.append(("brain_sell", {
            "symbol": symbol, "score": str(score),
            "price": f"{float(price):.2f}",
            "pnl": "0.0",
            "reason": f"SHORT entry — bearish signal (score {score})",
            "entry_score": str(score), "exit_score": str(score),
            "verdict": f"Brain opened SHORT bet against {symbol}.",
        }))

    return {"buys": buys, "sells": sells, "shorts": shorts_opened}


async def flush_brain_notifications(notifications: BrainNotificationQueue) -> int:
    """Drain the scan-local brain notification queue into the Telegram background worker.

    This is the ONLY function in this module that emits Telegram messages.
    Every other function APPENDS to the queue; this one drains it into the
    background `enqueue()` path so the scan NEVER blocks on Telegram HTTP.

    Before 2026-04-10: this function awaited `send_message()` per item —
    up to 150s of Telegram HTTP blocking inside the scan coroutine. That
    starved Claude Local subprocesses and caused AI synthesis failures
    when Telegram was slow or a login OTP collided with the scan.

    Now: each notification is enqueued instantly. The background worker in
    `telegram_bot._telegram_worker()` handles delivery + retry. The scan
    continues immediately after enqueue.

    Args:
        notifications: The scan-local queue threaded through every brain
            function this scan run. Will be cleared after enqueuing.

    Returns:
        Count of notifications enqueued. The queue is always cleared at
        the end regardless — the same notification should never be sent
        twice.
    """
    if not notifications:
        return 0
    from app.notifications.messages import msg
    from app.notifications.telegram_bot import enqueue
    sent = 0
    for key, kwargs in list(notifications):
        try:
            enqueue(settings.telegram_chat_id, msg(key, **kwargs))
            sent += 1
        except Exception as e:
            logger.debug(f"Brain notification enqueue failed ({key}): {e}")
    notifications.clear()
    return sent


# ── Direction-aware helpers (LONG vs SHORT) ──────────────────────

def _calc_pnl_pct(entry_price: float, current_price: float, direction: str) -> float:
    """P&L percentage respecting trade direction.

    LONG:  profit when price rises   → (current - entry) / entry
    SHORT: profit when price drops   → (entry - current) / entry
    """
    if direction == "SHORT":
        return (entry_price - current_price) / entry_price * 100
    return (current_price - entry_price) / entry_price * 100


def _calc_pnl_amount(entry_price: float, current_price: float, direction: str) -> float:
    """Dollar P&L per share respecting trade direction."""
    if direction == "SHORT":
        return entry_price - current_price
    return current_price - entry_price


# Column list for any SELECT that feeds `close_virtual_trade`. If the
# helper ever needs another field, add it here in one place instead of
# updating each caller — missing a SELECT is the class of bug that
# silently skips wallet settlement or recomputes per-share math wrong.
VIRTUAL_TRADES_CLOSE_FIELDS = (
    "id, user_id, symbol, entry_price, entry_date, entry_score, source, "
    "bucket, market_regime, target_price, stop_loss, direction, trade_horizon, "
    "thesis_last_status, peak_price, trough_price, "
    "shares, position_size_usd, is_wallet_trade"
)


def _compute_wallet_fields(
    running_balance: float,
    tier: int,
    trust_multiplier: float,
    price: float,
    symbol: str,
    *,
    kind: str,
) -> tuple[float, float, dict] | None:
    """Size a new brain entry and produce the extra virtual_trades fields.

    Returns (allocation_usd, shares, wallet_fields_dict) on success, or
    None when the entry should be skipped (wallet below the floor).
    Logs the skip reason internally so both BUY and SHORT call sites
    stay symmetric — `kind` just flavors the log line.

    When `settings.wallet_enabled` is False the trade inserts as legacy
    (is_wallet_trade=False, no shares/position_size) — matches pre-Day-15
    behavior and lets ops disable the wallet without orphaning rows.
    """
    from app.services import wallet as wallet_svc

    if not settings.wallet_enabled:
        return 0.0, 0.0, {"is_wallet_trade": False}

    allocation_usd = wallet_svc.calc_position_size_usd(running_balance, tier, trust_multiplier)
    if allocation_usd <= 0:
        floor_reason = (
            "balance below minimum"
            if running_balance < settings.wallet_min_balance_for_trade
            else f"allocation at tier {tier} is < ${settings.wallet_min_balance_for_trade:.0f}"
        )
        logger.info(
            f"Virtual {kind} skipped for {symbol}: {floor_reason} "
            f"(balance=${running_balance:.2f}, tier={tier})"
        )
        return None

    shares = allocation_usd / price if price else 0.0
    return allocation_usd, shares, {
        "shares": round(shares, 6),
        "position_size_usd": round(allocation_usd, 2),
        "is_wallet_trade": True,
    }


def _mark_to_market_one(
    *,
    entry_price: float,
    current_price: float,
    direction: str,
    is_wallet_trade: bool,
    shares: float,
) -> float:
    """What is one open brain position worth in dollars right now?

    Four cases — wallet vs legacy × LONG vs SHORT — each with different
    cash semantics:
      • Wallet LONG : shares × current_price
      • Wallet SHORT: (entry − current) × shares — just the unrealized
                      P&L; the collateral lives in wallet.collateral_reserved
      • Legacy LONG : 1 × current_price (1-share implicit)
      • Legacy SHORT: entry − current (per-share P&L, no collateral)
    """
    is_short = (direction or "LONG").upper() == "SHORT"
    if is_wallet_trade:
        if is_short:
            return (entry_price - current_price) * shares
        return current_price * shares
    # Legacy 1-share implicit
    if is_short:
        return entry_price - current_price
    return current_price


def calculate_brain_holdings_value(
    user_id: str | None = None,
    *,
    legacy_only: bool = False,
    strict: bool = False,
) -> float:
    """Sum the mark-to-market value of open brain positions for the user.

    Covers wallet LONG + wallet SHORT P&L + legacy LONG + legacy SHORT P&L.
    Lives here (not in wallet.py) because this function owns virtual_trades
    schema knowledge and the price fetch.

    Args:
        legacy_only: restrict to pre-wallet 1-share positions. Used once
            per user on the FIRST deposit to snapshot the ROI baseline.
        strict: raise `LegacySnapshotFailed` if any position has no price.
            Only meaningful when legacy_only=True: we must never silently
            baseline at cash-only when legacy positions exist.
    """
    from app.services.wallet import _resolve_user_id, LegacySnapshotFailed

    uid = _resolve_user_id(user_id)
    if not uid:
        return 0.0
    try:
        db = get_client()
        query = (
            db.table("virtual_trades")
            .select("symbol, shares, entry_price, direction, is_wallet_trade")
            .eq("user_id", uid)
            .eq("status", "OPEN")
            .eq("source", "brain")
        )
        if legacy_only:
            query = query.eq("is_wallet_trade", False)
        rows = query.execute().data or []
        if not rows:
            return 0.0
        symbols = list({r["symbol"] for r in rows if r.get("symbol")})
        price_map = _fetch_prices_batch(symbols)
        total = 0.0
        missing: list[str] = []
        for r in rows:
            price_tuple = price_map.get(r["symbol"])
            price = price_tuple[0] if price_tuple else None
            if not price:
                missing.append(r["symbol"])
                continue
            total += _mark_to_market_one(
                entry_price=float(r.get("entry_price") or 0),
                current_price=float(price),
                direction=r.get("direction") or "LONG",
                is_wallet_trade=bool(r.get("is_wallet_trade")),
                shares=float(r.get("shares") or 0),
            )
        if missing and strict:
            raise LegacySnapshotFailed(
                f"Could not price {len(missing)} position(s): {', '.join(missing)}. "
                f"Refusing to baseline ROI at cash-only — retry when the price feed recovers."
            )
        return total
    except LegacySnapshotFailed:
        raise
    except Exception as e:
        if strict:
            raise LegacySnapshotFailed(f"Holdings snapshot failed: {e}") from e
        logger.warning(f"calculate_brain_holdings_value failed: {e}")
        return 0.0


def _sum_holdings_from_enriched(enriched_open: list[dict]) -> float:
    """Sum holdings from rows that already went through `_enrich_open_trade`.

    Used by `get_virtual_summary` so we don't re-SELECT virtual_trades or
    re-fetch prices for a value we just computed row-by-row. Enriched
    rows already carry `current_price`, `entry_price`, `direction`,
    `is_wallet_trade`, and (for wallet trades) `shares` +
    `current_position_value` — so we can reuse `_mark_to_market_one`.
    """
    total = 0.0
    for t in enriched_open:
        if t.get("source") != "brain":
            continue
        current_price = t.get("current_price")
        if current_price is None:
            continue
        total += _mark_to_market_one(
            entry_price=float(t.get("entry_price") or 0),
            current_price=float(current_price),
            direction=t.get("direction") or "LONG",
            is_wallet_trade=bool(t.get("is_wallet_trade")),
            shares=float(t.get("shares") or 0),
        )
    return total


def close_virtual_trade(
    trade: dict,
    exit_price: float,
    exit_reason: str,
    exit_score: int | None,
    exit_action: str | None = None,
    exit_date_iso: str | None = None,
) -> dict:
    """The one true close path: pnl math, DB UPDATE, wallet settlement, learning loop.

    Every exit site in this module and in watchdog_service funnels through
    here so the math is computed one way. Three things happen:

      1. Compute pnl_pct + direction-aware per-share dollar P&L. For wallet
         trades (is_wallet_trade=True), store TOTAL-dollar P&L (shares ×
         per-share). For legacy trades (pre-wallet), store per-share — that
         matches the historical pnl_amount semantics so existing closed
         rows remain consistent.

      2. UPDATE virtual_trades with status='CLOSED' + the close fields,
         guarded by .eq("status", "OPEN") to prevent race-condition
         overwrites (scan + watchdog running in parallel).

      3. If is_wallet_trade, settle the wallet: credit proceeds on LONG
         close, release collateral + P&L on SHORT close. The wallet layer
         writes its own audit ledger entry.

      4. Forward to the learning loop via _record_brain_outcome (best-effort).

    Args:
        trade: The loaded virtual_trades row. Must include at minimum id,
            symbol, entry_price, direction, source, and (for wallet trades)
            shares, position_size_usd, is_wallet_trade, user_id.
        exit_price: Price at which the trade is being closed.
        exit_reason: STOP_HIT, TARGET_HIT, TRAILING_STOP, SIGNAL, etc.
        exit_score: Latest signal score at close time (for telemetry).
        exit_action: Signal action that triggered this close (set only for
            SIGNAL exits — SELL, AVOID). None for price-driven closes.
        exit_date_iso: ISO timestamp to write. Defaults to now(UTC).

    Returns:
        dict with keys pnl_pct, pnl_amount_stored, is_win — so callers can
        log / notify without recomputing. Returns {"skipped": True, ...}
        when the close was suppressed (race-guard or Day-0 grace period).
    """
    # Day-0 grace period: thesis-driven exits (THESIS_INVALIDATED,
    # QUALITY_PRUNE) on a position less than 24h old are suppressed.
    # Two real cases drove this: IONQ entered Apr 23 score 79 validated,
    # thesis flipped "weakening" within hours; BCE.TO entered Apr 27
    # score 77, thesis flipped to "invalid" 90 minutes later. Both were
    # closed at small losses despite Claude validating them at entry —
    # the conservative bias re-reads fresh data through a more cautious
    # lens before the position has had a chance to develop. Price-based
    # exits (STOP, TARGET, TRAILING, TIME_EXPIRED) still fire; the
    # catastrophic stop in `_exit_is_thesis_protected` already bypasses
    # any thesis gating at -8% pnl, so a fresh entry that craters fast
    # still gets cut.
    THESIS_GATED = {"THESIS_INVALIDATED", "QUALITY_PRUNE"}
    grace_hours = settings.new_position_grace_hours
    if exit_reason in THESIS_GATED and grace_hours > 0:
        entry_dt_str = trade.get("entry_date")
        if entry_dt_str:
            try:
                entry_dt = parse_iso_utc(entry_dt_str)
                if entry_dt is not None:
                    age_hours = (datetime.now(timezone.utc) - entry_dt).total_seconds() / 3600
                    if age_hours < grace_hours:
                        logger.info(
                            f"Day-0 grace: {exit_reason} suppressed for "
                            f"{trade.get('symbol')} (age {age_hours:.1f}h < {grace_hours:.0f}h). "
                            f"Letting the fresh thesis develop."
                        )
                        return {"pnl_pct": 0, "pnl_amount_stored": 0, "is_win": False, "skipped": True}
            except Exception:
                pass

    db = get_client()
    entry_price = float(trade["entry_price"])
    direction = trade.get("direction") or "LONG"
    pnl_pct = _calc_pnl_pct(entry_price, exit_price, direction)
    per_share_pnl = _calc_pnl_amount(entry_price, exit_price, direction)
    is_win = pnl_pct > 0

    is_wallet = bool(trade.get("is_wallet_trade"))
    shares = float(trade.get("shares") or 0)
    position_size_usd = float(trade.get("position_size_usd") or 0)

    if is_wallet and shares > 0:
        # Wallet trades store TOTAL-dollar P&L so the field is meaningful
        # without needing `shares` re-joined at summary time.
        pnl_amount_stored = per_share_pnl * shares
    else:
        # Legacy 1-share trades keep per-share semantics (historical compat).
        pnl_amount_stored = per_share_pnl

    now_iso = exit_date_iso or datetime.now(timezone.utc).isoformat()

    patch: dict = {
        "status": "CLOSED",
        "exit_price": exit_price,
        "exit_date": now_iso,
        "exit_score": exit_score,
        "pnl_pct": round(pnl_pct, 2),
        "pnl_amount": round(pnl_amount_stored, 2),
        "is_win": is_win,
        "exit_reason": exit_reason,
    }
    if exit_action is not None:
        patch["exit_action"] = exit_action

    # Status guard: the .eq("status", "OPEN") here prevents this UPDATE from
    # overwriting a row that another parallel path (watchdog / rotation)
    # already closed. Belt-and-braces — without this, a race between the
    # scan SIGNAL close and a concurrent watchdog close could double-write
    # the pnl fields. Inspect the result: if no rows matched (the row was
    # already closed by another path), skip wallet settlement so we don't
    # double-credit the wallet for the same trade.
    update_result = (
        db.table("virtual_trades")
        .update(patch)
        .eq("id", trade["id"])
        .eq("status", "OPEN")
        .execute()
    )
    if not (update_result.data or []):
        logger.info(
            f"close_virtual_trade: {trade.get('symbol')} already closed "
            f"by another path ({exit_reason}) — skipping wallet + learning."
        )
        return {
            "pnl_pct": pnl_pct,
            "pnl_amount_stored": pnl_amount_stored,
            "is_win": is_win,
            "skipped": True,
        }

    # Wallet settlement routing:
    #   wallet + shares>0 → full settle (BUY/SELL/SHORT_OPEN/SHORT_COVER)
    #   brain legacy      → 1-share liquidation (LEGACY_SELL / LEGACY_COVER)
    #   watchlist         → no wallet touch
    source = trade.get("source", "")
    sym = trade["symbol"]
    user_id = trade.get("user_id")
    try:
        from app.services import wallet as wallet_svc
        if is_wallet and shares > 0:
            pnl_usd_total = per_share_pnl * shares
            if direction == "SHORT":
                wallet_svc.release_for_short_cover(
                    user_id=user_id, original_allocation_usd=position_size_usd,
                    pnl_usd=pnl_usd_total, trade_id=trade["id"], symbol=sym,
                    shares=shares, price=exit_price, exit_reason=exit_reason,
                )
            else:
                wallet_svc.credit_for_long_sell(
                    user_id=user_id, proceeds_usd=shares * exit_price,
                    pnl_usd=pnl_usd_total, trade_id=trade["id"], symbol=sym,
                    shares=shares, price=exit_price, exit_reason=exit_reason,
                )
        elif not is_wallet and source == "brain":
            # per_share_pnl IS the full cash event for a 1-share legacy.
            if direction == "SHORT":
                wallet_svc.credit_for_legacy_cover(
                    user_id=user_id, pnl_usd=per_share_pnl,
                    trade_id=trade["id"], symbol=sym, exit_reason=exit_reason,
                )
            else:
                wallet_svc.credit_for_legacy_sell(
                    user_id=user_id, exit_price=exit_price,
                    trade_id=trade["id"], symbol=sym, exit_reason=exit_reason,
                    pnl_usd=per_share_pnl,
                )
    except Exception as e:
        logger.error(
            f"Wallet settlement FAILED for {sym} ({exit_reason}, "
            f"direction={direction}, is_wallet={is_wallet}): {e}. "
            f"Row is closed; reconstruct from wallet_transactions if needed."
        )

    # Learning loop. Best-effort: the close must NEVER fail because the
    # learner had a hiccup. _record_brain_outcome is already defensive
    # about watchlist trades (no-op for non-brain).
    try:
        _record_brain_outcome(trade, exit_price, exit_score, exit_reason, pnl_pct)
    except Exception as e:
        logger.warning(f"Failed to record outcome for {trade.get('symbol')}: {e}")

    return {
        "pnl_pct": pnl_pct,
        "pnl_amount_stored": pnl_amount_stored,
        "is_win": is_win,
    }


def _is_stop_hit(current_price: float, stop_loss: float, direction: str) -> bool:
    """Check if stop loss is hit (direction-aware).

    LONG:  stop fires when price drops BELOW stop
    SHORT: stop fires when price rises ABOVE stop
    """
    if direction == "SHORT":
        return current_price >= stop_loss
    return current_price <= stop_loss


def _is_target_hit(current_price: float, target_price: float, direction: str) -> bool:
    """Check if target is hit (direction-aware).

    LONG:  target fires when price rises ABOVE target
    SHORT: target fires when price drops BELOW target
    """
    if direction == "SHORT":
        return current_price <= target_price
    return current_price >= target_price


def check_virtual_exits(notifications: BrainNotificationQueue) -> dict:
    """Close open virtual trades whose stop/target/profit-take/age conditions hit.

    This is the brain's RISK MANAGEMENT pass. It runs after `process_virtual_trades`
    on every scan. Where `process_virtual_trades` reacts to fresh SIGNALS,
    this function reacts to fresh PRICES — a position can hit its stop loss
    even if the signal hasn't changed.

    Exit conditions, checked in priority order (first match wins):

      1. STOP_HIT      — current_price <= stop_loss
                         Hard exit. The signal's reasoning is irrelevant —
                         risk management trumps thesis.

      2. TARGET_HIT    — current_price >= target_price
                         Take-profit at the planned level. Locks in the
                         signal's projected gain.

      3. PROFIT_TAKE   — pnl_pct >= 3.0% AND days_held >= 2
                         A "let it run for a couple days, then lock gains"
                         heuristic. Prevents giving back gains on signals
                         that hit a brief +3% spike before reversing.
                         Only fires if neither stop nor target tripped.

      4. TIME_EXPIRED  — days_held >= virtual_trade_max_days (config)
                         Closes positions that have been open too long
                         without hitting their target. Prevents capital
                         from sitting in stale ideas. P&L is whatever
                         it is at the time of forced exit.

    Market hours guard:
      • Equity exits are SKIPPED when the market is closed — the trade
        wouldn't fill at the cached price (which would be stale anyway).
        The next in-hours scan picks them up.
      • Crypto exits proceed regardless (24/7 markets).

    Args:
        notifications: Scan-local queue. PROFIT_TAKE exits queue a
            "brain_sell" notification. STOP_HIT, TARGET_HIT, and
            TIME_EXPIRED exits don't notify here — they log only,
            because the user has already been warned by the watchdog
            for stops and the target_hit is implied by the original
            BUY notification.

    Returns:
        Dict with counters: stops_hit, targets_hit, profit_takes, expired.
    """
    db = get_client()
    max_days = settings.virtual_trade_max_days

    open_result = (
        db.table("virtual_trades")
        .select(VIRTUAL_TRADES_CLOSE_FIELDS)
        .eq("status", "OPEN")
        .execute()
    )
    open_trades = open_result.data or []
    if not open_trades:
        return {"stops_hit": 0, "targets_hit": 0, "profit_takes": 0, "expired": 0}

    # Batch-fetch current prices
    symbols = list({t["symbol"] for t in open_trades})
    prices = _fetch_prices_batch(symbols)

    # Batch-fetch latest score + action for every open symbol (1 query
    # instead of N). QUALITY_PRUNE reads `action` to gate on "Claude
    # still wants this position"; score feeds the rollback telemetry.
    current_scores: dict[str, int] = {}
    current_actions: dict[str, str] = {}
    sig_result = (
        db.table("signals")
        .select("symbol, score, action")
        .in_("symbol", symbols)
        .order("created_at", desc=True)
        .execute()
    )
    for row in (sig_result.data or []):
        sym = row.get("symbol")
        if sym and sym not in current_scores:
            current_scores[sym] = row.get("score", 0)
            current_actions[sym] = row.get("action")

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    market_open = _is_us_market_open()
    stops_hit = 0
    targets_hit = 0
    expired = 0
    profit_takes = 0

    def _rollback_counter(reason: str) -> None:
        """Undo whichever counter was pre-incremented for this exit_reason.
        Trailing stops increment `profit_takes` in the detection block
        below — keep the two in sync or the summary log miscounts.
        Defined once here rather than per-iteration inside the loop."""
        nonlocal stops_hit, targets_hit, profit_takes, expired
        if reason == "STOP_HIT": stops_hit -= 1
        elif reason == "TARGET_HIT": targets_hit -= 1
        elif reason == "TRAILING_STOP": profit_takes -= 1
        elif reason == "TIME_EXPIRED": expired -= 1

    for trade in open_trades:
        symbol = trade["symbol"]
        entry_price = float(trade["entry_price"])
        current_price, _ = prices.get(symbol, (None, None))

        if current_price is None:
            continue

        # Equity exits (stop/target/profit-take) can't fill when market is
        # closed, and the cached price would be stale. Skip non-crypto exits
        # entirely outside market hours — the next in-hours exit check will
        # catch them. Crypto continues normally (24/7 markets).
        is_crypto = symbol.endswith("-USD")
        if not is_crypto and not market_open:
            continue

        target = float(trade["target_price"]) if trade.get("target_price") else None
        stop = float(trade["stop_loss"]) if trade.get("stop_loss") else None
        direction = trade.get("direction") or "LONG"
        horizon = trade.get("trade_horizon") or "SHORT"
        pnl_pct = _calc_pnl_pct(entry_price, current_price, direction)

        # Parse entry_date for age check
        days_held = days_since(trade.get("entry_date"), now=now)

        # ── Peak / trough tracking for trailing stop ──
        # LONG positions track peak (highest), SHORT positions track trough (lowest).
        # Updated every scan so the trailing stop ratchets in the winning direction.
        if direction == "SHORT":
            # SHORT: track lowest price (trough). Trail fires when price RISES above trough + X%.
            trough = float(trade.get("trough_price") or entry_price)
            if current_price < trough:
                trough = current_price
                try:
                    db.table("virtual_trades").update(
                        {"trough_price": trough}
                    ).eq("id", trade["id"]).execute()
                except Exception:
                    pass
            peak = entry_price  # not used for SHORT trail calc
            # SHORT trailing: active when position has been 3%+ profitable (price dropped 3%+ from entry)
            trailing_active = trough <= entry_price * 0.97
            trail_pct = settings.brain_short_trail_pct / 100
            # For shorts: trail is ABOVE trough (price rising back toward us = danger)
            soft_trail = trough * (1 + trail_pct * 0.6) if trailing_active else None
            hard_trail = trough * (1 + trail_pct) if trailing_active else None
        else:
            # LONG: track highest price (peak). Trail fires when price DROPS below peak - X%.
            peak = float(trade.get("peak_price") or entry_price)
            if current_price > peak:
                peak = current_price
                try:
                    db.table("virtual_trades").update(
                        {"peak_price": peak}
                    ).eq("id", trade["id"]).execute()
                except Exception:
                    pass
            trough = entry_price  # not used for LONG trail calc
            trailing_active = peak >= entry_price * 1.03
            if horizon == "LONG":
                soft_pct = 1.0 - settings.horizon_long_trail_pct / 100 * 0.6
                hard_pct = 1.0 - settings.horizon_long_trail_pct / 100
            else:
                soft_pct = 0.97
                hard_pct = 0.95
            # Floor at entry_price — once up 3%+, worst exit is breakeven (RRX Day 9 fix).
            soft_trail = max(peak * soft_pct, entry_price) if trailing_active else None
            hard_trail = max(peak * hard_pct, entry_price) if trailing_active else None

        thesis_status = (trade.get("thesis_last_status") or "").lower()

        # Determine exit reason (priority: stop > hard_trail > soft_trail > target > time)
        # Uses direction-aware helpers for stop/target checks.
        exit_reason = None
        if stop and _is_stop_hit(current_price, stop, direction):
            exit_reason = "STOP_HIT"
            stops_hit += 1
        elif trailing_active and direction == "SHORT" and current_price >= hard_trail:
            # SHORT hard trailing stop — price bounced back above trough + trail_pct
            exit_reason = "TRAILING_STOP"
            profit_takes += 1
            logger.info(
                f"Virtual TRAILING STOP (hard, SHORT): {symbol} at {pnl_pct:+.1f}% "
                f"(trough ${trough:.2f}, hard trail ${hard_trail:.2f}, now ${current_price:.2f})"
            )
            notifications.append(("brain_sell", {
                "symbol": symbol, "price": f"{current_price:.2f}",
                "pnl": f"{pnl_pct:+.1f}",
                "reason": f"Short trailing stop (trough ${trough:.2f}, bounced {trail_pct*100:.0f}%)",
                "entry_score": str(trade.get("entry_score", 0)),
                "exit_score": str(current_scores.get(symbol, 0)),
                "verdict": "Short trailing stop — price bouncing back, locking in gains.",
            }))
        elif trailing_active and direction != "SHORT" and current_price <= hard_trail:
            # Hard trailing stop — always fires, no thesis check.
            # 5% from peak means something real is happening.
            exit_reason = "TRAILING_STOP"
            profit_takes += 1
            logger.info(
                f"Virtual TRAILING STOP (hard): {symbol} at {pnl_pct:+.1f}% "
                f"(peak ${peak:.2f}, hard trail ${hard_trail:.2f}, now ${current_price:.2f})"
            )
            notifications.append(("brain_sell", {
                "symbol": symbol, "price": f"{current_price:.2f}",
                "pnl": f"{pnl_pct:+.1f}",
                "reason": f"Trailing stop (peak ${peak:.2f}, dropped 5% — hard exit)",
                "entry_score": str(trade.get("entry_score", 0)),
                "exit_score": str(current_scores.get(symbol, 0)),
                "verdict": "Hard trailing stop fired — 5% drop from peak.",
            }))
        elif trailing_active and soft_trail is not None and (
            (direction == "SHORT" and current_price >= soft_trail)
            or (direction != "SHORT" and current_price <= soft_trail)
        ):
            # Soft trailing stop — thesis-gated.
            # If thesis is valid, this is just noise. Hold.
            # If thesis is weakening/invalid, price confirms — exit.
            ref_label = f"trough ${trough:.2f}" if direction == "SHORT" else f"peak ${peak:.2f}"
            if thesis_status == "valid":
                logger.info(
                    f"Virtual TRAILING STOP suppressed for {symbol} — thesis still valid "
                    f"({ref_label}, soft trail ${soft_trail:.2f}, now ${current_price:.2f}, "
                    f"P&L {pnl_pct:+.1f}%). Holding through noise."
                )
            else:
                exit_reason = "TRAILING_STOP"
                profit_takes += 1
                logger.info(
                    f"Virtual TRAILING STOP (soft, thesis={thesis_status}): {symbol} at {pnl_pct:+.1f}% "
                    f"({ref_label}, soft trail ${soft_trail:.2f}, now ${current_price:.2f})"
                )
                notifications.append(("brain_sell", {
                    "symbol": symbol, "price": f"{current_price:.2f}",
                    "pnl": f"{pnl_pct:+.1f}",
                    "reason": f"Trailing stop ({ref_label}, thesis {thesis_status})",
                    "entry_score": str(trade.get("entry_score", 0)),
                    "exit_score": str(current_scores.get(symbol, 0)),
                    "verdict": f"Thesis was {thesis_status}, price move confirmed — locked in gains.",
                }))
        elif target and _is_target_hit(current_price, target, direction):
            # Suppress TARGET_HIT for young, winning positions — let the
            # trailing stop manage the exit instead. After 7 days, the
            # fixed target fires to close the trade.
            if days_held < 7 and pnl_pct > 3.0 and trailing_active:
                logger.info(
                    f"Virtual TARGET_HIT suppressed for {symbol} — "
                    f"held {days_held}d, P&L {pnl_pct:+.1f}%, trailing stop active "
                    f"(letting winner run, trail at ${soft_trail:.2f})"
                )
                continue  # skip this exit, trailing stop will manage
            exit_reason = "TARGET_HIT"
            targets_hit += 1
        elif days_held >= (
            settings.brain_short_expiry_days if direction == "SHORT"
            else settings.horizon_long_expiry_days if (trade.get("trade_horizon") or "SHORT") == "LONG"
            else settings.horizon_short_expiry_days
        ):
            exit_reason = "TIME_EXPIRED"
            expired += 1

        # ── Quality prune: cut bad entries early ──
        # If no price-based exit triggered, check if this position is
        # dead weight that should be freed up. A portfolio manager
        # wouldn't hold a losing position with a deteriorating thesis
        # for 30 days waiting for the stop — they'd cut it early and
        # redeploy the slot.
        #
        # Conditions (ALL must be true):
        #   • No other exit triggered (stop/trail/target didn't fire)
        #   • Position is DOWN from entry (pnl < 0)
        #   • Held 2-7 days (give it a chance, but don't wait forever)
        #   • Claude's latest signal is NOT BUY (the AI doesn't want it)
        #   • Thesis is weakening or invalid (the reason is degrading)
        #
        # This catches: BLK -1.40% (day 1, Claude=HOLD, bearish),
        # VZ -1.80% (day 1, Claude=HOLD, falling knife). It does NOT
        # catch positions with valid thesis or positions Claude still
        # likes — those deserve time to play out.
        # LONG positions skip quality prune — they're held for the trend,
        # not for short-term score confirmation. Only thesis=invalid or
        # the hard stop closes a LONG position early.
        if not exit_reason and trade.get("source") == "brain" and horizon != "LONG":
            latest_action = current_actions.get(symbol)

            # Magnitude gate: only prune when the loss is meaningful.
            # Without this, the rule fires on −0.5% drawdowns that would
            # likely recover, locking in trivial losses + churning slots.
            # Threshold mirrors the trailing-stop activation (3% from
            # entry) — symmetric: positions up 3% start ratcheting trails,
            # positions down 3% start being pruned. See
            # `brain_quality_prune_min_loss_pct` in config.
            if (
                pnl_pct < -settings.brain_quality_prune_min_loss_pct
                and 2 <= days_held <= 7
                and thesis_status in ("weakening", "invalid", "")
                and latest_action in ("HOLD", "AVOID", "SELL", None)
            ):
                exit_reason = "QUALITY_PRUNE"
                logger.info(
                    f"Virtual QUALITY PRUNE: {symbol} at {pnl_pct:+.1f}% "
                    f"(held {days_held}d, thesis={thesis_status or 'none'}, "
                    f"latest_action={latest_action}) — freeing slot for better pick"
                )
                notifications.append(("brain_sell", {
                    "symbol": symbol, "price": f"{current_price:.2f}",
                    "pnl": f"{pnl_pct:+.1f}",
                    "reason": f"Quality prune (thesis {thesis_status or 'none'}, {days_held}d held)",
                    "entry_score": str(trade.get("entry_score", 0)),
                    "exit_score": str(current_scores.get(symbol, 0)),
                    "verdict": "Position underperforming with deteriorating thesis — slot freed for stronger pick.",
                }))

        # ── STAGNATION_PRUNE: LONG/LONG dead-capital detection (Day 14) ──
        # Targets REGN-type holds: week+ with no meaningful movement and the
        # thesis drifting weakening/invalid. Distinct from QUALITY_PRUNE
        # (which needs pnl < 0 and days 2-7) — this catches the flat dead
        # trades that sit in a slot producing ~0% for weeks. Preserves real
        # LONG winners by requiring |pnl| < 2% (winners up 3%+ don't match).
        if (
            not exit_reason
            and trade.get("source") == "brain"
            and direction == "LONG"
            and horizon == "LONG"
            and days_held >= settings.brain_stagnation_min_days
            and abs(pnl_pct) < settings.brain_stagnation_pnl_range_pct
            and thesis_status in ("weakening", "invalid")
        ):
            exit_reason = "STAGNATION_PRUNE"
            logger.info(
                f"Virtual STAGNATION PRUNE: {symbol} at {pnl_pct:+.2f}% "
                f"(held {days_held}d, thesis={thesis_status}, "
                f"|pnl| < {settings.brain_stagnation_pnl_range_pct}% for a week+) — "
                f"dead capital, freeing slot"
            )
            notifications.append(("brain_sell", {
                "symbol": symbol, "price": f"{current_price:.2f}",
                "pnl": f"{pnl_pct:+.2f}",
                "reason": f"Stagnation prune (held {days_held}d, thesis {thesis_status}, no meaningful movement)",
                "entry_score": str(trade.get("entry_score", 0)),
                "exit_score": str(current_scores.get(symbol, 0)),
                "verdict": "Position has gone nowhere for a week+ with deteriorating thesis — freeing slot for something that moves.",
            }))

        if not exit_reason:
            continue

        # Stage 6 gate: if the thesis is still valid, suppress this
        # price-based exit as noise. The catastrophic carve-out at
        # settings.brain_thesis_hard_stop_pct still fires unconditionally.
        # Only applied to brain trades (watchlist track is exploratory
        # and doesn't carry a thesis).
        if trade.get("source") == "brain" and _exit_is_thesis_protected(trade, exit_reason, pnl_pct):
            logger.info(
                f"Virtual {exit_reason} SUPPRESSED for {symbol} — thesis still valid "
                f"(P&L {pnl_pct:+.1f}%, holding through the noise)"
            )
            _rollback_counter(exit_reason)
            continue

        is_win = pnl_pct > 0
        source = trade.get("source", "watchlist")
        exit_score = current_scores.get(symbol)

        # Route through close_virtual_trade — wallet settlement, learning
        # loop, and DB update all happen in one place. The pnl_pct used
        # above for thesis gating is the same per-share % the helper
        # computes internally. If the row was closed by another path
        # between our SELECT and the UPDATE, the helper returns
        # skipped=True and we roll back the counter we pre-incremented.
        close_res = close_virtual_trade(
            trade, current_price, exit_reason, exit_score,
            exit_date_iso=now_iso,
        )
        if close_res.get("skipped"):
            _rollback_counter(exit_reason)
            continue

        emoji = "✅" if is_win else "❌"
        logger.info(
            f"Virtual EXIT [{source}]: {emoji} {symbol} @ ${current_price:.2f} "
            f"(entry ${entry_price:.2f}, P&L {pnl_pct:+.1f}%, reason={exit_reason}, exit_score={exit_score})"
        )

    total = stops_hit + targets_hit + profit_takes + expired
    if total:
        logger.info(f"Virtual exits: {stops_hit} stops, {targets_hit} targets, {profit_takes} profit takes, {expired} expired")

    return {"stops_hit": stops_hit, "targets_hit": targets_hit, "profit_takes": profit_takes, "expired": expired}


_vp_cache = TTLCache(max_size=2, default_ttl=300)


@with_retry
def get_brain_tier_breakdown() -> dict:
    """Get brain trade performance broken down by entry tier.

    Returns counts, win rate, and avg P&L for each tier (1=validated,
    2=low_confidence, 3=tech_only). Includes both open and closed trades.
    Cached for 5 minutes.

    Returns:
        {
            "tiers": [
                {
                    "tier": 1,
                    "label": "Validated",
                    "trust_pct": 100,
                    "open_count": int,
                    "closed_count": int,
                    "win_rate": float (0-1),
                    "avg_pnl_pct": float,
                    "best_pnl_pct": float | None,
                    "worst_pnl_pct": float | None,
                },
                ...
            ],
            "total_brain_trades": int,
            "trades_with_tier": int,
        }
    """
    cached = _vp_cache.get("tier_breakdown")
    if cached is not None:
        return cached

    db = get_client()
    try:
        result = (
            db.table("virtual_trades")
            .select("entry_tier, status, is_win, pnl_pct")
            .eq("source", "brain")
            .execute()
        )
        rows = result.data or []
    except Exception as e:
        logger.warning(f"Failed to fetch tier breakdown: {e}")
        return {"tiers": [], "total_brain_trades": 0, "trades_with_tier": 0}

    tier_meta = {
        1: {"label": "Validated AI", "trust_pct": 100},
        2: {"label": "Low Confidence", "trust_pct": 50},
        3: {"label": "Tech-Only Confirmed", "trust_pct": 50},
    }

    # Bucket rows by tier
    by_tier: dict[int, dict] = {
        1: {"open": 0, "closed": [], "wins": 0},
        2: {"open": 0, "closed": [], "wins": 0},
        3: {"open": 0, "closed": [], "wins": 0},
    }
    trades_with_tier = 0
    for row in rows:
        tier = row.get("entry_tier")
        if tier not in (1, 2, 3):
            continue
        trades_with_tier += 1
        if row.get("status") == "OPEN":
            by_tier[tier]["open"] += 1
        else:
            pnl = row.get("pnl_pct")
            if pnl is not None:
                by_tier[tier]["closed"].append(float(pnl))
            if row.get("is_win"):
                by_tier[tier]["wins"] += 1

    tiers_out = []
    for tier_num in (1, 2, 3):
        bucket = by_tier[tier_num]
        closed_count = len(bucket["closed"])
        win_rate = (bucket["wins"] / closed_count) if closed_count > 0 else 0.0
        avg_pnl = (sum(bucket["closed"]) / closed_count) if closed_count > 0 else 0.0
        best = max(bucket["closed"]) if bucket["closed"] else None
        worst = min(bucket["closed"]) if bucket["closed"] else None
        tiers_out.append({
            "tier": tier_num,
            "label": tier_meta[tier_num]["label"],
            "trust_pct": tier_meta[tier_num]["trust_pct"],
            "open_count": bucket["open"],
            "closed_count": closed_count,
            "win_rate": round(win_rate, 4),
            "avg_pnl_pct": round(avg_pnl, 2),
            "best_pnl_pct": round(best, 2) if best is not None else None,
            "worst_pnl_pct": round(worst, 2) if worst is not None else None,
        })

    summary = {
        "tiers": tiers_out,
        "total_brain_trades": len(rows),
        "trades_with_tier": trades_with_tier,
    }
    _vp_cache.set("tier_breakdown", summary, ttl=300)
    return summary


def get_virtual_summary() -> dict:
    """Get virtual portfolio performance summary for the dashboard.

    Includes live P&L for open positions via current price fetch.
    Cached for 5 minutes to avoid repeated DB + price queries on every page load.
    """
    cached = _vp_cache.get("summary")
    if cached is not None:
        return cached

    db = get_client()

    # All trades. Wallet fields (shares, position_size_usd, is_wallet_trade)
    # are pulled so the frontend can render "6.06 shares @ $164.96 ($1,000
    # invested)" and distinguish wallet trades from legacy 1-share rows.
    open_result = (
        db.table("virtual_trades")
        .select("symbol, entry_price, entry_date, entry_score, bucket, signal_style, source, "
                "target_price, stop_loss, thesis_last_status, tier_reason, trade_horizon, "
                "direction, consecutive_avoid_count, "
                "shares, position_size_usd, is_wallet_trade")
        .eq("status", "OPEN")
        .order("entry_date", desc=True)
        .execute()
    )
    open_trades = open_result.data or []

    closed_result = (
        db.table("virtual_trades")
        .select("symbol, entry_price, exit_price, pnl_pct, pnl_amount, is_win, "
                "entry_date, exit_date, entry_score, exit_score, bucket, source, exit_reason, "
                "peak_price, entry_thesis, thesis_last_reason, tier_reason, trade_horizon, direction, "
                "shares, position_size_usd, is_wallet_trade")
        .eq("status", "CLOSED")
        .order("exit_date", desc=True)
        .limit(50)
        .execute()
    )
    closed_trades = closed_result.data or []

    # Fetch current prices for open positions
    now = datetime.now(timezone.utc)
    current_prices = {}
    signal_context = {}
    if open_trades:
        symbols = list({t["symbol"] for t in open_trades})
        price_data = _fetch_prices_batch(symbols)
        current_prices = {sym: p for sym, (p, _) in price_data.items() if p is not None}

        # Batch fetch latest signal context for all open symbols (1 query instead of N)
        sig_result = (
            db.table("signals")
            .select("symbol, score, reasoning, risk_reward, signal_style, contrarian_score, market_regime")
            .in_("symbol", symbols)
            .order("created_at", desc=True)
            .execute()
        )
        for row in (sig_result.data or []):
            sym = row.get("symbol")
            if sym and sym not in signal_context:
                signal_context[sym] = row

    def _build_exit_context(t: dict) -> str:
        """Build a one-line human-readable explanation of why a trade was closed."""
        reason = t.get("exit_reason", "")
        peak = t.get("peak_price")
        entry = float(t.get("entry_price") or 0)
        exit_px = float(t.get("exit_price") or 0)
        thesis_reason = t.get("thesis_last_reason") or ""

        if reason == "TRAILING_STOP" and peak:
            peak_pnl = ((float(peak) - entry) / entry * 100) if entry else 0
            drop_pct = ((float(peak) - exit_px) / float(peak) * 100) if float(peak) else 0
            thesis = t.get("thesis_last_status") or "unknown"
            return (
                f"Peak ${float(peak):.2f} (+{peak_pnl:.1f}%), dropped {drop_pct:.1f}% from peak. "
                f"Thesis was {thesis} — {'price drop confirmed weakness' if thesis != 'valid' else 'hard safety net triggered'}"
            )
        if reason == "TARGET_HIT":
            target = t.get("target_price")
            return f"Hit target ${float(target):.2f}" if target else "Hit AI-generated target"
        if reason == "STOP_HIT":
            stop = t.get("stop_loss")
            return f"Hit stop loss ${float(stop):.2f}" if stop else "Hit stop loss"
        if reason == "THESIS_INVALIDATED":
            snippet = thesis_reason[:120].strip()
            return f"Thesis invalidated: {snippet}" if snippet else "Thesis invalidated by Stage 6 re-eval"
        if reason == "WATCHDOG_EXIT":
            snippet = thesis_reason[:120].strip()
            return f"Watchdog: bearish sentiment + price drop" + (f". {snippet}" if snippet else "")
        if reason == "TIME_EXPIRED":
            return "Held maximum 30 days without hitting target or stop"
        if reason == "QUALITY_PRUNE":
            thesis = t.get("thesis_last_status") or "none"
            return f"Pruned: losing position with {thesis} thesis — slot freed for a stronger pick"
        if reason == "STAGNATION_PRUNE":
            thesis = t.get("thesis_last_status") or "none"
            return f"Stagnation prune: held a week+ with no meaningful movement and {thesis} thesis — dead capital, slot freed"
        if reason == "ROTATION":
            return "Rotated out for a stronger candidate"
        return reason or "Unknown"

    def _calc_stats(trades: list[dict]) -> dict:
        # pnl_amount semantics depend on is_wallet_trade: wallet trades
        # store TOTAL dollars, legacy trades store per-share. Summing
        # across the mix is apples-and-oranges, so the two totals are
        # reported separately. The frontend picks whichever is non-zero
        # or renders both when migration populations coexist.
        #
        # ⚠ Day-21 deprecation: `total_return_pct` below sums per-trade
        # pnl_pct values, which is mathematically meaningless because each
        # trade has a different cost basis. Example: -10% on $1k + +5% on
        # $500 = sum of -5% but actual dollar net is $-75 vs $25k portfolio
        # = -0.3%. The field is kept for backwards compat but the frontend
        # no longer surfaces it as "Total Return" — that role has moved to
        # `wallet.roi_pct` (mark-to-market portfolio vs initial capital)
        # and `avg_return_pct` (per-trade arithmetic mean) as fallback.
        # DO NOT add new consumers of `total_return_pct`. Use one of:
        #   - wallet.roi_pct          (true return on capital, includes unrealized)
        #   - avg_return_pct          (mean of per-trade pnl_pct, defined here)
        #   - total_pnl_amount_wallet (raw realized $ for wallet trades)
        total = len(trades)
        wins = sum(1 for t in trades if t.get("is_win"))
        win_rate = (wins / total * 100) if total > 0 else 0
        avg_ret = sum(t.get("pnl_pct", 0) for t in trades) / total if total else 0
        total_ret = sum(t.get("pnl_pct", 0) for t in trades)
        wallet_trades = [t for t in trades if t.get("is_wallet_trade")]
        legacy_trades = [t for t in trades if not t.get("is_wallet_trade")]
        total_pnl_amount_wallet = sum(t.get("pnl_amount") or 0 for t in wallet_trades)
        total_pnl_amount_legacy = sum(t.get("pnl_amount") or 0 for t in legacy_trades)
        best = max(trades, key=lambda t: t.get("pnl_pct", 0)) if trades else None
        worst = min(trades, key=lambda t: t.get("pnl_pct", 0)) if trades else None
        return {
            "closed_count": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": round(win_rate, 1),
            "avg_return_pct": round(avg_ret, 2),
            "total_return_pct": round(total_ret, 2),
            "wallet_closed_count": len(wallet_trades),
            "legacy_closed_count": len(legacy_trades),
            "total_pnl_amount_wallet": round(total_pnl_amount_wallet, 2),
            "total_pnl_amount_legacy": round(total_pnl_amount_legacy, 2),
            "best_trade": {"symbol": best["symbol"], "pnl_pct": best["pnl_pct"], "pnl_amount": best.get("pnl_amount")} if best else None,
            "worst_trade": {"symbol": worst["symbol"], "pnl_pct": worst["pnl_pct"], "pnl_amount": worst.get("pnl_amount")} if worst else None,
        }

    def _enrich_open_trade(t: dict) -> dict:
        symbol = t["symbol"]
        entry_price = float(t["entry_price"])
        current = current_prices.get(symbol)

        # Calculate days held
        days_held = days_since(t.get("entry_date"), now=now)

        # Get signal reasoning (why the brain picked this)
        sig = signal_context.get(symbol, {})

        is_wallet = bool(t.get("is_wallet_trade"))
        shares_open = float(t.get("shares") or 0)
        position_size_usd = float(t.get("position_size_usd") or 0)

        enriched = {
            "symbol": symbol,
            "entry_price": entry_price,
            "entry_score": t.get("entry_score"),
            "bucket": t.get("bucket"),
            "source": t.get("source", "watchlist"),
            "signal_style": t.get("signal_style") or sig.get("signal_style"),
            "target_price": t.get("target_price"),
            "stop_loss": t.get("stop_loss"),
            "days_held": days_held,
            "current_score": sig.get("score"),
            "reasoning": sig.get("reasoning"),
            "risk_reward": sig.get("risk_reward"),
            "contrarian_score": sig.get("contrarian_score"),
            "market_regime": sig.get("market_regime"),
            "thesis_status": t.get("thesis_last_status"),  # valid/weakening/invalid/None
            "tier_reason": t.get("tier_reason"),
            "trade_horizon": t.get("trade_horizon") or "SHORT",
            "direction": t.get("direction") or "LONG",
            "consecutive_avoid_count": t.get("consecutive_avoid_count") or 0,
            # Wallet metadata — frontend uses these to render "6.06 shares
            # @ $164.96 ($1,000 invested)" rows and to distinguish wallet
            # trades from legacy 1-share holdings with a subtle badge.
            "is_wallet_trade": is_wallet,
            "shares": round(shares_open, 6) if shares_open else None,
            "position_size_usd": round(position_size_usd, 2) if position_size_usd else None,
        }

        if current:
            _d = t.get("direction") or "LONG"
            pnl_pct = _calc_pnl_pct(entry_price, current, _d)
            per_share_pnl = _calc_pnl_amount(entry_price, current, _d)
            enriched["current_price"] = round(current, 2)
            enriched["unrealized_pnl_pct"] = round(pnl_pct, 2)
            # For wallet trades, unrealized_pnl_amount is TOTAL dollars so
            # the UI can show "+$42.15" without re-deriving shares. For
            # legacy trades it stays per-share (1 implicit share).
            if is_wallet and shares_open > 0:
                enriched["unrealized_pnl_amount"] = round(per_share_pnl * shares_open, 2)
                enriched["current_position_value"] = round(current * shares_open, 2)
            else:
                enriched["unrealized_pnl_amount"] = round(per_share_pnl, 2)

        return enriched

    # Enrich open trades with live P&L
    enriched_open = [_enrich_open_trade(t) for t in open_trades]

    # Calculate aggregate unrealized P&L per source
    def _unrealized_agg(trades: list[dict]) -> float:
        pnls = [t.get("unrealized_pnl_pct", 0) for t in trades if "unrealized_pnl_pct" in t]
        return round(sum(pnls) / len(pnls), 2) if pnls else 0

    # Split by source
    watchlist_open_enriched = [t for t in enriched_open if t.get("source") == "watchlist"]
    brain_open_enriched = [t for t in enriched_open if t.get("source") == "brain"]
    watchlist_closed = [t for t in closed_trades if t.get("source") == "watchlist"]
    brain_closed = [t for t in closed_trades if t.get("source") == "brain"]

    # Wallet summary (Day 15). Sum Holdings from the rows we already
    # enriched — reuses the price batch + per-trade math that
    # `_enrich_open_trade` just did, instead of kicking off a second
    # virtual_trades SELECT + price fetch through the wallet service.
    try:
        from app.services import wallet as wallet_svc
        open_positions_value = _sum_holdings_from_enriched(enriched_open)
        wallet_summary_dict = wallet_svc.wallet_summary(
            user_id=None,  # default to brain user
            open_positions_value=open_positions_value,
        )
    except Exception as e:
        logger.warning(f"Wallet summary failed: {e}")
        wallet_summary_dict = None

    result = {
        "open_count": len(open_trades),
        "open_trades": enriched_open,
        # Combined stats
        **_calc_stats(closed_trades),
        "recent_closed": [
            {
                "symbol": t["symbol"],
                "pnl_pct": t["pnl_pct"],
                "pnl_amount": t.get("pnl_amount"),
                "is_win": t["is_win"],
                "source": t.get("source", "watchlist"),
                "exit_reason": t.get("exit_reason"),
                "entry_score": t.get("entry_score"),
                "exit_score": t.get("exit_score"),
                # Frontend (brain/performance page) renders
                # "entry_date entry_price → exit_date exit_price"
                # under each closed-trade row. These fields are already
                # loaded by the SELECT above; omitting them here is what
                # made the UI render dashes instead of actual values.
                "entry_date": t.get("entry_date"),
                "exit_date": t.get("exit_date"),
                "entry_price": t.get("entry_price"),
                "exit_price": t.get("exit_price"),
                "peak_price": t.get("peak_price"),
                "exit_context": _build_exit_context(t),
                # Day 26: full entry/exit reasoning for the inline detail
                # panel on the closed-trade row. entry_thesis was the
                # synthesis Claude wrote at insert time; thesis_last_reason
                # is the most recent thesis re-eval explanation. Together
                # they answer "why bought" and "why sold". Truncate at
                # 800 chars each to keep payload bounded — full text is
                # available in DB if needed.
                "entry_thesis": (t.get("entry_thesis") or "")[:800],
                "thesis_last_reason": (t.get("thesis_last_reason") or "")[:800],
                "trade_horizon": t.get("trade_horizon") or "SHORT",
                "direction": t.get("direction") or "LONG",
                # Wallet metadata so the UI can render "$1,000 invested,
                # +$42 realized" for wallet closes vs legacy per-share rows.
                "is_wallet_trade": bool(t.get("is_wallet_trade")),
                "shares": t.get("shares"),
                "position_size_usd": t.get("position_size_usd"),
            }
            # Send all closed trades fetched (DB query above is `.limit(50)`).
            # The performance page paginates client-side in batches of 5 via
            # a "Load more" button; the dashboard widget slices its own view.
            for t in closed_trades
        ],
        # Per-source breakdown
        "watchlist": {
            "open_count": len(watchlist_open_enriched),
            "avg_unrealized_pnl_pct": _unrealized_agg(watchlist_open_enriched),
            **_calc_stats(watchlist_closed),
        },
        "brain": {
            "open_count": len(brain_open_enriched),
            "avg_unrealized_pnl_pct": _unrealized_agg(brain_open_enriched),
            **_calc_stats(brain_closed),
        },
        # Watchdog summary
        "watchdog": _get_watchdog_summary(db, len(brain_open_enriched)),
        # Wallet state (Day 15) — balance, collateral, total_value, ROI.
        # None when the wallet module failed or no users exist. UI should
        # hide the wallet card gracefully in that case.
        "wallet": wallet_summary_dict,
    }

    _vp_cache.set("summary", result)
    return result


def _get_watchdog_summary(db, positions_monitored: int) -> dict:
    """Get watchdog status for the dashboard."""
    try:
        recent = (
            db.table("watchdog_events")
            .select("symbol, event_type, created_at")
            .order("created_at", desc=True)
            .limit(5)
            .execute()
        )
        return {
            "active": settings.watchdog_enabled,
            "positions_monitored": positions_monitored,
            "recent_events": recent.data or [],
        }
    except Exception as e:
        logger.warning(f"Watchdog summary query failed: {e}")
        return {"active": settings.watchdog_enabled, "positions_monitored": positions_monitored, "recent_events": []}


@with_retry
def get_virtual_charts() -> dict:
    """Get chart data for the brain performance page.

    Returns pre-computed data structures the frontend can render directly.
    Cached for 5 minutes to avoid repeated DB queries on every page load.
    """
    cached = _vp_cache.get("charts")
    if cached is not None:
        return cached

    db = get_client()

    # All closed trades for charts
    result = (
        db.table("virtual_trades")
        .select("symbol, entry_price, exit_price, pnl_pct, is_win, entry_date, exit_date, "
                "entry_score, bucket, source, exit_reason, signal_style")
        .eq("status", "CLOSED")
        .order("exit_date", desc=True)
        .limit(200)
        .execute()
    )
    closed = result.data or []

    if not closed:
        return {
            "pnl_by_bucket": [],
            "monthly_returns": [],
            "exit_reasons": [],
            "score_vs_pnl": [],
            "win_rate_over_time": [],
        }

    # 1. P&L by bucket (brain vs watchlist, SAFE_INCOME vs HIGH_RISK)
    bucket_groups: dict[str, dict] = {}
    for t in closed:
        key = f"{t.get('source', 'watchlist')}_{t.get('bucket', 'UNKNOWN')}"
        if key not in bucket_groups:
            bucket_groups[key] = {"source": t.get("source"), "bucket": t.get("bucket"), "trades": 0, "total_pnl": 0, "wins": 0}
        bucket_groups[key]["trades"] += 1
        bucket_groups[key]["total_pnl"] += t.get("pnl_pct", 0)
        if t.get("is_win"):
            bucket_groups[key]["wins"] += 1

    pnl_by_bucket = [
        {
            "source": v["source"],
            "bucket": v["bucket"],
            "trades": v["trades"],
            "total_pnl_pct": round(v["total_pnl"], 2),
            "avg_pnl_pct": round(v["total_pnl"] / v["trades"], 2) if v["trades"] else 0,
            "win_rate": round(v["wins"] / v["trades"] * 100, 1) if v["trades"] else 0,
        }
        for v in bucket_groups.values()
    ]

    # 2. Monthly returns (brain track)
    brain_closed = [t for t in closed if t.get("source") == "brain"]
    monthly: dict[str, dict] = {}
    for t in brain_closed:
        exit_date = t.get("exit_date", "")
        if not exit_date:
            continue
        month_key = exit_date[:7]  # "2026-04"
        if month_key not in monthly:
            monthly[month_key] = {"month": month_key, "trades": 0, "total_pnl": 0, "wins": 0}
        monthly[month_key]["trades"] += 1
        monthly[month_key]["total_pnl"] += t.get("pnl_pct", 0)
        if t.get("is_win"):
            monthly[month_key]["wins"] += 1

    monthly_returns = sorted([
        {
            "month": v["month"],
            "trades": v["trades"],
            "total_pnl_pct": round(v["total_pnl"], 2),
            "avg_pnl_pct": round(v["total_pnl"] / v["trades"], 2) if v["trades"] else 0,
            "win_rate": round(v["wins"] / v["trades"] * 100, 1) if v["trades"] else 0,
        }
        for v in monthly.values()
    ], key=lambda x: x["month"])

    # 3. Exit reasons distribution
    reason_counts: dict[str, int] = {}
    for t in closed:
        reason = t.get("exit_reason", "SIGNAL") or "SIGNAL"
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    exit_reasons = [
        {"reason": reason, "count": count, "pct": round(count / len(closed) * 100, 1)}
        for reason, count in sorted(reason_counts.items())
    ]

    # 4. Score vs P&L scatter (for all closed trades)
    score_vs_pnl = [
        {
            "symbol": t["symbol"],
            "entry_score": t.get("entry_score"),
            "pnl_pct": t.get("pnl_pct"),
            "source": t.get("source"),
            "bucket": t.get("bucket"),
        }
        for t in closed
        if t.get("entry_score") is not None and t.get("pnl_pct") is not None
    ]

    # 5. Rolling win rate (last N trades, window of 10)
    win_rate_over_time = []
    # Reverse to chronological order
    chronological = list(reversed(closed))
    window = 10
    for i in range(window - 1, len(chronological)):
        batch = chronological[i - window + 1: i + 1]
        wins = sum(1 for t in batch if t.get("is_win"))
        trade = chronological[i]
        win_rate_over_time.append({
            "trade_num": i + 1,
            "symbol": trade.get("symbol"),
            "exit_date": trade.get("exit_date", "")[:10],
            "win_rate": round(wins / window * 100, 1),
        })

    result = {
        "pnl_by_bucket": pnl_by_bucket,
        "monthly_returns": monthly_returns,
        "exit_reasons": exit_reasons,
        "score_vs_pnl": score_vs_pnl,
        "win_rate_over_time": win_rate_over_time,
    }

    _vp_cache.set("charts", result)
    return result


def snapshot_virtual_portfolio() -> dict:
    """Take a daily snapshot of portfolio state for the equity curve.

    Call once per day (after the last scan). Upserts by snapshot_date.
    """
    db = get_client()
    summary = get_virtual_summary()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Get cumulative closed P&L (all time)
    all_closed = (
        db.table("virtual_trades")
        .select("pnl_pct, source")
        .eq("status", "CLOSED")
        .execute()
    )
    all_closed_data = all_closed.data or []
    brain_cum = sum(t.get("pnl_pct", 0) for t in all_closed_data if t.get("source") == "brain")
    watchlist_cum = sum(t.get("pnl_pct", 0) for t in all_closed_data if t.get("source") == "watchlist")

    # Fetch SPY price for benchmark
    spy_data = _fetch_prices_batch(["SPY"])
    spy_price, _ = spy_data.get("SPY", (None, None))

    snapshot = {
        "snapshot_date": today,
        "brain_open": summary.get("brain", {}).get("open_count", 0),
        "brain_unrealized_pnl": summary.get("brain", {}).get("avg_unrealized_pnl_pct", 0),
        "brain_cumulative_pnl": round(brain_cum, 2),
        "watchlist_open": summary.get("watchlist", {}).get("open_count", 0),
        "watchlist_unrealized_pnl": summary.get("watchlist", {}).get("avg_unrealized_pnl_pct", 0),
        "watchlist_cumulative_pnl": round(watchlist_cum, 2),
        "spy_price": spy_price,
    }

    # Upsert by snapshot_date
    db.table("virtual_snapshots").upsert(snapshot, on_conflict="snapshot_date").execute()
    logger.info(f"Virtual snapshot saved for {today}: brain_cum={brain_cum:+.1f}%, watchlist_cum={watchlist_cum:+.1f}%")

    return snapshot
