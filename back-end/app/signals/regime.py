"""Market regime detection — runs ONCE per scan, not per ticker.

Four regimes: TRENDING, VOLATILE, CRISIS, RECOVERY.
Affects signal generation, Kelly sizing, and score multipliers.

RECOVERY is distinct from TRENDING: it fires only when VIX is falling
from crisis levels (20-30 range) AND SPY has reclaimed its 50-day SMA
AND VIX was above 30 within the last 30 days. This prevents false
triggers on routine pullback recoveries. Historically, RECOVERY
produces the highest risk-adjusted returns of any regime — momentum
works exceptionally well because the reversal is over and a new trend
is forming.
"""

from loguru import logger


def _was_crisis_recently(macro_data: dict) -> bool:
    """Check if VIX was above 30 within the last 30 calendar days.

    Reads `macro_data["vix_30d_high"]` which is fetched ONCE per scan
    by `macro_scanner.get_macro_snapshot()` alongside all other macro data.
    No extra yfinance calls — the data is already in hand.

    Returns False on missing data so the RECOVERY boost is never
    awarded without positive evidence of a recent crisis.
    """
    if not macro_data:
        return False
    # Fast path: if current VIX > 28, crisis is basically now
    current_vix = macro_data.get("vix")
    if current_vix is not None and current_vix > 28:
        return True
    # Check pre-fetched 30-day VIX high
    vix_30d_high = macro_data.get("vix_30d_high")
    if vix_30d_high is not None and vix_30d_high > 30:
        return True
    return False


def get_market_regime(macro_data: dict, as_of_date: str = None) -> str:
    """Compute market regime from macro data.

    Returns: TRENDING | VOLATILE | CRISIS | RECOVERY
    This runs ONCE per scan, not per ticker.
    """
    try:
        vix = None

        # Extract VIX from macro data
        if macro_data:
            # Live scan format: macro_data has 'vix' key directly
            vix = macro_data.get("vix")

            # Fallback: FRED format with VIXCLS series
            if vix is None and "VIXCLS" in macro_data:
                vix_series = macro_data["VIXCLS"]
                if hasattr(vix_series, "iloc") and not vix_series.empty:
                    if as_of_date:
                        vix_series = vix_series[vix_series.index <= as_of_date]
                    if not vix_series.empty:
                        vix = float(vix_series.iloc[-1])

        # SPY vs SMA data (if available from macro scanner)
        spy_vs_sma200 = macro_data.get("spy_vs_sma200") if macro_data else None
        spy_vs_sma50 = macro_data.get("spy_vs_sma50") if macro_data else None

        if vix is None:
            logger.debug("VIX data unavailable — defaulting to TRENDING")
            return "TRENDING"

        # CRISIS: highest priority
        if vix > 30 or (spy_vs_sma200 is not None and spy_vs_sma200 < -2):
            logger.info(f"Market regime: CRISIS (VIX={vix})")
            return "CRISIS"

        # RECOVERY: VIX elevated (20-30) but SPY reclaiming trend after recent crisis
        # Requires: VIX was > 30 within last 30 days (not just a routine pullback)
        if 20 < vix <= 30:
            if (spy_vs_sma50 is not None and spy_vs_sma50 > 0
                    and spy_vs_sma200 is not None and spy_vs_sma200 < 5
                    and _was_crisis_recently(macro_data)):
                logger.info(f"Market regime: RECOVERY (VIX={vix}, SPY reclaiming trend after recent crisis)")
                return "RECOVERY"

        # VOLATILE
        if vix > 20 or (spy_vs_sma50 is not None and spy_vs_sma50 < -1):
            logger.info(f"Market regime: VOLATILE (VIX={vix})")
            return "VOLATILE"

        logger.info(f"Market regime: TRENDING (VIX={vix})")
        return "TRENDING"

    except Exception as e:
        logger.warning(f"Regime detection failed: {e}. Defaulting to TRENDING.")
        return "TRENDING"
