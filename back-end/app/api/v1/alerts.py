"""Price alerts (migration 015). No AI. Web and iOS use the same endpoints.

  GET    /api/v1/alerts?symbol=         area.stock          list (optionally one symbol)
  POST   /api/v1/alerts                 action.alerts.edit  {symbol, direction, target_price, currency?, note?}
  PATCH  /api/v1/alerts/{id}            action.alerts.edit  {direction?, target_price?, currency?, note?, active?}
  DELETE /api/v1/alerts/{id}            action.alerts.edit

Alert:
  {"id", "symbol", "direction": "above" | "below",
   "target_price": float, "currency": "USD",          # target in this currency
   "note": str | null, "active": bool,
   "triggered_at": ISO | null, "last_price": float | null,   # set when it fired (then active=false)
   "created_at": ISO,
   "current_price": float | null,     # latest shared quote, in the alert currency (USD/CAD converted)
   "distance_pct": float | null,      # (target / current - 1) x 100; -27.5 = price must fall 27.5%;
                                      # null when inactive or unpriced
   "as_of": ISO | null}               # time of current_price (delayed ~15 min)
List: {"items": [Alert], "count", "symbol": str | null,
       "active": int (all symbols), "limit": 3 | null (null = unlimited), "remaining": int | null}
Delete: {"deleted": true, "id"}

Rules: fires once when price >= target (above) / <= target (below), checked
by the quotes job after each refresh; a fired alert is deactivated and shows
in GET /events/upcoming as a recent "price_alert" item for 7 days.
`currency` defaults to the quote's (else .TO/.V -> CAD, otherwise USD).
PATCH active=true re-arms an alert (clears triggered_at) and counts toward
the limit; changing direction/target of an active alert re-arms it too.

Errors ({"detail": {"code", "message", ...}}):
  403 alert_limit {"limit", "active", "upgrade": {"feature": "feature.unlimited_alerts", "plan": "premium"}}
      (free: 3 active alerts) · 403 upgrade_required (plan)
  404 alert_not_found
  422 invalid_symbol | invalid_direction | invalid_price | invalid_currency | invalid_note |
      nothing_to_update | already_crossed {"current_price", "currency"}
  503 migration_required {"migration": "015_price_alerts_and_slots.sql"} | storage_unavailable
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict

from app.core.access import require_feature
from app.core.api_errors import api_error, run_db_for
from app.core.dependencies import get_current_user
from app.services import price_alerts as svc

router = APIRouter(prefix="/alerts", tags=["Alerts"])


class AlertIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: Optional[Any] = None
    direction: Optional[Any] = None
    target_price: Optional[Any] = None
    currency: Optional[Any] = None
    note: Optional[Any] = None


class AlertPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    direction: Optional[Any] = None
    target_price: Optional[Any] = None
    currency: Optional[Any] = None
    note: Optional[Any] = None
    active: Optional[bool] = None


def _symbol(raw: Any) -> str:
    from app.services.stock_page import StockPageError, normalize
    try:
        return normalize(str(raw or ""))
    except StockPageError as e:
        raise api_error("invalid_symbol", e.message, 422, field="symbol")


@router.get("", dependencies=[Depends(require_feature("area.stock"))])
async def list_alerts(symbol: Optional[str] = Query(None, max_length=20),
                      user: dict = Depends(get_current_user)):
    sym = _symbol(symbol) if symbol else None
    return await run_db_for(svc.MIGRATION, svc.list_alerts, user, sym)


@router.post("", dependencies=[Depends(require_feature("action.alerts.edit"))],
             status_code=status.HTTP_201_CREATED)
async def create_alert(body: AlertIn, user: dict = Depends(get_current_user)):
    sym = _symbol(body.symbol)
    return await run_db_for(svc.MIGRATION, svc.create_alert, user, sym, body.model_dump(exclude={"symbol"}))


@router.patch("/{alert_id}", dependencies=[Depends(require_feature("action.alerts.edit"))])
async def update_alert(alert_id: UUID, body: AlertPatch, user: dict = Depends(get_current_user)):
    data = {k: getattr(body, k) for k in body.model_fields_set}
    return await run_db_for(svc.MIGRATION, svc.update_alert, user, str(alert_id), data)


@router.delete("/{alert_id}", dependencies=[Depends(require_feature("action.alerts.edit"))])
async def delete_alert(alert_id: UUID, user: dict = Depends(get_current_user)):
    return await run_db_for(svc.MIGRATION, svc.delete_alert, user, str(alert_id))
