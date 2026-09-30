"""Price alerts (migration 015, table `price_alerts`) — no AI, no per-user market calls.

A user asks "tell me when ENB.TO goes below 50". The alert is checked by the
existing quotes job (services/quotes.refresh_followed_quotes): right after
the refreshed quotes are stored, `evaluate_refreshed(quotes)` reads the
ACTIVE alerts of those symbols and fires every one whose condition holds:

  above   fires when price >= target_price
  below   fires when price <= target_price

Currency: `target_price` is in the alert's `currency`. When the quote is in
another currency, the price is converted with USD/CAD only
(portfolio_snapshots.convert); an alert that can't be converted is left
active and untouched (never fired on a wrong comparison).

Firing sets triggered_at + last_price (in the alert currency) and
deactivates the alert (active=false), so it fires once. The user sees it in
GET /events/upcoming as a recent "price_alert" item for RECENT_DAYS (7)
days (`feed_items`); push delivery comes later.

Because the job only refreshes followed symbols, the symbols of active
alerts are added to the job's follow rows (`alert_follow_rows`), at the
alert owner's refresh tier (a free user has at most FREE_ALERT_LIMIT active
alerts, so the extra cost is bounded).

Limits: a free user keeps at most access.FREE_ALERT_LIMIT (3) ACTIVE alerts;
premium / owner are unlimited (feature.unlimited_alerts). Triggered and
paused alerts don't count. Over the limit -> 403
  {"code": "alert_limit", "limit": 3, "active": 3, "message",
   "upgrade": {"feature": "feature.unlimited_alerts", "plan": "premium"}}

Creating an alert whose condition already holds at the current price is
rejected (422 already_crossed, with current_price) — it would fire at once.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import status
from loguru import logger

from app.core.access import alert_limit, upgrade_hint
from app.core.api_errors import api_error
from app.services.portfolio_snapshots import convert

MIGRATION = "015_price_alerts_and_slots.sql"
DIRECTIONS = ("above", "below")
RECENT_DAYS = 7
NOTE_MAX = 200


def _f(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def default_currency(symbol: str) -> str:
    from app.services.holdings_service import holding_currency
    return holding_currency({"symbol": symbol})


# ============================================================
# Pure logic
# ============================================================

def price_in(price: float | None, price_ccy: str | None, alert_ccy: str, usdcad: float | None) -> float | None:
    """Quote price expressed in the alert currency (USD/CAD only). None = unknown."""
    if price is None:
        return None
    return convert(price, (price_ccy or alert_ccy), alert_ccy, usdcad)


def is_crossed(direction: str, target: float, price: float | None) -> bool:
    """above: price >= target; below: price <= target. Pure."""
    if price is None or target is None:
        return False
    return price >= target if direction == "above" else price <= target


def distance_pct(target: float | None, price: float | None) -> float | None:
    """How far the target is from the price, in percent of the price
    (target 50, price 69 -> -27.54: the price must fall 27.5%)."""
    if target is None or not price:
        return None
    return round((target / price - 1) * 100, 2)


def evaluate(alerts: list[dict], quotes: dict[str, dict], usdcad: float | None,
             now: datetime | None = None) -> list[dict]:
    """[{"id", "triggered_at", "last_price"}] for the active alerts that fire. Pure."""
    now = now or datetime.now(timezone.utc)
    fired = []
    for a in alerts or []:
        if not a.get("active", True):
            continue
        q = quotes.get(str(a.get("symbol") or "").upper()) or {}
        ccy = str(a.get("currency") or "").upper() or None
        target = _f(a.get("target_price"))
        if ccy is None or target is None:
            continue
        price = price_in(_f(q.get("price")), q.get("currency"), ccy, usdcad)
        if is_crossed(str(a.get("direction")), target, price):
            fired.append({"id": a["id"], "user_id": a.get("user_id"), "symbol": a.get("symbol"),
                          "triggered_at": now.isoformat(), "last_price": round(price, 4)})
    return fired


def enrich(alert: dict, quote: dict | None, usdcad: float | None) -> dict:
    """API shape of one alert (+ current price and distance). Pure."""
    q = quote or {}
    ccy = str(alert.get("currency") or "").upper()
    target = _f(alert.get("target_price"))
    cur = price_in(_f(q.get("price")), q.get("currency"), ccy, usdcad) if ccy else None
    return {
        "id": alert.get("id"),
        "symbol": alert.get("symbol"),
        "direction": alert.get("direction"),
        "target_price": target,
        "currency": ccy or None,
        "note": alert.get("note"),
        "active": bool(alert.get("active")),
        "triggered_at": alert.get("triggered_at"),
        "last_price": _f(alert.get("last_price")),
        "created_at": alert.get("created_at"),
        "current_price": round(cur, 4) if cur is not None else None,
        "distance_pct": distance_pct(target, cur) if alert.get("active") else None,
        "as_of": q.get("as_of"),
    }


def feed_items(rows: list[dict], names: dict[str, dict] | None = None) -> list[dict]:
    """Recent "price_alert" items for /events/upcoming (triggered alerts). Pure."""
    names = names or {}
    out = []
    for a in rows or []:
        when = str(a.get("triggered_at") or "")[:10]
        if not when:
            continue
        sym = str(a.get("symbol") or "").upper()
        target, price = _f(a.get("target_price")), _f(a.get("last_price"))
        out.append({
            "type": "price_alert", "date": when, "symbol": sym,
            "name": (names.get(sym) or {}).get("name"),
            "title": f"{sym} {'rose above' if a.get('direction') == 'above' else 'fell below'} {target:g}"
            if target is not None else sym,
            "detail": f"Price {price:g} {a.get('currency') or ''}".strip() if price is not None else "",
            "cash": None, "cash_home": None, "currency": a.get("currency"), "estimated": False,
            "owned": bool((names.get(sym) or {}).get("shares")), "recent": True,
            "alert_id": a.get("id"), "direction": a.get("direction"), "target_price": target,
            "last_price": price, "triggered_at": a.get("triggered_at"),
        })
    return out


# ============================================================
# Validation
# ============================================================

def validate(body: dict, partial: bool = False) -> dict:
    """Clean {symbol?, direction, target_price, currency, note, active?}; 422 on bad input."""
    out: dict = {}
    if "direction" in body or not partial:
        d = str(body.get("direction") or "").lower()
        if d not in DIRECTIONS:
            raise api_error("invalid_direction", "direction must be 'above' or 'below'.", 422, field="direction")
        out["direction"] = d
    if "target_price" in body or not partial:
        p = _f(body.get("target_price"))
        if p is None or p <= 0:
            raise api_error("invalid_price", "target_price must be a positive number.", 422, field="target_price")
        out["target_price"] = p
    if body.get("currency") is not None:
        c = str(body["currency"]).strip().upper()
        if len(c) != 3 or not c.isalpha():
            raise api_error("invalid_currency", "currency must be a 3-letter code.", 422, field="currency")
        out["currency"] = c
    if "note" in body:
        note = (str(body["note"]).strip() if body["note"] is not None else "") or None
        if note and len(note) > NOTE_MAX:
            raise api_error("invalid_note", f"note must be at most {NOTE_MAX} characters.", 422, field="note")
        out["note"] = note
    if partial and "active" in body and body["active"] is not None:
        out["active"] = bool(body["active"])
    return out


def alert_limit_error(limit: int, active: int):
    return api_error("alert_limit", f"Your plan keeps up to {limit} active price alerts.",
                     status.HTTP_403_FORBIDDEN, limit=limit, active=active,
                     upgrade=upgrade_hint("feature.unlimited_alerts"))


# ============================================================
# Service (sync; the API runs these with run_db_for)
# ============================================================

def _quotes_for(symbols: set[str]) -> tuple[dict, float | None]:
    from app.services.price_cache import get_usdcad_rate
    from app.services.quotes import get_quotes
    try:
        qs = get_quotes(symbols) if symbols else {}
    except Exception as e:
        logger.debug(f"alerts: quotes unavailable: {e}")
        qs = {}
    try:
        usdcad = get_usdcad_rate()
    except Exception:
        usdcad = None
    return qs, usdcad


def summary(user: dict, rows: list[dict]) -> dict:
    limit = alert_limit(user.get("access_level") or "free")
    active = sum(1 for r in rows if r.get("active"))
    return {"active": active, "limit": limit, "remaining": None if limit is None else max(0, limit - active)}


def list_alerts(user: dict, symbol: str | None = None) -> dict:
    from app.db import queries
    rows = queries.list_price_alerts(user["user_id"], symbol)
    all_rows = rows if symbol is None else queries.list_price_alerts(user["user_id"])
    qs, usdcad = _quotes_for({str(r["symbol"]).upper() for r in rows if r.get("symbol")})
    items = [enrich(r, qs.get(str(r.get("symbol") or "").upper()), usdcad) for r in rows]
    return {"items": items, "count": len(items), "symbol": symbol, **summary(user, all_rows)}


def _check_limit(user: dict) -> None:
    from app.db import queries
    limit = alert_limit(user.get("access_level") or "free")
    if limit is None:
        return
    active = queries.count_active_price_alerts(user["user_id"])
    if active >= limit:
        raise alert_limit_error(limit, active)


def _reject_if_crossed(direction: str, target: float, ccy: str, symbol: str,
                       q: dict | None, usdcad: float | None) -> None:
    """422 already_crossed when the condition already holds (it would fire at once)."""
    price = price_in(_f((q or {}).get("price")), (q or {}).get("currency"), ccy, usdcad)
    if is_crossed(direction, target, price):
        raise api_error("already_crossed",
                        f"{symbol} is already {'above' if direction == 'above' else 'below'} {target:g}.",
                        422, field="target_price", current_price=round(price, 4), currency=ccy)


def create_alert(user: dict, symbol: str, body: dict) -> dict:
    from app.db import queries
    data = validate(body)
    _check_limit(user)
    qs, usdcad = _quotes_for({symbol})
    q = qs.get(symbol)
    ccy = data.get("currency") or str((q or {}).get("currency") or default_currency(symbol)).upper()
    _reject_if_crossed(data["direction"], data["target_price"], ccy, symbol, q, usdcad)
    row = queries.insert_price_alert(user["user_id"], {
        "symbol": symbol, "direction": data["direction"], "target_price": data["target_price"],
        "currency": ccy, "note": data.get("note"), "active": True,
    })
    return enrich(row, q, usdcad)


def update_alert(user: dict, alert_id: str, body: dict) -> dict:
    from app.db import queries
    cur = queries.get_price_alert(alert_id, user["user_id"])
    if not cur:
        raise api_error("alert_not_found", "Alert not found.", status.HTTP_404_NOT_FOUND)
    data = validate(body, partial=True)
    if not data:
        raise api_error("nothing_to_update", "Send at least one field to change.", 422)
    merged = {**cur, **data}
    reactivating = data.get("active") is True and not cur.get("active")
    if reactivating:
        _check_limit(user)
    sym = str(merged["symbol"]).upper()
    qs, usdcad = _quotes_for({sym})
    if merged.get("active") and ({"direction", "target_price", "currency"} & set(data) or reactivating):
        _reject_if_crossed(merged["direction"], float(merged["target_price"]),
                           str(merged["currency"]).upper(), sym, qs.get(sym), usdcad)
    if reactivating or (merged.get("active") and {"direction", "target_price"} & set(data)):
        data.update({"triggered_at": None, "last_price": None})
    row = queries.update_price_alert(alert_id, user["user_id"], data)
    if not row:
        raise api_error("alert_not_found", "Alert not found.", status.HTTP_404_NOT_FOUND)
    return enrich(row, qs.get(sym), usdcad)


def delete_alert(user: dict, alert_id: str) -> dict:
    from app.db import queries
    if not queries.delete_price_alert(alert_id, user["user_id"]):
        raise api_error("alert_not_found", "Alert not found.", status.HTTP_404_NOT_FOUND)
    return {"deleted": True, "id": alert_id}


def recent_triggered(user_id: str, now: datetime | None = None) -> list[dict]:
    from app.db import queries
    since = ((now or datetime.now(timezone.utc)) - timedelta(days=RECENT_DAYS)).isoformat()
    return queries.get_triggered_price_alerts(user_id, since)


# ============================================================
# Quotes job hooks (never raise)
# ============================================================

def alert_follow_rows() -> list[dict]:
    """[{user_id, symbol}] of active alerts (quotes job). [] before 015."""
    from app.db import queries
    try:
        return queries.get_active_alert_follow_rows()
    except Exception as e:
        logger.debug(f"alerts: follow rows unavailable (apply {MIGRATION}?): {e}")
        return []


def evaluate_refreshed(quotes: dict[str, dict], now: datetime | None = None) -> int:
    """Fire the active alerts of the just-refreshed symbols. Returns the count."""
    from app.db import queries
    from app.services.price_cache import get_usdcad_rate

    symbols = sorted(s for s, q in (quotes or {}).items() if _f((q or {}).get("price")))
    if not symbols:
        return 0
    try:
        alerts = queries.get_active_price_alerts(symbols)
    except Exception as e:
        logger.debug(f"alerts: not evaluated (apply {MIGRATION}?): {e}")
        return 0
    if not alerts:
        return 0
    try:
        usdcad = get_usdcad_rate()
    except Exception:
        usdcad = None
    fired = evaluate(alerts, quotes, usdcad, now)
    n = 0
    for f in fired:
        try:
            queries.mark_price_alert_triggered(f["id"], f["triggered_at"], f["last_price"])
            n += 1
            logger.info(f"alerts: {f['symbol']} alert {f['id']} fired at {f['last_price']}")
        except Exception as e:
            logger.warning(f"alerts: could not mark {f['id']} triggered: {e}")
    return n
