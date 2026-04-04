"""Pre-filter logic: reduce ~1000 tickers down to ~50 candidates."""

from loguru import logger

from app.core.config import settings


def prefilter_candidates(screening_data: dict[str, dict]) -> list[str]:
    """Filter screening data down to the best candidates.

    Args:
        screening_data: Dict from market_scanner.get_bulk_screening().

    Returns:
        List of ticker symbols sorted by absolute day change.
    """
    candidates = []

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

        candidates.append((ticker, day_change, volume))

    candidates.sort(key=lambda x: (-x[1], -x[2]))
    top = candidates[: settings.max_candidates]
    tickers = [t[0] for t in top]

    logger.info(
        f"Pre-filter: {len(screening_data)} tickers → {len(tickers)} candidates"
    )

    return tickers
