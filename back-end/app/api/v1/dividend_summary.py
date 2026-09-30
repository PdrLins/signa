"""Dividend summary and income quality (portfolio tracker, no AI).

  GET /api/v1/dividends/summary?period=next12m|YYYY&account_id=&person_id=     area.dividends
  GET /api/v1/portfolio/income-quality/{symbol}                                area.insights

Rules, thresholds and the tax model: app/services/dividend_summary.py,
dividend_tax.py, income_quality.py, income_forecast.py (docstrings).
Money is in the user's home currency.

GET /dividends/summary ->
{
  "period": "next12m" | "2025", "kind": "expected" | "received",
  "currency": "CAD", "as_of": ISO | null, "delayed_minutes": 15, "today": "2026-09-30",
  "usdcad": 1.39 | null,
  "total", "steady_total", "variable_total",        # the period's income
  "after_tax_total": float | null,                  # only with the tax view
  "months": [{"month": "2026-09", "total", "steady", "variable", "after_tax" | null,
              "days": [{"date": "2026-09-15", "amount"}]}],          # 12 months
  "forward_income",                                 # next 12 months expected (always)
  "yield_pct", "yield_on_cost_pct", "market_value",
  "growth": {"growth_5y_pct", "growth_1y_pct", "coverage_5y_pct", "coverage_1y_pct"},
  "payers": [{"symbol", "annual_amount", "period_amount", "share_pct", "yield_pct", "frequency",
              "safety": "growing"|"steady"|"variable"|"watch"|"cut"|null, "detail": code,
              "growth_5y_pct", "growth_1y_pct", "months": [12 x bool, Jan..Dec],
              "next_ex_date", "next_pay_date"}],
  "non_payers": ["BTC-USD", ...],
  "upcoming": [{"symbol", "account_id", "account_name", "ex_date", "pay_date", "pay_date_estimated",
                "per_share", "currency", "shares", "cash", "cash_native", "after_tax" | null,
                "withholding_code" | null, "estimated", "ex_passed"}],        # next 60 days
  "income_change": {"days": 30, "from_date", "to_date", "full_period", "available_from",
                    "before_total", "now_total", "change",
                    "components": {"fx", "raises", "cuts", "new_shares", "removed_shares"} | null,
                    "usdcad_before", "usdcad_now",
                    "items": [{"symbol", "kind": "raise"|"cut"|"new_position"|"removed_position"|
                               "more_shares"|"fewer_shares", "amount", ...}],
                    "reason": null | "no_history_yet" | "partial_history" | "migration_required" |
                              "whole_portfolio_only"},
  "tax": null | {"view": "after", "country", "gross_total", "after_tax_total", "lost", "recoverable",
                 "inside_fund", "cash_received",
                 "by_account_type": [{"account_type", "gross", "lost", "recoverable", "inside_fund", "after_tax"}],
                 "untyped_accounts": [{"account_id", "name", "gross"}], "notes": [...]},
  "tax_reason": null | "not_eligible" | "country_not_supported" | "view_before" | "ledger_as_recorded",
  "unconverted": ["SYM", ...], "notes": ["no_dividend_transactions"]?
}

GET /portfolio/income-quality/{symbol} ->
{"symbol", "name", "pays_dividend", "yield_pct", "frequency",
 "income_class": "steady"|"option_income"|"cash_like",
 "yield_source": "dividends_from_earnings"|"dividends_exceed_earnings"|"fund_distributions"|
                 "option_premiums"|"interest",
 "flags": ["return_of_capital_possible"]?,
 "payout_history": {"payments": [{"ex_date", "amount", "special", "change_pct"}],
                    "min_change_pct", "max_change_pct"},
 "underlying": "QQQ" | null,
 "total_return_5y": {"start", "end", "years", "symbol_pct", "underlying_pct"} | null,
 "comparison": {"difference_pct", "currency_mismatch"} | null,
 "as_of": "2026-09-30"}

Errors ({"detail": {"code", "message", ...}}): 404 account_not_found | person_not_found | not_found ·
422 invalid_period | invalid_scope | invalid_symbol · 403 upgrade_required ·
503 migration_required | storage_unavailable
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.access import require_feature
from app.core.dependencies import get_current_user
from app.services import dividend_summary, income_quality

router = APIRouter(prefix="/dividends", tags=["Dividends"])
income_router = APIRouter(prefix="/portfolio", tags=["Portfolio"])


@router.get("/summary", dependencies=[Depends(require_feature("area.dividends"))])
async def summary(
    period: str = Query("next12m", max_length=10),
    account_id: Optional[UUID] = Query(None),
    person_id: Optional[UUID] = Query(None),
    user: dict = Depends(get_current_user),
):
    return await dividend_summary.get_summary(user, period, str(account_id) if account_id else None,
                                              str(person_id) if person_id else None)


@income_router.get("/income-quality/{symbol}", dependencies=[Depends(require_feature("area.insights"))])
async def quality(symbol: str):
    return await income_quality.get_income_quality(symbol)
