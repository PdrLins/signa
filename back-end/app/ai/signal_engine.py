"""Signal scoring engine — the rules that turn raw data into a 0-100 score.

============================================================
WHAT THIS MODULE IS
============================================================

This is the heart of Signa's signal generation. Every ticker analyzed by
the scan pipeline ends up here, and this module decides:

  1. SCORE — a 0-100 composite that summarizes the bullish/bearish case.
  2. ACTION — BUY / HOLD / SELL / AVOID derived from the score and bucket.
  3. BLOCKERS — hard-fail conditions that override the score (fraud,
     hostile macro, overbought RSI, suspicious volume, SMA overextension).
  4. GEM — a flag for the highest-conviction signals (5 strict conditions).
  5. STATUS — CONFIRMED / WEAKENING / UPGRADED / CANCELLED relative to
     the previous signal for the same ticker.

The scoring weights and thresholds were tuned from a 6-month backtest
(Oct 2024 - Apr 2025, 30 tickers, ~18,000 signals). Key findings that
shaped the rules:

  • RSI 50-65 is the sweet spot for HIGH_RISK (57.3% win rate).
    RSI > 75 has an INVERTED win rate (60%+ failure) — auto-blocked.
    RSI 30-50 is the contrarian zone, handled by `contrarian.py`.

  • SAFE_INCOME wins on LOW volume (institutional accumulation),
    HIGH_RISK wins on MODERATE volume (z-score 1.0-2.0). Volume z-score
    > 2.0 is panic / FOMO and is less reliable.

  • Momentum +1% to +3% is optimal. Anything > +5% is a reversal trap
    (the move has already happened).

  • MACD histogram > 2.0 predicts surges. Missed surgers in the
    backtest had average histogram 3.3 vs 1.5 for non-surgers.

  • Stocks > 50% above their SMA200 have INVERTED returns
    (gravity wins). Auto-blocked.

  • Score ceiling at 72 — scores between 72 and 90 are the meaningful
    BUY zone. Scores > 90 have inverted win rates (overbought trap)
    and get force-converted to HOLD.

============================================================
THE TWO BUCKETS
============================================================

Every signal is classified into one of two buckets, and each bucket has
its own scoring formula and BUY threshold:

  SAFE_INCOME (dividend stocks, blue-chips, REITs, ETFs)
  ------------------------------------------------------
    Stock weights:  35% dividend reliability + 30% fundamental health +
                    25% macro + 10% sentiment
    ETF weights:    40% fundamental + 30% macro + 15% dividend + 15% sentiment
                    (ETFs don't pay individual dividends so the dividend
                    weight is reduced and reallocated)
    BUY threshold:  62 (validated at 60.6% win rate by backtest)
    Bonus:          Quality bonus (up to +6) from Fama-French QMJ-inspired
                    factors (margins, earnings stability, leverage)

  HIGH_RISK (growth stocks, tech, biotech, crypto, small caps)
  -----------------------------------------------------------
    Weights:        35% sentiment + 30% catalyst + 25% technical momentum +
                    10% fundamentals
    BUY threshold:  65 (validated at 52.6% win rate by backtest)
    Bonus:          Short-squeeze bonus (up to +20) when high short
                    interest combines with bullish momentum.
                    Momentum factor bonus (up to +6) from 3m+6m returns.

============================================================
DYNAMIC ADJUSTMENTS
============================================================

Several adjustments fire on top of the base score:

  Sentiment weight reduction (low-mention tickers)
    If grok_data.mention_count < 100, the sentiment is unreliable. The
    sentiment weight collapses from 35% (HIGH_RISK) or 10% (SAFE_INCOME)
    down to 5%, and the freed weight is given to technical_momentum
    (HIGH_RISK) or macro (SAFE_INCOME).

  Contrarian sentiment dampening
    Extreme bullish sentiment (> 85) is dampened by -10 (bubble deflation).
    Extreme bearish sentiment (< 15) is boosted by +10 (oversold bounce).
    Only fires when mention_count >= 100 (so the sentiment is meaningful).

  Regime multipliers
    VOLATILE + HIGH_RISK    → score × 0.85   (15% penalty)
    CRISIS + HIGH_RISK      → score = 0      (paused entirely)
    CRISIS + SAFE_INCOME    → score × 0.60   (40% penalty)
                              UNLESS the catalyst is DIVIDEND or PEAD
                              (those plays are defensive and OK in crisis)

  Catalyst type detection
    PEAD (Post-Earnings-Announcement Drift): earnings within 3 days +
      positive surprise + price hasn't moved more than 10% yet.
    PRE_EARNINGS: earnings within 30 days, no PEAD.
    These are mutually exclusive — you can't be both pre-earnings AND
    post-earnings drift.

============================================================
BLOCKERS (auto-AVOID, override the score entirely)
============================================================

ANY of these conditions triggers an immediate AVOID, regardless of how
high the score is:

  1. Fraud / legal risk in X sentiment or breaking news
     (keywords: fraud, sec investigation, lawsuit, scam, ponzi,
     insider trading)
  2. Hostile macro environment (high VIX + high Fed funds + high CPI)
  3. Suspiciously low volume (Z-score < -2.0 OR avg < 50K)
  4. Overbought RSI > 75 (backtest: 60%+ failure rate)
  5. SMA200 overextension > 50% (backtest: inverted returns)

NOTE: blockers are only checked for AI-analyzed signals. Tech-only
signals (below the top-15 by pre-score) skip this pass — but the brain
re-checks the most critical blockers in `_eval_brain_trust_tier` for
its tier 3 path, so it can't auto-buy a tech-only signal that would
have been blocked.

============================================================
GEM CONDITIONS (the highest-conviction signal class)
============================================================

A signal becomes a GEM only if ALL FIVE of these are true:

  1. Score >= 85
  2. Catalyst within 30 days (any type)
  3. Sentiment is bullish AND confidence >= 80%
  4. No red flags
  5. Risk/reward ratio >= 3.0x

GEMs are rare (typically 0-3 per day) and trigger an immediate Telegram
alert separate from the regular scan digest.
"""

from datetime import date

from loguru import logger

from app.core.config import settings


# ============================================================
# SCORING
# ============================================================

def compute_score(
    technical_data: dict,
    fundamental_data: dict,
    macro_data: dict,
    grok_data: dict,
    synthesis: dict,
    bucket: str,
    market_regime: str = "TRENDING",
    asset_type: str = "STOCK",
) -> tuple[int, dict]:
    """Compute the 0-100 composite score for one signal.

    This is the main scoring function. Every ticker analyzed by `scan_service`
    ends up here. The score drives the BUY/HOLD/SELL/AVOID action and feeds
    the brain's tier evaluation downstream.

    The function is bucket-aware: SAFE_INCOME and HIGH_RISK use different
    weight formulas (see file header). It also applies several dynamic
    adjustments on top of the base score:

      • Sentiment weight collapse for low-mention tickers (< 100 mentions
        → sentiment weight drops from 35%/10% to 5%, freed weight goes
        to technical_momentum/macro respectively).
      • Contrarian sentiment dampening (extreme bullish > 85 → -10,
        extreme bearish < 15 → +10) — only for high-mention tickers.
      • Catalyst type detection (PEAD vs PRE_EARNINGS, mutually exclusive).
      • Regime multipliers (VOLATILE × 0.85, CRISIS × 0.60 or 0).
      • Quality bonus for SAFE_INCOME (Fama-French QMJ-inspired, up to +6).
      • Short squeeze bonus + momentum factor bonus for HIGH_RISK.

    Args:
        technical_data: Output of `indicators.compute_indicators` — RSI,
            MACD, Bollinger Bands, SMA crosses, volume z-score, ATR, ADX.
        fundamental_data: Output of `market_scanner.get_fundamentals` —
            P/E, dividend yield, EPS growth, debt ratios, profit margins.
        macro_data: Output of `macro_scanner.get_macro_snapshot` — Fed
            funds, VIX, CPI, unemployment, Fear & Greed Index, intermarket
            signals. Single value per scan, shared across all tickers.
        grok_data: Output of `provider.analyze_sentiment` — X/Twitter
            sentiment from Grok or Gemini. Includes mention_count which
            gates the dynamic sentiment weight collapse.
        synthesis: Output of `provider.synthesize_signal` — the AI's
            BUY/HOLD/SELL/AVOID recommendation with confidence, target,
            stop, R/R ratio, catalyst, red flags. Empty dict for tech-only.
        bucket: "SAFE_INCOME" or "HIGH_RISK" (set by `_classify_bucket`
            in scan_service).
        market_regime: "TRENDING" / "VOLATILE" / "CRISIS" — drives the
            regime multiplier and the GEM eligibility for SAFE_INCOME.
        asset_type: "STOCK" / "ETF" / "CRYPTO". Only "ETF" affects scoring
            (uses ETF-specific weights with reduced dividend weight).

    Returns:
        (score, breakdown)

        score: 0-100 integer (clamped). 0 means "skip entirely", 90+ means
            "overbought trap, force HOLD" (handled in `score_to_action`).

        breakdown: Dict of per-component contributions for the UI factor
            labels and debugging. Keys include:
              dividend_reliability / fundamental_health / macro / sentiment
              (SAFE_INCOME) or sentiment / catalyst / technical_momentum /
              fundamentals (HIGH_RISK), plus quality_bonus, momentum_bonus,
              short_squeeze_bonus, total, market_regime, regime_adjustment_*,
              catalyst_type, sentiment_weight_effective, grok_mention_count.
    """
    # ── Null safety ──
    technical_data = technical_data or {}
    fundamental_data = fundamental_data or {}
    macro_data = macro_data or {}
    grok_data = grok_data or {}
    synthesis = synthesis or {}

    # ── Dynamic sentiment weight (Part 5) ──
    grok_mention_count = 0
    if isinstance(grok_data, dict):
        grok_mention_count = grok_data.get("mention_count", 0) or 0

    raw_sentiment_score = _score_sentiment(grok_data)

    # Contrarian adjustment for extreme sentiment
    if grok_mention_count >= 100:
        if raw_sentiment_score > 85:
            raw_sentiment_score = max(0, raw_sentiment_score - 10)
        elif raw_sentiment_score < 15:
            raw_sentiment_score = min(100, raw_sentiment_score + 10)

    # ── Mutual exclusive earnings catalyst (Part 2) ──
    catalyst_type = None
    if fundamental_data:
        days_since_earnings = fundamental_data.get("days_since_last_earnings", 999) or 999
        eps_surprise = fundamental_data.get("last_eps_surprise_pct", 0) or 0
        days_to_earnings = fundamental_data.get("days_to_next_earnings", 999) or 999
        price_change_5d = (technical_data or {}).get("price_change_5d", 0) or 0

        if (days_since_earnings <= 3 and eps_surprise > 0.03 and price_change_5d < 0.10):
            catalyst_type = "PEAD"
        elif days_to_earnings <= 30:
            catalyst_type = "PRE_EARNINGS"

    if bucket == "SAFE_INCOME":
        # ETFs get reduced dividend weight -- great ETFs like XEQT don't pay much
        if asset_type == "ETF":
            weights = {**settings.etf_weights}
        else:
            weights = {**settings.safe_income_weights}
        dividend_score = _score_dividend_reliability(fundamental_data)
        fundamental_score = _score_fundamentals(fundamental_data, bucket)
        macro_score = _score_macro(macro_data)
        quality_score = _score_quality(fundamental_data)

        # Dynamic sentiment weight for low-mention tickers
        if grok_mention_count < 100:
            effective_sent_w = 0.05
            technical_boost = weights["sentiment"] - effective_sent_w
            weights["sentiment"] = effective_sent_w
            weights["macro"] = weights["macro"] + technical_boost
        else:
            effective_sent_w = weights["sentiment"]

        total = (
            dividend_score * weights["dividend_reliability"]
            + fundamental_score * weights["fundamental_health"]
            + macro_score * weights["macro"]
            + raw_sentiment_score * weights["sentiment"]
        )

        # Quality bonus for SAFE_INCOME (high-quality companies deserve a boost)
        quality_bonus = max(0, (quality_score - 60) * 0.15)  # Up to +6 points
        total = total + quality_bonus

        breakdown = {
            "dividend_reliability": round(dividend_score * weights["dividend_reliability"], 1),
            "fundamental_health": round(fundamental_score * weights["fundamental_health"], 1),
            "macro": round(macro_score * weights["macro"], 1),
            "sentiment": round(raw_sentiment_score * weights["sentiment"], 1),
            "quality_score": round(quality_score, 1),
            "quality_bonus": round(quality_bonus, 1),
        }
    else:
        weights = {**settings.high_risk_weights}
        catalyst_score = _score_catalyst(synthesis)
        technical_score = _score_technical_momentum(technical_data)
        momentum_factor_score = _score_momentum_factor(technical_data)
        fundamental_score = _score_fundamentals(fundamental_data, bucket)

        # Dynamic sentiment weight for low-mention tickers
        if grok_mention_count < 100:
            effective_sent_w = 0.05
            technical_boost = weights["sentiment"] - effective_sent_w
            weights["sentiment"] = effective_sent_w
            weights["technical_momentum"] = weights["technical_momentum"] + technical_boost
        else:
            effective_sent_w = weights["sentiment"]

        total = (
            raw_sentiment_score * weights["sentiment"]
            + catalyst_score * weights["catalyst"]
            + technical_score * weights["technical_momentum"]
            + fundamental_score * weights["fundamentals"]
        )

        # Short squeeze bonus (additive, not weighted)
        squeeze_bonus = _score_short_squeeze(fundamental_data, technical_data)
        if squeeze_bonus > 0:
            total = total + squeeze_bonus

        # Momentum factor bonus (strong 3m+6m trend = higher conviction)
        momentum_bonus = max(0, (momentum_factor_score - 60) * 0.15)  # Up to +6 points
        total = total + momentum_bonus

        breakdown = {
            "sentiment": round(raw_sentiment_score * weights["sentiment"], 1),
            "catalyst": round(catalyst_score * weights["catalyst"], 1),
            "technical_momentum": round(technical_score * weights["technical_momentum"], 1),
            "fundamentals": round(fundamental_score * weights["fundamentals"], 1),
            "short_squeeze_bonus": squeeze_bonus,
            "momentum_factor_score": round(momentum_factor_score, 1),
            "momentum_bonus": round(momentum_bonus, 1),
        }

    score = max(0, min(100, total))

    # ── Regime score multiplier (Part 6) ──
    regime_adjustment_applied = False
    regime_adjustment_note = None

    if market_regime == "VOLATILE" and bucket == "HIGH_RISK":
        score = score * 0.85
        regime_adjustment_applied = True
        regime_adjustment_note = "Score reduced 15%: volatile market regime"
    elif market_regime == "RECOVERY" and bucket == "HIGH_RISK":
        score = score * 1.10
        regime_adjustment_applied = True
        regime_adjustment_note = "Score boosted 10%: recovery regime favors momentum"
    elif market_regime == "CRISIS":
        if bucket == "HIGH_RISK":
            score = 0
            regime_adjustment_applied = True
            regime_adjustment_note = "CRISIS regime: HIGH_RISK signals paused"
        elif bucket == "SAFE_INCOME":
            if catalyst_type not in ("DIVIDEND", "PEAD", "DIV_EXDATE"):
                score = score * 0.60
                regime_adjustment_applied = True
                regime_adjustment_note = "Score reduced 40%: crisis regime, non-dividend catalyst"

    score = int(round(score))
    breakdown["total"] = score
    breakdown["market_regime"] = market_regime
    breakdown["regime_adjustment_applied"] = regime_adjustment_applied
    breakdown["regime_adjustment_note"] = regime_adjustment_note
    breakdown["catalyst_type"] = catalyst_type
    breakdown["sentiment_weight_effective"] = round(effective_sent_w, 3)
    breakdown["grok_mention_count"] = grok_mention_count

    return score, breakdown


def score_to_action(score: int, bucket: str = "") -> str:
    """Convert a 0-100 composite score to a BUY/HOLD/SELL/AVOID action.

    Uses bucket-specific BUY thresholds validated by the 6-month backtest:
      • SAFE_INCOME at 62+ → 60.6% win rate
      • HIGH_RISK at 65+   → 52.6% win rate

    Action mapping:
      score >= buy_threshold AND score <= 90  → BUY
      score > 90                              → HOLD  (overbought trap —
                                                       backtest shows
                                                       inverted returns)
      score >= 55 AND score < buy_threshold   → HOLD
      score < 55                              → AVOID

    The 90-ceiling is critical: scores in the 90+ range correlate with
    overbought conditions where the rally is already exhausted. The
    backtest showed that 90+ scores have INVERTED win rates compared to
    scores in the 72-89 range. Force-converting to HOLD prevents the
    user from chasing tops.

    Args:
        score: 0-100 composite score from `compute_score`.
        bucket: "SAFE_INCOME" or "HIGH_RISK". An empty bucket falls back
            to the generic `score_buy` setting.

    Returns:
        One of: "BUY", "HOLD", "SELL", "AVOID". Note that this function
        never returns "SELL" — SELL actions are produced by external
        signals (deteriorating trends from previous-signal comparisons),
        not by score thresholds.
    """
    if bucket == "SAFE_INCOME":
        buy_threshold = settings.score_buy_safe
    elif bucket == "HIGH_RISK":
        buy_threshold = settings.score_buy_risk
    else:
        buy_threshold = settings.score_buy

    hold_threshold = settings.score_hold
    ceiling = 90

    if score >= buy_threshold and score <= ceiling:
        return "BUY"
    if score > ceiling:
        return "HOLD"
    if score >= hold_threshold:
        return "HOLD"
    return "AVOID"


# ============================================================
# GEM DETECTION
# ============================================================

def check_gem(score: int, grok_data: dict, synthesis: dict) -> tuple[bool, list[str]]:
    """Decide if a signal qualifies as a GEM alert.

    GEMs are the highest-conviction signal class. They get a dedicated
    Telegram alert (separate from the regular scan digest) and are
    expected to be rare — typically 0-3 per day across the full universe.

    A signal is a GEM only if ALL FIVE conditions are met:

      1. Score >= settings.gem_min_score (default 85)
      2. Catalyst is set AND its date is within settings.gem_catalyst_days
         (default 30) — i.e., something concrete happens soon (earnings,
         product launch, dividend, etc.)
      3. X/Twitter sentiment label == "bullish" AND confidence >= 80%
         (so we have high-quality social proof, not just neutral data)
      4. synthesis.red_flags is empty (no fraud, no insider sells,
         no regulatory issues)
      5. risk_reward_ratio >= settings.gem_min_rr_ratio (default 3.0)
         (the math has to work — at least $3 of upside per $1 of risk)

    The 5-of-5 requirement is intentionally strict. Lowering any of these
    in the past has produced false-positive GEMs that hurt the user's
    trust in the alert.

    Args:
        score: 0-100 composite score from `compute_score`.
        grok_data: Sentiment dict (label, confidence, themes, etc.)
        synthesis: AI synthesis dict (catalyst, catalyst_date, red_flags,
            risk_reward_ratio, target_price, stop_loss, etc.)

    Returns:
        (is_gem, conditions)

        is_gem: True if all 5 conditions pass.
        conditions: List of human-readable strings (one per condition)
            with [PASS]/[FAIL] markers. Used for the Telegram GEM alert
            body and for debugging when a near-GEM doesn't qualify.
    """
    conditions = []
    passed = 0

    if score >= settings.gem_min_score:
        conditions.append(f"[PASS] Score {score} >= {settings.gem_min_score}")
        passed += 1
    else:
        conditions.append(f"[FAIL] Score {score} < {settings.gem_min_score}")

    catalyst_date = synthesis.get("catalyst_date")
    if catalyst_date and synthesis.get("catalyst"):
        try:
            cat_date = date.fromisoformat(catalyst_date)
            days_away = (cat_date - date.today()).days
            if 0 <= days_away <= settings.gem_catalyst_days:
                conditions.append(f"[PASS] Catalyst in {days_away} days")
                passed += 1
            else:
                conditions.append(f"[FAIL] Catalyst {days_away} days away")
        except (ValueError, TypeError):
            conditions.append("[FAIL] Invalid catalyst date")
    else:
        conditions.append("[FAIL] No catalyst detected")

    label = grok_data.get("label", "neutral")
    confidence = grok_data.get("confidence", 0)
    if label == "bullish" and confidence >= 80:
        conditions.append(f"[PASS] Sentiment: {label} (confidence={confidence})")
        passed += 1
    else:
        conditions.append(f"[FAIL] Sentiment: {label} (confidence={confidence})")

    red_flags = synthesis.get("red_flags", [])
    if not red_flags:
        conditions.append("[PASS] No red flags")
        passed += 1
    else:
        conditions.append(f"[FAIL] Red flags: {', '.join(red_flags)}")

    rr = synthesis.get("risk_reward_ratio")
    if rr is not None and rr >= settings.gem_min_rr_ratio:
        conditions.append(f"[PASS] R/R: {rr:.1f}x")
        passed += 1
    else:
        conditions.append(f"[FAIL] R/R: {rr or 0:.1f}x")

    is_gem = passed == 5
    if is_gem:
        logger.info("GEM ALERT detected! All 5 conditions met.")

    return is_gem, conditions


# ============================================================
# BLOCKERS
# ============================================================

def check_blockers(
    grok_data: dict,
    fundamental_data: dict,
    macro_data: dict,
    technical_data: dict,
) -> tuple[bool, list[str]]:
    """Check if any signal blocker fired — auto-AVOID overrides the score.

    Blockers exist because the score-based action mapping isn't sufficient
    on its own. A 78-score ticker with fraud allegations is still a no-go.
    Each blocker is backtested-validated and reflects a category of
    failure where the score lies about the underlying risk.

    The 6 blockers, in order of severity:

      1. FRAUD / LEGAL RISK
         Triggers if any of these keywords appear in the X sentiment
         summary, top themes, or breaking news:
           fraud, sec investigation, lawsuit, scam, ponzi, insider trading
         Why: an earnings beat means nothing if the SEC is closing in.

      2. (Reserved — was "2+ consecutive earnings misses" in earlier
         versions; removed because the data wasn't reliable enough.)

      3. HOSTILE MACRO ENVIRONMENT
         Triggers if `macro_data.environment == "hostile"` (set by
         `macro_scanner.classify_macro_environment` based on VIX + Fed
         funds + CPI). Why: even great companies fall in bad regimes.

      4. SUSPICIOUSLY LOW VOLUME
         Two sub-checks:
           • volume_zscore < -2.0  (today's volume is 2+ std-devs below
             the 20-day average — institutional desertion)
           • volume_avg < 50,000   (chronically illiquid — slippage will
             kill any alpha you think you have)

      5. OVERBOUGHT RSI > 75
         Backtest validation: tickers with RSI > 75 had a 60%+ failure
         rate on BUY signals. The momentum is exhausted. Auto-AVOID
         protects against chasing tops.

      6. SMA200 OVEREXTENSION > 50%
         Backtest validation: stocks trading more than 50% above their
         200-day moving average have INVERTED returns over the next
         20 days. Gravity wins. Auto-AVOID.

    NOTE: This function is NOT called for tech-only signals (those that
    were below the top-15 by pre-score and skipped AI synthesis). The
    brain re-checks blockers 4-6 in `_eval_brain_trust_tier` for its
    Tier 3 path so it can't auto-buy a tech-only signal that would
    have been blocked here.

    Args:
        grok_data: Sentiment dict (used for fraud keyword scan).
        fundamental_data: Fundamentals (currently unused after the
            earnings-miss blocker was removed; kept in the signature
            for future use).
        macro_data: Macro snapshot (used for environment check).
        technical_data: Technical indicators (used for RSI/volume/SMA).

    Returns:
        (is_blocked, reasons)

        is_blocked: True if any blocker fired.
        reasons: List of human-readable blocker descriptions. Shown in
            the signal's reasoning text and logged as a warning.
    """
    reasons = []

    # 1. Fraud / legal risk in sentiment
    fraud_keywords = ["fraud", "sec investigation", "lawsuit", "scam", "ponzi", "insider trading"]
    sentiment_text = (
        grok_data.get("summary", "") + " " + " ".join(grok_data.get("top_themes", []))
    ).lower()
    for keyword in fraud_keywords:
        if keyword in sentiment_text:
            reasons.append(f"Fraud/legal risk: '{keyword}' detected in X sentiment")
            break

    news = grok_data.get("breaking_news", "")
    if news:
        for keyword in fraud_keywords:
            if keyword in news.lower():
                reasons.append(f"Breaking news red flag: '{keyword}'")
                break

    # 3. Hostile macro
    if macro_data.get("environment") == "hostile":
        reasons.append(f"Hostile macro (VIX={macro_data.get('vix')}, Fed={macro_data.get('fed_funds_rate')}%)")

    # 4. Suspicious volume
    vol_z = technical_data.get("volume_zscore")
    if vol_z is not None and vol_z < -2.0:
        reasons.append(f"Suspiciously low volume (Z-score: {vol_z:.2f})")
    vol_avg = technical_data.get("volume_avg")
    if vol_avg is not None and vol_avg < 50_000:
        reasons.append(f"Very low avg volume: {vol_avg:,.0f}")

    # 5. Overbought RSI blocker (backtest-validated)
    rsi = technical_data.get("rsi")
    if rsi is not None and rsi > 75:
        reasons.append(f"RSI overbought at {rsi:.0f} (>75 has inverted win rate)")

    # 6. SMA200 overextension — backtest shows tickers >50% above SMA200 fail most BUYs
    sma200_dist = technical_data.get("vs_sma200")
    if sma200_dist is not None and sma200_dist > 50:
        reasons.append(f"Extreme overextension: {sma200_dist:.0f}% above SMA200 (>50% has inverted returns)")

    is_blocked = len(reasons) > 0
    if is_blocked:
        logger.warning(f"Signal BLOCKED: {', '.join(reasons)}")

    return is_blocked, reasons


# ============================================================
# STATUS MANAGEMENT
# ============================================================

def determine_status(
    current_action: str,
    current_score: int,
    previous_signal: dict | None,
) -> str:
    """Decide a signal's STATUS by comparing it to the previous signal for the same ticker.

    The STATUS field tells the user (and the brain) HOW the signal evolved
    relative to the last scan. Same action twice in a row is "CONFIRMED".
    A worsening signal is "WEAKENING". A reversal is "CANCELLED". An
    improving signal is "UPGRADED".

    Status transitions:

      previous = None (first time we see this ticker)
        → CONFIRMED  (no comparison possible)

      previous BUY → current SELL/AVOID
        → CANCELLED  (the BUY thesis is dead)

      current_score < previous_score - 15  (lost 15+ points)
        → WEAKENING  (signal eroding even if action unchanged)

      current_score > previous_score + 10  (gained 10+ points)
        → UPGRADED   (signal improving)

      previous HOLD → current BUY
        → UPGRADED   (HOLD that strengthened to a BUY is a meaningful change)

      Otherwise
        → CONFIRMED  (unchanged or minor drift)

    The 15-point WEAKENING threshold is asymmetric with the 10-point
    UPGRADED threshold on purpose: we want to surface deterioration
    earlier than improvement (catching exits is more time-sensitive
    than catching entries).

    Args:
        current_action: BUY/HOLD/SELL/AVOID for this scan's signal.
        current_score: 0-100 score for this scan's signal.
        previous_signal: The most recent signal record for the same
            ticker, or None if this is the first time we see it.

    Returns:
        One of: "CONFIRMED", "WEAKENING", "UPGRADED", "CANCELLED".
    """
    if previous_signal is None:
        return "CONFIRMED"

    prev_score = previous_signal.get("score", 0)
    prev_action = previous_signal.get("action", "HOLD")

    if prev_action == "BUY" and current_action in ("SELL", "AVOID"):
        return "CANCELLED"
    if current_score < prev_score - 15:
        return "WEAKENING"
    if current_score > prev_score + 10:
        return "UPGRADED"
    if prev_action == "HOLD" and current_action == "BUY":
        return "UPGRADED"

    return "CONFIRMED"


# ============================================================
# PRIVATE SCORING HELPERS
# ============================================================

def _score_dividend_reliability(fund_data: dict) -> float:
    """Score dividend reliability (0-100)."""
    score = 50.0
    dy = fund_data.get("dividend_yield")
    if dy is not None:
        if dy > 0.05:
            score += 25
        elif dy > 0.03:
            score += 15
        elif dy > 0.01:
            score += 5
        elif dy == 0:
            score -= 30

    pr = fund_data.get("payout_ratio")
    if pr is not None:
        if 0.3 <= pr <= 0.6:
            score += 15
        elif pr > 0.85:
            score -= 15

    return max(0, min(100, score))


def _score_short_squeeze(fund_data: dict, technical_data: dict) -> float:
    """Bonus score for short squeeze potential (0-20).

    High short float + bullish momentum = squeeze catalyst.
    Only applies as a bonus, never penalizes.
    """
    short_float = fund_data.get("short_percent_of_float")
    if short_float is None or short_float < 0.05:
        return 0

    bonus = 0
    # High short interest (>10%)
    if short_float >= 0.20:
        bonus += 12
    elif short_float >= 0.10:
        bonus += 8
    else:
        bonus += 4

    # Bullish momentum confirmation
    rsi = technical_data.get("rsi")
    macd_hist = technical_data.get("macd_histogram")
    if rsi is not None and 50 <= rsi <= 70 and macd_hist is not None and macd_hist > 0:
        bonus += 8

    return min(20, bonus)


def _score_quality(fund_data: dict) -> float:
    """Score company quality (0-100) — Fama-French QMJ inspired.

    Quality = profitability + earnings stability + low leverage.
    High-quality companies have persistent alpha with lower drawdowns.
    """
    score = 50.0

    # Profitability (ROE proxy via profit margins)
    margin = fund_data.get("profit_margin") or fund_data.get("profitMargins")
    if margin is not None:
        if margin > 0.25:
            score += 15
        elif margin > 0.15:
            score += 10
        elif margin > 0.08:
            score += 5
        elif margin < 0:
            score -= 15

    # Earnings growth stability
    eg = fund_data.get("eps_growth")
    rg = fund_data.get("revenue_growth")
    if eg is not None and rg is not None:
        if eg > 0.10 and rg > 0.05:
            score += 10  # Growing on both lines
        elif eg > 0 and rg > 0:
            score += 5
        elif eg < -0.10:
            score -= 10

    # Low leverage
    dte = fund_data.get("debt_to_equity")
    if dte is not None:
        if dte < 30:
            score += 10
        elif dte < 80:
            score += 5
        elif dte > 200:
            score -= 10

    # Forward P/E below trailing P/E = earnings acceleration
    fpe = fund_data.get("forward_pe")
    pe = fund_data.get("pe_ratio")
    if fpe is not None and pe is not None and pe > 0:
        if fpe < pe * 0.85:
            score += 10  # Strong earnings acceleration
        elif fpe < pe:
            score += 5

    return max(0, min(100, score))


def _score_momentum_factor(technical_data: dict) -> float:
    """Score momentum factor (0-100) — Fama-French UMD inspired.

    Uses 3-month and 6-month returns. Momentum winners (positive 3m+6m)
    keep winning on 1-12 month horizon. Strongest documented factor.
    """
    score = 50.0

    mom_3m = technical_data.get("momentum_3m")
    mom_6m = technical_data.get("momentum_6m")

    if mom_3m is not None:
        if mom_3m > 15:
            score += 15
        elif mom_3m > 5:
            score += 10
        elif mom_3m > 0:
            score += 3
        elif mom_3m < -15:
            score -= 15
        elif mom_3m < -5:
            score -= 10
        elif mom_3m < 0:
            score -= 3

    if mom_6m is not None:
        if mom_6m > 20:
            score += 10
        elif mom_6m > 10:
            score += 5
        elif mom_6m < -20:
            score -= 10
        elif mom_6m < -10:
            score -= 5

    # ADX confirmation: strong trend makes momentum more reliable
    adx = technical_data.get("adx")
    if adx is not None:
        if adx > 30:
            score += 5  # Strong trend confirmation
        elif adx < 15:
            score -= 5  # No trend = momentum unreliable

    return max(0, min(100, score))


# ============================================================
# PROBABILITY VS BENCHMARK
# ============================================================

# Derived from backtest: 18,759 signals across ~18 months (tech-only, no AI).
# Maps score ranges to 20-day probability of beating SPY.
# AI-analyzed signals add ~5% to win rate over tech-only baseline.
_PROB_VS_SPY = {
    "SAFE_INCOME": {
        (80, 101): 68.0,
        (70, 80): 64.5,
        (65, 70): 62.2,
        (60, 65): 58.4,
        (55, 60): 54.0,
        (0, 55): 48.0,
    },
    "HIGH_RISK": {
        (80, 101): 62.0,
        (70, 80): 59.5,
        (65, 70): 56.7,
        (60, 65): 53.6,
        (55, 60): 50.5,
        (0, 55): 45.0,
    },
}


def compute_probability_vs_spy(score: int, bucket: str, has_ai: bool = False) -> float:
    """Compute probability of beating SPY in 20 days based on backtest data.

    Returns a percentage (e.g. 62.2 means "62.2% chance of beating SPY").
    AI-analyzed signals get a +5% boost over tech-only baseline.
    """
    table = _PROB_VS_SPY.get(bucket, _PROB_VS_SPY["HIGH_RISK"])
    prob = 50.0  # default: coin flip
    for (lo, hi), p in table.items():
        if lo <= score < hi:
            prob = p
            break
    if has_ai:
        prob = min(85.0, prob + 5.0)
    return round(prob, 1)


# ============================================================
# FACTOR IMPACT LABELS
# ============================================================

def compute_factor_labels(breakdown: dict, bucket: str, asset_type: str = "STOCK") -> dict:
    """Convert raw sub-scores into qualitative labels: Strong / Neutral / Weak.

    Thresholds: weighted contribution >= 60% of max -> Strong, >= 35% -> Neutral, else Weak.
    """
    if bucket == "SAFE_INCOME":
        factors = ["dividend_reliability", "fundamental_health", "macro", "sentiment"]
        if asset_type == "ETF":
            max_weights = {"fundamental_health": 40, "macro": 30, "dividend_reliability": 15, "sentiment": 15}
        else:
            max_weights = {"dividend_reliability": 35, "fundamental_health": 30, "macro": 25, "sentiment": 10}
    else:
        factors = ["sentiment", "catalyst", "technical_momentum", "fundamentals"]
        max_weights = {"sentiment": 35, "catalyst": 30, "technical_momentum": 25, "fundamentals": 10}

    labels = {}
    for factor in factors:
        weighted_val = breakdown.get(factor, 0)
        max_possible = max_weights.get(factor, 25)
        pct_of_max = (weighted_val / max_possible * 100) if max_possible > 0 else 0
        if pct_of_max >= 60:
            labels[factor] = "Strong"
        elif pct_of_max >= 35:
            labels[factor] = "Neutral"
        else:
            labels[factor] = "Weak"
    return labels


def _score_fundamentals(fund_data: dict, bucket: str) -> float:
    """Score fundamentals (0-100) — tuned from backtest."""
    score = 50.0

    if bucket == "SAFE_INCOME":
        dy = fund_data.get("dividend_yield")
        if dy is not None:
            if dy > 0.04:
                score += 20
            elif dy > 0.02:
                score += 10
            elif dy == 0:
                score -= 15

        dte = fund_data.get("debt_to_equity")
        if dte is not None:
            if dte < 50:
                score += 10
            elif dte > 150:
                score -= 10

        margin = fund_data.get("profit_margin") or fund_data.get("profitMargins")
        if margin is not None:
            if margin > 0.20:
                score += 10
            elif margin > 0.10:
                score += 5
    else:
        eg = fund_data.get("eps_growth")
        if eg is not None:
            if eg > 0.25:
                score += 20
            elif eg > 0.10:
                score += 10
            elif eg < 0:
                score -= 10

        rg = fund_data.get("revenue_growth")
        if rg is not None:
            if rg > 0.15:
                score += 10
            elif rg < 0:
                score -= 5

        fpe = fund_data.get("forward_pe")
        pe = fund_data.get("pe_ratio")
        if fpe is not None and pe is not None and fpe < pe:
            score += 10

    return max(0, min(100, score))


def _score_macro(macro_data: dict) -> float:
    """Score macro environment (0-100) — includes VIX and Fear & Greed Index."""
    env = macro_data.get("environment", "neutral")
    vix = macro_data.get("vix")
    fear_greed = macro_data.get("fear_greed")

    env_score = 50
    if env == "favorable":
        env_score = 80
    elif env == "hostile":
        env_score = 20

    vix_score = 55
    if vix is not None:
        v = float(vix) if not isinstance(vix, (int, float)) else vix
        if v < 15:
            vix_score = 75
        elif v < 20:
            vix_score = 65
        elif v < 25:
            vix_score = 50
        elif v < 35:
            vix_score = 35
        else:
            vix_score = 20

    # Fear & Greed Index: 0 = Extreme Fear, 100 = Extreme Greed
    # Maps directly to a 0-100 score (higher = more bullish macro)
    fg_score = 50
    if fear_greed and isinstance(fear_greed, dict):
        fg_val = fear_greed.get("score")
        if fg_val is not None:
            fg_score = max(0, min(100, float(fg_val)))

    return env_score * 0.45 + vix_score * 0.30 + fg_score * 0.25


def _score_sentiment(grok_data: dict) -> float:
    """Score sentiment (0-100) combining Grok/X sentiment with Barchart options flow.

    When Twitter sentiment and options flow agree, boost confidence (+/- 8 points).
    When they conflict, dampen toward neutral (flag uncertainty for AI synthesis).
    """
    base_score = max(0, min(100, float(grok_data.get("score", 50))))

    options_flow = grok_data.get("_options_flow")
    if not options_flow or not isinstance(options_flow, dict):
        return base_score

    options_direction = options_flow.get("signal", "neutral")
    options_strength = options_flow.get("signal_strength", 0)

    if options_direction == "neutral" or options_strength < 10:
        return base_score

    # Determine sentiment direction from base score
    if base_score >= 60:
        sentiment_direction = "bullish"
    elif base_score <= 40:
        sentiment_direction = "bearish"
    else:
        sentiment_direction = "neutral"

    # Agreement: both point same way → boost conviction
    if sentiment_direction == options_direction:
        boost = min(8, options_strength * 0.3)
        if options_direction == "bullish":
            return min(100, base_score + boost)
        else:
            return max(0, base_score - boost)

    # Conflict: sentiment and options disagree → dampen toward 50 (uncertain)
    if sentiment_direction != "neutral" and options_direction != sentiment_direction:
        dampen = min(6, options_strength * 0.2)
        if base_score > 50:
            return base_score - dampen
        else:
            return base_score + dampen

    return base_score


def _score_catalyst(synthesis: dict) -> float:
    """Score catalyst presence (0-100)."""
    if not synthesis.get("catalyst"):
        return 30

    score = 60
    cat_date = synthesis.get("catalyst_date")
    if cat_date:
        try:
            days_away = (date.fromisoformat(cat_date) - date.today()).days
            if 0 <= days_away <= 30:
                score += 30
            elif 30 < days_away <= 90:
                score += 15
        except (ValueError, TypeError):
            score += 10
    else:
        score += 10

    return min(100, score)


def _score_technical_momentum(technical_data: dict) -> float:
    """Score technical momentum (0-100) — backtest-tuned.

    Key insight: RSI 50-65 sweet spot, high MACD histogram
    predicts surges, momentum > 5% is a trap.
    """
    score = 50.0

    rsi = technical_data.get("rsi")
    if rsi is not None:
        if 50 <= rsi <= 65:
            score += 15  # Sweet spot
        elif 40 <= rsi < 50:
            score += 5
        elif rsi > 70:
            score -= 15  # Overbought trap
        elif rsi < 30:
            score -= 5   # Falling knife

    macd_hist = technical_data.get("macd_histogram")
    if macd_hist is not None:
        if macd_hist > 2.0:
            score += 15  # Strong bullish (surger signal)
        elif macd_hist > 0:
            score += 8
        else:
            score -= 10

    vol_z = technical_data.get("volume_zscore")
    if vol_z is not None:
        if 1.0 < vol_z <= 2.0:
            score += 8   # Moderate volume confirmation
        elif vol_z > 2.0:
            score += 5   # High volume — less reliable
        elif vol_z < -1.0:
            score -= 8

    sma_cross = technical_data.get("sma_cross")
    if sma_cross == "golden_cross":
        score += 12
    elif sma_cross == "death_cross":
        score -= 12

    return max(0, min(100, score))
