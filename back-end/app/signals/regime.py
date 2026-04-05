"""Market regime detection — runs ONCE per scan, not per ticker.

Three regimes: TRENDING, VOLATILE, CRISIS.
Affects signal generation, Kelly sizing, and score multipliers.
"""

from loguru import logger


def get_market_regime(macro_data: dict, as_of_date: str = None) -> str:
    """Compute market regime from macro data.

    Returns: TRENDING | VOLATILE | CRISIS
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

        if vix > 30 or (spy_vs_sma200 is not None and spy_vs_sma200 < -2):
            logger.info(f"Market regime: CRISIS (VIX={vix})")
            return "CRISIS"
        elif vix > 20 or (spy_vs_sma50 is not None and spy_vs_sma50 < -1):
            logger.info(f"Market regime: VOLATILE (VIX={vix})")
            return "VOLATILE"
        else:
            logger.info(f"Market regime: TRENDING (VIX={vix})")
            return "TRENDING"

    except Exception as e:
        logger.warning(f"Regime detection failed: {e}. Defaulting to TRENDING.")
        return "TRENDING"
