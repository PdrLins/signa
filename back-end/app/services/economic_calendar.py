"""Macro events for "Coming up": central-bank rate decisions and CPI releases.

MANUALLY MAINTAINED. There is no free, reliable API for these dates, so they
are listed here by hand from the publishers' schedules:

  * Bank of Canada — policy interest rate announcements (bankofcanada.ca,
    "Schedule for policy interest rate announcements")
  * Federal Reserve — FOMC meetings; the decision is the LAST day of each
    meeting (federalreserve.gov, "Meeting calendars")
  * US CPI — BLS release schedule (bls.gov/schedule/news_release/cpi.htm)
  * Canada CPI — Statistics Canada release schedule ("The Daily")

LAST_REVIEWED says when the list was last checked. Dates are the
maintainer's best reading of the published schedules; entries flagged
provisional=True (all of 2027, and CPI dates not yet confirmed by the
agency) follow the usual pattern and MUST be re-checked when the agency
publishes its calendar (usually in the autumn of the prior year). Update:
edit the tuples below, bump LAST_REVIEWED, run tests/test_events_feed.py.

  events_between(start, end) -> [{"date", "code", "country", "title",
                                  "detail", "provisional"}]   pure, sorted
No AI, no network.
"""

from __future__ import annotations

from datetime import date

LAST_REVIEWED = date(2026, 9, 30)

# code -> (country, title, detail)
KINDS: dict[str, tuple[str, str, str]] = {
    "boc_rate": ("CA", "Bank of Canada rate decision",
                 "The Bank of Canada announces its policy interest rate (10:00 ET)."),
    "fed_rate": ("US", "Fed rate decision (FOMC)",
                 "The US Federal Reserve announces its rate decision (14:00 ET)."),
    "us_cpi": ("US", "US inflation (CPI)",
               "US consumer price index for the previous month (08:30 ET)."),
    "ca_cpi": ("CA", "Canada inflation (CPI)",
               "Canadian consumer price index for the previous month (08:30 ET)."),
}

# (code, ISO date, provisional)
_EVENTS: tuple[tuple[str, str, bool], ...] = (
    # ---- Bank of Canada 2026 (published)
    ("boc_rate", "2026-01-28", False), ("boc_rate", "2026-03-18", False), ("boc_rate", "2026-04-29", False),
    ("boc_rate", "2026-06-10", False), ("boc_rate", "2026-07-15", False), ("boc_rate", "2026-09-02", False),
    ("boc_rate", "2026-10-28", False), ("boc_rate", "2026-12-09", False),
    # ---- Bank of Canada 2027 (provisional: usual 8-date pattern)
    ("boc_rate", "2027-01-27", True), ("boc_rate", "2027-03-10", True), ("boc_rate", "2027-04-14", True),
    ("boc_rate", "2027-06-02", True), ("boc_rate", "2027-07-14", True), ("boc_rate", "2027-09-08", True),
    ("boc_rate", "2027-10-27", True), ("boc_rate", "2027-12-08", True),
    # ---- FOMC 2026 (published; decision day = second meeting day)
    ("fed_rate", "2026-01-28", False), ("fed_rate", "2026-03-18", False), ("fed_rate", "2026-04-29", False),
    ("fed_rate", "2026-06-17", False), ("fed_rate", "2026-07-29", False), ("fed_rate", "2026-09-16", False),
    ("fed_rate", "2026-10-28", False), ("fed_rate", "2026-12-09", False),
    # ---- FOMC 2027 (provisional)
    ("fed_rate", "2027-01-27", True), ("fed_rate", "2027-03-17", True), ("fed_rate", "2027-04-28", True),
    ("fed_rate", "2027-06-16", True), ("fed_rate", "2027-07-28", True), ("fed_rate", "2027-09-22", True),
    ("fed_rate", "2027-10-27", True), ("fed_rate", "2027-12-08", True),
    # ---- US CPI 2026 (BLS schedule)
    ("us_cpi", "2026-01-13", False), ("us_cpi", "2026-02-11", False), ("us_cpi", "2026-03-11", False),
    ("us_cpi", "2026-04-10", False), ("us_cpi", "2026-05-12", False), ("us_cpi", "2026-06-10", False),
    ("us_cpi", "2026-07-14", False), ("us_cpi", "2026-08-12", False), ("us_cpi", "2026-09-11", False),
    ("us_cpi", "2026-10-14", True), ("us_cpi", "2026-11-10", True), ("us_cpi", "2026-12-10", True),
    # ---- US CPI 2027 (provisional)
    ("us_cpi", "2027-01-13", True), ("us_cpi", "2027-02-10", True), ("us_cpi", "2027-03-10", True),
    ("us_cpi", "2027-04-13", True), ("us_cpi", "2027-05-12", True), ("us_cpi", "2027-06-10", True),
    ("us_cpi", "2027-07-14", True), ("us_cpi", "2027-08-11", True), ("us_cpi", "2027-09-14", True),
    ("us_cpi", "2027-10-13", True), ("us_cpi", "2027-11-10", True), ("us_cpi", "2027-12-10", True),
    # ---- Canada CPI 2026 (Statistics Canada)
    ("ca_cpi", "2026-01-20", False), ("ca_cpi", "2026-02-17", False), ("ca_cpi", "2026-03-16", False),
    ("ca_cpi", "2026-04-21", False), ("ca_cpi", "2026-05-19", False), ("ca_cpi", "2026-06-16", False),
    ("ca_cpi", "2026-07-21", False), ("ca_cpi", "2026-08-18", False), ("ca_cpi", "2026-09-15", False),
    ("ca_cpi", "2026-10-20", True), ("ca_cpi", "2026-11-17", True), ("ca_cpi", "2026-12-15", True),
    # ---- Canada CPI 2027 (provisional)
    ("ca_cpi", "2027-01-19", True), ("ca_cpi", "2027-02-16", True), ("ca_cpi", "2027-03-16", True),
    ("ca_cpi", "2027-04-20", True), ("ca_cpi", "2027-05-18", True), ("ca_cpi", "2027-06-15", True),
    ("ca_cpi", "2027-07-20", True), ("ca_cpi", "2027-08-17", True), ("ca_cpi", "2027-09-21", True),
    ("ca_cpi", "2027-10-19", True), ("ca_cpi", "2027-11-16", True), ("ca_cpi", "2027-12-14", True),
)

COVERED_UNTIL = max(date.fromisoformat(d) for _c, d, _p in _EVENTS)


def events_between(start: date, end: date) -> list[dict]:
    """Macro events dated start..end (inclusive), sorted by date then code. Pure."""
    out = []
    for code, iso, provisional in _EVENTS:
        d = date.fromisoformat(iso)
        if start <= d <= end:
            country, title, detail = KINDS[code]
            out.append({"date": iso, "code": code, "country": country, "title": title,
                        "detail": detail, "provisional": provisional})
    out.sort(key=lambda e: (e["date"], e["code"]))
    return out
