"""Stock page — free for every access level (feature `area.stock`). Protected.

  GET /api/v1/stocks/{symbol}

No AI and no per-user cost: shared market data cached per symbol (see
app/services/stock_page.py). Consumed by the iOS app.
"""

from fastapi import APIRouter, Depends, HTTPException, Path

from app.core.access import require_feature
from app.core.dependencies import get_current_user
from app.services import stock_page

router = APIRouter(prefix="/stocks", tags=["Stocks"])


@router.get("/{symbol}", dependencies=[Depends(require_feature("area.stock"))])
async def get_stock(
    symbol: str = Path(..., min_length=1, max_length=20),
    user: dict = Depends(get_current_user),
):
    """Price, dividends, events and rule-based Signa checks for one symbol.

    `symbol`: a ticker (AAPL, ENB.TO, BTC-USD). A bare symbol is resolved
    like Check a stock: SYM, then SYM.TO, then SYM-USD (members of Signa's
    universe first, so XEQT -> XEQT.TO and BTC -> BTC-USD). The resolved
    symbol is returned in `symbol`.

    Errors: 400 {"detail": {"code": "invalid_symbol", "message"}},
            404 {"detail": {"code": "not_found", "message"}},
            403 {"detail": {"code": "upgrade_required", ...}} (plan).
    Missing data never errors: the field is null (or "na" for a check).

    Response (money in the listing `currency`; percents are PERCENT unless
    noted; dates ISO yyyy-mm-dd):
    {
      "symbol": "ENB.TO", "name": "Enbridge Inc.",
      "exchange": "NYSE" | "NASDAQ" | "TSX" | "TSXV" | "CRYPTO",
      "exchange_name": "Toronto" | null, "currency": "CAD",
      "asset_type": "stock" | "etf" | "crypto",
      "sector": str | null, "industry": str | null,
      "quote": {"price", "change_pct" (1 day), "high_52w", "low_52w",
                "market_cap", "as_of" (ISO datetime)},          # each nullable
                # price / change_pct / as_of come from the shared quotes table (the price
                # `position`, /holdings and /portfolio/summary use) when its row is at least
                # as recent as the cached page quote (Yahoo info, ~15 min cache)
      "dividend": {
        "profile": {...},        # services/dividends.get_dividend_profile (yield etc. are FRACTIONS)
                                 # + "growth_1y_pct", "growth_3y_pct", "growth_5y_pct", "growth_10y_pct":
                                 #   dividend CAGR, PERCENT per year (trailing annual total vs N years
                                 #   earlier, same math as growth_5y_cagr which is a FRACTION); null when
                                 #   the history is too short / irregular, and for funds
        "rating": "good" | "fair" | "poor" | "n/a",
        "rating_code": "measured" | "none" | "etf_distribution" | "suspended" | "not_applicable" | "unavailable",
        "rules": [{"code", "effect": positive|negative|caution|info, "text", "params"}]
      },
      "events": {
        "earnings": {"date", "days", "trading_days"} | null,
        "ex_dividend": {"date", "estimated": bool, "amount"} | null,
        "dividend_payment": {"date", "estimated": bool} | null
      },
      "checks": [{"key": "uptrend" | "not_overheated" | "liquidity" | "earnings_soon" | "dividend_health",
                  "status": "pass" | "warn" | "fail" | "na",
                  "value": number | str | null, "detail_code": str, "params": {...}}],
      "statistics": {"day_low", "day_high", "low_52w", "high_52w", "market_cap",
                     "pe_ratio" (trailing), "forward_pe",
                     "dividend_yield" (FRACTION, 0.035 = 3.5%),
                     "avg_volume" (~3 months, shares), "volume" (today, shares),
                     "beta"},                                 # each nullable
      "fund": null (not an ETF, or no fund data) | {           # ETFs: long_term_check.build_fund_info
        "expense_ratio" (PERCENT, 0.2 = 0.20%/yr), "expense_ratio_source", "aum" (listing currency),
        "yield" (PERCENT), "family", "category", "legal_type", "inception_date" (yyyy-mm-dd),
        "top_holdings": [{"symbol", "name", "weight" (PERCENT)}],   # up to 15
        "holdings_listed" (int), "top10_weight" (PERCENT), "fund_of_funds" (bool),
        "sector_weights": {key: PERCENT}, "asset_classes": {key: PERCENT},   # largest first
        "pe", "pb", "turnover" (PERCENT),
        "regions": null | {"us" | "canada" | "intl_developed" | "emerging": PERCENT}   # approximate:
                   # fund-of-funds holdings mapped to regions, or a single-region index (services/fund_regions.py)
      },                                                      # each field nullable; cached ~12 h
      "similar": null | [{"symbol", "name", "expense_ratio" (PERCENT), "yield" (null),
                          "return_1y_pct", "return_5y_pct" (total return, PERCENT), "current" (bool)}],
                 # ETFs with curated peers (services/similar_funds.py), Premium (feature.similar_funds);
                 # the page's own fund is the first row (current: true). Cached ~12 h.
      "similar_locked": bool,   # Free: similar funds exist but need Premium (show the hint)
      "about": null | {"description" (longBusinessSummary, <= 3000 chars), "country", "city",
                       "state", "website", "employees" (int)},       # each nullable (Yahoo info)
      "generated_at": ISO datetime (the shared body is cached ~15 min),

      # ---- this user, never cached ----
      "followed": {"in_holdings": bool, "in_watchlist": bool},
      "slots": {"used", "limit", "remaining"} | null,         # limit/remaining null = unlimited
      "position": null (not held) | {
        "shares" (sum over accounts), "avg_cost" (share-weighted), "currency" (listing),
        "price", "home_currency",
        "market_value" (native), "market_value_home" (USD/CAD converted, else null),
        "weight_pct" (of the portfolio's priced market value, home currency, excl. cash),
        "today_pl": {"abs", "pct", "abs_home"},               # null without a live quote
        "open_pl": {"abs", "pct", "abs_home"},                # unrealized vs avg cost, over the
                                                              # lots that have an avg_cost
        "dividends_received": float | null,                   # ledger (null without transactions)
        "realized_pl": float | null,                          # ledger (null without transactions)
        "total_gain": {"abs", "pct", "abs_home"},             # open + dividends + realized; pct of cost
        "has_transactions": bool,
        "price_source": "quote" | "last_close" | null, "as_of": ISO | null,
        "per_account": [{"account_id" | null, "account_name" | null, "shares", "avg_cost",
                         "value", "value_home"}]              # largest first
      }
    }
    Checks describe the stock (information only, not advice); thresholds
    and detail codes are documented in app/services/stock_page.py.
    """
    try:
        return await stock_page.get_stock_page(symbol, user)
    except stock_page.StockPageError as e:
        raise HTTPException(status_code=e.status, detail={"code": e.code, "message": e.message})
