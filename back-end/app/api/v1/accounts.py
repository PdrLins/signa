"""People and accounts — user-created, user-named (migration 013). No AI.

People (who an account belongs to):
  GET    /api/v1/people               area.holdings
  POST   /api/v1/people               action.accounts.edit   {name, color?}
  PATCH  /api/v1/people/{id}          action.accounts.edit   {name?, color?}
  DELETE /api/v1/people/{id}          action.accounts.edit   (its accounts keep existing, person_id -> null)
  Person: {"id", "name", "color": "#RRGGBB" | null, "accounts_count", "created_at"}
  List:   {"items": [Person], "count"}

Accounts:
  GET    /api/v1/accounts?person_id=  area.holdings
  POST   /api/v1/accounts             action.accounts.edit
         {name, person_id?, currency? (default: home currency), cash_balance? (0),
          account_type? (premium + country CA/US only)}
  PATCH  /api/v1/accounts/{id}        action.accounts.edit   same fields, all optional
  DELETE /api/v1/accounts/{id}?move_to=<account_id>|force=true   action.accounts.edit
  Account: {"id", "name", "person_id", "person_name", "account_type", "currency",
            "cash_balance", "holdings_count", "created_at", "updated_at"}
  List:    {"items": [Account], "count", "account_types": {"country", "types": [...]}}
  Delete:  {"deleted": true, "id", "moved_to", "moved_holdings", "merged_holdings"}

Errors ({"detail": {"code", "message", ...}}):
  400 nothing_to_update · 404 not_found · 409 duplicate_name | too_many_accounts |
  too_many_people | account_has_holdings {holdings} · 403 upgrade_required
  (account_type without action.accounts.type) · 422 invalid_name | invalid_color |
  invalid_currency | invalid_cash_balance | invalid_person | invalid_account_type |
  account_type_unavailable (country not CA/US) | invalid_move_to ·
  503 migration_required
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict

from app.core.access import require_feature
from app.core.api_errors import run_db, run_db_write, PORTFOLIO_MIGRATION
from app.core.dependencies import get_current_user
from app.services import accounts_service as svc

people_router = APIRouter(prefix="/people", tags=["Accounts"])
router = APIRouter(prefix="/accounts", tags=["Accounts"])


class PersonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[Any] = None
    color: Optional[Any] = None


class AccountIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[Any] = None
    person_id: Optional[UUID] = None
    currency: Optional[Any] = None
    cash_balance: Optional[Any] = None
    account_type: Optional[Any] = None


def _sent(body: BaseModel) -> dict:
    out = {}
    for k in body.model_fields_set:
        v = getattr(body, k)
        out[k] = str(v) if isinstance(v, UUID) else v
    return out


# ---------------------------------------------------------------- people

@people_router.get("", dependencies=[Depends(require_feature("area.holdings"))])
async def list_people(user: dict = Depends(get_current_user)):
    return await run_db(svc.list_people, user["user_id"])


@people_router.post("", dependencies=[Depends(require_feature("action.accounts.edit"))],
                    status_code=status.HTTP_201_CREATED)
async def create_person(body: PersonIn, user: dict = Depends(get_current_user)):
    return await run_db_write(PORTFOLIO_MIGRATION, svc.create_person, user["user_id"], _sent(body))


@people_router.patch("/{person_id}", dependencies=[Depends(require_feature("action.accounts.edit"))])
async def update_person(person_id: UUID, body: PersonIn, user: dict = Depends(get_current_user)):
    return await run_db(svc.update_person, user["user_id"], str(person_id), _sent(body))


@people_router.delete("/{person_id}", dependencies=[Depends(require_feature("action.accounts.edit"))])
async def delete_person(person_id: UUID, user: dict = Depends(get_current_user)):
    return await run_db(svc.delete_person, user["user_id"], str(person_id))


# ---------------------------------------------------------------- accounts

@router.get("", dependencies=[Depends(require_feature("area.holdings"))])
async def list_accounts(person_id: Optional[UUID] = Query(None), user: dict = Depends(get_current_user)):
    return await run_db(svc.list_accounts, user["user_id"], str(person_id) if person_id else None)


@router.post("", dependencies=[Depends(require_feature("action.accounts.edit"))],
             status_code=status.HTTP_201_CREATED)
async def create_account(body: AccountIn, user: dict = Depends(get_current_user)):
    return await run_db_write(PORTFOLIO_MIGRATION, svc.create_account, user, _sent(body))


@router.patch("/{account_id}", dependencies=[Depends(require_feature("action.accounts.edit"))])
async def update_account(account_id: UUID, body: AccountIn, user: dict = Depends(get_current_user)):
    return await run_db(svc.update_account, user, str(account_id), _sent(body))


@router.delete("/{account_id}", dependencies=[Depends(require_feature("action.accounts.edit"))])
async def delete_account(
    account_id: UUID,
    move_to: Optional[UUID] = Query(None),
    force: bool = Query(False),
    user: dict = Depends(get_current_user),
):
    return await run_db(svc.delete_account, user["user_id"], str(account_id),
                        str(move_to) if move_to else None, force)
