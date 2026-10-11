"""Transactions — manual entry and CSV import with Signa's template (migration 013).

No broker integrations, no AI. Field rules and CSV formats: see
app/services/transactions_service.py. `amount` is always a positive cash
amount; the direction comes from `type`.

  GET    /api/v1/transactions                    area.holdings
         ?account_id=&symbol=&type=&from=YYYY-MM-DD&to=YYYY-MM-DD&limit=100&offset=0
         -> {"items": [Tx], "count", "total", "limit", "offset", "has_more"}  (newest first)
  POST   /api/v1/transactions                    action.transactions.edit  -> 201 Tx
  PATCH  /api/v1/transactions/{id}               action.transactions.edit  -> Tx
  DELETE /api/v1/transactions/{id}               action.transactions.edit  -> {"deleted": true, "id"}
  GET    /api/v1/transactions/template?format=csv|json   action.import.csv
         csv  -> text/csv file: header + 3 example rows
         json -> {"columns": [...], "column_help": {...}, "examples": [[...]], "csv": "..."}
  POST   /api/v1/transactions/import             action.import.csv
         multipart/form-data, field "file" (CSV, <= 2 MB, <= 5,000 rows)
         ?dry_run=true (default) -> {"dry_run": true, "summary", "rows": [{"line", "status": "ok"|"error",
                                      "data", "errors": [{"field", "code", "message"}]}], "errors"}
         ?dry_run=false          -> {"dry_run": false, "import_batch_id", "imported", "skipped",
                                      "accounts_created": [{"id", "name"}], "summary", "errors"}
         &create_missing_accounts=true  create accounts named in the file that don't exist
         &skip_errors=true              import the valid rows even if some rows have errors
         &date_format=auto|dmy|mdy
         Any file's rows are skipped when identical to a stored transaction (account, date, type,
         symbol, quantity, amount): status "duplicate", summary.duplicates.
  POST   /api/v1/transactions/import/inspect     action.import.csv   (any bank's / broker's CSV)
         multipart "file" -> {"file_id" (kept 30 min), "delimiter", "encoding", "decimal",
         "header_row", "rows", "columns": [{"index", "header", "samples"}], "signature",
         "saved_mapping": Mapping | null, "suggested": {"fields", "date_format", "amount_sign",
         "type_values": [{"value", "count", "suggested"}], "extract_from_description"},
         "account_names", "warnings": [no_date_column | no_amount_column | no_symbol_column |
         ambiguous_dates | mixed_currencies_no_column | too_many_rows]}
  POST   /api/v1/transactions/import  application/json  {"file_id", "mapping": Mapping, "dry_run": true,
         "skip_errors", "create_missing_accounts", "save_mapping"?: {"name"}} -> the same answers as
         the file upload, + summary.skipped_by_mapping. Mapping: app/services/import_mapping.py.
         404 import_file_expired · 422 invalid_mapping {"field"}
  GET    /api/v1/transactions/import/mappings          -> {"items": [{"id", "name", "signature", "headers",
                                                           "updated_at"}]}   (migration 035)
  PATCH  /api/v1/transactions/import/mappings/{id}     {"name"} · DELETE same path
  DELETE /api/v1/transactions/import/{batch_id}  action.import.csv -> {"deleted": n, "import_batch_id"}

Tx: {"id", "account_id", "account_name", "symbol", "type", "trade_date", "quantity",
     "price", "amount", "currency", "fee", "note", "source": "manual"|"csv",
     "import_batch_id", "created_at"}

Errors ({"detail": {"code", "message", "field"?, "errors"?}}):
  400 nothing_to_update · 404 not_found · 413 file_too_large ·
  422 invalid_type | invalid_date | date_in_future | symbol_required |
      symbol_not_allowed | invalid_symbol | invalid_number | quantity_required |
      price_required | amount_required | invalid_split_ratio | unknown_account |
      invalid_currency | note_too_long | invalid_file | empty_file | invalid_header |
      too_many_rows | ambiguous_dates | nothing_to_import | import_has_errors ·
  503 migration_required
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, File, Query, Request, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict

from app.core.access import require_feature
from app.core.api_errors import api_error, run_db, run_db_for, run_db_write, PORTFOLIO_MIGRATION
from app.core.dependencies import get_current_user
from app.services import import_mapping
from app.services import transactions_service as svc

router = APIRouter(prefix="/transactions", tags=["Transactions"])

TxType = Literal["buy", "sell", "dividend", "deposit", "withdrawal", "split", "fee"]


class TransactionIn(BaseModel):
    """Values are checked by the service so every error carries a code."""
    model_config = ConfigDict(extra="forbid")
    account_id: Optional[UUID] = None
    symbol: Optional[str] = None
    type: Optional[str] = None
    trade_date: Optional[date] = None
    quantity: Optional[float] = None
    price: Optional[float] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    fee: Optional[float] = None
    note: Optional[str] = None


def _sent(body: BaseModel) -> dict[str, Any]:
    out = {}
    for k in body.model_fields_set:
        v = getattr(body, k)
        out[k] = str(v) if isinstance(v, UUID) else v
    return out


@router.get("", dependencies=[Depends(require_feature("area.holdings"))])
async def list_transactions(
    account_id: Optional[UUID] = Query(None),
    symbol: Optional[str] = Query(None, max_length=24),
    type: Optional[TxType] = Query(None),
    from_: Optional[date] = Query(None, alias="from"),
    to: Optional[date] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=100_000),
    user: dict = Depends(get_current_user),
):
    filters = {"account_id": str(account_id) if account_id else None,
               "symbol": symbol.strip().upper() if symbol else None, "type": type,
               "from": from_.isoformat() if from_ else None, "to": to.isoformat() if to else None}
    return await run_db(svc.list_transactions, user["user_id"], filters, limit, offset)


@router.post("", dependencies=[Depends(require_feature("action.transactions.edit"))],
             status_code=status.HTTP_201_CREATED)
async def create_transaction(body: TransactionIn, user: dict = Depends(get_current_user)):
    return await run_db_write(PORTFOLIO_MIGRATION, svc.create_transaction, user["user_id"], _sent(body))


@router.get("/template", dependencies=[Depends(require_feature("action.import.csv"))])
async def template(format: Literal["csv", "json"] = Query("csv"), user: dict = Depends(get_current_user)):
    csv_text = svc.template_csv()
    if format == "json":
        return {"columns": list(svc.TEMPLATE_COLUMNS), "column_help": svc.COLUMN_HELP,
                "examples": [list(r) for r in svc.TEMPLATE_EXAMPLES], "csv": csv_text,
                "max_rows": svc.MAX_IMPORT_ROWS, "max_bytes": svc.MAX_IMPORT_BYTES}
    return Response(content=csv_text, media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="signa-transactions-template.csv"'})


async def _upload(file: UploadFile) -> bytes:
    content = await file.read(svc.MAX_IMPORT_BYTES + 1)
    if len(content) > svc.MAX_IMPORT_BYTES:
        raise api_error("file_too_large", "The file is larger than 2 MB.",
                        413, max_bytes=svc.MAX_IMPORT_BYTES)
    return content


@router.post("/import/inspect", dependencies=[Depends(require_feature("action.import.csv"))])
async def inspect_import(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    content = await _upload(file)
    return await run_db(import_mapping.inspect_upload, user["user_id"], content)


@router.post("/import", dependencies=[Depends(require_feature("action.import.csv"))])
async def import_transactions(
    request: Request,
    dry_run: bool = Query(True),
    create_missing_accounts: bool = Query(False),
    skip_errors: bool = Query(False),
    date_format: Literal["auto", "dmy", "mdy"] = Query("auto"),
    user: dict = Depends(get_current_user),
):
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("application/json"):   # {file_id, mapping, ...} after /import/inspect
        try:
            body = await request.json()
        except ValueError:
            raise api_error("invalid_body", "The body must be JSON.", 422)
        if not isinstance(body, dict) or not body.get("file_id"):
            raise api_error("invalid_body", "Send file_id and mapping (from /transactions/import/inspect).", 422)
        return await run_db_write(PORTFOLIO_MIGRATION, import_mapping.import_with_mapping, user["user_id"], body)
    form = await request.form()
    file = form.get("file")
    if file is None or not hasattr(file, "read"):
        raise api_error("invalid_file", "Send the CSV as the multipart field \"file\".", 422)
    content = await _upload(file)
    result = await run_db_write(PORTFOLIO_MIGRATION, svc.import_csv, user["user_id"], content, dry_run=dry_run,
                          create_missing_accounts=create_missing_accounts, skip_errors=skip_errors,
                          date_format=date_format)
    return result


@router.get("/import/mappings", dependencies=[Depends(require_feature("action.import.csv"))])
async def list_import_mappings(user: dict = Depends(get_current_user)):
    return await run_db_for(import_mapping.MIGRATION, import_mapping.list_mappings, user["user_id"])


@router.patch("/import/mappings/{mapping_id}", dependencies=[Depends(require_feature("action.import.csv"))])
async def rename_import_mapping(mapping_id: UUID, body: dict = Body(...), user: dict = Depends(get_current_user)):
    return await run_db_for(import_mapping.MIGRATION, import_mapping.rename, user["user_id"], str(mapping_id),
                            body.get("name"))


@router.delete("/import/mappings/{mapping_id}", dependencies=[Depends(require_feature("action.import.csv"))])
async def delete_import_mapping(mapping_id: UUID, user: dict = Depends(get_current_user)):
    return await run_db_for(import_mapping.MIGRATION, import_mapping.delete, user["user_id"], str(mapping_id))


@router.delete("/import/{batch_id}", dependencies=[Depends(require_feature("action.import.csv"))])
async def undo_import(batch_id: UUID, user: dict = Depends(get_current_user)):
    return await run_db(svc.undo_import, user["user_id"], str(batch_id))


@router.patch("/{tx_id}", dependencies=[Depends(require_feature("action.transactions.edit"))])
async def update_transaction(tx_id: UUID, body: TransactionIn, user: dict = Depends(get_current_user)):
    return await run_db(svc.update_transaction, user["user_id"], str(tx_id), _sent(body))


@router.delete("/{tx_id}", dependencies=[Depends(require_feature("action.transactions.edit"))])
async def delete_transaction(tx_id: UUID, user: dict = Depends(get_current_user)):
    return await run_db(svc.delete_transaction, user["user_id"], str(tx_id))
