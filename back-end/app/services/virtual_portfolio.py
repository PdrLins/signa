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
      • score >= 72  (BRAIN_MIN_SCORE)
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

BRAIN_MIN_SCORE = 72
"""Tier 1 floor — validated AI signals must clear this score to be bought.
Backtest shows 60.6% win rate at 72+ for SAFE_INCOME, 52.6% for HIGH_RISK."""

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
    if pnl_pct <= settings.brain_thesis_hard_stop_pct:
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
    open_result = (
        db.table("virtual_trades")
        .select("id, symbol, entry_price, entry_date, entry_score, source, "
                "pending_review_at, thesis_last_status, "
                # bucket + market_regime + target_price + stop_loss are
                # required by _record_brain_outcome so that SIGNAL and
                # ROTATION exits write correct trade_outcomes rows and
                # the learning loop can match (bucket, regime) patterns.
                # Missing any of these silently corrupts pattern_stats data.
                "bucket, market_regime, target_price, stop_loss")
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
    open_brain: set[str] = set()
    brain_open_count = 0
    brain_entry_prices: list[float] = []
    for r in all_open:
        if r.get("source") == "brain":
            open_brain.add(r["symbol"])
            brain_open_count += 1
            brain_entry_prices.append(float(r.get("entry_price", 0)))
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

    # Factor 1: Portfolio unrealized P&L (do we have gains to protect?)
    if brain_entry_prices and brain_open_count >= 3:
        brain_symbols = [r["symbol"] for r in all_open if r.get("source") == "brain"]
        brain_prices = _fetch_prices_batch(brain_symbols)
        total_unrealized = 0.0
        priced_count = 0
        for r in all_open:
            if r.get("source") != "brain":
                continue
            px, _ = brain_prices.get(r["symbol"], (None, None))
            ep = float(r.get("entry_price", 0))
            if px and ep > 0:
                total_unrealized += ((px - ep) / ep) * 100
                priced_count += 1
        avg_unrealized = total_unrealized / priced_count if priced_count else 0
        if avg_unrealized > 2.0:  # avg position is up >2% — meaningful gains
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
            f"positions={brain_open_count}, avg_pnl={avg_unrealized if brain_entry_prices else 0:+.1f}%, "
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

    now = datetime.now(timezone.utc).isoformat()
    market_open = _is_us_market_open()

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
                pnl_pct = ((price - entry_price) / entry_price) * 100
                pnl_amount = price - entry_price
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

                # Status guard: the .eq("status", "OPEN") prevents this UPDATE
                # from ever mutating an already-closed row. Belt-and-braces
                # against the SELL→rotation race that previously allowed a
                # later signal to overwrite a closed trade's pnl/is_win.
                db.table("virtual_trades").update({
                    "status": "CLOSED",
                    "exit_price": price,
                    "exit_date": now,
                    "exit_score": score,
                    "exit_action": action,
                    "pnl_pct": round(pnl_pct, 2),
                    "pnl_amount": round(pnl_amount, 2),
                    "is_win": is_win,
                    "exit_reason": "SIGNAL",
                }).eq("id", pos["id"]).eq("status", "OPEN").execute()
                sells += 1
                _record_brain_outcome(pos, price, score, "SIGNAL", pnl_pct)

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
            if brain_open_count >= settings.brain_max_open:
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
                    w_pnl = ((w_exit_price - w_entry) / w_entry) * 100 if w_entry > 0 else 0
                    # Status guard prevents this UPDATE from ever mutating
                    # an already-closed row. Combined with the lazy-recompute
                    # of `weakest` above, the rotation flow can no longer
                    # overwrite a closed trade's financial fields.
                    db.table("virtual_trades").update({
                        "status": "CLOSED",
                        "exit_price": w_exit_price,
                        "exit_date": now,
                        "exit_score": score,
                        "pnl_pct": round(w_pnl, 2),
                        "pnl_amount": round(w_exit_price - w_entry, 2),
                        "is_win": w_pnl > 0,
                        "exit_reason": "ROTATION",
                    }).eq("id", weakest["id"]).eq("status", "OPEN").execute()
                    _record_brain_outcome(weakest, w_exit_price, score, "ROTATION", w_pnl)
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
                    "source": "brain",
                    "target_price": target,
                    "stop_loss": stop,
                    "entry_tier": brain_tier,
                    "trust_multiplier": trust_multiplier,
                    "tier_reason": tier_reason,
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
                }).execute()
                buys += 1
                brain_open_count += 1
                open_brain.add(symbol)  # block any further inserts this scan
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

    return {"buys": buys, "sells": sells}


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
        .select("id, symbol, entry_price, entry_score, entry_date, source, "
                "target_price, stop_loss, bucket, market_regime, "
                "thesis_last_status, peak_price")
        .eq("status", "OPEN")
        .execute()
    )
    open_trades = open_result.data or []
    if not open_trades:
        return {"stops_hit": 0, "targets_hit": 0, "profit_takes": 0, "expired": 0}

    # Batch-fetch current prices
    symbols = list({t["symbol"] for t in open_trades})
    prices = _fetch_prices_batch(symbols)

    # Batch fetch latest signal scores for exit tracking (1 query instead of N)
    current_scores: dict[str, int] = {}
    sig_result = (
        db.table("signals")
        .select("symbol, score")
        .in_("symbol", symbols)
        .order("created_at", desc=True)
        .execute()
    )
    for row in (sig_result.data or []):
        sym = row.get("symbol")
        if sym and sym not in current_scores:
            current_scores[sym] = row.get("score", 0)

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    market_open = _is_us_market_open()
    stops_hit = 0
    targets_hit = 0
    expired = 0
    profit_takes = 0

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
        pnl_pct = ((current_price - entry_price) / entry_price) * 100

        # Parse entry_date for age check
        days_held = days_since(trade.get("entry_date"), now=now)

        # ── Peak price tracking for trailing stop ──
        # Track the highest price since entry. Updated every scan so the
        # trailing stop ratchets upward as the position wins.
        peak = float(trade.get("peak_price") or entry_price)
        if current_price > peak:
            peak = current_price
            try:
                db.table("virtual_trades").update(
                    {"peak_price": peak}
                ).eq("id", trade["id"]).execute()
            except Exception:
                pass  # non-critical, will retry next scan

        # Trailing stop is "active" once the position has been at least 3%
        # above entry at ANY point (peak_price >= entry * 1.03). Once
        # active, two levels protect the position:
        #
        #   SOFT trail (3% below peak): thesis-gated. Only fires when
        #     thesis is weakening or invalid. If thesis is valid, a 3%
        #     pullback is treated as noise — a portfolio manager wouldn't
        #     sell a fundamentally sound stock on a routine dip.
        #
        #   HARD trail (5% below peak): always fires regardless of thesis.
        #     If the price drops 5% from peak, something real is happening
        #     and we protect gains unconditionally.
        #
        # This was refined after PBR-A (Apr 14): the 3% mechanical stop
        # sold at +1.13% on a routine pullback while the thesis was only
        # "weakening" — a portfolio manager would have checked the context
        # before selling.
        trailing_active = peak >= entry_price * 1.03
        soft_trail = peak * 0.97 if trailing_active else None   # 3% below peak
        hard_trail = peak * 0.95 if trailing_active else None   # 5% below peak

        thesis_status = (trade.get("thesis_last_status") or "").lower()

        # Determine exit reason (priority: stop > hard_trail > soft_trail > target > time)
        exit_reason = None
        if stop and current_price <= stop:
            exit_reason = "STOP_HIT"
            stops_hit += 1
        elif trailing_active and current_price <= hard_trail:
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
        elif trailing_active and current_price <= soft_trail:
            # Soft trailing stop — thesis-gated.
            # If thesis is valid, this is just noise. Hold.
            # If thesis is weakening/invalid, price confirms — sell.
            if thesis_status == "valid":
                logger.info(
                    f"Virtual TRAILING STOP suppressed for {symbol} — thesis still valid "
                    f"(peak ${peak:.2f}, soft trail ${soft_trail:.2f}, now ${current_price:.2f}, "
                    f"P&L {pnl_pct:+.1f}%). Holding through noise."
                )
                # Don't exit — treat as noise. The hard trail at 5% is the safety net.
            else:
                exit_reason = "TRAILING_STOP"
                profit_takes += 1
                logger.info(
                    f"Virtual TRAILING STOP (soft, thesis={thesis_status}): {symbol} at {pnl_pct:+.1f}% "
                    f"(peak ${peak:.2f}, soft trail ${soft_trail:.2f}, now ${current_price:.2f})"
                )
                notifications.append(("brain_sell", {
                    "symbol": symbol, "price": f"{current_price:.2f}",
                    "pnl": f"{pnl_pct:+.1f}",
                    "reason": f"Trailing stop (peak ${peak:.2f}, thesis {thesis_status})",
                    "entry_score": str(trade.get("entry_score", 0)),
                    "exit_score": str(current_scores.get(symbol, 0)),
                    "verdict": f"Thesis was {thesis_status}, price drop confirmed — locked in gains.",
                }))
        elif target and current_price >= target:
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
        elif days_held >= max_days:
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
        if not exit_reason and trade.get("source") == "brain":
            latest_sig = current_scores_full.get(symbol) if 'current_scores_full' in dir() else None
            # Use the signal action from the batch we already fetched
            latest_action = None
            for row in (sig_result.data or []):
                if row.get("symbol") == symbol:
                    latest_action = row.get("action")
                    break

            if (
                pnl_pct < 0
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
            # Roll back the counter we incremented when we set exit_reason
            if exit_reason == "STOP_HIT": stops_hit -= 1
            elif exit_reason == "TARGET_HIT": targets_hit -= 1
            elif exit_reason == "PROFIT_TAKE": profit_takes -= 1
            elif exit_reason == "TIME_EXPIRED": expired -= 1
            continue

        pnl_amount = current_price - entry_price
        is_win = pnl_pct > 0
        source = trade.get("source", "watchlist")

        exit_score = current_scores.get(symbol)

        # Status guard: never mutate an already-closed row.
        db.table("virtual_trades").update({
            "status": "CLOSED",
            "exit_price": current_price,
            "exit_date": now_iso,
            "exit_score": exit_score,
            "pnl_pct": round(pnl_pct, 2),
            "pnl_amount": round(pnl_amount, 2),
            "is_win": is_win,
            "exit_reason": exit_reason,
        }).eq("id", trade["id"]).eq("status", "OPEN").execute()
        # Forward to learning loop. The trade dict carries bucket +
        # market_regime from the SELECT above, so no extra query.
        _record_brain_outcome(trade, current_price, exit_score, exit_reason, pnl_pct)

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

    # All trades
    open_result = (
        db.table("virtual_trades")
        .select("symbol, entry_price, entry_date, entry_score, bucket, signal_style, source, target_price, stop_loss, thesis_last_status, tier_reason")
        .eq("status", "OPEN")
        .order("entry_date", desc=True)
        .execute()
    )
    open_trades = open_result.data or []

    closed_result = (
        db.table("virtual_trades")
        .select("symbol, entry_price, exit_price, pnl_pct, pnl_amount, is_win, "
                "entry_date, exit_date, entry_score, exit_score, bucket, source, exit_reason, "
                "peak_price, thesis_last_reason, tier_reason")
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
        if reason == "ROTATION":
            return "Rotated out for a stronger candidate"
        return reason or "Unknown"

    def _calc_stats(trades: list[dict]) -> dict:
        total = len(trades)
        wins = sum(1 for t in trades if t.get("is_win"))
        win_rate = (wins / total * 100) if total > 0 else 0
        avg_ret = sum(t.get("pnl_pct", 0) for t in trades) / total if total else 0
        total_ret = sum(t.get("pnl_pct", 0) for t in trades)
        best = max(trades, key=lambda t: t.get("pnl_pct", 0)) if trades else None
        worst = min(trades, key=lambda t: t.get("pnl_pct", 0)) if trades else None
        return {
            "closed_count": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": round(win_rate, 1),
            "avg_return_pct": round(avg_ret, 2),
            "total_return_pct": round(total_ret, 2),
            "best_trade": {"symbol": best["symbol"], "pnl_pct": best["pnl_pct"]} if best else None,
            "worst_trade": {"symbol": worst["symbol"], "pnl_pct": worst["pnl_pct"]} if worst else None,
        }

    def _enrich_open_trade(t: dict) -> dict:
        symbol = t["symbol"]
        entry_price = float(t["entry_price"])
        current = current_prices.get(symbol)

        # Calculate days held
        days_held = days_since(t.get("entry_date"), now=now)

        # Get signal reasoning (why the brain picked this)
        sig = signal_context.get(symbol, {})

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
        }

        if current:
            pnl_pct = ((current - entry_price) / entry_price) * 100
            enriched["current_price"] = round(current, 2)
            enriched["unrealized_pnl_pct"] = round(pnl_pct, 2)
            enriched["unrealized_pnl_amount"] = round(current - entry_price, 2)

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

    result = {
        "open_count": len(open_trades),
        "open_trades": enriched_open,
        # Combined stats
        **_calc_stats(closed_trades),
        "recent_closed": [
            {
                "symbol": t["symbol"],
                "pnl_pct": t["pnl_pct"],
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
            }
            for t in closed_trades[:5]
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
