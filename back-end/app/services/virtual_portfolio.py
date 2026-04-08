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

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from loguru import logger

from app.core.cache import TTLCache
from app.core.config import settings
from app.db.supabase import get_client, with_retry
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


def _eval_brain_trust_tier(sig: dict) -> tuple[int, float, str]:
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

    # Tier 1: validated AI + standard score threshold
    if ai_status == "validated" and score >= BRAIN_MIN_SCORE:
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
        .select("id, symbol, entry_price, entry_date, entry_score, source, pending_review_at")
        .eq("status", "OPEN")
        .execute()
    )
    all_open = open_result.data or []

    # Two parallel sets keep O(1) "is this symbol already held?" checks for
    # both tracks. We also pre-compute the weakest brain position now so the
    # rotation logic doesn't need to re-scan the list per signal.
    open_watchlist: set[str] = set()
    open_brain: set[str] = set()
    brain_open_count = 0
    weakest_brain: dict | None = None
    weakest_brain_score = 999  # Sentinel: any real score is lower
    for r in all_open:
        if r.get("source") == "brain":
            open_brain.add(r["symbol"])
            brain_open_count += 1
            es = r.get("entry_score", 0) or 0
            if es < weakest_brain_score:
                weakest_brain_score = es
                weakest_brain = r
        else:
            open_watchlist.add(r["symbol"])

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
                }).eq("id", pos["id"]).execute()
                sells += 1

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

        # Track 1: Watchlist picks (score 62+) — only on explicit BUY action
        if action == "BUY" and is_watchlisted and score >= 62 and symbol not in open_watchlist:
            db.table("virtual_trades").insert({
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
            }).execute()
            buys += 1
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
        brain_tier, trust_multiplier, tier_reason = _eval_brain_trust_tier(sig)
        if brain_tier > 0 and symbol not in open_brain:
            # ── Rotation: brain at max capacity, only rotate if the new
            # ── signal is meaningfully better (+5 points) than the weakest
            # ── currently-held brain position.
            #
            # The +5 margin avoids constant churn on small score differences.
            # We use entry_score as the tie-breaker; higher entry_score
            # implied a more confident initial decision.
            if brain_open_count >= settings.brain_max_open:
                if weakest_brain and score >= weakest_brain_score + 5:
                    weakest = weakest_brain
                    weakest_score = weakest_brain_score
                    w_symbol = weakest["symbol"]
                    w_entry = float(weakest["entry_price"])
                    # Use the LIVE price for the rotated-out position so the
                    # recorded P&L is realistic. Fall back to the new signal's
                    # price only if the live fetch fails (rare).
                    w_prices = _fetch_prices_batch([w_symbol])
                    w_current, _ = w_prices.get(w_symbol, (None, None))
                    w_exit_price = w_current if w_current else price
                    w_pnl = ((w_exit_price - w_entry) / w_entry) * 100 if w_entry > 0 else 0
                    db.table("virtual_trades").update({
                        "status": "CLOSED",
                        "exit_price": w_exit_price,
                        "exit_date": now,
                        "exit_score": score,
                        "pnl_pct": round(w_pnl, 2),
                        "pnl_amount": round(w_exit_price - w_entry, 2),
                        "is_win": w_pnl > 0,
                        "exit_reason": "ROTATION",
                    }).eq("id", weakest["id"]).execute()
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
                    # Recompute the weakest brain position for the next
                    # rotation candidate this scan. We use `open_brain`
                    # (which we just updated via .discard) as the source
                    # of truth for "still open" — this correctly excludes
                    # ALL previously-rotated symbols this scan, not just
                    # the most recent one. Earlier versions of this code
                    # only filtered the most-recently-rotated symbol,
                    # which was a bug if multiple rotations happened in
                    # one scan (the second rotation could re-pick a
                    # symbol that had already been closed).
                    weakest_brain = None
                    weakest_brain_score = 999
                    for r in all_open:
                        if r.get("source") != "brain":
                            continue
                        if r.get("symbol") not in open_brain:
                            continue  # already rotated out earlier this scan
                        es = r.get("entry_score", 0) or 0
                        if es < weakest_brain_score:
                            weakest_brain_score = es
                            weakest_brain = r
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
                }).execute()
                buys += 1
                brain_open_count += 1
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
    """Drain the scan-local brain notification queue and send each entry via Telegram.

    This is the ONLY function in this module that actually sends Telegram
    messages. Every other function APPENDS to the queue; this one drains it.
    Centralising the send means:
      1. We can batch all brain alerts at the end of a scan in a single
         async pass instead of awaiting individual sends inside sync code.
      2. If a previous scan crashed mid-loop, the new scan starts with a
         fresh queue (because each scan creates its own via
         `new_notification_queue()`).
      3. Send failures don't break the scan — each send is wrapped in
         try/except and we keep going.

    Args:
        notifications: The scan-local queue threaded through every brain
            function this scan run. Will be cleared after sending.

    Returns:
        Count of notifications successfully sent. The queue is always
        cleared at the end regardless of how many sends succeeded — the
        same notification should never be sent twice.
    """
    if not notifications:
        return 0
    from app.notifications.messages import msg
    from app.notifications.telegram_bot import send_message
    sent = 0
    # Iterate a copy in case any handler mutates the queue
    for key, kwargs in list(notifications):
        try:
            await send_message(settings.telegram_chat_id, msg(key, **kwargs))
            sent += 1
        except Exception as e:
            logger.debug(f"Brain notification failed ({key}): {e}")
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
        .select("id, symbol, entry_price, entry_score, entry_date, source, target_price, stop_loss")
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
        entry_date_str = trade.get("entry_date", "")
        try:
            entry_date = datetime.fromisoformat(entry_date_str.replace("Z", "+00:00"))
            days_held = (now - entry_date).days
        except (ValueError, TypeError):
            days_held = 0

        # Determine exit reason (priority: stop > target > profit_take > time)
        exit_reason = None
        if stop and current_price <= stop:
            exit_reason = "STOP_HIT"
            stops_hit += 1
        elif target and current_price >= target:
            exit_reason = "TARGET_HIT"
            targets_hit += 1
        # Profit-taking: lock in gains at +3%+ after 2+ days (let thesis play out first)
        elif pnl_pct >= 3.0 and days_held >= 2:
            exit_reason = "PROFIT_TAKE"
            profit_takes += 1
            logger.info(f"Virtual PROFIT TAKE: {symbol} at +{pnl_pct:.1f}% (locking in gains)")
            notifications.append(("brain_sell", {
                "symbol": symbol, "price": f"{current_price:.2f}",
                "pnl": f"{pnl_pct:+.1f}", "reason": "Profit take at +3%",
                "entry_score": str(trade.get("entry_score", 0)),
                "exit_score": str(current_scores.get(symbol, 0)),
                "verdict": "Gains locked in. Goal: make profit.",
            }))
        elif days_held >= max_days:
            exit_reason = "TIME_EXPIRED"
            expired += 1

        if not exit_reason:
            continue
        pnl_amount = current_price - entry_price
        is_win = pnl_pct > 0
        source = trade.get("source", "watchlist")

        exit_score = current_scores.get(symbol)

        db.table("virtual_trades").update({
            "status": "CLOSED",
            "exit_price": current_price,
            "exit_date": now_iso,
            "exit_score": exit_score,
            "pnl_pct": round(pnl_pct, 2),
            "pnl_amount": round(pnl_amount, 2),
            "is_win": is_win,
            "exit_reason": exit_reason,
        }).eq("id", trade["id"]).execute()

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
        .select("symbol, entry_price, entry_date, entry_score, bucket, signal_style, source, target_price, stop_loss")
        .eq("status", "OPEN")
        .order("entry_date", desc=True)
        .execute()
    )
    open_trades = open_result.data or []

    closed_result = (
        db.table("virtual_trades")
        .select("symbol, entry_price, exit_price, pnl_pct, pnl_amount, is_win, "
                "entry_date, exit_date, entry_score, exit_score, bucket, source, exit_reason")
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
        entry_date_str = t.get("entry_date", "")
        try:
            entry_date = datetime.fromisoformat(entry_date_str.replace("Z", "+00:00"))
            days_held = (now - entry_date).days
        except (ValueError, TypeError):
            days_held = 0

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
