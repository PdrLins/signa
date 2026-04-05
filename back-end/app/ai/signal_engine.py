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
        weights = {**settings.safe_income_weights}
        dividend_score = _score_dividend_reliability(fundamental_data)
        fundamental_score = _score_fundamentals(fundamental_data, bucket)
        macro_score = _score_macro(macro_data)

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

        breakdown = {
            "dividend_reliability": round(dividend_score * weights["dividend_reliability"], 1),
            "fundamental_health": round(fundamental_score * weights["fundamental_health"], 1),
            "macro": round(macro_score * weights["macro"], 1),
            "sentiment": round(raw_sentiment_score * weights["sentiment"], 1),
        }
    else:
        weights = {**settings.high_risk_weights}
        catalyst_score = _score_catalyst(synthesis)
        technical_score = _score_technical_momentum(technical_data)
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

        breakdown = {
            "sentiment": round(raw_sentiment_score * weights["sentiment"], 1),
            "catalyst": round(catalyst_score * weights["catalyst"], 1),
            "technical_momentum": round(technical_score * weights["technical_momentum"], 1),
            "fundamentals": round(fundamental_score * weights["fundamentals"], 1),
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


def score_to_action(score: int) -> str:
    """Convert a composite score to a signal action.

    Backtest-validated: scores above 72 have inverted win rates
    (overbought trap). Apply a ceiling to avoid false BUYs.
    """
    buy_threshold = settings.score_buy
    hold_threshold = settings.score_hold
    ceiling = 90  # Live system has AI — ceiling is higher than backtest

    if score >= buy_threshold and score <= ceiling:
        return "BUY"
    if score > ceiling:
        return "HOLD"  # Overbought — AI confidence is too aggressive
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
    """Score macro environment (0-100) — includes VIX."""
    env = macro_data.get("environment", "neutral")
    vix = macro_data.get("vix")

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

    return env_score * 0.6 + vix_score * 0.4


def _score_sentiment(grok_data: dict) -> float:
    """Pass through sentiment score (already 0-100 from Grok)."""
    return max(0, min(100, float(grok_data.get("score", 50))))


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
