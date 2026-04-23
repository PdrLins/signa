"""Brain Wallet API — deposits, withdrawals, transaction history.

The wallet powers every new brain trade after Day 15. Users deposit cash
(default $10,000), the brain sizes positions as a % of balance, and the
ledger here records every mutation for audit and reconstruction.

Endpoints:

  GET  /api/v1/wallet                 — balance, reserved, total value, ROI
  POST /api/v1/wallet/deposit         — credit the wallet
  POST /api/v1/wallet/withdraw        — debit (errors if > free balance)
  GET  /api/v1/wallet/transactions    — paginated audit ledger

All sync wallet work runs through asyncio.to_thread so FastAPI's event
loop stays unblocked during Supabase round trips.
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.core.dependencies import get_current_user
from app.services import wallet as wallet_svc

router = APIRouter(prefix="/wallet", tags=["Wallet"])


class WalletAmountRequest(BaseModel):
    amount: float = Field(..., gt=0, description="Dollar amount, must be positive")
    note: str | None = Field(None, max_length=500)


@router.get("")
async def get_wallet(user: dict = Depends(get_current_user)):
    """Return current wallet state + open-position mark-to-market value.

    total_value = Pocket + Reserved + Holdings (mark-to-market of every
    open brain position, wallet and legacy). Computes directly — does
    NOT go through the 5-minute virtual_summary cache — so deposit and
    withdraw feedback is immediate and accurate.
    """
    def _fetch():
        from app.services.virtual_portfolio import calculate_brain_holdings_value
        open_value = calculate_brain_holdings_value(user["user_id"])
        return wallet_svc.wallet_summary(user["user_id"], open_positions_value=open_value)

    return await asyncio.to_thread(_fetch)


@router.post("/deposit", status_code=status.HTTP_201_CREATED)
async def deposit(body: WalletAmountRequest, user: dict = Depends(get_current_user)):
    """Credit the wallet. First deposit sets initial_deposit for the ROI baseline.

    Returns the raw wallet state (balance / collateral / initial / deposited /
    withdrawn). Does NOT include total_value or ROI — those need the
    open-position mark-to-market, which the frontend gets by invalidating
    and re-reading GET /wallet. Keeping the mutation response honest
    about what it knows prevents the UI from rendering a stale total.

    Can return 503 if this is the first deposit and the legacy-holdings
    price snapshot fails (e.g. yfinance timeout). Retry when the feed
    recovers — we cannot baseline ROI safely without that snapshot.
    """
    try:
        await asyncio.to_thread(
            wallet_svc.deposit, user["user_id"], body.amount, body.note
        )
    except wallet_svc.LegacySnapshotFailed as e:
        # Transient — the user should retry in a moment. We refuse
        # rather than silently baselining at cash-only (which would
        # misread legacy liquidations as gains going forward).
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    # Invalidate the cached virtual_summary so the next /virtual-portfolio
    # read reflects the new balance immediately (otherwise the dashboard
    # keeps showing stale numbers for up to 5 minutes).
    _invalidate_summary_cache()

    return await asyncio.to_thread(wallet_svc.wallet_state, user["user_id"])


@router.post("/withdraw", status_code=status.HTTP_200_OK)
async def withdraw(body: WalletAmountRequest, user: dict = Depends(get_current_user)):
    """Debit the wallet. Collateral reserved for open shorts is NOT withdrawable.

    Returns the same raw wallet-state shape as /deposit.
    """
    try:
        await asyncio.to_thread(
            wallet_svc.withdraw, user["user_id"], body.amount, body.note
        )
    except ValueError as e:
        # Includes both "amount <= 0" and "insufficient balance" — both are
        # user-driven errors, 400 is the right code for both.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    _invalidate_summary_cache()

    return await asyncio.to_thread(wallet_svc.wallet_state, user["user_id"])


@router.get("/transactions")
async def list_transactions(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user),
):
    """Return the audit ledger, newest first. Paginated via `limit` + `offset`."""
    rows = await asyncio.to_thread(
        wallet_svc.list_transactions, user["user_id"], limit, offset
    )
    return {"transactions": rows, "count": len(rows), "limit": limit, "offset": offset}


def _invalidate_summary_cache() -> None:
    """Drop the virtual_summary TTLCache entry so the next read re-computes.

    Without this, a deposit/withdraw doesn't show up on /virtual-portfolio
    for up to 5 minutes (the default TTL).
    """
    try:
        from app.services.virtual_portfolio import _vp_cache
        _vp_cache.delete("summary")
    except Exception as e:
        from loguru import logger
        logger.debug(f"summary cache invalidation failed: {e}")
