"""Delete my account / download my data (migration 030, app/services/account.py).

  DELETE /api/v1/account        area.profile
         {"password": str, "now"?: false}
         200 {"status": "pending_deletion", "deletion_date": "YYYY-MM-DD"}   (30 days; sign in
             with "restore_account": true before then to keep the account)
           | {"status": "deleted"}                                           ("now": true)
         Every session is ended either way. 403 wrong_password | owner_cannot_delete.
  GET    /api/v1/account/export area.profile
         One JSON document with everything stored about the user (attachment
         signa-export-YYYY-MM-DD.json).
503 migration_required {"migration": "030_account_lifecycle.sql"} before the migration.
"""

from datetime import date

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.access import require_feature
from app.core.api_errors import run_db_for, run_db_write
from app.core.dependencies import get_current_user
from app.services import account as svc

router = APIRouter(prefix="/account", tags=["Account"])


class DeleteBody(BaseModel):
    password: str = Field(..., min_length=1, max_length=256)
    now: bool = False


@router.delete("", dependencies=[Depends(require_feature("area.profile"))])
async def delete_account(body: DeleteBody, user: dict = Depends(get_current_user)):
    return await run_db_write(svc.MIGRATION, svc.request_deletion, user["user_id"], body.password, body.now)


@router.get("/export", dependencies=[Depends(require_feature("area.profile"))])
async def export(user: dict = Depends(get_current_user)):
    data = await run_db_for(svc.MIGRATION, svc.export, user["user_id"])
    name = f"signa-export-{date.today().isoformat()}.json"
    return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="{name}"'})
