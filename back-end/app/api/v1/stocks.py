"""Stock page — free for every access level (feature `area.stock`). Protected.

  GET /api/v1/stocks/{symbol}

No AI and no per-user cost: shared market data cached per symbol (see
app/services/stock_page.py). Consumed by the web app and the iOS app;
front-end types: front-end/src/types/stock.ts.
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
      "dividend": {
        "profile": {...},        # services/dividends.get_dividend_profile (yield etc. are FRACTIONS)
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
      "generated_at": ISO datetime (the shared body is cached ~15 min),

      # ---- this user, never cached ----
      "followed": {"in_holdings": bool, "in_watchlist": bool},
      "slots": {"used", "limit", "remaining"} | null,         # limit/remaining null = unlimited
      "position": null (not held) | {
        "shares" (sum over accounts), "avg_cost" (share-weighted), "currency" (listing),
        "price", "home_currency",
        "market_value" (native), "market_value_home" (USD/CAD converted, else null),
        "weight_pct" (of the portfolio's priced market value, home currency, excl. cash),
        "today_pl": {"abs", "pct", "abs_home"},
        "open_pl": {"abs", "pct", "abs_home"},                # unrealized vs avg cost
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
