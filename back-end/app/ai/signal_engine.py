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

  • A strongly positive MACD histogram predicts surges. The original
    rule used a raw `hist > 2.0`, which is in PRICE units (2.0 is huge
    on a $20 stock and noise on a $900 one). It is now scored in ATR
    units (hist / ATR14 > settings.macd_hist_strong_atr) so it is
    price-invariant.

  • Stocks > 50% above their SMA200 have INVERTED returns
    (gravity wins). Auto-blocked.

  • Score ceiling at 90 — scores > 90 are force-converted to HOLD
    (overbought guard; `score_to_action`).

  NOTE (2026-09): the 2021-2026 study (8,996 trades, tech layer only)
  found the score has NO monotonic edge vs SPY, and names above RSI 75
  did best (n=104). The findings above are historical priors, not
  validated rules; the score no longer gates or ranks brain entries.

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
    Bonus:          Momentum factor bonus (up to +6) from 3m+6m returns.

============================================================
DYNAMIC ADJUSTMENTS
============================================================

Several adjustments fire on top of the base score:

  Sentiment weight reduction (low-mention tickers)
    If grok_data.mention_count < 100, the sentiment is unreliable. The
    sentiment weight collapses from 35% (HIGH_RISK) or 10% (SAFE_INCOME)
    down to 5%, and the freed weight is spread PROPORTIONALLY over the
    other components (it used to all go to technical_momentum / macro).

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

  1. MATERIAL red flag in CITED evidence: severity high/critical, or
     category fraud/accounting/going_concern at severity >= medium
     (see `red_flag_block_reason`). Flags without severity and cited
     breaking news fall back to keywords (fraud, sec investigation,
     scam, ponzi, insider trading — plain "lawsuit" no longer blocks)
  2. Hostile macro environment (high VIX + high Fed funds + high CPI)
  3. Suspiciously low volume (Z-score < -2.0 OR avg < 50K)
  4. Overbought RSI > 75 (backtest: 60%+ failure rate)
  5. SMA200 overextension > 50% (backtest: inverted returns)

NOTE: blockers run for BOTH AI-analyzed and tech-only signals.

Separately, `check_entry_blackout` downgrades a new BUY to HOLD when
the next earnings report is within settings.earnings_blackout_trading_days
trading sessions (it is not an AVOID — it must not trigger sells of
positions already held).

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
      • Momentum factor bonus for HIGH_RISK (no short-squeeze bonus).

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
        market_regime: "TRENDING" / "VOLATILE" / "CRISIS" / "RECOVERY"
            (RECOVERY gets no adjustment) — drives the
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
              total, market_regime, regime_adjustment_*,
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
        # Populated by scan_service from signals/earnings.get_earnings_context.
        # last_eps_surprise_pct is in PERCENT (Yahoo "Surprise(%)"), so a
        # 3% beat is 3.0. price_change_5d is a fraction.
        days_since_earnings = fundamental_data.get("days_since_last_earnings")
        days_since_earnings = 999 if days_since_earnings is None else days_since_earnings
        eps_surprise = fundamental_data.get("last_eps_surprise_pct", 0) or 0
        days_to_earnings = fundamental_data.get("days_to_next_earnings")
        days_to_earnings = 999 if days_to_earnings is None else days_to_earnings
        price_change_5d = (technical_data or {}).get("price_change_5d", 0) or 0

        if (days_since_earnings <= 3 and eps_surprise > 3.0 and price_change_5d < 0.10):
            catalyst_type = "PEAD"
        elif 0 <= days_to_earnings <= 30:
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
            effective_sent_w = min(0.05, weights["sentiment"])
            _redistribute_weight(weights, "sentiment", effective_sent_w)
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
            effective_sent_w = min(0.05, weights["sentiment"])
            _redistribute_weight(weights, "sentiment", effective_sent_w)
        else:
            effective_sent_w = weights["sentiment"]

        total = (
            raw_sentiment_score * weights["sentiment"]
            + catalyst_score * weights["catalyst"]
            + technical_score * weights["technical_momentum"]
            + fundamental_score * weights["fundamentals"]
        )

        # No short-squeeze bonus (removed 2026-09): high short interest
        # predicts LOWER average returns. The only short-interest input is
        # the enrichment short-trend adjustment (rising SI = -1).

        # Momentum factor bonus (strong 3m+6m trend = higher conviction)
        momentum_bonus = max(0, (momentum_factor_score - 60) * 0.15)  # Up to +6 points
        total = total + momentum_bonus

        breakdown = {
            "sentiment": round(raw_sentiment_score * weights["sentiment"], 1),
            "catalyst": round(catalyst_score * weights["catalyst"], 1),
            "technical_momentum": round(technical_score * weights["technical_momentum"], 1),
            "fundamentals": round(fundamental_score * weights["fundamentals"], 1),
            "momentum_factor_score": round(momentum_factor_score, 1),
            "momentum_bonus": round(momentum_bonus, 1),
        }

    # ── Richer-data adjustment (estimate revisions, relative strength,
    # insider buying, short-interest trend). UNVALIDATED priors, small
    # and capped at ±ENRICHMENT_CAP; stocks only. Disabled (0) by
    # settings.enrichment_scoring_enabled=False so backtests / outcome
    # tracking can measure the lift. See `_score_enrichment`.
    enrichment_bonus, enrichment_detail = 0.0, {}
    if asset_type == "STOCK" and getattr(settings, "enrichment_scoring_enabled", True):
        enrichment_bonus, enrichment_detail = _score_enrichment(fundamental_data, technical_data)
        total = total + enrichment_bonus
    breakdown["enrichment_bonus"] = round(enrichment_bonus, 1)
    if enrichment_detail:
        breakdown["enrichment_detail"] = enrichment_detail

    score = max(0, min(100, total))

    # ── Regime score multiplier (Part 6) ──
    regime_adjustment_applied = False
    regime_adjustment_note = None

    if market_regime == "VOLATILE" and bucket == "HIGH_RISK":
        score = score * 0.85
        regime_adjustment_applied = True
        regime_adjustment_note = "Score reduced 15%: volatile market regime"
    # RECOVERY: no adjustment. The old x1.10 HIGH_RISK boost was removed
    # (2026-09 audit): sharp rebounds from deep drawdowns are exactly when
    # momentum crashes (Daniel-Moskowitz), so boosting momentum there had
    # the sign backwards.
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


def _redistribute_weight(weights: dict, key: str, new_value: float) -> None:
    """Set weights[key] = new_value and spread the freed weight across the
    OTHER components in proportion to their existing weights (in place).

    Previously the whole freed sentiment weight (0.30 for HIGH_RISK) was
    dumped onto technical_momentum, taking it from 25% to 55%. Grok never
    returned `mention_count`, so that was the case for EVERY HIGH_RISK
    signal: scores were >half short-term technicals, and the strongest
    technical readings (the most extended names) saturated at 85-100 —
    consistent with the observed inverted win rate of 85+/90+ scores.
    Proportional redistribution keeps the documented relative weights.
    """
    freed = weights[key] - new_value
    weights[key] = new_value
    others = [k for k in weights if k != key]
    total_other = sum(weights[k] for k in others)
    if total_other <= 0 or freed <= 0:
        return
    for k in others:
        weights[k] = weights[k] + freed * (weights[k] / total_other)


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

    The 90-ceiling is an unvalidated overbought guard (from an old
    30-ticker test; the 2021-2026 study found no monotonic score edge).
    Scores above 90 are force-converted to HOLD.

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
# TECHNICAL FILTER (brain entry gate, pass/fail — not a ranking)
# ============================================================

def _num(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def technical_filter(
    technical_data: dict | None,
    fundamental_data: dict | None = None,
    asset_class: str | None = None,
    blockers: list[str] | None = None,
) -> tuple[bool, list[str]]:
    """Pass/fail technical gate for a brain entry. NOT a score.

    Why: the 2021-2026 signal study (docs/backtests/live-2021-2026/report.md,
    8,996 per-symbol trades) found that a higher `compute_score` did not
    predict better returns (band <50 best, 60-64 worst) and blocked vs
    unblocked did not separate outcomes. So instead of "higher score =
    stronger buy", the brain asks only "is this a sane long setup?".

    Conditions (all must hold; every failure is reported, in this order):
      trend      price > SMA200 AND SMA50 > SMA200
                 (SMA50/SMA200/price missing → "insufficient_history",
                 trend not evaluated)
      extension  RSI(14) <= tech_filter_max_rsi ("rsi_overbought") and price
                 <= tech_filter_max_ext_sma50_pct % above SMA50
                 ("overextended_vs_sma50")
      liquidity  20-session average dollar volume >= tech_filter_min_dollar_volume
                 (stocks/ETFs, native currency) or
                 tech_filter_min_dollar_volume_crypto (crypto; Yahoo crypto
                 volume is already USD-denominated). No volume data →
                 "no_liquidity_data"; below the floor → "low_liquidity".
      blocker    any active `check_blockers` reason passed in `blockers`
                 → "active_blocker".

    Args:
        technical_data: `compute_indicators` output (sma_50, sma_200, rsi,
            last_close/current_price, dollar_volume_avg_20 /
            volume_avg_20 / volume_avg).
        fundamental_data: used only to recognise crypto via quote_type.
        asset_class: "STOCK" | "ETF" | "CRYPTO" (None → inferred).
        blockers: reasons from `check_blockers`, when available.

    Returns:
        (passed, reasons) — reasons is empty when passed.
    """
    t = technical_data or {}
    f = fundamental_data or {}
    reasons: list[str] = []

    price = _num(t.get("last_close")) or _num(t.get("current_price"))
    sma50, sma200 = _num(t.get("sma_50")), _num(t.get("sma_200"))

    if not price or not sma50 or not sma200:
        reasons.append("insufficient_history")
    else:
        if price <= sma200:
            reasons.append("below_sma200")
        if sma50 <= sma200:
            reasons.append("sma50_below_sma200")

    rsi = _num(t.get("rsi"))
    if rsi is not None and rsi > settings.tech_filter_max_rsi:
        reasons.append("rsi_overbought")
    if price and sma50:
        ext_pct = (price / sma50 - 1.0) * 100.0
        if ext_pct > settings.tech_filter_max_ext_sma50_pct:
            reasons.append("overextended_vs_sma50")

    is_crypto = (
        (asset_class or "").upper() == "CRYPTO"
        or (f.get("quote_type") or "").upper() == "CRYPTOCURRENCY"
    )
    dollar_vol = None
    if is_crypto:
        # Yahoo quotes crypto volume in USD already — do not multiply by price.
        dollar_vol = _num(t.get("volume_avg_20")) or _num(t.get("volume_avg"))
    else:
        dollar_vol = _num(t.get("dollar_volume_avg_20"))
        if dollar_vol is None and price:
            shares = _num(t.get("volume_avg_20")) or _num(t.get("volume_avg"))
            dollar_vol = shares * price if shares is not None else None
    floor = (settings.tech_filter_min_dollar_volume_crypto if is_crypto
             else settings.tech_filter_min_dollar_volume)
    if dollar_vol is None:
        reasons.append("no_liquidity_data")
    elif dollar_vol < floor:
        reasons.append("low_liquidity")

    if blockers:
        reasons.append("active_blocker")

    return (not reasons), reasons


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

      1. MATERIAL RED FLAG (cited evidence only)
         A red flag with a cited url blocks when the sentiment model
         rated it severity high/critical, or category fraud / accounting
         / going_concern at severity >= medium — unless a stated monetary
         impact is < 1% of market cap for a non-integrity category (a
         $5.7B patent verdict at a ~$5T company is immaterial). Flags
         without severity (old prompts / cached results) and cited
         breaking news use the keyword fallback: fraud, sec
         investigation, scam, ponzi, insider trading. Plain "lawsuit" no
         longer blocks — routine litigation is not a fraud signal.
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

    NOTE: called for both AI-analyzed and tech-only signals. The fraud
    check only reads cited evidence (`red_flags` entries with a url,
    `breaking_news`) and is skipped when sentiment errored/confidence 0.

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

    grok_data = grok_data or {}
    fundamental_data = fundamental_data or {}
    macro_data = macro_data or {}
    technical_data = technical_data or {}

    # 1. Material red flag — CITED evidence only.
    # The sentiment provider validates `red_flags` (list of {text, url,
    # severity?, category?, estimated_impact_usd?}; each url must be one
    # of the live-search citations) and `breaking_news` (kept only when
    # its url is cited). The free-text `summary` / `top_themes` are
    # uncited LLM prose — a keyword there is as likely hallucinated or
    # generic ("no lawsuit risk") as real, so they are ignored. A failed
    # / uncited sentiment call (error set or confidence 0) contributes
    # nothing. Materiality rules: see `red_flag_block_reason`.
    sentiment_ok = not grok_data.get("error") and (grok_data.get("confidence") or 0) > 0
    if sentiment_ok:
        market_cap = fundamental_data.get("market_cap")
        for flag in grok_data.get("red_flags") or []:
            reason = red_flag_block_reason(flag, market_cap)
            if reason:
                reasons.append(reason)
                break

        news = grok_data.get("breaking_news") or ""
        if news and isinstance(news, str):
            hit = _fraud_keyword(news)
            if hit:
                reasons.append(f"Breaking news red flag: '{hit}'")

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


# Keyword fallback for flags WITHOUT a model severity (older prompt /
# cached sentiment) and for cited breaking news. "lawsuit" was dropped:
# routine litigation is not a fraud signal and blocked mega-caps on
# immaterial verdicts.
FRAUD_KEYWORDS = ("fraud", "sec investigation", "scam", "ponzi", "insider trading")
_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
# Categories that block from "medium" up — integrity / solvency issues
# where the stated dollar amount understates the damage.
_INTEGRITY_CATEGORIES = ("fraud", "accounting", "going_concern")
# A stated monetary impact below this fraction of market cap makes a
# non-integrity flag immaterial even if the model rated it "high".
IMMATERIAL_IMPACT_FRACTION = 0.01


def _fraud_keyword(text: str) -> str | None:
    low = (text or "").lower()
    return next((k for k in FRAUD_KEYWORDS if k in low), None)


def red_flag_block_reason(flag: dict, market_cap: float | None = None) -> str | None:
    """Return a blocker reason if this red flag is MATERIAL, else None.

    Rules (a url — i.e. a cited source — is always required):
      • severity present (new sentiment schema):
          - category fraud / accounting / going_concern and severity >= medium → block
          - any category with severity high / critical → block, EXCEPT a
            non-integrity flag whose stated `estimated_impact_usd` is
            < IMMATERIAL_IMPACT_FRACTION (1%) of market cap
          - everything else (low; medium litigation/regulatory/other) → no block
      • severity absent (legacy): block only on the fraud keywords
        (fraud, sec investigation, scam, ponzi, insider trading).
    """
    if not isinstance(flag, dict):
        return None
    url = flag.get("url")
    text = str(flag.get("text") or "")
    if not url or not text:
        return None

    severity = str(flag.get("severity") or "").lower()
    if severity not in _SEVERITY_RANK:
        hit = _fraud_keyword(text)
        return f"Fraud/legal risk: '{hit}' in cited red flag ({url})" if hit else None

    rank = _SEVERITY_RANK[severity]
    category = str(flag.get("category") or "other").lower()
    if category in _INTEGRITY_CATEGORIES and rank >= _SEVERITY_RANK["medium"]:
        return f"Material red flag ({category}, {severity}): {text[:120]} ({url})"
    if rank >= _SEVERITY_RANK["high"]:
        impact = flag.get("estimated_impact_usd")
        try:
            frac = float(impact) / float(market_cap) if impact and market_cap else None
        except (TypeError, ValueError, ZeroDivisionError):
            frac = None
        if frac is not None and frac < IMMATERIAL_IMPACT_FRACTION:
            logger.info(
                f"Red flag rated {severity} but stated impact is {frac:.2%} of market cap "
                f"— treated as immaterial: {text[:80]}"
            )
            return None
        return f"Material red flag ({category}, {severity}): {text[:120]} ({url})"
    return None


def check_entry_blackout(fundamental_data: dict) -> str | None:
    """Return a reason string if a NEW BUY must be suppressed, else None.

    Earnings blackout: no new BUY when the next earnings report is within
    `settings.earnings_blackout_trading_days` trading sessions (0 = report
    today). A binary gap event inside a short-term holding window is a
    coin flip the score cannot see.

    This is deliberately NOT a blocker (blockers produce AVOID, which the
    brain and watchlist alerts treat as a sell signal for held positions).
    Callers downgrade BUY -> HOLD.

    Reads `trading_days_to_next_earnings`, set by scan_service from
    `signals.earnings.get_earnings_context` (or the fundamentals'
    `earnings_date` fallback). Missing data -> no blackout.
    """
    fundamental_data = fundamental_data or {}
    n = settings.earnings_blackout_trading_days
    td = fundamental_data.get("trading_days_to_next_earnings")
    if td is None or n <= 0:
        return None
    try:
        td = int(td)
    except (TypeError, ValueError):
        return None
    if 0 <= td <= n:
        return (
            f"Earnings blackout: next report in {td} trading day(s) "
            f"({fundamental_data.get('next_earnings_date') or fundamental_data.get('earnings_date')}), "
            f"limit {n}"
        )
    return None


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

ENRICHMENT_CAP = 5.0


def _score_enrichment(fund_data: dict, technical_data: dict) -> tuple[float, dict]:
    """Additive score points from the richer equity data (±ENRICHMENT_CAP).

    ALL WEIGHTS HERE ARE UNVALIDATED PRIORS, deliberately small. They
    encode well-documented effects (analyst estimate-revision momentum,
    industry-relative price momentum, opportunistic insider buying,
    rising short interest as informed pessimism) but have NOT been
    backtested on this system. `settings.enrichment_scoring_enabled`
    turns them off; `breakdown["enrichment_detail"]` records each part so
    outcome tracking can attribute results. Missing data → 0.

      revisions (±3): mean % change of consensus EPS estimates
          (`eps_revision_momentum`): >=+5 → +2, >=+1 → +1, <=-1 → -1,
          <=-5 → -2; plus ±1 when 30-day up/down revision counts differ
          by >= 3.
      relative_strength (±2): mean of 3m/6m return minus the sector ETF
          (XIU.TO for TSX; SPY when no sector benchmark), in %-points:
          >=+10 → +2, >=+3 → +1, <=-3 → -1, <=-10 → -2.
      insider_buying (0..+1): net insider shares bought over 6 months > 0
          with >= 2 purchase transactions. Selling is NOT penalized
          (usually diversification / tax / comp-driven).
      short_interest (-1..0): shares short up >= 25% month over month.
    """
    from app.scanners.indicators import compute_relative_strength

    fund_data = fund_data or {}
    detail: dict = {}

    def _f(key):
        v = fund_data.get(key)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    rev = 0.0
    m = _f("eps_revision_momentum")
    if m is not None:
        if m >= 5:
            rev += 2
        elif m >= 1:
            rev += 1
        elif m <= -5:
            rev -= 2
        elif m <= -1:
            rev -= 1
    up, down = _f("eps_revisions_up_30d"), _f("eps_revisions_down_30d")
    if up is not None or down is not None:
        net = (up or 0) - (down or 0)
        if net >= 3:
            rev += 1
        elif net <= -3:
            rev -= 1
    rev = max(-3.0, min(3.0, rev))
    if rev:
        detail["revisions"] = rev

    rs = compute_relative_strength(technical_data or {}, fund_data)
    rs_vals = [rs[k] for k in ("rs_vs_benchmark_3m", "rs_vs_benchmark_6m") if k in rs]
    if not rs_vals:
        rs_vals = [rs[k] for k in ("rs_vs_spy_3m", "rs_vs_spy_6m") if k in rs]
    if rs_vals:
        avg = sum(rs_vals) / len(rs_vals)
        pts = 2 if avg >= 10 else 1 if avg >= 3 else -2 if avg <= -10 else -1 if avg <= -3 else 0
        if pts:
            detail["relative_strength"] = float(pts)

    net_sh, buys = _f("insider_net_shares_6m"), _f("insider_buy_count_6m")
    if net_sh is not None and net_sh > 0 and (buys or 0) >= 2:
        detail["insider_buying"] = 1.0

    sic = _f("short_interest_change_pct")
    if sic is not None and sic >= 25:
        detail["short_interest"] = -1.0

    total = max(-ENRICHMENT_CAP, min(ENRICHMENT_CAP, sum(detail.values())))
    return total, detail


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

# The old score -> "probability of beating SPY" table (45-68%, from an
# 18,759-signal tech-only backtest, +5 for AI) was removed in 2026-09: the
# 2021-2026 study found about 40% of trades beat SPY in EVERY score band,
# so the table invented probabilities. Until a calibrated model exists this
# returns None and the UI hides the badge (it renders only when != null).
def compute_probability_vs_spy(score: int, bucket: str, has_ai: bool = False) -> float | None:
    """Probability of beating SPY — not available (no calibrated model). Returns None."""
    return None


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


def _macd_hist_atr(technical_data: dict) -> float | None:
    """MACD histogram in ATR units (price-invariant). None if unavailable."""
    v = technical_data.get("macd_hist_atr")
    if v is not None:
        return float(v)
    hist = technical_data.get("macd_histogram")
    atr = technical_data.get("atr")
    if hist is None or not atr or atr <= 0:
        return None
    return float(hist) / float(atr)


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
        hist_atr = _macd_hist_atr(technical_data)
        if hist_atr is not None and hist_atr > settings.macd_hist_strong_atr:
            score += 15  # Strong bullish (surger signal), price-invariant
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
