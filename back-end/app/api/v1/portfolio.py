"""Portfolio API routes — protected."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.dependencies import get_current_user
from app.db import queries
from app.models.portfolio import PortfolioAddRequest, PortfolioUpdateRequest

router = APIRouter(prefix="/portfolio", tags=["Portfolio"])


@router.get("")
async def get_portfolio(user: dict = Depends(get_current_user)):
    """Get all portfolio positions."""
    items = queries.get_portfolio(user["user_id"])
    return {"items": items, "count": len(items)}


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_portfolio_item(
    body: PortfolioAddRequest,
    user: dict = Depends(get_current_user),
):
    """Add a position to the portfolio."""
    data = {
        "symbol": body.symbol.upper(),
        "bucket": body.bucket,
        "account_type": body.account_type,
        "shares": float(body.shares) if body.shares else None,
        "avg_cost": float(body.avg_cost) if body.avg_cost else None,
        "currency": body.currency,
    }
    item = queries.add_portfolio_item(user["user_id"], data)
    return item


@router.put("/{item_id}")
async def update_portfolio_item(
    item_id: UUID,
    body: PortfolioUpdateRequest,
    user: dict = Depends(get_current_user),
):
    """Update a portfolio position."""
    data = body.model_dump(exclude_none=True)
    if "shares" in data:
        data["shares"] = float(data["shares"])
    if "avg_cost" in data:
        data["avg_cost"] = float(data["avg_cost"])
    item = queries.update_portfolio_item(str(item_id), user["user_id"], data)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio item not found")
    return item


@router.delete("/{item_id}")
async def delete_portfolio_item(
    item_id: UUID,
    user: dict = Depends(get_current_user),
):
    """Delete a portfolio position."""
    deleted = queries.delete_portfolio_item(str(item_id), user["user_id"])
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio item not found")
    return {"message": "Portfolio item deleted"}
