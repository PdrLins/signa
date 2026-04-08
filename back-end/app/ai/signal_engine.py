"""Signal scoring engine — scoring, GEM detection, blocker checks, and status management.

Tuned from backtest analysis (Oct 2024 → Apr 2025, 30 tickers):
- RSI 55-65 sweet spot for HIGH_RISK (57.3% win rate)
- Low volume wins for SAFE_INCOME, moderate volume for HIGH_RISK
- Momentum +1% to +3% is optimal; >5% is a reversal trap
- High MACD histogram predicts surges (missed surgers had 3.3 vs 1.5)
- Score ceiling at 72 — higher scores have INVERTED win rates
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
    """Compute the composite score using bucket-specific weights.

    Includes:
    - Dynamic sentiment weighting based on mention count
    - Contrarian adjustment for extreme sentiment
    - Regime score multiplier for VOLATILE/CRISIS
    - Mutual exclusive PEAD vs PRE_EARNINGS catalyst detection
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
    """Convert a composite score to a signal action.

    Uses bucket-specific thresholds validated by 2-year backtest.
    Safe Income at 62+ → 60.6% win rate. High Risk at 65+ → 52.6%.
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
    """Check if a signal qualifies as a GEM alert.

    All 5 conditions must be true:
    1. Score >= 85
    2. Catalyst within 30 days
    3. Grok sentiment bullish with confidence >= 80
    4. No red flags
    5. Risk/reward >= 3x
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
    """Check if any signal blockers are triggered.

    Blockers (auto-AVOID regardless of score):
    1. Fraud allegations on X
    2. 2+ consecutive earnings misses
    3. Hostile macro environment
    4. Suspiciously low volume
    5. Overbought RSI > 75 (backtest-validated — these fail 60%+ of the time)
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
    """Determine signal status based on comparison with previous signal."""
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
