"""Dividend summary for the tracker (GET /api/v1/dividends/summary). No AI.

Built from shared, cached data only: dividend profiles
(services/dividends.get_dividend_profile, ~12h per symbol, shared), the
shared quotes table, the user's ledger (transactions) and the daily
income forecast snapshots (migration 014).

  build_summary(...)   pure — everything below
  get_summary(user, period, account_id, person_id)   async orchestrator

Periods
  next12m (default)  EXPECTED income: every dividend event dated today ..
                     today+365 (pay date, else ex-date) from each profile's
                     schedule (dividend_calendar.profile_events), x the
                     shares of each holding row (account-aware).
  YYYY               RECEIVED income: the ledger's `dividend` transactions
                     of that calendar year (amounts as recorded, converted to
                     home currency on today's USD/CAD rate — simplified).
                     No dividend transactions -> totals 0 and
                     notes ["no_dividend_transactions"].
  The forward blocks (yield, growth, payers, upcoming, income_change) always
  describe the holdings as they stand today.

Money is in the user's home currency (USD/CAD converted, others listed in
`unconverted`).

Safety grade per payer (order of precedence)
  cut       recent cut (<= 24 months) or suspended           (dividends.py rules)
  watch     payout ratio > 100%, or the yield-trap rule fired
            (yield >= 1.5x its 5y average and >= 4%), or hold-mode rating "poor"
  variable  payout volatility: coefficient of variation of the payments of
            the last 12 months > VOLATILE_CV (0.25) (>= 3 payments), or an
            irregular schedule; funds with CV > FUND_STEADY_CV (0.15)
  growing   consistent grower: 5y dividend CAGR > 0 and no cut for >= 5 years
            (stocks), or 1y growth >= 3% with steady payouts (funds)
  steady    everything else that pays
Steady vs variable income (monthly bars): steady = growing | steady;
variable = variable | watch | cut, and symbols with no usable profile.

Growth (portfolio, weighted by each payer's expected income)
  growth_5y_pct  profile growth_5y_cagr (stocks with 5y history)
  growth_1y_pct  regular payments per share of the last 365 days vs the 365
                 days before (needs both windows populated with the SAME
                 number of payments: a payment that slipped across the
                 boundary or a schedule change is not growth or a cut)
  coverage_pct   share of income that had a growth figure

Payment months: 12 booleans (Jan..Dec) — months with an event in the next
12 months (pay date, else ex-date), else months of the last 12 months' ex-dates.

Why your income changed (income_change, whole portfolio only)
  today's forecast (income_forecast.compute_forecast) vs the stored
  snapshot closest to 30 days ago (latest one dated <= today-30). Until one
  that old exists, the oldest snapshot is used (full_period=false) and
  available_from = oldest + 30 days. No snapshot yet -> components null,
  available_from = today + 30. Table missing (before 014) -> available_from
  null, reason "migration_required". Scoped to an account/person ->
  reason "whole_portfolio_only".

Tax: see dividend_tax.py. Applied to expected income only (the ledger's
received amounts are shown as recorded, reason "ledger_as_recorded").
"""

from __future__ import annotations

import asyncio
import math
import statistics
from datetime import date, timedelta

from app.core.api_errors import api_error
from app.services import dividend_tax, dividends
from app.services.dividend_calendar import profile_events
from app.services.holdings_service import holding_currency
from app.services.income_forecast import compute_forecast, diff_forecasts
from app.services.portfolio_context import price_meta, to_home, value_positions

VOLATILE_CV = 0.25
FUND_STEADY_CV = 0.15
FUND_GROWING_1Y = 0.03
UPCOMING_DAYS = 60
CHANGE_DAYS = 30
STEADY_GRADES = ("growing", "steady")


def _f(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _r(v, nd=2):
    return round(v, nd) if v is not None and math.isfinite(v) else None


def _d(v) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def parse_period(period: str | None, today: date) -> tuple[str, int | None]:
    p = (period or "next12m").strip().lower()
    if p == "next12m":
        return "next12m", None
    if len(p) == 4 and p.isdigit() and 1900 <= int(p) <= today.year:
        return "year", int(p)
    raise api_error("invalid_period", "period must be next12m or a year like 2025 (not in the future).", 422,
                    field="period")


# ============================================================
# Per-symbol analytics (pure)
# ============================================================

def _history(profile: dict) -> list[tuple[date, float, bool]]:
    out = []
    for p in profile.get("history") or profile.get("last_payments") or []:
        d, a = _d(p.get("ex_date")), _f(p.get("amount"))
        if d and a:
            out.append((d, a, bool(p.get("special"))))
    return sorted(out)


def payout_cv(profile: dict, today: date) -> float | None:
    """Coefficient of variation of the last 12 months' payments (>= 3)."""
    amts = [a for d, a, _s in _history(profile) if 0 <= (today - d).days <= 365]
    if len(amts) < 3:
        return None
    mean = statistics.mean(amts)
    return statistics.pstdev(amts) / mean if mean > 0 else None


def growth_1y(profile: dict, today: date) -> float | None:
    reg = [(d, a) for d, a, s in _history(profile) if not s]
    last_w = [a for d, a in reg if 0 <= (today - d).days <= 365]
    prior_w = [a for d, a in reg if 365 < (today - d).days <= 730]
    last, prior = sum(last_w), sum(prior_w)
    has_prior = any((today - d).days > 700 for d, _ in reg)   # history reaches back ~2 years
    if not last or not prior or not has_prior or len(last_w) != len(prior_w):
        return None
    return last / prior - 1


def safety_grade(profile: dict | None, asset_type: str, today: date, option_income: bool = False) -> tuple[str | None, str]:
    """(grade, detail code). grade None for non-payers / unknown.

    Funds: uneven distributions are normal for broad index ETFs (XEQT, VFV
    pay a different amount each quarter) -> "steady" with detail
    "fund_distributions_vary". Only option-income funds are graded
    "variable" for volatile payouts."""
    p = profile or {}
    if p.get("suspended") or p.get("recent_cut"):
        return "cut", "suspended" if p.get("suspended") else "recent_cut"
    if not p.get("pays_dividend"):
        return None, p.get("reason") or "no_dividend"
    cv = payout_cv(p, today)
    fund = bool(p.get("is_fund")) or asset_type == "ETF"
    if fund:
        g1 = growth_1y(p, today)
        volatile = p.get("frequency") in (None, "irregular") or (cv is not None and cv > FUND_STEADY_CV)
        if volatile and option_income:
            return "variable", "volatile_distributions"
        if volatile:
            return "steady", "fund_distributions_vary"
        if g1 is not None and g1 >= FUND_GROWING_1Y:
            return "growing", "distribution_growing"
        return "steady", "steady_distributions"
    a = dividends.long_term_dividend_assessment(p, "STOCK", p.get("sector"), p.get("industry"))
    codes = {r["code"] for r in a["rules"]}
    if "payout_unsustainable" in codes:
        return "watch", "payout_over_100"
    if "yield_trap" in codes:
        return "watch", "yield_trap"
    if a["item"]["rating"] == "poor":
        return "watch", "rating_poor"
    if p.get("frequency") == "irregular" or (cv is not None and cv > VOLATILE_CV):
        return "variable", "volatile_payouts"
    if "consistent_grower" in codes:
        return "growing", "grows_5y"
    return "steady", "steady_payer"


def months_pattern(events: list[dict], profile: dict, today: date) -> list[bool]:
    months = [False] * 12
    for ev in events:
        d = _d(ev.get("pay_date") or ev.get("ex_date"))
        if d:
            months[d.month - 1] = True
    if not any(months):
        for d, _a, _s in _history(profile):
            if 0 <= (today - d).days <= 365:
                months[d.month - 1] = True
    return months


# ============================================================
# Tax aggregation
# ============================================================

class _Tax:
    def __init__(self, country: str | None, accounts: dict[str, dict]):
        self.country = country
        self.accounts = accounts
        self.by_type: dict[str, dict] = {}
        self.untyped: dict[str, dict] = {}
        self.totals = {"gross": 0.0, "lost": 0.0, "recoverable": 0.0, "inside_fund": 0.0, "after_tax": 0.0,
                       "cash_received": 0.0}

    def split(self, sym: str, ccy: str, account_id, gross: float, profile: dict | None) -> dict:
        acct = self.accounts.get(str(account_id)) if account_id else None
        atype = (acct or {}).get("account_type")
        rule = dividend_tax.rule_for(sym, ccy, atype, self.country, profile)
        parts = dividend_tax.apply(gross, rule)
        for k in self.totals:
            self.totals[k] += parts[k]
        if not rule["applies"]:
            key = str(account_id) if account_id else "none"
            u = self.untyped.setdefault(key, {"account_id": account_id, "name": (acct or {}).get("name"),
                                              "gross": 0.0})
            u["gross"] += gross
        else:
            b = self.by_type.setdefault(atype, {"account_type": atype, "gross": 0.0, "lost": 0.0, "recoverable": 0.0,
                                                "inside_fund": 0.0, "after_tax": 0.0})
            for k in ("gross", "lost", "recoverable", "inside_fund", "after_tax"):
                b[k] += parts[k]
        return {**parts, "code": rule["code"]}

    def out(self) -> dict:
        return {
            "view": "after", "country": self.country,
            **{f"{k}_total" if k in ("gross", "after_tax") else k: _r(v) for k, v in self.totals.items()},
            "by_account_type": [{k: (_r(v) if isinstance(v, float) else v) for k, v in b.items()}
                                for b in sorted(self.by_type.values(), key=lambda x: x["account_type"])],
            "untyped_accounts": [{**u, "gross": _r(u["gross"])} for u in self.untyped.values()],
            "notes": ["withholding_only", "inside_fund_already_in_distribution"],
        }


def tax_status(scope: dict, period_kind: str) -> tuple[bool, str | None]:
    if not scope.get("tax_eligible"):
        country = (scope.get("country") or "").upper()
        return False, "country_not_supported" if country not in ("CA", "US") and scope.get("level") != "free" \
            else "not_eligible"
    if scope.get("tax_view") != "after":
        return False, "view_before"
    if period_kind == "year":
        return False, "ledger_as_recorded"
    return True, None


# ============================================================
# Income change (pure)
# ============================================================

def income_change(snapshots: list[dict] | None, now_fc: dict, home: str, today: date,
                  scoped: bool, missing: bool = False) -> dict:
    base_out = {"days": CHANGE_DAYS, "from_date": None, "to_date": today.isoformat(), "full_period": False,
                "available_from": None, "before_total": None, "now_total": now_fc.get("total_home"),
                "change": None, "components": None, "items": [], "reason": None}
    if scoped:
        return {**base_out, "reason": "whole_portfolio_only"}
    if missing:
        return {**base_out, "reason": "migration_required"}
    snaps = sorted((s for s in snapshots or [] if _d(s.get("snapshot_date"))), key=lambda s: str(s["snapshot_date"]))
    snaps = [s for s in snaps if _d(s["snapshot_date"]) < today]
    if not snaps:
        return {**base_out, "available_from": (today + timedelta(days=CHANGE_DAYS)).isoformat(),
                "reason": "no_history_yet"}
    cutoff = today - timedelta(days=CHANGE_DAYS)
    old = [s for s in snaps if _d(s["snapshot_date"]) <= cutoff]
    base = old[-1] if old else snaps[0]
    bd = _d(base["snapshot_date"])
    full = bool(old)
    diff = diff_forecasts(base, now_fc, home)
    first = _d(snaps[0]["snapshot_date"])
    return {**base_out, "from_date": bd.isoformat(), "full_period": full,
            "available_from": None if full else (first + timedelta(days=CHANGE_DAYS)).isoformat(),
            "reason": None if full else "partial_history", **diff}


# ============================================================
# Build (pure)
# ============================================================

def build_summary(scope: dict, profiles: dict[str, dict | None], today: date, period: str = "next12m",
                  snapshots: list[dict] | None = None, snapshots_missing: bool = False) -> dict:
    kind, year = parse_period(period, today)
    home = scope["home_currency"]
    usdcad = scope.get("usdcad")
    holdings = [h for h in scope["holdings"] if (_f(h.get("shares")) or 0) > 0]
    accounts = {str(a.get("id")): a for a in scope.get("all_accounts") or scope.get("accounts") or []}
    positions = value_positions(scope["holdings"], scope.get("quotes") or {}, home, usdcad)
    tax_on, tax_reason = tax_status(scope, kind)
    tax = _Tax(scope.get("country"), accounts) if tax_on else None
    unconverted: set[str] = set()

    # --- grades per symbol
    syms = sorted({str(h.get("symbol")).upper() for h in holdings}
                  | {str(t.get("symbol") or "").upper() for t in scope.get("transactions") or []
                     if t.get("type") == "dividend" and t.get("symbol")})
    atype = {str(h.get("symbol")).upper(): str(h.get("asset_type") or "").upper() for h in holdings}
    from app.services.allocation import classify
    names = {str(h.get("symbol")).upper(): h.get("name") for h in holdings}
    option_income = {s for s in syms
                     if classify(s, names.get(s) or (profiles.get(s) or {}).get("name"), atype.get(s)) == "option_income_etfs"}
    grades = {s: safety_grade(profiles.get(s), atype.get(s, ""), today, s in option_income) for s in syms}

    def is_steady(sym: str) -> bool:
        # Income split: option-income funds and cut/at-risk payers are variable;
        # everything else (stocks, broad ETFs) is steady income.
        return sym not in option_income and grades.get(sym, (None,))[0] in STEADY_GRADES

    # --- forward events (always: payers, yield, upcoming)
    end12 = today + timedelta(days=365)
    fwd_by_sym: dict[str, float] = {}
    events_by_sym: dict[str, list[dict]] = {}
    fwd_rows: list[dict] = []
    upcoming: list[dict] = []
    fwd_by_holding: dict[int, float] = {}
    for idx, h in enumerate(holdings):
        sym = str(h["symbol"]).upper()
        prof = profiles.get(sym)
        if not prof or not prof.get("pays_dividend"):
            continue
        ccy = str(prof.get("currency") or holding_currency(h)).upper()
        shares = _f(h.get("shares"))
        evs = profile_events(prof, today)
        events_by_sym.setdefault(sym, evs)
        for ev in evs:
            d = _d(ev.get("pay_date") or ev.get("ex_date"))
            amt = ev.get("amount_per_share")
            if d is None or d < today or d > end12 or amt is None:
                continue
            cash_native = shares * amt
            cash = to_home(cash_native, ccy, home, usdcad)
            if cash is None:
                unconverted.add(sym)
                continue
            parts = tax.split(sym, ccy, h.get("account_id"), cash, prof) if tax else None
            row = {"symbol": sym, "account_id": h.get("account_id"), "date": d, "cash": cash,
                   "after_tax": parts["after_tax"] if parts else None, "steady": is_steady(sym)}
            fwd_rows.append(row)
            fwd_by_sym[sym] = fwd_by_sym.get(sym, 0.0) + cash
            fwd_by_holding[idx] = fwd_by_holding.get(idx, 0.0) + cash
            if d <= today + timedelta(days=UPCOMING_DAYS):
                acct = accounts.get(str(h.get("account_id"))) if h.get("account_id") else None
                upcoming.append({
                    "symbol": sym, "account_id": h.get("account_id"), "account_name": (acct or {}).get("name"),
                    "ex_date": ev["ex_date"], "pay_date": ev.get("pay_date"),
                    "pay_date_estimated": ev.get("pay_date_estimated"), "per_share": amt, "currency": ccy,
                    "shares": shares, "cash": _r(cash), "cash_native": _r(cash_native),
                    "after_tax": _r(parts["after_tax"]) if parts else None,
                    "withholding_code": parts["code"] if parts else None,
                    "estimated": bool(ev.get("estimated")), "ex_passed": bool(ev.get("ex_passed")),
                })
    upcoming.sort(key=lambda u: (u["pay_date"] or u["ex_date"], u["symbol"]))
    forward_total = sum(fwd_by_sym.values())

    # --- the period's bars
    if kind == "next12m":
        start = date(today.year, today.month, 1)
        period_rows = [{"symbol": r["symbol"], "date": r["date"], "cash": r["cash"], "after_tax": r["after_tax"],
                        "steady": r["steady"]} for r in fwd_rows]
    else:
        start = date(year, 1, 1)
        period_rows = []
        for t in scope.get("transactions") or []:
            d = _d(t.get("trade_date"))
            if t.get("type") != "dividend" or d is None or d.year != year:
                continue
            sym = str(t.get("symbol") or "").upper()
            amt = _f(t.get("amount")) or 0.0
            cash = to_home(amt, t.get("currency") or holding_currency({"symbol": sym}), home, usdcad)
            if cash is None:
                unconverted.add(sym)
                continue
            period_rows.append({"symbol": sym, "date": d, "cash": cash, "after_tax": None, "steady": is_steady(sym)})
    month_keys = []
    y, m = start.year, start.month
    for _ in range(12):
        month_keys.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    months = {k: {"month": k, "total": 0.0, "steady": 0.0, "variable": 0.0, "after_tax": 0.0 if tax else None,
                  "days": {}} for k in month_keys}
    total = steady_total = 0.0
    received_by_sym: dict[str, float] = {}
    for r in period_rows:
        mk = r["date"].strftime("%Y-%m")
        total += r["cash"]
        steady_total += r["cash"] if r["steady"] else 0.0
        received_by_sym[r["symbol"]] = received_by_sym.get(r["symbol"], 0.0) + r["cash"]
        b = months.get(mk)
        if b is None:
            continue
        b["total"] += r["cash"]
        b["steady" if r["steady"] else "variable"] += r["cash"]
        if tax is not None and r["after_tax"] is not None:
            b["after_tax"] += r["after_tax"]
        dk = r["date"].isoformat()
        b["days"][dk] = b["days"].get(dk, 0.0) + r["cash"]
    months_out = [{"month": b["month"], "total": _r(b["total"]), "steady": _r(b["steady"]),
                   "variable": _r(b["variable"]), "after_tax": _r(b["after_tax"]) if tax else None,
                   "days": [{"date": d, "amount": _r(v)} for d, v in sorted(b["days"].items())]}
                  for b in months.values()]

    # --- yield / yield on cost
    mv = sum(p["value_home"] for p in positions if p.get("value_home"))
    inc_cost = cost = 0.0
    pos_by = {}
    for q in positions:   # first match wins, like the scan it replaces (O(n) not O(n²))
        pos_by.setdefault((q["symbol"], q.get("account_id")), q)
    for idx, h in enumerate(holdings):
        p = pos_by.get((str(h["symbol"]).upper(), h.get("account_id")))
        if p and p.get("cost_home"):
            cost += p["cost_home"]
            inc_cost += fwd_by_holding.get(idx, 0.0)

    # --- growth weighted by income
    g5_num = g5_w = g1_num = g1_w = 0.0
    payers = []
    for sym, inc in sorted(fwd_by_sym.items(), key=lambda kv: -kv[1]):
        prof = profiles.get(sym) or {}
        g5 = _f(prof.get("growth_5y_cagr"))
        g1 = growth_1y(prof, today)
        if g5 is not None:
            g5_num += g5 * inc
            g5_w += inc
        if g1 is not None:
            g1_num += g1 * inc
            g1_w += inc
        grade, detail = grades.get(sym, (None, "unknown"))
        payers.append({
            "symbol": sym, "annual_amount": _r(inc), "period_amount": _r(received_by_sym.get(sym, 0.0)),
            "share_pct": _r(inc / forward_total * 100) if forward_total else None,
            "yield_pct": _r(_f(prof.get("yield")) * 100) if _f(prof.get("yield")) is not None else None,
            "frequency": prof.get("frequency"), "safety": grade, "detail": detail,
            "growth_5y_pct": _r(g5 * 100) if g5 is not None else None,
            "growth_1y_pct": _r(g1 * 100) if g1 is not None else None,
            "months": months_pattern(events_by_sym.get(sym, []), prof, today),
            "next_ex_date": prof.get("next_ex_date"), "next_pay_date": prof.get("next_pay_date"),
        })
    # symbols only in the ledger for that year
    for sym, amt in received_by_sym.items():
        if sym not in fwd_by_sym:
            grade, detail = grades.get(sym, (None, "unknown"))
            payers.append({"symbol": sym, "annual_amount": None, "period_amount": _r(amt), "share_pct": None,
                           "yield_pct": None, "frequency": None, "safety": grade, "detail": detail,
                           "growth_5y_pct": None, "growth_1y_pct": None, "months": [False] * 12,
                           "next_ex_date": None, "next_pay_date": None})

    notes = []
    if kind == "year" and not period_rows:
        notes.append("no_dividend_transactions")
    now_fc = compute_forecast(holdings, profiles, home, usdcad)
    meta = price_meta(positions)
    return {
        "period": period if kind == "year" else "next12m",
        "kind": "received" if kind == "year" else "expected",
        "currency": home,
        "as_of": meta["as_of"], "delayed_minutes": meta["delayed_minutes"],
        "today": today.isoformat(),
        "usdcad": usdcad,
        "total": _r(total),
        "steady_total": _r(steady_total),
        "variable_total": _r(total - steady_total),
        "after_tax_total": _r(tax.totals["after_tax"]) if tax else None,
        "months": months_out,
        "forward_income": _r(forward_total),
        "yield_pct": _r(forward_total / mv * 100) if mv > 0 else None,
        "yield_on_cost_pct": _r(inc_cost / cost * 100) if cost > 0 else None,
        "market_value": _r(mv) if mv else None,
        "growth": {"growth_5y_pct": _r(g5_num / g5_w * 100) if g5_w else None,
                   "growth_1y_pct": _r(g1_num / g1_w * 100) if g1_w else None,
                   "coverage_5y_pct": _r(g5_w / forward_total * 100) if forward_total else None,
                   "coverage_1y_pct": _r(g1_w / forward_total * 100) if forward_total else None},
        "payers": payers,
        "non_payers": sorted(s for s in {str(h["symbol"]).upper() for h in holdings}
                             if not (profiles.get(s) or {}).get("pays_dividend")),
        "upcoming": upcoming,
        "income_change": income_change(snapshots, now_fc, home, today, scope.get("account_ids") is not None,
                                       snapshots_missing),
        "tax": tax.out() if tax else None,
        "tax_reason": tax_reason,
        "unconverted": sorted(unconverted),
        "notes": notes,
    }


# ============================================================
# Orchestrator
# ============================================================

async def get_summary(user: dict, period: str | None, account_id: str | None, person_id: str | None,
                      fetch=None) -> dict:
    from app.core.api_errors import is_missing_schema, run_db
    from app.db import queries
    from app.services import dividend_calendar, usage_metrics
    from app.services.portfolio_context import load_scope

    usage_metrics.record("requests.dividends_summary")
    today = dividends.today_et()
    kind, year = parse_period(period, today)
    scope = await run_db(load_scope, user, account_id, person_id)
    syms = {str(h.get("symbol") or "").upper() for h in scope["holdings"] if h.get("symbol")}
    if kind == "year":   # a past year also lists what was received from stocks since sold
        syms |= {str(t.get("symbol") or "").upper() for t in scope["transactions"]
                 if t.get("type") == "dividend" and t.get("symbol")
                 and str(t.get("trade_date") or "")[:4] == str(year)}

    async def snapshots():
        if scope["account_ids"] is not None:
            return None, False
        try:   # only the two rows income_change reads, not 400 days of per-symbol JSON
            cutoff = today - timedelta(days=CHANGE_DAYS)
            return await asyncio.to_thread(queries.get_income_snapshot_bounds, user["user_id"],
                                           cutoff.isoformat(), today.isoformat()), False
        except Exception as e:
            return None, is_missing_schema(e)
    profiles, (snaps, missing) = await asyncio.gather(
        dividend_calendar.fetch_profiles(sorted(syms), fetch), snapshots())
    return build_summary(scope, profiles, today, period or "next12m", snaps, missing)
