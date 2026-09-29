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

UPDATE (decision-quality reset): 2026 stays hardcoded (verified), and
every year from 2027 on is COMPUTED from the NYSE / TMX holiday rules
(`generate_us_holidays` / `generate_tsx_holidays`), so a forgotten
December update can no longer silently turn holidays into trading days.

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

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


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


# ── Rule-based generation (2027+) ───────────────────────────
# The hardcoded 2026 sets above are the verified source of truth for
# 2026. Every later year is COMPUTED from the published NYSE / TMX
# holiday rules so the calendar can never silently lapse at a year
# roll (the old design defaulted every uncovered year to "open").
# `tests/test_scoring_calendar.py` pins that the generator reproduces
# the verified 2026 lists exactly, plus the known 2027 dates.
#
# Not modeled: one-off closures (national days of mourning, weather).


def _easter_sunday(year: int) -> date:
    """Gregorian Easter (anonymous Gregorian algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    month = (h + ll - 7 * m + 114) // 31
    day = ((h + ll - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-th (1-based) given weekday (Mon=0) of a month."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    nxt = date(year + (month // 12), (month % 12) + 1, 1)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _us_observed(d: date) -> date:
    """NYSE rule: Saturday holiday -> Friday, Sunday holiday -> Monday."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def _ca_observed(d: date) -> date:
    """TSX rule: weekend holiday -> following Monday."""
    if d.weekday() == 5:
        return d + timedelta(days=2)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def generate_us_holidays(year: int) -> frozenset[str]:
    """NYSE/NASDAQ full-day closures for `year`."""
    days: set[date] = set()
    ny = date(year, 1, 1)
    # NYSE does NOT close on Friday Dec 31 when Jan 1 is a Saturday.
    if ny.weekday() != 5:
        days.add(_us_observed(ny))
    days.add(_nth_weekday(year, 1, 0, 3))    # MLK Day
    days.add(_nth_weekday(year, 2, 0, 3))    # Presidents' Day
    days.add(_easter_sunday(year) - timedelta(days=2))  # Good Friday
    days.add(_last_weekday(year, 5, 0))      # Memorial Day
    days.add(_us_observed(date(year, 6, 19)))  # Juneteenth
    days.add(_us_observed(date(year, 7, 4)))   # Independence Day
    days.add(_nth_weekday(year, 9, 0, 1))    # Labor Day
    days.add(_nth_weekday(year, 11, 3, 4))   # Thanksgiving (4th Thu)
    days.add(_us_observed(date(year, 12, 25)))  # Christmas
    return frozenset(d.isoformat() for d in days)


def generate_tsx_holidays(year: int) -> frozenset[str]:
    """TSX full-day closures for `year`."""
    days: set[date] = set()
    days.add(_ca_observed(date(year, 1, 1)))   # New Year's Day
    days.add(_nth_weekday(year, 2, 0, 3))      # Family Day
    days.add(_easter_sunday(year) - timedelta(days=2))  # Good Friday
    may24 = date(year, 5, 24)                  # Victoria Day: Monday on/before May 24
    days.add(may24 - timedelta(days=may24.weekday()))
    days.add(_ca_observed(date(year, 7, 1)))   # Canada Day
    days.add(_nth_weekday(year, 8, 0, 1))      # Civic Holiday
    days.add(_nth_weekday(year, 9, 0, 1))      # Labour Day
    days.add(_nth_weekday(year, 10, 0, 2))     # Thanksgiving (CA)
    # Christmas + Boxing Day, both shifted off weekends without colliding.
    xmas = _ca_observed(date(year, 12, 25))
    boxing = date(year, 12, 26)
    if boxing.weekday() >= 5 or boxing <= xmas:
        boxing = xmas + timedelta(days=1)
        while boxing.weekday() >= 5:
            boxing += timedelta(days=1)
    days.add(xmas)
    days.add(boxing)
    return frozenset(d.isoformat() for d in days)


# Years generated eagerly so covered_years_for() reports them.
_GENERATED_YEARS = range(2027, 2036)

# Master lookup keyed by exchange. 2026 = verified hardcoded lists;
# later years computed from rules.
_BY_EXCHANGE: dict[str, dict[int, frozenset[str]]] = {
    "TSX": {2026: TSX_HOLIDAYS_2026, **{y: generate_tsx_holidays(y) for y in _GENERATED_YEARS}},
    "NYSE": {2026: US_HOLIDAYS_2026, **{y: generate_us_holidays(y) for y in _GENERATED_YEARS}},
    "NASDAQ": {2026: US_HOLIDAYS_2026, **{y: generate_us_holidays(y) for y in _GENERATED_YEARS}},
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
    if holidays_for_year is None and on_date.year > 2026:
        # Beyond the eager window — compute from the rules.
        holidays_for_year = (
            generate_tsx_holidays(on_date.year) if exchange == "TSX"
            else generate_us_holidays(on_date.year)
        )
    if holidays_for_year is None:
        # Pre-2026 — not modeled, default open.
        return True
    return on_date.isoformat() not in holidays_for_year


def covered_years_for(exchange: str) -> set[int]:
    """Return the set of years we have explicit coverage for on this
    exchange. Used by the test suite to ensure the current year is
    always in scope so December rolls don't silently disable the
    holiday filter."""
    return set((_BY_EXCHANGE.get(exchange) or {}).keys())


# ============================================================
# SESSION / BAR HELPERS (used by indicators + earnings blackout)
# ============================================================

_ET = ZoneInfo("America/New_York")
# TSX and NYSE/NASDAQ share the 16:00 ET regular close.
REGULAR_SESSION_CLOSE_ET = time(16, 0)


def is_daily_bar_complete(exchange: str | None, bar_date: date, now: datetime | None = None) -> bool:
    """Return True if the daily bar dated `bar_date` is final.

    Equities: a bar for today's ET date is incomplete until the
    regular session closes (16:00 ET). Bars for earlier dates are
    complete.

    Crypto: yfinance crypto daily bars are UTC calendar days, so the
    bar for today's UTC date is always still forming.
    """
    now = now or datetime.now(_ET)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_ET)
    if exchange == "CRYPTO":
        return bar_date < now.astimezone(ZoneInfo("UTC")).date()
    now_et = now.astimezone(_ET)
    if bar_date < now_et.date():
        return True
    if bar_date > now_et.date():
        return False
    # Today's bar: final only after the close (or if the exchange didn't
    # trade today at all — then the bar is a stale artefact, treat final).
    if not is_market_open(exchange, now_et.date()):
        return True
    return now_et.time() >= REGULAR_SESSION_CLOSE_ET


def trading_days_until(exchange: str | None, target: date, today: date | None = None) -> int | None:
    """Count trading sessions after `today` up to and including `target`.

    0 = target is today, 1 = next session, ... Returns None if target is
    in the past. Crypto counts calendar days.
    """
    today = today or datetime.now(_ET).date()
    if target < today:
        return None
    if target == today:
        return 0
    count = 0
    d = today
    while d < target:
        d += timedelta(days=1)
        if exchange == "CRYPTO" or is_market_open(exchange, d):
            count += 1
    return count
