"""Seed brain knowledge for Phase 1 features.

Run with: python -m app.db.seed_phase1_knowledge
"""

from loguru import logger
from app.db.supabase import get_client


KNOWLEDGE_ENTRIES = [
    {
        "topic": "factor_investing",
        "key_concept": "quality_factor_qmj",
        "explanation": "The Quality-Minus-Junk factor (QMJ) shows that companies with high profitability, stable earnings growth, and low leverage consistently outperform. For SAFE_INCOME signals, a quality score above 60 adds bonus points. Key metrics: profit margin > 15%, positive EPS and revenue growth, debt-to-equity < 80, forward P/E below trailing P/E (earnings acceleration).",
        "formula": "quality_score = f(profit_margin, eps_growth, revenue_growth, debt_to_equity, forward_pe_vs_pe)",
        "example": "ENB.TO: margin 12%, EPS growth +8%, D/E 120 = quality score 55 (neutral). BCE.TO: margin 18%, EPS growth +15%, D/E 45 = quality score 75 (strong).",
    },
    {
        "topic": "factor_investing",
        "key_concept": "momentum_factor_umd",
        "explanation": "The momentum factor (Up-Minus-Down) is the strongest documented factor in finance. Stocks with positive 3-month and 6-month returns tend to continue outperforming for 1-12 months. For HIGH_RISK signals, strong multi-period momentum adds bonus points. ADX above 25 confirms the trend is real, not noise. Momentum above +5% reversal threshold requires confirmation.",
        "formula": "momentum_factor = f(3m_return, 6m_return, ADX_confirmation)",
        "example": "SHOP.TO: 3m +22%, 6m +35%, ADX 32 = strong momentum, +6 bonus. TSLA: 3m -8%, 6m +45%, ADX 18 = contradictory, no bonus.",
    },
    {
        "topic": "technical_analysis",
        "key_concept": "adx_trend_strength",
        "explanation": "The Average Directional Index (ADX) measures trend strength regardless of direction. ADX > 25 means a strong trend exists (momentum strategies work). ADX < 20 means range-bound market (mean reversion/contrarian strategies work). The brain uses ADX to dynamically adjust whether to favor momentum or contrarian signals. High ADX + bullish RSI = high conviction BUY. Low ADX = be cautious with momentum plays.",
        "formula": "ADX = smoothed average of DM+/DM- directional movement (14-period default)",
        "example": "ADX 35 + RSI 58 + golden cross = strong momentum BUY. ADX 12 + RSI 58 = range-bound, momentum unreliable.",
    },
    {
        "topic": "macro_analysis",
        "key_concept": "vix_term_structure_signal",
        "explanation": "VIX term structure compares spot VIX to 3-month VIX futures. In contango (spot < futures, ratio < 1.0), the market is complacent — this is normal and slightly bullish. In backwardation (spot > futures, ratio > 1.0), the market is stressed now but expects recovery — this is actually a BUY signal as stress is typically temporary. Extreme backwardation (ratio > 1.15) signals peak fear, historically the best time to buy.",
        "formula": "VIX_ratio = VIX_spot / VIX_3M_futures. Backwardation if ratio > 1.0.",
        "example": "VIX spot 28, VIX3M 24, ratio 1.17 = backwardation = market expects recovery. Good time for SAFE_INCOME entries.",
    },
    {
        "topic": "macro_analysis",
        "key_concept": "intermarket_copper_gold_ratio",
        "explanation": "The copper-to-gold ratio is a leading indicator of economic health. Copper = industrial demand (growth). Gold = safe haven (fear). Rising ratio = economy expanding (bullish for HIGH_RISK, especially industrials/tech). Falling ratio = economy slowing (defensive, favor SAFE_INCOME). The ratio typically leads stock market moves by 2-4 weeks.",
        "formula": "ratio = copper_price / gold_price * 1000",
        "example": "Copper/Gold ratio rising from 4.2 to 4.8 over 2 weeks = industrial expansion signal. Favor HIGH_RISK cyclical names.",
    },
    {
        "topic": "earnings_analysis",
        "key_concept": "post_earnings_drift_pead",
        "explanation": "Post-Earnings Announcement Drift (PEAD) is one of the most documented anomalies: stocks continue drifting in the direction of an earnings surprise for 20-60 trading days. A positive EPS surprise > 5% generates 3-7% additional drift. The brain adds drift bonus points to signals within 40 days of a positive surprise. Negative surprises trigger AVOID bias. Pre-earnings (7 days before) should reduce position size due to binary outcome risk.",
        "formula": "drift_score = min(15, surprise_pct * 0.5) if surprise > 5% and days_since <= 40",
        "example": "AAPL beats EPS by 8%, 15 days ago = POSITIVE_DRIFT, +4 bonus points. HUM misses by -3%, 10 days ago = NEGATIVE_DRIFT, no bonus.",
    },
    {
        "topic": "technical_analysis",
        "key_concept": "short_squeeze_mechanics",
        "explanation": "When a stock has high short interest (>10% of float) and bullish momentum develops (RSI 50-70, positive MACD), short sellers face margin pressure and must buy to cover, creating a feedback loop that accelerates the price rise. The brain adds up to 20 bonus points for HIGH_RISK signals with short squeeze potential. Key: short interest alone is not enough — you need bullish momentum confirmation to trigger the squeeze. Without momentum, high short interest just means the market is bearish.",
        "formula": "squeeze_bonus = tier_bonus(short_float) + momentum_confirmation(RSI, MACD)",
        "example": "GME: 140% short float + RSI 55 + positive MACD = maximum squeeze bonus. But 30% short + RSI 35 + negative MACD = no squeeze, shorts are right.",
    },
    {
        "topic": "risk_management",
        "key_concept": "crypto_volatility_asymmetry",
        "explanation": "Crypto assets exhibit 3-5x higher daily volatility than equities. The brain compensates by halving Kelly position sizes for crypto and enforcing an 8% maximum stop loss. This prevents outsized losses from crypto's characteristic sudden drawdowns while still allowing exposure to parabolic upside moves. Backtest shows best and worst trades are ALL crypto — position sizing is the key risk control lever.",
        "formula": "crypto_kelly = equity_kelly * 0.5; crypto_max_stop = entry_price * 0.92",
        "example": "SOL-USD with Kelly 12% becomes 6% for crypto. Stop at $180 entry = $165.60 max stop (8% below).",
    },
    {
        "topic": "scoring_methodology",
        "key_concept": "etf_scoring_weights",
        "explanation": "ETFs (Exchange Traded Funds) use different scoring weights than individual stocks. While dividend-paying stocks get 35% weight on dividend reliability, ETFs reduce this to 15% because many excellent ETFs (like XEQT, VEQT, VFV) pay minimal or no dividends. Instead, ETFs get 40% weight on fundamental health (tracking error, diversification, expense ratio proxy) and 30% on macro conditions. This prevents penalizing all-in-one portfolio ETFs that are fundamentally superior investments but happen to not prioritize dividend income.",
        "formula": "ETF weights: fundamental_health=40%, macro=30%, dividend=15%, sentiment=15%",
        "example": "XEQT.TO (iShares All-Equity ETF): dividend yield 0.5% would score poorly under normal SAFE_INCOME weights (35% dividend = drag). Under ETF weights, fundamental health (diversified global equity, low MER) gets 40% weight and drives the score higher. This correctly reflects that XEQT is one of the best long-term investments for Canadians.",
    },
    {
        "topic": "scoring_methodology",
        "key_concept": "asset_class_classification",
        "explanation": "Signa classifies every ticker into one of three asset classes: STOCK (individual equities), ETF (exchange-traded funds), or CRYPTO (cryptocurrencies). This classification affects scoring weights, position sizing, and stop loss levels. ETFs use SAFE_INCOME weights with reduced dividend emphasis. Crypto uses halved Kelly position sizes and 8% max stop loss. Stocks use standard bucket-specific weights. The classification is determined by the ticker symbol format: -USD suffix for crypto, membership in the ETF set for ETFs, everything else is a stock.",
        "formula": "asset_class = CRYPTO if ticker ends in -USD, ETF if in ETF set, else STOCK",
        "example": "VFV.TO = ETF (S&P 500 tracker, scored with ETF weights). AAPL = STOCK (individual equity). BTC-USD = CRYPTO (halved position sizes).",
    },
]


def seed():
    """Insert Phase 1 knowledge entries into signal_knowledge table."""
    db = get_client()

    for entry in KNOWLEDGE_ENTRIES:
        try:
            # Check if already exists
            existing = (
                db.table("signal_knowledge")
                .select("id")
                .eq("key_concept", entry["key_concept"])
                .limit(1)
                .execute()
            )

            if existing.data:
                # Update existing
                db.table("signal_knowledge").update({
                    "explanation": entry["explanation"],
                    "formula": entry.get("formula"),
                    "example": entry.get("example"),
                    "is_active": True,
                }).eq("key_concept", entry["key_concept"]).execute()
                logger.info(f"Updated knowledge: {entry['key_concept']}")
            else:
                # Insert new
                db.table("signal_knowledge").insert({
                    "topic": entry["topic"],
                    "key_concept": entry["key_concept"],
                    "explanation": entry["explanation"],
                    "formula": entry.get("formula"),
                    "example": entry.get("example"),
                    "is_active": True,
                }).execute()
                logger.info(f"Inserted knowledge: {entry['key_concept']}")

        except Exception as e:
            logger.error(f"Failed to seed {entry['key_concept']}: {e}")

    logger.info(f"Phase 1 knowledge seeding complete: {len(KNOWLEDGE_ENTRIES)} entries")


if __name__ == "__main__":
    seed()
