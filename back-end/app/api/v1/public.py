"""Public data for the web's search-engine pages ("PETR4 dividendos", "ENB.TO
ex-dividend date"). No sign-in; the same shared, cached body as the stock page
(nothing per user). Rate-limited per IP like every request.

  GET /api/v1/public/stocks/{symbol}
      The shared part of GET /stocks/{symbol} (symbol, name, quote, dividends,
      events, checks, statistics, fund, about, generated_at); no followed /
      position / slots / similar. Cache-Control: public, max-age=300.
      404 not_found · 503 data_unavailable (Yahoo down)
"""

from fastapi import APIRouter, HTTPException, Path, Response

from app.services import stock_page

router = APIRouter(prefix="/public", tags=["Public"])

PUBLIC_MAX_AGE_S = 300


@router.get("/stocks/{symbol}")
async def public_stock(response: Response, symbol: str = Path(..., min_length=1, max_length=20)):
    try:
        body = await stock_page.get_shared_page(symbol)
    except stock_page.StockPageError as e:
        raise HTTPException(status_code=e.status, detail={"code": e.code, "message": e.message})
    response.headers["Cache-Control"] = f"public, max-age={PUBLIC_MAX_AGE_S}"
    return body
