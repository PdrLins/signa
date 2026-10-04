"""Fixed income entered by hand (migration 032, app/services/fixed_income.py).

  GET    /api/v1/fixed-income         area.holdings
         {"items": [Asset], "count", "home_currency", "total_home", "invested_home", "estimated"}
  POST   /api/v1/fixed-income         action.holdings.edit   -> 201 Asset
         {"name", "kind", "indexer"?, "rate", "principal", "start_date", "maturity_date"?,
          "tax_exempt"?, "currency"? ("BRL"), "account_id"?, "note"?}
  PATCH  /api/v1/fixed-income/{id}    action.holdings.edit   any of the fields -> Asset
  DELETE /api/v1/fixed-income/{id}    action.holdings.edit   -> {"deleted": true, "id"}

kind: tesouro_selic | tesouro_prefixado | tesouro_ipca | cdb | lci | lca | lc | debenture | cri | cra | other
indexer: cdi | selic | pre | ipca (Tesouro kinds default to theirs). rate: cdi/selic = % of the index
(110 = 110% of CDI, 1-300); pre = % a year (0-100); ipca = spread % a year over IPCA (0-50).
tax_exempt defaults to true for LCI, LCA, CRI, CRA.

Asset: the stored fields + {"value" (gross, today), "gain", "gain_pct", "net_value" (after the
estimated income tax), "tax_rate" (0.225 ... 0.15, 0 when exempt), "days", "estimated" (rates
unavailable: value = principal), "matured", "value_home"}.
Errors: 422 invalid_name | invalid_kind | invalid_indexer | invalid_rate {"min", "max"} |
invalid_principal | invalid_start_date | invalid_maturity_date | invalid_tax_exempt |
invalid_currency | invalid_note | invalid_account | fixed_income_limit (200) | nothing_to_update ·
404 not_found · 503 migration_required {"migration": "032_auto_dividends_fixed_income.sql"}.
"""

from uuid import UUID

from fastapi import APIRouter, Body, Depends, status

from app.core.access import require_feature
from app.core.api_errors import run_db_for, run_db_write
from app.core.dependencies import get_current_user
from app.services import fixed_income as svc

router = APIRouter(prefix="/fixed-income", tags=["Fixed income"])


@router.get("", dependencies=[Depends(require_feature("area.holdings"))])
async def list_assets(user: dict = Depends(get_current_user)):
    return await run_db_for(svc.MIGRATION, svc.list_body, user)


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_feature("action.holdings.edit"))])
async def create(body: dict = Body(...), user: dict = Depends(get_current_user)):
    return await run_db_write(svc.MIGRATION, svc.create, user, body)


@router.patch("/{asset_id}", dependencies=[Depends(require_feature("action.holdings.edit"))])
async def update(asset_id: UUID, body: dict = Body(...), user: dict = Depends(get_current_user)):
    return await run_db_for(svc.MIGRATION, svc.update, user, str(asset_id), body)


@router.delete("/{asset_id}", dependencies=[Depends(require_feature("action.holdings.edit"))])
async def delete(asset_id: UUID, user: dict = Depends(get_current_user)):
    return await run_db_for(svc.MIGRATION, svc.delete, user, str(asset_id))
