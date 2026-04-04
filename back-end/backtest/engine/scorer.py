"""Core scoring logic for backtest — tuned from backtest data analysis.

Key findings from data:
- RSI 55-80 wins more than oversold (57.3% vs 52.9%)
- Low volume (< 0.7) wins 57.8%, high volume is noise
- Momentum +1% to +3% is the sweet spot (56.9%), >5% is a trap (46.2%)
- Missed surgers had high MACD histogram and high vs_sma200
- Safe Income: lower RSI + lower volume wins (buy the dip on stable stocks)
- High Risk: higher volume + moderate RSI wins (momentum confirmation)
"""


# ============================================================
# SCORING HELPERS — tuned from backtest analysis
# ============================================================

def _score_rsi_safe(rsi: float) -> float:
    """RSI scoring for SAFE_INCOME — buy the dip on stable stocks.

    Data shows: Safe winners avg RSI 52, losers avg 49.
    Lower RSI on stable stocks = better entry.
    """
    if rsi < 30:
        return 90.0   # Deep value on stable stock
    if rsi < 40:
        return 80.0
    if rsi < 50:
        return 70.0   # Good entry zone
    if rsi <= 60:
        return 60.0
    if rsi <= 70:
        return 40.0   # Getting stretched
    return 20.0        # Overbought — avoid


def _score_rsi_risk(rsi: float) -> float:
    """RSI scoring for HIGH_RISK — needs momentum but not overbought.

    Data shows: Risk winners avg RSI 63, losers avg 66.
    Sweet spot is 50-65 — confirmed momentum without exhaustion.
    """
    if rsi < 30:
        return 30.0   # Falling knife
    if rsi < 40:
        return 40.0
    if rsi < 50:
        return 55.0   # Building momentum
    if rsi <= 65:
        return 80.0   # Sweet spot — confirmed momentum
    if rsi <= 75:
        return 50.0   # Getting hot
    return 20.0        # Overbought — reversal risk


def _score_macd(macd_line: float, macd_signal: float, macd_hist: float) -> float:
    """MACD scoring — data shows high histogram predicts surges.

    Missed surgers had avg macd_hist +3.3 vs normal +1.5.
    Weight histogram strength, not just crossover direction.
    """
    bullish = macd_line > macd_signal

    if bullish and macd_hist > 2.0:
        return 90.0   # Strong bullish momentum
    if bullish and macd_hist > 0.5:
        return 75.0   # Solid bullish
    if bullish:
        return 65.0   # Weak bullish
    if macd_hist > 0:
        return 45.0   # Bearish but histogram turning
    if macd_hist > -0.5:
        return 30.0   # Mildly bearish
    return 15.0        # Strong bearish


def _score_trend(vs_sma50: float | None, vs_sma200: float | None) -> float:
    """Trend scoring — data shows vs_sma200 is the key predictor.

    Missed surgers: avg vs_sma200 = +20% vs normal +13%.
    Weight vs_sma200 more heavily, and reward magnitude not just direction.
    """
    s200 = vs_sma200 or 0
    s50 = vs_sma50 or 0

    # vs_sma200 is the primary trend signal
    if s200 > 0.15:
        trend_score = 85.0   # Strong long-term uptrend
    elif s200 > 0.05:
        trend_score = 70.0   # Moderate uptrend
    elif s200 > 0:
        trend_score = 60.0   # Slight uptrend
    elif s200 > -0.05:
        trend_score = 40.0   # Slight downtrend
    else:
        trend_score = 20.0   # Strong downtrend

    # Bonus for short-term confirmation
    if s50 > 0 and s200 > 0:
        trend_score = min(95, trend_score + 10)
    elif s50 < 0 and s200 < 0:
        trend_score = max(10, trend_score - 10)

    return trend_score


def _score_volume_safe(volume_ratio: float | None) -> float:
    """Volume scoring for SAFE_INCOME — low volume wins.

    Data shows: Safe winners avg volume 0.977, losers avg 1.071.
    Stable stocks do better on quiet days (no panic).
    """
    if volume_ratio is None:
        return 55.0
    if volume_ratio < 0.5:
        return 70.0   # Very quiet — stable accumulation
    if volume_ratio < 0.8:
        return 75.0   # Low volume sweet spot
    if volume_ratio < 1.2:
        return 60.0   # Normal
    if volume_ratio < 1.5:
        return 45.0   # Getting noisy
    return 30.0        # High volume on safe stock = uncertainty


def _score_volume_risk(volume_ratio: float | None) -> float:
    """Volume scoring for HIGH_RISK — needs volume confirmation.

    Data shows: Risk winners avg volume 1.222, losers avg 1.120.
    Momentum stocks need volume to confirm the move.
    """
    if volume_ratio is None:
        return 40.0
    if volume_ratio > 2.0:
        return 75.0   # Strong conviction
    if volume_ratio > 1.5:
        return 80.0   # Best sweet spot
    if volume_ratio > 1.0:
        return 70.0   # Decent confirmation
    if volume_ratio > 0.7:
        return 45.0   # Weak volume
    return 25.0        # No conviction


def _score_momentum(momentum_5d: float | None, momentum_20d: float | None) -> float:
    """Momentum scoring — data shows +1% to +3% is the sweet spot.

    >5% wins only 46.2% (mean reversion trap).
    -3% to -1% wins 59.2% (bounce opportunity).
    """
    m5 = (momentum_5d or 0) * 100  # Convert to percentage
    m20 = (momentum_20d or 0) * 100

    # 5-day momentum (primary)
    if 1 <= m5 <= 3:
        m5_score = 80.0    # Sweet spot
    elif -3 <= m5 < -1:
        m5_score = 75.0    # Bounce opportunity
    elif 0 <= m5 < 1:
        m5_score = 60.0    # Flat/slight positive
    elif 3 < m5 <= 5:
        m5_score = 45.0    # Getting extended
    elif m5 > 5:
        m5_score = 30.0    # Overextended — likely to reverse
    elif m5 < -3:
        m5_score = 35.0    # Falling hard
    else:
        m5_score = 50.0

    # 20-day momentum (confirmation)
    if m20 > 5:
        m20_score = 75.0
    elif m20 > 0:
        m20_score = 65.0
    elif m20 > -5:
        m20_score = 45.0
    else:
        m20_score = 25.0

    return m5_score * 0.6 + m20_score * 0.4


def _score_dividend(dividend_yield: float | None) -> float:
    """Dividend scoring — unchanged, this works well."""
    if dividend_yield is None or dividend_yield == 0:
        return 0.0
    if dividend_yield > 0.08:
        return 100.0
    if dividend_yield > 0.05:
        return 80.0
    if dividend_yield > 0.03:
        return 60.0
    if dividend_yield > 0.01:
        return 40.0
    return 20.0


def _score_fundamentals_safe(
    pe: float | None,
    margin: float | None,
    debt_equity: float | None,
) -> float:
    """Fundamental scoring for SAFE_INCOME — value + quality."""
    scores = []

    if pe is not None and pe > 0:
        if pe < 15:
            scores.append(90.0)
        elif pe < 20:
            scores.append(75.0)
        elif pe < 30:
            scores.append(55.0)
        else:
            scores.append(30.0)

    if margin is not None:
        if margin > 0.20:
            scores.append(90.0)
        elif margin > 0.10:
            scores.append(70.0)
        elif margin > 0.05:
            scores.append(50.0)
        else:
            scores.append(30.0)

    if debt_equity is not None:
        if debt_equity < 50:
            scores.append(85.0)
        elif debt_equity < 100:
            scores.append(65.0)
        elif debt_equity < 200:
            scores.append(45.0)
        else:
            scores.append(25.0)

    if not scores:
        return 50.0
    return sum(scores) / len(scores)


def _score_fundamentals_risk(
    eps_growth: float | None,
    revenue_growth: float | None,
    beta: float | None,
) -> float:
    """Fundamental scoring for HIGH_RISK — growth + momentum."""
    scores = []

    if eps_growth is not None:
        if eps_growth > 0.25:
            scores.append(90.0)
        elif eps_growth > 0.10:
            scores.append(75.0)
        elif eps_growth > 0:
            scores.append(55.0)
        else:
            scores.append(25.0)

    if revenue_growth is not None:
        if revenue_growth > 0.20:
            scores.append(90.0)
        elif revenue_growth > 0.10:
            scores.append(75.0)
        elif revenue_growth > 0:
            scores.append(55.0)
        else:
            scores.append(25.0)

    if beta is not None:
        if 1.0 <= beta <= 1.5:
            scores.append(80.0)   # Moderate risk
        elif 1.5 < beta <= 2.0:
            scores.append(65.0)   # High risk but manageable
        elif beta > 2.0:
            scores.append(40.0)   # Too volatile
        else:
            scores.append(50.0)   # Low beta for risk bucket

    if not scores:
        return 50.0
    return sum(scores) / len(scores)


def _score_macro(macro: dict) -> float:
    """Score macro environment — fed funds trend + VIX."""
    ff = macro.get("fed_funds_rate")
    vix = macro.get("vix")

    # Fed funds trend
    fed_score = 55.0
    if ff is not None and hasattr(ff, "iloc") and len(ff) >= 5:
        recent = ff.iloc[-1]
        earlier = ff.iloc[-5]
        if hasattr(recent, "item"):
            recent = recent.item()
        if hasattr(earlier, "item"):
            earlier = earlier.item()
        diff = recent - earlier
        if diff < -0.1:
            fed_score = 75.0   # Rate cuts — bullish
        elif diff > 0.1:
            fed_score = 30.0   # Rate hikes — bearish
        else:
            fed_score = 55.0

    # VIX component
    vix_score = 55.0
    if vix is not None:
        if isinstance(vix, (int, float)):
            v = vix
        else:
            v = float(vix)
        if v < 15:
            vix_score = 75.0   # Low fear — bullish
        elif v < 20:
            vix_score = 65.0
        elif v < 25:
            vix_score = 50.0
        elif v < 35:
            vix_score = 35.0   # Elevated fear
        else:
            vix_score = 20.0   # Panic

    return fed_score * 0.6 + vix_score * 0.4


# ============================================================
# MAIN SCORING FUNCTIONS
# ============================================================

def score_safe_income(indicators: dict, fundamentals: dict, macro: dict) -> dict:
    """Score a ticker using SAFE_INCOME weights.

    Rebalanced weights — increase technical + trend weight since
    Safe Income winners show clear RSI + volume patterns.

    Weights:
        dividend_reliability: 0.25 (was 0.35 — still important but not dominant)
        fundamental_health:   0.25 (was 0.30)
        macro_environment:    0.20 (was 0.25)
        technical + trend:    0.30 (was 0.10 — data shows this matters more)
    """
    dividend_score = _score_dividend(fundamentals.get("dividend_yield"))

    fundamental_score = _score_fundamentals_safe(
        pe=fundamentals.get("pe_ratio"),
        margin=fundamentals.get("profit_margin"),
        debt_equity=fundamentals.get("debt_to_equity"),
    )

    macro_score = _score_macro(macro)

    # Technical: RSI + trend + volume (all tuned for safe income)
    technical_score = (
        _score_rsi_safe(indicators["rsi"]) * 0.35
        + _score_trend(indicators.get("vs_sma50"), indicators.get("vs_sma200")) * 0.40
        + _score_volume_safe(indicators.get("volume_ratio")) * 0.25
    )

    total = (
        dividend_score * 0.25
        + fundamental_score * 0.25
        + macro_score * 0.20
        + technical_score * 0.30
    )

    return {
        "total_score": round(total, 1),
        "bucket": "SAFE_INCOME",
        "components": {
            "dividend": round(dividend_score, 1),
            "fundamental": round(fundamental_score, 1),
            "macro": round(macro_score, 1),
            "technical": round(technical_score, 1),
        },
    }


def score_high_risk(indicators: dict, fundamentals: dict, macro: dict) -> dict:
    """Score a ticker using HIGH_RISK weights.

    Rebalanced — MACD histogram and trend are the biggest predictors
    of surges. Momentum proxy replaces Grok but calibrated to avoid
    the >5% trap.

    Weights:
        trend + macd:    0.35 (primary — data shows these predict surges)
        momentum:        0.25 (calibrated sweet spot scoring)
        fundamental:     0.20
        macro:           0.20
    """
    # Trend + MACD (strongest predictors)
    trend_macd_score = (
        _score_trend(indicators.get("vs_sma50"), indicators.get("vs_sma200")) * 0.45
        + _score_macd(indicators["macd_line"], indicators["macd_signal"], indicators["macd_hist"]) * 0.35
        + _score_volume_risk(indicators.get("volume_ratio")) * 0.20
    )

    # Momentum (calibrated to avoid traps)
    momentum_score = _score_momentum(
        indicators.get("momentum_5d"),
        indicators.get("momentum_20d"),
    )

    # RSI as a filter on momentum
    rsi_adj = _score_rsi_risk(indicators["rsi"])
    momentum_score = momentum_score * 0.7 + rsi_adj * 0.3

    fundamental_score = _score_fundamentals_risk(
        eps_growth=fundamentals.get("eps_growth"),
        revenue_growth=fundamentals.get("revenue_growth"),
        beta=fundamentals.get("beta"),
    )

    macro_score = _score_macro(macro)

    total = (
        trend_macd_score * 0.35
        + momentum_score * 0.25
        + fundamental_score * 0.20
        + macro_score * 0.20
    )

    return {
        "total_score": round(total, 1),
        "bucket": "HIGH_RISK",
        "components": {
            "trend_macd": round(trend_macd_score, 1),
            "momentum": round(momentum_score, 1),
            "fundamental": round(fundamental_score, 1),
            "macro": round(macro_score, 1),
        },
    }


# ============================================================
# SIGNAL + GEM
# ============================================================

def determine_signal(
    score: float,
    bucket: str = "",
    thresholds: dict | None = None,
) -> str:
    """Convert score to signal action with bucket-aware thresholds.

    Data-driven insight: scores above 71 have inverted win rates
    (higher score = more likely to lose). This is because the
    components that push scores high signal overbought conditions.

    SAFE_INCOME: buy 65-70 (sweet spot 65-67)
    HIGH_RISK:   buy 65-72 (sweet spot 67-69)
    Above ceiling → HOLD (wait for pullback)
    """
    buy = 65
    hold = 50
    ceiling = 72  # Above this, signal inverts

    if thresholds:
        buy = thresholds.get("buy", 65)
        hold = thresholds.get("hold", 50)
        ceiling = thresholds.get("ceiling", 72)

    # Bucket-specific ceilings
    if bucket == "SAFE_INCOME":
        ceiling = min(ceiling, 70)

    if score >= buy and score <= ceiling:
        return "BUY"
    if score > ceiling:
        return "HOLD"  # Overbought — wait for pullback
    if score >= hold:
        return "HOLD"
    return "AVOID"


def check_gem_conditions(
    score_result: dict,
    indicators: dict,
    fundamentals: dict,
) -> tuple[bool, str | None]:
    """Check if a signal qualifies as a GEM alert.

    Relaxed conditions based on backtest data — the old conditions
    were impossible to trigger without sentiment data.

    All 4 conditions must be true:
    1. Score >= 78 (was 85 — unreachable without Grok)
    2. MACD bullish with strong histogram (> 1.0)
    3. Trend: above SMA200 by > 5%
    4. RSI in sweet spot (40-70)
    """
    score = score_result["total_score"]
    rsi = indicators.get("rsi", 0)
    macd_line = indicators.get("macd_line", 0)
    macd_signal = indicators.get("macd_signal", 0)
    macd_hist = indicators.get("macd_hist", 0) or 0
    vs_sma200 = indicators.get("vs_sma200", 0) or 0
    volume_ratio = indicators.get("volume_ratio", 0) or 0

    # Condition 1: Score >= 78
    if score < 78:
        return False, None

    # Condition 2: MACD bullish with strong histogram
    if macd_line <= macd_signal or macd_hist <= 1.0:
        return False, None

    # Condition 3: Above SMA200 by > 5%
    if vs_sma200 < 0.05:
        return False, None

    # Condition 4: RSI in sweet spot
    if rsi < 40 or rsi > 70:
        return False, None

    reason = (
        f"Score {score:.0f} | MACD hist {macd_hist:.1f} | "
        f"vs SMA200 {vs_sma200:+.1%} | RSI {rsi:.0f} | Vol {volume_ratio:.1f}x"
    )
    return True, reason
