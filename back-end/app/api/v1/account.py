"""Delete my account / download my data (migration 030, app/services/account.py).

  DELETE /api/v1/account        area.profile
         {"password": str, "now"?: false}
         200 {"status": "pending_deletion", "deletion_date": "YYYY-MM-DD"}   (30 days; sign in
             with "restore_account": true before then to keep the account)
           | {"status": "deleted"}                                           ("now": true)
         Every session is ended either way. 403 wrong_password | owner_cannot_delete.
  GET    /api/v1/account/export area.profile
         One JSON document with everything the user entered or that describes them
         (attachment signa-export-YYYY-MM-DD.json): one key per kind of data
         (account.EXPORT_TABLES, incl. fixed_income, dismissed_auto_dividends, telegram,
         invites_sent, active_days) and "left_out" {what: why} for what isn't included.
  GET    /api/v1/account/email  area.profile
         {"email" | null, "email_verified": bool, "has_telegram": bool, "signin_code": "telegram" | "email" | null}
  POST   /api/v1/account/email  {"email", "password"} -> {"session_token", "message"}: a code goes
         to the new address (403 wrong_password · 409 email_taken · 422 invalid_email)
  POST   /api/v1/account/email/confirm {"session_token", "code"} -> {"email", "email_verified_at"}
         A verified email lets the user reset a forgotten password (POST /auth/password/forgot).
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
from app.services import identity

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


class EmailBody(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=256)


class EmailConfirmBody(BaseModel):
    session_token: str = Field(..., min_length=10, max_length=200)
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


@router.get("/email", dependencies=[Depends(require_feature("area.profile"))])
async def email_status(user: dict = Depends(get_current_user)):
    return await run_db_for(identity.MIGRATION, identity.account_status, user["user_id"])


@router.post("/email", dependencies=[Depends(require_feature("area.profile"))])
async def email_start(body: EmailBody, user: dict = Depends(get_current_user)):
    return await run_db_for(identity.MIGRATION, identity.start_email_change, user["user_id"], body.email,
                            body.password)


@router.post("/email/confirm", dependencies=[Depends(require_feature("area.profile"))])
async def email_confirm(body: EmailConfirmBody, user: dict = Depends(get_current_user)):
    return await run_db_for(identity.MIGRATION, identity.confirm_email_change, user["user_id"],
                            body.session_token, body.code)
