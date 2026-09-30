"""Positions from transactions — average-cost method. Pure (no DB, no network).

    derive_positions(transactions) -> {"positions": [...], "cash": [...], "warnings": [...]}

Transactions are processed in trade_date order (ties keep their input
order, so pass them oldest-first as stored). Amount conventions (migration
013): `amount` is always a positive cash amount; `fee` is >= 0.

  buy       shares += qty; cost_basis += gross + fee
            (gross = amount, or qty x price when amount is missing)
  sell      avg = cost_basis / shares; realized += gross - fee - avg x qty;
            cost_basis -= avg x qty; shares -= qty. Selling more than held
            sells what is held and adds a warning ("oversold").
  split     quantity = ratio (2 = 2-for-1, 0.1 = 1-for-10): shares x ratio,
            cost basis unchanged (so avg_cost / ratio).
  dividend  dividends[year] += amount (and total); does not touch cost.
  fee       with a symbol: realized -= amount; always reduces account cash.
  deposit / withdrawal   account cash only.

A position is one (account_id, symbol) pair; account_id None = "no account".
Cash per account: deposits - withdrawals - buys - fees + sells + dividends
(per currency as recorded; nothing is converted here).
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date
from typing import Any, Iterable

EPS = 1e-9


def _f(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _year(d: Any) -> int | None:
    if isinstance(d, date):
        return d.year
    try:
        return int(str(d)[:4])
    except (TypeError, ValueError):
        return None


def _gross(tx: dict) -> float:
    amt = _f(tx.get("amount"))
    if amt is not None:
        return abs(amt)
    q, p = _f(tx.get("quantity")), _f(tx.get("price"))
    return abs(q * p) if q is not None and p is not None else 0.0


def _new_position(account_id, symbol, currency) -> dict:
    return {"account_id": account_id, "symbol": symbol, "currency": currency, "shares": 0.0,
            "cost_basis": 0.0, "realized_pl": 0.0, "fees": 0.0, "dividends_total": 0.0,
            "dividends_by_year": defaultdict(float), "first_trade_date": None, "last_trade_date": None,
            "transactions": 0}


def derive_positions(transactions: Iterable[dict]) -> dict:
    txs = sorted(enumerate(transactions or []), key=lambda it: (str(it[1].get("trade_date") or ""), it[0]))
    pos: dict[tuple, dict] = {}
    cash: dict[tuple, float] = defaultdict(float)
    warnings: list[dict] = []

    for _, tx in txs:
        typ = str(tx.get("type") or "").lower()
        acct = tx.get("account_id")
        acct = str(acct) if acct else None
        sym = str(tx.get("symbol") or "").upper() or None
        ccy = (tx.get("currency") or None)
        fee = abs(_f(tx.get("fee")) or 0.0)
        gross = _gross(tx)
        ckey = (acct, ccy)

        if typ in ("deposit", "withdrawal"):
            cash[ckey] += gross if typ == "deposit" else -gross
            continue
        if typ == "fee" and not sym:
            cash[ckey] -= gross
            continue
        if not sym:
            warnings.append({"code": "missing_symbol", "id": tx.get("id"), "type": typ})
            continue

        key = (acct, sym)
        p = pos.get(key)
        if p is None:
            p = pos[key] = _new_position(acct, sym, ccy)
        elif ccy and p["currency"] and ccy != p["currency"]:
            warnings.append({"code": "mixed_currency", "id": tx.get("id"), "symbol": sym,
                             "account_id": acct, "currency": ccy, "position_currency": p["currency"]})
        p["currency"] = p["currency"] or ccy
        d = tx.get("trade_date")
        p["first_trade_date"] = p["first_trade_date"] or (str(d) if d else None)
        p["last_trade_date"] = str(d) if d else p["last_trade_date"]
        p["transactions"] += 1
        qty = abs(_f(tx.get("quantity")) or 0.0)

        if typ == "buy":
            if qty <= 0:
                warnings.append({"code": "zero_quantity", "id": tx.get("id"), "symbol": sym})
                continue
            p["shares"] += qty
            p["cost_basis"] += gross + fee
            p["fees"] += fee
            cash[ckey] -= gross + fee
        elif typ == "sell":
            if qty <= 0:
                warnings.append({"code": "zero_quantity", "id": tx.get("id"), "symbol": sym})
                continue
            held = p["shares"]
            if qty > held + EPS:
                warnings.append({"code": "oversold", "id": tx.get("id"), "symbol": sym, "account_id": acct,
                                 "sold": qty, "held": round(held, 8)})
            sold = min(qty, held)
            avg = p["cost_basis"] / held if held > EPS else 0.0
            # proceeds of the part actually held (an oversell's excess is ignored)
            proceeds = gross * (sold / qty) if qty > 0 else 0.0
            p["realized_pl"] += proceeds - fee - avg * sold
            p["cost_basis"] -= avg * sold
            p["shares"] -= sold
            p["fees"] += fee
            if p["shares"] <= EPS:
                p["shares"], p["cost_basis"] = 0.0, 0.0
            cash[ckey] += gross - fee
        elif typ == "split":
            ratio = _f(tx.get("quantity"))
            if not ratio or ratio <= 0:
                warnings.append({"code": "invalid_split", "id": tx.get("id"), "symbol": sym})
                continue
            p["shares"] *= ratio
        elif typ == "dividend":
            y = _year(d)
            if y is not None:
                p["dividends_by_year"][y] += gross
            p["dividends_total"] += gross
            cash[ckey] += gross - fee
        elif typ == "fee":
            p["realized_pl"] -= gross
            p["fees"] += gross
            cash[ckey] -= gross
        else:
            warnings.append({"code": "unknown_type", "id": tx.get("id"), "type": typ})

    positions = []
    for p in pos.values():
        shares = p["shares"]
        positions.append({
            "account_id": p["account_id"],
            "symbol": p["symbol"],
            "currency": p["currency"],
            "shares": round(shares, 8),
            "avg_cost": round(p["cost_basis"] / shares, 6) if shares > EPS else None,
            "cost_basis": round(p["cost_basis"], 4),
            "realized_pl": round(p["realized_pl"], 4),
            "fees": round(p["fees"], 4),
            "dividends_total": round(p["dividends_total"], 4),
            "dividends_by_year": {y: round(v, 4) for y, v in sorted(p["dividends_by_year"].items())},
            "open": shares > EPS,
            "first_trade_date": p["first_trade_date"],
            "last_trade_date": p["last_trade_date"],
            "transactions": p["transactions"],
        })
    positions.sort(key=lambda x: (str(x["account_id"] or ""), x["symbol"]))
    cash_out = [{"account_id": a, "currency": c, "cash": round(v, 4)}
                for (a, c), v in sorted(cash.items(), key=lambda kv: (str(kv[0][0] or ""), str(kv[0][1] or "")))]
    return {"positions": positions, "cash": cash_out, "warnings": warnings}
