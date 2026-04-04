"""Position tracking API routes — protected."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from app.core.dependencies import get_current_user
from app.models.positions import PositionCloseRequest, PositionCreateRequest, PositionUpdateRequest
from app.services import position_service

router = APIRouter(prefix="/positions", tags=["Positions"])


@router.get("")
async def get_positions(user: dict = Depends(get_current_user)):
    """Get all open positions."""
    positions = position_service.get_open_positions()
    return {"positions": positions, "count": len(positions)}


@router.get("/history")
async def get_position_history(
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_current_user),
):
    """Get closed positions (trade history)."""
    positions = position_service.get_closed_positions(limit)
    return {"positions": positions, "count": len(positions)}


@router.get("/{position_id}")
async def get_position(
    position_id: UUID,
    user: dict = Depends(get_current_user),
):
    """Get a single position."""
    position = position_service.get_position(str(position_id))
    if not position:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found")
    return position


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_position(
    body: PositionCreateRequest,
    user: dict = Depends(get_current_user),
):
    """Open a new position."""
    position = position_service.open_position(
        symbol=body.symbol.upper(),
        entry_price=float(body.entry_price),
        shares=float(body.shares),
        account_type=body.account_type,
        bucket=body.bucket,
        currency=body.currency,
        target_price=float(body.target_price) if body.target_price else None,
        stop_loss=float(body.stop_loss) if body.stop_loss else None,
        notes=body.notes,
    )
    return position


@router.put("/{position_id}")
async def update_position(
    position_id: UUID,
    body: PositionUpdateRequest,
    user: dict = Depends(get_current_user),
):
    """Update target price, stop loss, or notes."""
    data = body.model_dump(exclude_none=True)
    if "target_price" in data:
        data["target_price"] = float(data["target_price"])
    if "stop_loss" in data:
        data["stop_loss"] = float(data["stop_loss"])

    position = position_service.update_position(str(position_id), data)
    if not position:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found")
    return position


@router.post("/{position_id}/close")
async def close_position(
    position_id: UUID,
    body: PositionCloseRequest,
    user: dict = Depends(get_current_user),
):
    """Close a position (sell)."""
    position = position_service.close_position_by_id(
        str(position_id), float(body.exit_price),
    )
    if not position:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found")
    return position
