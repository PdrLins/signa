"""Dividend profile + the brain's deterministic dividend rules.

Used by "Check a stock" (trade mode: services/stock_check.py, hold mode:
services/long_term_check.py) and by the compare view. Nothing here touches
the scan or the brain's entry logic.

  get_dividend_profile(symbol)   async, yfinance (blocking calls in a thread),
                                 TTL-cached ~12h per symbol
  build_profile(...)             pure: the profile from raw data
  trade_dividend_rules(...)      pure: trade-mode (5-20 trading days) rules
  long_term_dividend_assessment  pure: hold-mode scorecard item + rules + cap
  ai_summary(profile)            pure: one factual line for the AI prompts

yfinance sources (verified against yfinance 1.7.0):
  * Ticker.dividends  Series of cash amounts per share indexed by the
    EX-date (tz-aware, 09:30 local). Split-adjusted by Yahoo. Pay dates
    are NOT in the history.
  * Ticker.calendar   {"Ex-Dividend Date": date, "Dividend Date": date}
    (the latest announced cycle; often already in the past).
  * Ticker.info       exDividendDate / dividendDate (epoch s), dividendRate
    (forward annual, per share), trailingAnnualDividendRate, payoutRatio
    (fraction), fiveYearAvgDividendYield (PERCENT), sector, industry.

Pure computations (history cleaning, frequency, cuts, growth, projection)
work on a list of (date, amount) tuples, oldest first.

------------------------------------------------------------------------
THE RULES (heuristics; named constants below, easy to audit and change)
------------------------------------------------------------------------
Data rules
  * Special dividends: a payment more than SPECIAL_MULT x the median of the
    payments within +-400 days is a special (shown, but not used for
    frequency / cuts / growth). An off-cycle payment (gap to its neighbour
    < OFF_CYCLE_FRACTION of the usual gap) that deviates more from the
    local median than its neighbour is also treated as a special/extra.
  * Frequency: median gap of the regular payments over the last 3 years:
    <=45d monthly, 70-110d quarterly, 150-215d semiannual, 300-430d
    annual, otherwise irregular (and no cut/growth/projection).
  * Cut: a regular payment more than CUT_TOLERANCE below the same-slot
    payment one cycle (~1 year) earlier. Same-slot comparison keeps
    interim/final patterns (UK, Australia, Japan) from looking like cuts.
    A payer that went silent (no regular payment for ~1.5 intervals) is
    "suspended": counts as a cut.
  * recent_cut: a cut within RECENT_CUT_MONTHS (24).
  * 5-year growth: trailing annual total (last p regular payments, p =
    payments per year) now vs ~5 years earlier, as a CAGR.
  * Next ex-date / pay date: an announced date in the future (calendar /
    info) is used as-is (estimated=false); otherwise projected from the
    last ex-date + the usual gap and flagged estimated=true.

Trade mode (5-20 trading days, stock_check)
  * T1 ex_dividend_in_window: an ex-date within TRADE_WINDOW_TRADING_DAYS
    (20) trading days, at least one session away (you must own the shares
    BEFORE the ex-date). The price drops by about the dividend on the
    ex-date — that is not a loss in total return; the dividend adds
    amount/price to the expected return. Informational: the brain's
    verdict (BUY_NOW/WAIT/AVOID) is unchanged, because the brain's stops,
    targets and R:R are price-only; the reward:risk including the
    dividend is shown next to it.
  * T2 ex_dividend_stop_risk: the dividend is >= STOP_RISK_FRACTION (25%)
    of the entry-to-stop distance -> the mechanical ex-date drop alone
    eats that share of the risk budget and could trigger the price stop.
    Caution note (negative).
  * T3 ex_dividend_just_passed: the ex-date is today -> buying now does
    not get this payment.

Hold mode (long_term_check) — scorecard category "dividend"
  Positives
    P1 consistent_grower: 5y dividend CAGR > 0 AND no cut for >= 5 years
    P2 sustainable_payout: payout <= 0.75 (<= 0.90 for utilities; for
       REITs / midstream the EPS payout is noted as not meaningful)
  Negatives
    N1 recent_cut (or suspended) within 24 months            severe
    N2 payout > 1.0 ("may be unsustainable")                 severe
       (REIT / utility / midstream: moderate, with a note that their
       payout is usually judged on FFO / cash flow, not EPS)
    N3 possible yield trap: yield >= 1.5x its 5-year average
       and yield >= 4%                                        moderate
    N4 payout 0.75-1.0 (non-utility / non-REIT)               mild
  Rating: any severe -> poor; else any moderate/mild -> fair;
          P1 and P2 and no negative -> good; otherwise fair.
  Non-payers and crypto: n/a (not counted). ETFs: n/a, informational
  (fund distributions vary with holdings; cut/growth rules don't apply).
  Effect on the verdict:
    * the rating counts in the rule-based scorecard verdict like any other
      category (one "poor" can move SOLID -> REASONABLE_WITH_CAVEATS);
    * CAP: recent cut AND payout > 1.0 -> the final verdict (AI or
      scorecard) is capped at REASONABLE_WITH_CAVEATS. The brain's rule
      wins over the AI here. Dividends never upgrade a verdict.
"""

from __future__ import annotations

import asyncio
import math
import statistics
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from loguru import logger

from app.core.cache import TTLCache

ET = ZoneInfo("America/New_York")

# ── data heuristics ──
SPECIAL_MULT = 2.5
SPECIAL_WINDOW_DAYS = 400
OFF_CYCLE_FRACTION = 0.4
FREQ_LOOKBACK_YEARS = 3
FREQ_BANDS = (  # (label, payments per year, min gap, max gap)
    ("monthly", 12, 20, 45),
    ("quarterly", 4, 70, 110),
    ("semiannual", 2, 150, 215),
    ("annual", 1, 300, 430),
)
PER_YEAR = {label: p for label, p, _lo, _hi in FREQ_BANDS}
CUT_TOLERANCE = 0.15
SLOT_MIN_DAYS, SLOT_MAX_DAYS = 300, 430   # same-slot payment must be ~1 year earlier
RECENT_CUT_MONTHS = 24
GROWTH_YEARS = 5
GROWTH_DATE_TOLERANCE_DAYS = 120
LAST_PAYMENTS = 8
SCHEDULE_DAYS = 365
MAX_PAY_OFFSET_DAYS = 75
FLAT_TOLERANCE = 0.15                     # last p payments within 15% -> flat payer

# ── trade-mode rules ──
TRADE_WINDOW_TRADING_DAYS = 20
STOP_RISK_FRACTION = 0.25

# ── hold-mode rules ──
PAYOUT_SUSTAINABLE_MAX = 0.75
PAYOUT_SUSTAINABLE_MAX_UTILITY = 0.90
PAYOUT_UNSUSTAINABLE = 1.0
GROWER_MIN_YEARS_NO_CUT = 5.0
YIELD_TRAP_RATIO = 1.5
YIELD_TRAP_MIN_YIELD = 0.04

_cache = TTLCache(max_size=500, default_ttl=12 * 3600)
_CACHE_TTL = 12 * 3600
_FAIL_TTL = 600

Payment = tuple[date, float]


def _num(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def today_et() -> date:
    return datetime.now(ET).date()


def is_crypto(symbol: str, info: dict | None = None) -> bool:
    qt = str((info or {}).get("quoteType") or "").upper()
    return symbol.upper().endswith("-USD") or qt == "CRYPTOCURRENCY"


# ============================================================
# Pure: history
# ============================================================

def clean_payments(raw: Any) -> list[Payment]:
    """(date, amount) oldest first from a pandas Series (index = ex-date) or
    an iterable of pairs. Non-positive / non-numeric amounts are dropped;
    several payments on one date are summed."""
    if raw is None:
        return []
    pairs: Iterable = raw.items() if hasattr(raw, "items") else raw
    by_day: dict[date, float] = {}
    for d, a in pairs:
        amt = _num(a)
        if amt is None or amt <= 0:
            continue
        day = _to_date(d)
        if day is None:
            continue
        by_day[day] = by_day.get(day, 0.0) + amt
    return sorted(by_day.items())


def _to_date(v) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if hasattr(v, "date") and callable(v.date):   # pandas Timestamp
        try:
            return v.date()
        except Exception:
            return None
    f = _num(v)
    if f is not None and f > 0:   # epoch seconds (yfinance info)
        try:
            return datetime.fromtimestamp(f, timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _local_median(payments: list[Payment], i: int, window_days: int = SPECIAL_WINDOW_DAYS) -> float | None:
    d0 = payments[i][0]
    others = [a for j, (d, a) in enumerate(payments) if j != i and abs((d - d0).days) <= window_days]
    return statistics.median(others) if len(others) >= 2 else None


def split_specials(payments: list[Payment]) -> tuple[list[Payment], list[Payment]]:
    """(regular, specials). See the module docstring for the two rules."""
    if len(payments) < 3:
        return list(payments), []
    special_idx: set[int] = set()
    for i, (_d, a) in enumerate(payments):
        med = _local_median(payments, i)
        if med and a > SPECIAL_MULT * med:
            special_idx.add(i)
    rest = [(i, p) for i, p in enumerate(payments) if i not in special_idx]
    gaps = [(rest[k][1][0] - rest[k - 1][1][0]).days for k in range(1, len(rest))]
    if len(gaps) >= 3:
        usual = statistics.median(gaps)
        for k in range(1, len(rest)):
            (i0, p0), (i1, p1) = rest[k - 1], rest[k]
            if i0 in special_idx or i1 in special_idx:
                continue
            if (p1[0] - p0[0]).days < OFF_CYCLE_FRACTION * usual:
                m0 = _local_median(payments, i0) or p0[1]
                m1 = _local_median(payments, i1) or p1[1]
                dev0 = abs(p0[1] - m0) / m0 if m0 else 0.0
                dev1 = abs(p1[1] - m1) / m1 if m1 else 0.0
                special_idx.add(i1 if dev1 >= dev0 else i0)
    regular = [p for i, p in enumerate(payments) if i not in special_idx]
    specials = [p for i, p in enumerate(payments) if i in special_idx]
    return regular, specials


def infer_frequency(regular: list[Payment], lookback_years: int = FREQ_LOOKBACK_YEARS) -> tuple[str | None, int | None]:
    """(label, usual gap in days). None when fewer than 2 payments;
    "irregular" when the gaps fit no band (or are inconsistent)."""
    if len(regular) < 2:
        return None, None
    last = regular[-1][0]
    recent = [p for p in regular if (last - p[0]).days <= lookback_years * 366]
    if len(recent) < 2:
        recent = regular[-2:]
    gaps = [(recent[k][0] - recent[k - 1][0]).days for k in range(1, len(recent))]
    med = statistics.median(gaps)
    for label, _p, lo, hi in FREQ_BANDS:
        if lo <= med <= hi:
            inside = sum(1 for g in gaps if lo * 0.7 <= g <= hi * 1.3)
            if inside / len(gaps) >= 0.6:
                return label, int(round(med))
            break
    return "irregular", int(round(med))


def detect_cuts(regular: list[Payment], frequency: str | None) -> list[date]:
    """Dates of payments more than CUT_TOLERANCE below the same-slot payment
    one cycle earlier (~1 year). Irregular / unknown frequency -> []."""
    p = PER_YEAR.get(frequency or "")
    if not p:
        return []
    cuts: list[date] = []
    cut_level: float | None = None
    for i in range(p, len(regular)):
        d, a = regular[i]
        d0, a0 = regular[i - p]
        if not (SLOT_MIN_DAYS <= (d - d0).days <= SLOT_MAX_DAYS):
            continue  # misaligned history (a missed / extra payment)
        if a < (1 - CUT_TOLERANCE) * a0:
            # The p-1 payments after a cut still compare with pre-cut slots:
            # same cut unless the amount fell again below the cut level.
            if cuts and d0 < cuts[-1] and cut_level is not None and a >= (1 - CUT_TOLERANCE) * cut_level:
                continue
            cuts.append(d)
            cut_level = a
    return cuts


def is_stale(last_ex: date | None, interval_days: int | None, today: date) -> bool:
    """No regular payment for ~1.5 usual gaps (+45d slack; <= 450d)."""
    if last_ex is None:
        return True
    limit = min(int((interval_days or 300) * 1.5) + 45, 450)
    return (today - last_ex).days > limit


def dividend_cagr(regular: list[Payment], frequency: str | None, years: int = GROWTH_YEARS) -> float | None:
    """CAGR (fraction) of the trailing annual total (last p regular payments)
    now vs `years` earlier. None when history is too short or irregular."""
    p = PER_YEAR.get(frequency or "")
    if not p:
        return None
    n = len(regular)
    j = n - 1 - years * p
    if j - p + 1 < 0:
        return None
    d_now, d_then = regular[-1][0], regular[j][0]
    span_days = (d_now - d_then).days
    if abs(span_days - years * 365.25) > GROWTH_DATE_TOLERANCE_DAYS:
        return None
    s_now = sum(a for _d, a in regular[n - p:])
    s_then = sum(a for _d, a in regular[j - p + 1:j + 1])
    if s_then <= 0 or s_now <= 0:
        return None
    return (s_now / s_then) ** (365.25 / span_days) - 1


def years_without_cut(regular: list[Payment], cuts: list[date], today: date) -> float | None:
    if not regular:
        return None
    since = cuts[-1] if cuts else regular[0][0]
    return round(max(0.0, (today - since).days / 365.25), 1)


def projected_amounts(regular: list[Payment], frequency: str | None) -> list[float]:
    """Amounts for the next cycle, in order. Flat payers (last p payments
    within FLAT_TOLERANCE) repeat the latest amount; seasonal payers
    (interim/final) repeat the amounts of the last cycle."""
    p = PER_YEAR.get(frequency or "")
    if not p or not regular:
        return []
    last_cycle = [a for _d, a in regular[-p:]]
    lo, hi = min(last_cycle), max(last_cycle)
    if hi <= 0:
        return []
    if (hi - lo) / hi <= FLAT_TOLERANCE:
        return [regular[-1][1]] * p
    return last_cycle


def project_schedule(last_ex: date | None, interval_days: int | None, amounts: list[float], today: date,
                     confirmed_ex: date | None = None, confirmed_pay: date | None = None,
                     pay_offset_days: int | None = None, horizon_days: int = SCHEDULE_DAYS) -> list[dict]:
    """Ex-dates in [today, today + horizon]. The first one is the confirmed
    future ex-date when known (estimated=false), otherwise last_ex + k gaps.
    Pay dates: confirmed for the confirmed cycle, else ex + a known offset
    (estimated), else None."""
    out: list[dict] = []
    end = today + timedelta(days=horizon_days)
    if confirmed_ex is not None and confirmed_ex >= today:
        start, first_confirmed = confirmed_ex, True
    elif last_ex is not None and interval_days:
        start = last_ex + timedelta(days=interval_days)
        while start < today:
            start += timedelta(days=interval_days)
        first_confirmed = False
    else:
        return out
    k = 0
    cur = start
    while cur <= end:
        confirmed = first_confirmed and k == 0
        if confirmed and confirmed_pay is not None and confirmed_pay >= cur:
            pay, pay_est = confirmed_pay, False
        elif pay_offset_days is not None:
            pay, pay_est = cur + timedelta(days=pay_offset_days), True
        else:
            pay, pay_est = None, True
        amt = amounts[k % len(amounts)] if amounts else None
        out.append({"ex_date": cur.isoformat(), "pay_date": pay.isoformat() if pay else None,
                    "amount": round(amt, 6) if amt is not None else None,
                    "estimated": not confirmed, "pay_estimated": pay_est if pay else True})
        if not interval_days:
            break
        k += 1
        cur = cur + timedelta(days=interval_days)
    return out


# ============================================================
# Pure: profile
# ============================================================

def empty_profile(symbol: str, reason: str = "no_dividend") -> dict:
    return {
        "symbol": symbol, "pays_dividend": False, "suspended": False, "reason": reason,
        "currency": None, "annual_rate": None, "yield": None, "payout_ratio": None,
        "five_year_avg_yield": None, "frequency": None, "interval_days": None,
        "next_ex_date": None, "next_pay_date": None, "next_amount": None,
        "next_estimated": None, "next_pay_estimated": None,
        "upcoming": [], "last_payments": [], "growth_5y_cagr": None,
        "years_without_cut": None, "last_cut_date": None, "recent_cut": False,
        "is_fund": False, "sector": None, "industry": None,
        "history": [], "name": None, "category": None,
    }


def _months_between(a: date, b: date) -> float:
    return (b - a).days / 30.44


def build_profile(symbol: str, info: dict | None, raw_dividends: Any, calendar: dict | None,
                  today: date, price: float | None = None) -> dict:
    """The dividend profile from raw yfinance pieces. Pure."""
    from app.scanners.market_scanner import _cap_dividend_yield, _dividend_yield_fraction, _fraction

    info = info or {}
    calendar = calendar or {}
    if is_crypto(symbol, info):
        return empty_profile(symbol, "crypto")

    payments = [p for p in clean_payments(raw_dividends) if p[0] <= today]
    regular, specials = split_specials(payments)
    freq, gap = infer_frequency(regular)
    last_ex = regular[-1][0] if regular else None
    stale = is_stale(last_ex, gap if freq != "irregular" else None, today)

    rate = _num(info.get("dividendRate"))
    trailing = _num(info.get("trailingAnnualDividendRate"))
    qt = str(info.get("quoteType") or "").upper()
    is_fund = qt in ("ETF", "MUTUALFUND")

    pays = bool(regular) and not stale
    if not regular and rate and rate > 0:
        pays = True   # no history but Yahoo lists a forward rate
    cuts = detect_cuts(regular, freq) if not is_fund else []
    suspended = bool(regular) and stale and (today - (last_ex or today)).days <= RECENT_CUT_MONTHS * 30.44
    if not pays:
        prof = empty_profile(symbol, "suspended" if suspended else "no_dividend")
        prof.update({
            "suspended": suspended,
            "recent_cut": suspended,
            "last_cut_date": last_ex.isoformat() if suspended and last_ex else None,
            "last_payments": _last_payments(payments, specials),
            "currency": info.get("currency"),
            "is_fund": is_fund, "sector": info.get("sector"), "industry": info.get("industry"),
            "history": _history(payments, specials, today),
            "name": info.get("longName") or info.get("shortName"), "category": info.get("category"),
        })
        return prof

    p = PER_YEAR.get(freq or "")
    annual = None
    if rate and rate > 0:
        annual = rate
    elif trailing and trailing > 0:
        annual = trailing
    elif p and len(regular) >= p:
        annual = sum(a for _d, a in regular[-p:])
    else:
        annual = sum(a for d, a in payments if (today - d).days <= 365) or None

    y = _cap_dividend_yield(_dividend_yield_fraction(info))
    px = price or _num(info.get("regularMarketPrice")) or _num(info.get("currentPrice")) or _num(info.get("previousClose"))
    if y is None and annual and px:
        y = _cap_dividend_yield(annual / px)
    five = _num(info.get("fiveYearAvgDividendYield"))

    # Announced dates (only a FUTURE ex-date counts as the next one). The
    # calendar wins over info: info's epochs can be a day off (MSFT info
    # exDividendDate = 2026-11-19 00:00 UTC while the calendar says 11-18).
    ex_cands = [d for d in (_to_date(calendar.get("Ex-Dividend Date")), _to_date(info.get("exDividendDate"))) if d]
    pay_cands = [d for d in (_to_date(calendar.get("Dividend Date")), _to_date(info.get("dividendDate"))) if d]
    future_ex = next((d for d in ex_cands if d >= today), None)
    pay_offset = None
    for ex in ex_cands:
        for pay in pay_cands:
            if 0 <= (pay - ex).days <= MAX_PAY_OFFSET_DAYS:
                pay_offset = (pay - ex).days
                break
        if pay_offset is not None:
            break
    confirmed_pay = None
    if future_ex is not None:
        confirmed_pay = min((d for d in pay_cands if 0 <= (d - future_ex).days <= MAX_PAY_OFFSET_DAYS), default=None)

    amounts = projected_amounts(regular, freq)
    interval = gap if freq in PER_YEAR else None
    schedule = project_schedule(last_ex, interval, amounts, today, confirmed_ex=future_ex,
                                confirmed_pay=confirmed_pay, pay_offset_days=pay_offset)
    nxt = schedule[0] if schedule else None
    cagr = dividend_cagr(regular, freq) if not is_fund else None
    ywc = years_without_cut(regular, cuts, today) if (not is_fund and freq in PER_YEAR) else None
    last_cut = cuts[-1] if cuts else None
    recent = bool(last_cut and _months_between(last_cut, today) <= RECENT_CUT_MONTHS)

    return {
        "symbol": symbol,
        "pays_dividend": True,
        "suspended": False,
        "reason": None,
        "currency": info.get("currency"),
        "annual_rate": round(annual, 6) if annual else None,
        "yield": round(y, 6) if y is not None else None,
        "payout_ratio": _fraction(info.get("payoutRatio")),
        "five_year_avg_yield": round(five / 100, 6) if five is not None and five > 0 else None,
        "frequency": freq,
        "interval_days": interval,
        "next_ex_date": nxt["ex_date"] if nxt else None,
        "next_pay_date": nxt["pay_date"] if nxt else None,
        "next_amount": nxt["amount"] if nxt else None,
        "next_estimated": nxt["estimated"] if nxt else None,
        "next_pay_estimated": nxt["pay_estimated"] if nxt else None,
        "upcoming": schedule,
        "last_payments": _last_payments(payments, specials),
        "growth_5y_cagr": round(cagr, 6) if cagr is not None else None,
        "years_without_cut": ywc,
        "last_cut_date": last_cut.isoformat() if last_cut else None,
        "recent_cut": recent,
        "is_fund": is_fund,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "history": _history(payments, specials, today),
        "name": info.get("longName") or info.get("shortName"),
        "category": info.get("category"),
    }


HISTORY_YEARS = 6   # profile["history"]: payments of the last 6 years (1y/5y growth, payout volatility)


def _history(payments: list[Payment], specials: list[Payment], today: date) -> list[dict]:
    """[{ex_date, amount, special}] of the last HISTORY_YEARS years, oldest first."""
    sp = set(specials)
    cutoff = today - timedelta(days=int(HISTORY_YEARS * 365.25))
    return [{"ex_date": d.isoformat(), "amount": round(a, 6), "special": (d, a) in sp}
            for d, a in payments if d >= cutoff]


def _last_payments(payments: list[Payment], specials: list[Payment]) -> list[dict]:
    sp = set(specials)
    return [{"ex_date": d.isoformat(), "amount": round(a, 6), "special": (d, a) in sp}
            for d, a in reversed(payments[-LAST_PAYMENTS:])]


# ============================================================
# Fetch (blocking) + cache
# ============================================================

def _fetch_raw(symbol: str, info: dict | None = None) -> dict:
    """yfinance: info (unless given), dividends history, calendar. Blocking.
    Tests replace this function (no network)."""
    import yfinance as yf

    t = yf.Ticker(symbol)
    out: dict = {"info": info or {}, "dividends": None, "calendar": {}}
    if info is None:
        try:
            out["info"] = t.info or {}
        except Exception as e:
            logger.debug(f"dividends: info({symbol}) failed: {e}")
    try:
        out["dividends"] = t.dividends
    except Exception as e:
        logger.debug(f"dividends: history({symbol}) failed: {e}")
    try:
        cal = t.calendar
        out["calendar"] = cal if isinstance(cal, dict) else {}
    except Exception as e:
        logger.debug(f"dividends: calendar({symbol}) failed: {e}")
    return out


async def get_dividend_profile(symbol: str, info: dict | None = None, price: float | None = None) -> dict:
    """Dividend profile for one symbol (cached ~12h). Never raises."""
    if is_crypto(symbol, info):
        return empty_profile(symbol, "crypto")
    cached = _cache.get(symbol)
    if cached is not None:
        return cached
    try:
        raw = await asyncio.to_thread(_fetch_raw, symbol, info)
        prof = build_profile(symbol, raw.get("info"), raw.get("dividends"), raw.get("calendar"),
                             today_et(), price)
        ok = bool(raw.get("info")) or raw.get("dividends") is not None
    except Exception as e:
        logger.warning(f"dividends: profile({symbol}) failed: {e}")
        prof, ok = empty_profile(symbol, "unavailable"), False
    _cache.set(symbol, prof, ttl=_CACHE_TTL if ok else _FAIL_TTL)
    return prof


# ============================================================
# Pure: rules
# ============================================================

def _rule(code: str, effect: str, text: str, params: dict | None = None) -> dict:
    """effect: positive | negative | caution | info."""
    return {"code": code, "effect": effect, "text": text, "params": params or {}}


def trade_dividend_rules(profile: dict | None, price: float | None, entry: float | None, stop: float | None,
                         target: float | None, exchange: str | None, today: date | None = None,
                         window: int = TRADE_WINDOW_TRADING_DAYS) -> tuple[list[dict], dict | None]:
    """(rules, levels_dividend) for the trade-mode check. Informational:
    the brain verdict is unchanged (see the module docstring)."""
    from app.core.market_calendar import trading_days_until

    prof = profile or {}
    if not prof.get("pays_dividend"):
        return [], None
    today = today or today_et()
    ex = _to_date(prof.get("next_ex_date"))
    amount = _num(prof.get("next_amount"))
    if ex is None:
        return [], None
    try:
        td = trading_days_until(exchange, ex, today)
    except Exception:
        td = None
    if td is None:
        td = max(0, int((ex - today).days * 5 / 7))
    if td == 0:
        return [_rule("ex_dividend_just_passed", "info",
                      "The stock goes ex-dividend today: buying now does not get this payment.",
                      {"date": ex.isoformat()})], None
    if td > window:
        return [], None
    px = price or entry
    pct = round(amount / px * 100, 2) if amount and px else None
    rr_div = None
    if amount and entry and stop is not None and target is not None and entry > stop:
        rr_div = round((target - entry + amount) / (entry - stop), 2)
    params = {"date": ex.isoformat(), "days": td, "amount": round(amount, 4) if amount else None, "pct": pct,
              "estimated": bool(prof.get("next_estimated")), "pay_date": prof.get("next_pay_date"),
              "rr": rr_div}
    rules = [_rule("ex_dividend_in_window", "positive",
                   f"Ex-dividend on {ex.isoformat()} ({td} trading days"
                   + (", estimated" if params["estimated"] else "") + "): the price should drop by about the "
                   f"dividend ({amount if amount else '?'} per share, {pct if pct is not None else '?'}% of the price) "
                   "on that day. That drop is not a loss in total return — owners before the ex-date receive the "
                   "dividend, which adds to the expected return.", params)]
    if amount and entry and stop is not None and entry > stop:
        frac = amount / (entry - stop)
        if frac >= STOP_RISK_FRACTION:
            rules.append(_rule("ex_dividend_stop_risk", "caution",
                               f"The dividend is {frac * 100:.0f}% of the distance to the stop: the ex-date drop "
                               "alone could bring the price close to the stop (stops are price-only).",
                               {"pct_of_risk": round(frac * 100, 0), "date": ex.isoformat()}))
    levels = {"ex_date": ex.isoformat(), "trading_days": td, "amount": params["amount"], "pct": pct,
              "estimated": params["estimated"], "pay_date": prof.get("next_pay_date"), "rr_with_dividend": rr_div}
    return rules, levels


def _context(profile: dict, sector: str | None, industry: str | None) -> str | None:
    """'reit' | 'utility' | 'midstream' | None — payout on EPS reads differently."""
    s = (sector or profile.get("sector") or "").lower()
    ind = (industry or profile.get("industry") or "").lower()
    if "reit" in ind or s == "real estate":
        return "reit"
    if s == "utilities" or "utilit" in ind:
        return "utility"
    if "midstream" in ind:
        return "midstream"
    return None


def long_term_dividend_assessment(profile: dict | None, asset_type: str, sector: str | None = None,
                                  industry: str | None = None) -> dict:
    """{"item": scorecard item, "rules": [...], "cap": bool}. Pure.
    See the module docstring for P1-P2 / N1-N4 and the cap."""
    prof = profile or {}
    rules: list[dict] = []

    def item(code: str, rating: str, reason: str, params: dict | None = None) -> dict:
        return {"key": "dividend", "code": code, "rating": rating, "reason": reason, "params": params or {}}

    if asset_type == "CRYPTO":
        return {"item": item("not_applicable", "n/a", "Crypto assets pay no dividends."), "rules": [], "cap": False}
    if prof.get("suspended"):
        rules.append(_rule("suspended", "negative", "The dividend appears suspended (no recent payment).",
                           {"date": prof.get("last_cut_date")}))
        rating = "poor" if asset_type == "STOCK" else "n/a"
        return {"item": item("suspended", rating, "Dividend suspended in the last 24 months — a cut to zero."),
                "rules": rules, "cap": False}
    if not prof.get("pays_dividend"):
        return {"item": item("none", "n/a", "Pays no dividend: returns rely on price growth only."),
                "rules": [], "cap": False}

    y = _num(prof.get("yield"))
    yield_pct = round(y * 100, 2) if y is not None else None
    if asset_type == "ETF" or prof.get("is_fund"):
        return {"item": item("etf_distribution", "n/a",
                             f"Distributes about {yield_pct if yield_pct is not None else '?'}% a year "
                             f"({prof.get('frequency') or 'irregular'}); fund distributions vary with the holdings, "
                             "so the cut/growth rules don't apply.",
                             {"yield": yield_pct, "frequency": prof.get("frequency")}),
                "rules": [], "cap": False}

    payout = _num(prof.get("payout_ratio"))
    cagr = _num(prof.get("growth_5y_cagr"))
    ywc = _num(prof.get("years_without_cut"))
    five = _num(prof.get("five_year_avg_yield"))
    ctx = _context(prof, sector, industry)
    severe = moderate = mild = False

    # Positives
    grower = cagr is not None and cagr > 0 and ywc is not None and ywc >= GROWER_MIN_YEARS_NO_CUT
    if grower:
        rules.append(_rule("consistent_grower", "positive",
                           f"Dividend grew {cagr * 100:.1f}%/yr over 5 years with no cut for {ywc:.0f}+ years.",
                           {"cagr": round(cagr * 100, 1), "years": ywc}))
    sustainable_max = PAYOUT_SUSTAINABLE_MAX_UTILITY if ctx == "utility" else PAYOUT_SUSTAINABLE_MAX
    sustainable = payout is not None and 0 <= payout <= sustainable_max
    if sustainable:
        rules.append(_rule("sustainable_payout", "positive",
                           f"Payout ratio {payout * 100:.0f}% of earnings (sustainable ≤ {sustainable_max * 100:.0f}%).",
                           {"payout": round(payout * 100, 0), "max": round(sustainable_max * 100, 0)}))
    if ctx in ("reit", "midstream"):
        rules.append(_rule(f"context_{ctx}", "info",
                           "For REITs and pipelines the payout on earnings (EPS) overstates the burden: "
                           "they are judged on funds from operations / distributable cash flow."))

    # Negatives
    if prof.get("recent_cut"):
        severe = True
        rules.append(_rule("recent_cut", "negative",
                           f"Dividend cut on {prof.get('last_cut_date')} (within the last {RECENT_CUT_MONTHS} months).",
                           {"date": prof.get("last_cut_date"), "months": RECENT_CUT_MONTHS}))
    if payout is not None and payout > PAYOUT_UNSUSTAINABLE:
        if ctx in ("reit", "utility", "midstream"):
            moderate = True
        else:
            severe = True
        rules.append(_rule("payout_unsustainable", "negative",
                           f"Payout ratio {payout * 100:.0f}% of earnings: the dividend exceeds profits and may be "
                           "unsustainable.", {"payout": round(payout * 100, 0)}))
    elif payout is not None and payout > sustainable_max and ctx is None:
        mild = True
        rules.append(_rule("payout_high", "caution",
                           f"Payout ratio {payout * 100:.0f}% leaves little room to raise or protect the dividend.",
                           {"payout": round(payout * 100, 0)}))
    if (y is not None and five is not None and five > 0 and y >= YIELD_TRAP_RATIO * five
            and y >= YIELD_TRAP_MIN_YIELD):
        moderate = True
        rules.append(_rule("yield_trap", "negative",
                           f"Yield {y * 100:.1f}% is far above its 5-year average {five * 100:.1f}%: the market may "
                           "expect a cut (possible yield trap).",
                           {"yield": round(y * 100, 1), "avg": round(five * 100, 1)}))

    cap = bool(prof.get("recent_cut")) and payout is not None and payout > PAYOUT_UNSUSTAINABLE
    if cap:
        rules.append(_rule("cap_verdict", "negative",
                           "Recent dividend cut and a payout above 100%: the verdict is capped at "
                           "'Reasonable, with caveats'."))

    if severe:
        rating = "poor"
    elif moderate or mild:
        rating = "fair"
    elif grower and sustainable:
        rating = "good"
    else:
        rating = "fair"
    parts = [f"yield {yield_pct:.2f}%" if yield_pct is not None else None,
             f"payout {payout * 100:.0f}%" if payout is not None else None,
             f"5y growth {cagr * 100:+.1f}%/yr" if cagr is not None else None,
             f"{ywc:.0f} years without a cut" if ywc is not None else None]
    reason = ", ".join(x for x in parts if x) or "Dividend data incomplete."
    reason = reason[0].upper() + reason[1:] + " (good: growing, no cut for 5+ years, payout ≤ 75%)."
    params = {"yield": yield_pct, "payout": round(payout * 100, 0) if payout is not None else None,
              "cagr": round(cagr * 100, 1) if cagr is not None else None, "years": ywc}
    return {"item": item("measured", rating, reason, params), "rules": rules, "cap": cap}


LONG_VERDICT_ORDER = ("NOT_A_GOOD_FIT", "REASONABLE_WITH_CAVEATS", "SOLID")


def apply_verdict_cap(verdict: str, cap: bool) -> tuple[str, dict | None]:
    """SOLID -> REASONABLE_WITH_CAVEATS when the dividend cap fires."""
    if cap and verdict == "SOLID":
        return "REASONABLE_WITH_CAVEATS", {"code": "dividend_cut_unsustainable", "from": "SOLID",
                                           "to": "REASONABLE_WITH_CAVEATS"}
    return verdict, None


def ai_summary(profile: dict | None) -> str:
    """One factual line for the AI prompts (kept short on purpose)."""
    p = profile or {}
    if p.get("suspended"):
        return f"Dividend suspended (last payment {p.get('last_cut_date')})."
    if not p.get("pays_dividend"):
        return "No regular dividend."
    bits = []
    y = _num(p.get("yield"))
    if y is not None:
        bits.append(f"yield {y * 100:.2f}%")
    if p.get("annual_rate"):
        bits.append(f"annual {p['annual_rate']:g}/share")
    if p.get("frequency"):
        bits.append(str(p["frequency"]))
    if p.get("next_ex_date"):
        bits.append(f"next ex-date {p['next_ex_date']}" + (" (estimated)" if p.get("next_estimated") else ""))
    g = _num(p.get("growth_5y_cagr"))
    if g is not None:
        bits.append(f"5y dividend CAGR {g * 100:+.1f}%/yr")
    if p.get("years_without_cut") is not None:
        bits.append(f"{p['years_without_cut']:g} years without a cut")
    bits.append(f"recent cut: {'yes (' + str(p.get('last_cut_date')) + ')' if p.get('recent_cut') else 'no'}")
    pr = _num(p.get("payout_ratio"))
    if pr is not None:
        bits.append(f"payout ratio {pr * 100:.0f}%")
    return "Dividend: " + ", ".join(bits) + "."
