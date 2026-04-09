"""Pre-filter logic: reduce ~1000 tickers down to ~50 candidates."""

from loguru import logger

from app.core.config import settings


def prefilter_candidates(
    screening_data: dict[str, dict],
    watchlist_symbols: set[str] | None = None,
    held_brain_symbols: set[str] | None = None,
) -> list[str]:
    """Filter screening data down to the best candidates.

    Reserves at least 5 slots for crypto tickers so they aren't
    crowded out by higher-volume equities.

    Watchlisted tickers bypass volume/change filters -- the user
    explicitly wants to track them regardless of daily activity.

    HELD BRAIN POSITIONS also bypass filters -- on quiet days an open
    position can move < 1% intraday and would be filtered out, leaving
    the Stage 6 thesis tracker with no fresh signal to re-evaluate
    against. That silently broke the "continuous re-eval" guarantee
    until 2026-04-09. Held positions are always-included now and
    sit ADDITIVELY alongside watchlist (don't eat into the 50-slot cap).

    Args:
        screening_data: Dict from market_scanner.get_bulk_screening().
        watchlist_symbols: User's watchlisted tickers (always included).
        held_brain_symbols: Symbols the brain currently has open
            virtual_trades for. Always included regardless of pre-filter
            criteria so the thesis tracker can re-evaluate them.

    Returns:
        List of ticker symbols sorted by absolute day change.
    """
    watchlist = watchlist_symbols or set()
    held_brain = held_brain_symbols or set()
    MAX_WATCHLIST_SCAN = 30  # Cap watchlist candidates to prevent scan bloat
    watchlist_candidates = []
    held_candidates = []
    equity_candidates = []
    crypto_candidates = []

    for ticker, data in screening_data.items():
        volume = data.get("avg_volume", 0)
        day_change = abs(data.get("day_change", 0))
        price = data.get("price", 0)

        is_watchlisted = ticker in watchlist
        is_held = ticker in held_brain

        # Watchlisted AND held positions bypass filters -- both are
        # explicitly opted-in by user/brain, regardless of daily activity.
        if not is_watchlisted and not is_held:
            if volume < settings.min_volume:
                continue
            if day_change < settings.min_abs_change:
                continue
            if price < 1.0:
                continue

        entry = (ticker, day_change, volume)
        if is_held:
            # Held positions get their own bucket so they're always
            # included even if they're also watchlisted (dedup happens
            # later, but the held bucket is the strongest claim).
            held_candidates.append(entry)
        elif is_watchlisted:
            watchlist_candidates.append(entry)
        elif ticker.endswith("-USD"):
            crypto_candidates.append(entry)
        else:
            equity_candidates.append(entry)

    equity_candidates.sort(key=lambda x: (-x[1], -x[2]))
    crypto_candidates.sort(key=lambda x: (-x[1], -x[2]))

    # Reserve up to 5 slots for crypto, rest for equities
    # Watchlist + held_brain are ADDITIVE -- they don't eat into the cap
    max_crypto = min(5, len(crypto_candidates))
    max_equity = settings.max_candidates - max_crypto

    top_equity = equity_candidates[:max_equity]
    top_crypto = crypto_candidates[:max_crypto]
    combined = (
        held_candidates                              # always-included held
        + watchlist_candidates[:MAX_WATCHLIST_SCAN]  # additive watchlist
        + top_equity
        + top_crypto
    )

    # Deduplicate (a ticker might be in multiple buckets)
    seen = set()
    tickers = []
    for t in combined:
        if t[0] not in seen:
            seen.add(t[0])
            tickers.append(t[0])

    logger.info(
        f"Pre-filter: {len(screening_data)} tickers -> "
        f"{len(held_candidates)} held + {len(watchlist_candidates)} watchlist + "
        f"{len(top_equity)} equity + {len(top_crypto)} crypto = {len(tickers)} candidates"
    )

    return tickers
