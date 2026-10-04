"""Stock suggestions without AI (migration 028, app/services/suggestions.py).
Ideas to look at, never advice ("disclaimer": "ideas_not_advice").

  GET /api/v1/stocks/{symbol}/similar   area.stock
      {"symbol", "similar": [Row], "also_followed": [Row], "more_locked": bool, "disclaimer"}
  GET /api/v1/suggestions               area.home
      {"also_followed": [Row], "more_locked": bool,
       "gaps": [Gap], "gaps_locked": bool, "home_currency", "disclaimer"}

Row: {"symbol", "name" | null, "asset_type": "stock" | "etf" | "crypto", "exchange_label",
      "sector" | null, "dividend_yield" (FRACTION) | null, "followed": bool,
      "reason": "same_fund_group" | "same_industry" | "same_sector" | "same_category" | "also_followed",
      "params": {"industry" | "sector" | "category": str} | {"users": int (multiple of 5, >= 5), "via": symbol} | {}}
Gap: {"code": "single_position_heavy" {"symbol", "pct"} | "sector_heavy" {"sector", "pct"}
              | "home_country_only" {"pct"} | "no_dividend_payers" {},
      "params", "ideas": [{"symbol", "name" | null}]}

Free: 3 rows per list (more_locked = there are more); Premium (feature.suggestions_all): 10.
Gaps: Premium (feature.portfolio_gaps); Free gets gaps: [] and gaps_locked: true.
503 migration_required {"migration": "028_suggestions.sql"} before the migration.
"""

from fastapi import APIRouter, Depends, Path

from app.core.access import require_feature
from app.core.api_errors import run_db_for
from app.core.dependencies import get_current_user
from app.services import stock_page
from app.services import suggestions as svc

router = APIRouter(tags=["Suggestions"])


@router.get("/stocks/{symbol}/similar", dependencies=[Depends(require_feature("area.stock"))])
async def similar(symbol: str = Path(..., min_length=1, max_length=20), user: dict = Depends(get_current_user)):
    return await run_db_for(svc.MIGRATION, svc.stock_body, stock_page.normalize(symbol), user)


@router.get("/suggestions", dependencies=[Depends(require_feature("area.home"))])
async def for_portfolio(user: dict = Depends(get_current_user)):
    return await run_db_for(svc.MIGRATION, svc.portfolio_body, user)
