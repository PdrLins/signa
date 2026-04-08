"""Pre-filter logic: reduce ~1000 tickers down to ~50 candidates."""

from loguru import logger

from app.core.config import settings


def prefilter_candidates(
    screening_data: dict[str, dict],
    watchlist_symbols: set[str] | None = None,
) -> list[str]:
    """Filter screening data down to the best candidates.

    Reserves at least 5 slots for crypto tickers so they aren't
    crowded out by higher-volume equities.

    Watchlisted tickers bypass volume/change filters -- the user
    explicitly wants to track them regardless of daily activity.

    Args:
        screening_data: Dict from market_scanner.get_bulk_screening().
        watchlist_symbols: User's watchlisted tickers (always included).

    Returns:
        List of ticker symbols sorted by absolute day change.
    """
    watchlist = watchlist_symbols or set()
    MAX_WATCHLIST_SCAN = 30  # Cap watchlist candidates to prevent scan bloat
    watchlist_candidates = []
    equity_candidates = []
    crypto_candidates = []

    for ticker, data in screening_data.items():
        volume = data.get("avg_volume", 0)
        day_change = abs(data.get("day_change", 0))
        price = data.get("price", 0)

        is_watchlisted = ticker in watchlist

        # Watchlisted tickers bypass filters -- user wants them scanned
        if not is_watchlisted:
            if volume < settings.min_volume:
                continue
            if day_change < settings.min_abs_change:
                continue
            if price < 1.0:
                continue

        entry = (ticker, day_change, volume)
        if is_watchlisted:
            watchlist_candidates.append(entry)
        elif ticker.endswith("-USD"):
            crypto_candidates.append(entry)
        else:
            equity_candidates.append(entry)

    equity_candidates.sort(key=lambda x: (-x[1], -x[2]))
    crypto_candidates.sort(key=lambda x: (-x[1], -x[2]))

    # Reserve up to 5 slots for crypto, rest for equities
    # Watchlist is ADDITIVE -- does not eat into the cap
    max_crypto = min(5, len(crypto_candidates))
    max_equity = settings.max_candidates - max_crypto

    top_equity = equity_candidates[:max_equity]
    top_crypto = crypto_candidates[:max_crypto]
    combined = watchlist_candidates[:MAX_WATCHLIST_SCAN] + top_equity + top_crypto

    # Deduplicate (watchlist ticker might also appear in equity/crypto)
    seen = set()
    tickers = []
    for t in combined:
        if t[0] not in seen:
            seen.add(t[0])
            tickers.append(t[0])

    logger.info(
        f"Pre-filter: {len(screening_data)} tickers -> "
        f"{len(watchlist_candidates)} watchlist + {len(top_equity)} equity + "
        f"{len(top_crypto)} crypto = {len(tickers)} candidates"
    )

    return tickers
