"""Market holiday calendar for TSX, NYSE, NASDAQ.

============================================================
WHY THIS MODULE EXISTS
============================================================

Day 36 (May 18, 2026) was Victoria Day — a Canadian statutory holiday.
TSX was closed. The brain still ran its scan and admitted LUN.TO (a
Toronto-listed mining stock) at score 78 using STALE Friday-close
price data. The position died the next session (May 19) for -$19.66
via WATCHDOG_FORCE_SELL — entirely preventable cost.

This module provides a single function:

    is_market_open(exchange: str, on_date: date) -> bool

That the brain's entry pipeline calls before admitting any signal.
If the ticker's exchange is closed on the trade date, the signal is
skipped with `tier_reason = "exchange_closed_for_holiday"`.

============================================================
APPROACH: HARDCODED LIST
============================================================

We chose a hardcoded per-year list over `pandas_market_calendars`
(the standard market-calendar library) because:
  1. There are only ~11 Canadian and ~10 US holidays per year
  2. Holidays change rarely; the maintenance burden is one update per
     year (Dec: add next year's dates)
  3. No new dependency, no rolling-calendar abstraction to test
  4. The 60-second cost of looking up the next year's holidays is
     amortized over the 12 months they prevent ~$200 of losses

Trade-off: the list MUST be updated each December for the next year.
A failure mode would be: forget to update, brain assumes "no holiday"
in 2027+, suffers another LUN.TO-style trade. Mitigation: the lookup
defaults to "open" if no entry exists for the year, AND we add a
unit test that fails if the current year isn't covered.

If we ever add more exchanges (LSE, HKEX, ASX, etc.) or need
half-day handling (NYSE has half-days before Christmas/Thanksgiving),
swap to `pandas_market_calendars`. Today: not needed.

============================================================
COVERAGE
============================================================

  TSX (Toronto Stock Exchange):
    - New Year's Day · Family Day · Good Friday · Victoria Day
    - Canada Day · Civic Holiday · Labour Day · Thanksgiving (CA)
    - Christmas Day · Boxing Day (observed)

  NYSE / NASDAQ (US markets):
    - New Year's Day · MLK Day · Presidents' Day · Good Friday
    - Memorial Day · Juneteenth · Independence Day · Labor Day
    - Thanksgiving (US) · Christmas Day

  CRYPTO (24/7 markets):
    - Always open. No holidays. Even Christmas.

Half-day closures (e.g., NYSE 1pm close on Black Friday) are NOT
modeled — the brain only trades during the regular session anyway,
so a half-day still counts as "open" for our purposes.

============================================================
"""

from __future__ import annotations

from datetime import date


# ── 2026 ─────────────────────────────────────────────────────
# Source: TMX (TSX), NYSE official calendars. Verified against
# https://www.tmx.com/trading-hours-calendars (TSX)
# https://www.nyse.com/markets/hours-calendars (NYSE)
TSX_HOLIDAYS_2026: frozenset[str] = frozenset({
    "2026-01-01",  # New Year's Day
    "2026-02-16",  # Family Day (3rd Mon of Feb)
    "2026-04-03",  # Good Friday
    "2026-05-18",  # Victoria Day (last Mon before May 25) ← the Day-36 case
    "2026-07-01",  # Canada Day
    "2026-08-03",  # Civic Holiday (1st Mon of Aug)
    "2026-09-07",  # Labour Day (1st Mon of Sept)
    "2026-10-12",  # Thanksgiving CA (2nd Mon of Oct)
    "2026-12-25",  # Christmas Day
    "2026-12-28",  # Boxing Day observed (Dec 26 is a Saturday, moves to Mon)
})

US_HOLIDAYS_2026: frozenset[str] = frozenset({
    "2026-01-01",  # New Year's Day
    "2026-01-19",  # MLK Day (3rd Mon of Jan)
    "2026-02-16",  # Presidents' Day (3rd Mon of Feb)
    "2026-04-03",  # Good Friday
    "2026-05-25",  # Memorial Day (last Mon of May)
    "2026-06-19",  # Juneteenth
    "2026-07-03",  # Independence Day observed (July 4 is Saturday)
    "2026-09-07",  # Labor Day (1st Mon of Sept)
    "2026-11-26",  # Thanksgiving US (4th Thu of Nov)
    "2026-12-25",  # Christmas Day
})


# Master lookup keyed by exchange.
# When adding a new year: add a YYYY_TSX_HOLIDAYS_YYYY frozenset above,
# then add the entry here for each exchange that has the same calendar.
_BY_EXCHANGE: dict[str, dict[int, frozenset[str]]] = {
    "TSX": {2026: TSX_HOLIDAYS_2026},
    "NYSE": {2026: US_HOLIDAYS_2026},
    "NASDAQ": {2026: US_HOLIDAYS_2026},
    # CRYPTO is intentionally absent — handled in is_market_open below
}


def is_market_open(exchange: str | None, on_date: date) -> bool:
    """Return True if the given exchange is OPEN on the given date.

    Args:
        exchange: 'TSX' | 'NYSE' | 'NASDAQ' | 'CRYPTO' | None.
            None or unknown exchanges default to "open" — we don't
            want a missing exchange-id to silently block real trades.
        on_date: the calendar date to check (in the exchange's local
            time zone — for our case, US/Eastern works for both since
            Toronto and NY share ET).

    Returns:
        False only if the exchange is known AND the date is in the
        hardcoded holiday list AND the year has coverage.

    Weekends:
        Saturday and Sunday return False for equity exchanges (TSX,
        NYSE, NASDAQ). CRYPTO returns True. Caller already gates on
        market_open hours, but the weekend check is included so this
        function is a complete "is the market trading?" answer.
    """
    if exchange == "CRYPTO":
        return True  # 24/7
    if exchange is None:
        return True  # don't block on missing data
    # Weekends are closed for equity exchanges.
    # weekday(): Monday=0 ... Sunday=6
    if on_date.weekday() >= 5:
        return False
    cal_for_exchange = _BY_EXCHANGE.get(exchange)
    if cal_for_exchange is None:
        # Exchange not modeled — default open. Don't silently block.
        return True
    holidays_for_year = cal_for_exchange.get(on_date.year)
    if holidays_for_year is None:
        # Year not covered — default open. CI/tests should catch this.
        return True
    return on_date.isoformat() not in holidays_for_year


def covered_years_for(exchange: str) -> set[int]:
    """Return the set of years we have explicit coverage for on this
    exchange. Used by the test suite to ensure the current year is
    always in scope so December rolls don't silently disable the
    holiday filter."""
    return set((_BY_EXCHANGE.get(exchange) or {}).keys())
