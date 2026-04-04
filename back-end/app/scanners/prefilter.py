"""Pre-filter logic: reduce ~1000 tickers down to ~50 candidates."""

from loguru import logger

from app.core.config import settings


def prefilter_candidates(screening_data: dict[str, dict]) -> list[str]:
    """Filter screening data down to the best candidates.

    Reserves at least 5 slots for crypto tickers so they aren't
    crowded out by higher-volume equities.

    Args:
        screening_data: Dict from market_scanner.get_bulk_screening().

    Returns:
        List of ticker symbols sorted by absolute day change.
    """
    equity_candidates = []
    crypto_candidates = []

    for ticker, data in screening_data.items():
        volume = data.get("avg_volume", 0)
        day_change = abs(data.get("day_change", 0))
        price = data.get("price", 0)

        if volume < settings.min_volume:
            continue
        if day_change < settings.min_abs_change:
            continue
        if price < 1.0:
            continue

        entry = (ticker, day_change, volume)
        if ticker.endswith("-USD"):
            crypto_candidates.append(entry)
        else:
            equity_candidates.append(entry)

    equity_candidates.sort(key=lambda x: (-x[1], -x[2]))
    crypto_candidates.sort(key=lambda x: (-x[1], -x[2]))

    # Reserve up to 5 slots for crypto, rest for equities
    max_crypto = min(5, len(crypto_candidates))
    max_equity = settings.max_candidates - max_crypto

    top_equity = equity_candidates[:max_equity]
    top_crypto = crypto_candidates[:max_crypto]
    combined = top_equity + top_crypto
    tickers = [t[0] for t in combined]

    logger.info(
        f"Pre-filter: {len(screening_data)} tickers → "
        f"{len(top_equity)} equity + {len(top_crypto)} crypto = {len(tickers)} candidates"
    )

    return tickers
