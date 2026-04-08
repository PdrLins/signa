"""Kelly Criterion position sizing.

============================================================
WHAT THIS MODULE IS
============================================================

When a BUY signal fires, the user (or the brain) needs to decide HOW
MUCH of their capital to risk on it. This module computes that
recommended percentage using the Kelly Criterion — a math formula
from information theory that maximizes long-run growth given a known
edge.

The formula is:

    f* = (p * b - q) / b

  where:
    f* = fraction of capital to bet
    p  = probability of winning (win rate)
    q  = 1 - p (probability of losing)
    b  = ratio of win amount to loss amount (risk/reward ratio)

Pure Kelly is too aggressive — it would have you sizing positions at
40-60% of capital, which destroys you on a bad streak. Signa uses
FRACTIONAL KELLY (25% of full Kelly) which keeps the long-run growth
property while drastically cutting drawdown variance.

The output is then capped at MAX_POSITION_PCT (15% of portfolio) so
no single trade can take down the whole account.

============================================================
WHERE THE WIN RATE COMES FROM
============================================================

Kelly needs a win rate. We don't actually know the true win rate of
any individual signal — but we have backtest data showing the
empirical win rate at each score range. The `_SCORE_WIN_RATE` table
maps signal scores to win rates derived from the 6-month backtest
(Oct 2024 - Apr 2025, ~18,000 signals):

    Score 90+   → 70% win rate
    Score 85-89 → 65%
    Score 80-84 → 60%
    Score 75-79 → 55%
    Score 70-74 → 52%
    Score 65-69 → 50% (coin flip)
    Score 60-64 → 47%
    Score 50-59 → 42%
    Score < 50  → 35%

Higher score → higher confidence → larger Kelly fraction → bigger
recommended position. The mapping is the same for both buckets
(SAFE_INCOME and HIGH_RISK) because the score is already
bucket-normalized.

============================================================
REGIME ADJUSTMENTS
============================================================

The output is further reduced based on the macro regime:

  TRENDING  → no adjustment (full fractional Kelly)
  VOLATILE  → × 0.5  (cut size in half during high VIX)
  CRISIS    → cap at 5% (defensive mode, even strong signals get
              throttled)

Crypto positions are additionally halved regardless of regime to
account for crypto's 3-5x higher volatility vs equities.

============================================================
THE TRUST MULTIPLIER
============================================================

Calls can pass `trust_multiplier` to scale the final size. This is
plumbed through for the brain's tiered trust model — Tier 2 and
Tier 3 brain buys would call with `trust_multiplier=0.5` to halve
the position size, reflecting their lower confidence.

NOTE: as of writing, `scan_service` only calls `calculate_kelly` for
signals where `action == "BUY"`, which always have `ai_status =
"validated"`, so the multiplier defaults to 1.0 in practice. The
brain's tier 2/3 sizing is currently informational (the tier is
recorded on the virtual_trade row but no per-position Kelly is
computed). The parameter exists so future code can wire it up
without changing this function's signature.
"""

from loguru import logger


# Score-to-win-rate mapping from backtest validation
_SCORE_WIN_RATE = [
    (90, 0.70),  # Score 90+ → 70% win rate
    (85, 0.65),  # Score 85-89 → 65%
    (80, 0.60),  # Score 80-84 → 60%
    (75, 0.55),  # Score 75-79 → 55% (BUY threshold)
    (70, 0.52),  # Score 70-74 → 52%
    (65, 0.50),  # Score 65-69 → 50% (coinflip)
    (60, 0.47),  # Score 60-64 → 47%
    (50, 0.42),  # Score 50-59 → 42%
    (0, 0.35),   # Score below 50 → 35%
]

FRACTIONAL_KELLY = 0.25  # Use 25% of full Kelly
MAX_POSITION_PCT = 0.15  # Cap at 15% of portfolio


def score_to_win_rate(score: int) -> float:
    """Map a signal score (0-100) to an estimated win rate.

    Based on backtest data from Oct 2024 - Apr 2025.
    """
    for threshold, rate in _SCORE_WIN_RATE:
        if score >= threshold:
            return rate
    return 0.35


def calculate_kelly(
    risk_reward: float,
    win_rate: float | None = None,
    score: int | None = None,
    fractional: float = FRACTIONAL_KELLY,
    max_pct: float = MAX_POSITION_PCT,
    regime: str = "TRENDING",
    asset_type: str = "EQUITY",
    trust_multiplier: float = 1.0,
) -> dict:
    """Calculate recommended position size using fractional Kelly Criterion.

    Args:
        risk_reward: Risk/reward ratio (e.g., 3.2 means 3.2:1).
        win_rate: Explicit win rate (0-1). If None, derived from score.
        score: Signal score (0-100). Used to derive win_rate if not provided.
        fractional: Fraction of full Kelly to use (default 0.25).
        max_pct: Maximum position size as percentage (default 0.15 = 15%).
        trust_multiplier: Tier-based scaling for AI confidence (default 1.0).
            Halves position size for low-trust signals (low_confidence or
            tech-only). 1.0 = full size, 0.5 = half size, etc.

            Currently the production scan_service flow only calls this for
            BUY signals (which always have ai_status="validated"), so the
            default 1.0 is used in practice. The brain's tier 2/3 auto-buys
            track tier and trust_multiplier on the virtual_trades row directly
            without computing a per-trade Kelly. This parameter is exposed so
            that if the brain ever computes its own per-position Kelly, the
            tier-aware scaling is one line of integration away.

    Returns:
        Dict with full_kelly_pct, recommended_pct, win_rate, risk_reward,
        edge (expected value per dollar risked).
    """
    if win_rate is None:
        if score is None:
            raise ValueError("Either win_rate or score must be provided")
        win_rate = score_to_win_rate(score)

    if risk_reward <= 0:
        return {
            "full_kelly_pct": 0,
            "recommended_pct": 0,
            "win_rate": win_rate,
            "risk_reward": risk_reward,
            "edge": 0,
            "verdict": "no_edge",
            "regime": regime,
            "regime_note": None,
            "regime_adjusted": False,
        }

    # Kelly formula: f* = (p * b - q) / b
    # where p = win_rate, q = 1 - win_rate, b = risk_reward
    p = win_rate
    q = 1 - p
    b = risk_reward

    full_kelly = (p * b - q) / b
    edge = p * b - q  # Expected value per dollar risked

    if full_kelly <= 0:
        return {
            "full_kelly_pct": 0,
            "recommended_pct": 0,
            "win_rate": round(win_rate, 4),
            "risk_reward": round(risk_reward, 2),
            "edge": round(edge, 4),
            "verdict": "no_edge",
            "regime": regime,
            "regime_note": None,
            "regime_adjusted": False,
        }

    recommended = min(full_kelly * fractional, max_pct)

    # Verdict based on recommended size
    if recommended >= 0.10:
        verdict = "strong"
    elif recommended >= 0.05:
        verdict = "moderate"
    elif recommended > 0:
        verdict = "small"
    else:
        verdict = "no_edge"

    logger.debug(
        f"Kelly: win={win_rate:.2f} rr={risk_reward:.1f} "
        f"full={full_kelly:.3f} rec={recommended:.3f} ({verdict})"
    )

    # Apply regime adjustment (Part 4)
    regime_note = None
    if regime == "VOLATILE":
        recommended = recommended * 0.5
        regime_note = "Reduced 50% - volatile regime"
    elif regime == "CRISIS":
        recommended = min(recommended, 0.05)
        regime_note = "Capped at 5% - crisis regime"

    # Crypto volatility scaling — crypto swings 3-5x more than equities
    if asset_type == "CRYPTO":
        recommended = recommended * 0.5
        if regime_note:
            regime_note += "; Halved for crypto volatility"
        else:
            regime_note = "Halved for crypto volatility"

    # Trust tier scaling — reduces size for low-confidence or tech-only signals
    if trust_multiplier != 1.0:
        recommended = recommended * trust_multiplier
        trust_note = f"Trust multiplier {trust_multiplier:.0%}"
        regime_note = f"{regime_note}; {trust_note}" if regime_note else trust_note

    return {
        "full_kelly_pct": round(full_kelly * 100, 2),
        "recommended_pct": round(recommended * 100, 2),
        "win_rate": round(win_rate, 4),
        "risk_reward": round(risk_reward, 2),
        "edge": round(edge, 4),
        "regime": regime,
        "regime_note": regime_note,
        "regime_adjusted": regime != "TRENDING",
        "verdict": verdict,
    }
