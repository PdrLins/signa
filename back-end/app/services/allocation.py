"""Portfolio allocation: mix by class, holdings map, warnings, targets and a
deposit plan. Pure functions (the router loads the data). No AI.

CLASSES (classify(), first rule that matches wins)
  crypto              symbol ends with -USD, or asset_type CRYPTO
  cash_like           holdings_service.CASH_LIKE_FUNDS + CASH_LIKE_EXTRA (T-bill /
                      money-market / high-interest-savings ETFs), or a name with
                      "money market" / "t-bill" / "treasury bill" / "high interest savings";
                      plus every account's cash_balance
  option_income_etfs  holdings_service.COVERED_CALL_FUNDS + OPTION_INCOME_EXTRA
                      (YieldMax-style single-stock option-income ETFs), or a
                      name with "covered call" / "option income" / "premium income" /
                      "buywrite" / "enhanced income"
  broad_etfs          BROAD_ETFS (documented list of broad index / all-in-one ETFs)
                      or any other asset_type ETF, except OTHER_FUNDS
  other               OTHER_FUNDS (bond, gold/silver, commodity funds) or a name
                      with "bond" / "gold" / "silver" / "commodity"; asset_type OTHER
  stocks              asset_type STOCK, and the default for anything else
Symbols are compared without the exchange suffix (XEQT.TO -> XEQT).

WARNINGS (code + params; pct of the scope's total = holdings value + cash)
  top3_concentration  the 3 largest holdings > 40%     {pct, limit: 40, symbols}
  single_holding      one holding > 20% (one per)      {symbol, pct, limit: 20}
  cash_like_high      cash_like class > 10%            {pct, limit: 10}
  option_income_high  option_income_etfs > 25%         {pct, limit: 25}

TARGETS  {class: pct}: known classes only, numbers 0..100, sum = 100 (±0.01);
         omitted classes = 0. null clears.
PLAN     split a new deposit across UNDER-target classes only (never sells):
           gap(c) = target%(c) x (total + amount) - value(c), positive gaps only;
           each class gets amount x gap / sum(gaps), capped at its gap (so when
           the gaps add up to less than the amount, the rest is "unallocated").
         Holding to buy per class: the largest existing holding of that class
         in the scope, else DEFAULT_BUYS (by home currency), else null with
         code "no_default" (stocks / other: picking a single stock is the user's call).
"""

from __future__ import annotations

import math
from typing import Any

from fastapi import status

from app.core.api_errors import api_error
from app.services.holdings_service import CASH_LIKE_FUNDS, COVERED_CALL_FUNDS, base_symbol

CLASSES: tuple[str, ...] = ("stocks", "broad_etfs", "option_income_etfs", "cash_like", "crypto", "other")

CASH_LIKE_EXTRA = {"BIL", "SGOV", "SHV", "USFR", "TFLO", "BILS", "CLIP", "TBIL", "GBIL", "CMR", "PSU.U",
                   "ZMMK", "CBIL", "CASH", "PSA", "HISA", "CSAV", "MNY", "UBIL", "ZST", "HSAV", "NSAV"}
OPTION_INCOME_EXTRA = {"NVDY", "TSLY", "CONY", "MSTY", "APLY", "AMZY", "GOOY", "FBY", "NFLY", "OARK",
                       "MSFO", "YMAX", "YMAG", "ULTY", "PLTY", "AMDY", "SPYI", "QQQI", "DIVO", "QDTE",
                       "XDTE", "RDTE", "SVOL", "ISPY", "BALI", "GPIX", "GPIQ", "TSPY", "JEPY"}
BROAD_ETFS = {"XEQT", "VEQT", "ZEQT", "HEQT", "XGRO", "VGRO", "ZGRO", "XBAL", "VBAL", "VFV", "VOO", "SPY",
              "IVV", "SPLG", "VTI", "ITOT", "VT", "VXUS", "QQQ", "QQQM", "XIU", "XIC", "VCN", "ZCN", "ZSP",
              "XUS", "XUU", "VUN", "XAW", "VXC", "XEF", "IEFA", "VEA", "VWO", "IEMG", "XEC", "HXT", "HXS",
              "SCHB", "SCHX", "SCHD", "DIA", "IWM", "VIG", "VYM", "VDY", "XEI", "ZDV"}
OTHER_FUNDS = {"XBB", "ZAG", "VAB", "BND", "AGG", "TLT", "IEF", "ZFL", "XSB", "GLD", "IAU", "SLV", "CGL",
               "PHYS", "PSLV", "SVR", "XGD", "ZGD", "GDX", "DBC", "PDBC", "USO", "UNG"}

_CASH_WORDS = ("money market", "t-bill", "treasury bill", "high interest savings", "savings account etf")
_OPTION_WORDS = ("covered call", "option income", "premium income", "buywrite", "buy-write", "enhanced income")
_OTHER_WORDS = ("bond", "gold", "silver", "commodity", "commodities")

# Default holding to buy when the scope holds nothing in that class.
DEFAULT_BUYS: dict[str, dict[str, str | None]] = {
    "broad_etfs": {"CAD": "XEQT.TO", "default": "VT"},
    "cash_like": {"CAD": "CASH.TO", "default": "SGOV"},
    "option_income_etfs": {"CAD": "ZWC.TO", "default": "JEPI"},
    "crypto": {"CAD": "BTC-USD", "default": "BTC-USD"},
    "stocks": {"default": None},
    "other": {"default": None},
}

TOP3_LIMIT = 40.0
SINGLE_LIMIT = 20.0
CASH_LIKE_LIMIT = 10.0
OPTION_INCOME_LIMIT = 25.0
MAX_PLAN_AMOUNT = 1e9


def _f(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _r(v: float | None, nd: int = 2) -> float | None:
    return round(v, nd) if v is not None and math.isfinite(v) else None


# ============================================================
# Classification
# ============================================================

def classify(symbol: str, name: str | None = None, asset_type: str | None = None) -> str:
    """Allocation class of one holding (rules in the module docstring)."""
    sym = str(symbol or "").upper()
    b = base_symbol(sym)
    at = str(asset_type or "").upper()
    nm = str(name or "").lower()
    if sym.endswith("-USD") or at == "CRYPTO":
        return "crypto"
    if b in CASH_LIKE_FUNDS or b in CASH_LIKE_EXTRA or any(w in nm for w in _CASH_WORDS):
        return "cash_like"
    if b in COVERED_CALL_FUNDS or b in OPTION_INCOME_EXTRA or any(w in nm for w in _OPTION_WORDS):
        return "option_income_etfs"
    if b in OTHER_FUNDS:
        return "other"
    if b in BROAD_ETFS:
        return "broad_etfs"
    if at == "ETF":
        return "other" if any(w in nm for w in _OTHER_WORDS) else "broad_etfs"
    if at == "OTHER":
        return "other"
    return "stocks"


# ============================================================
# Allocation
# ============================================================

def build_allocation(positions: list[dict], cash_home: float = 0.0) -> dict:
    """positions: portfolio_context.merge_positions_by_symbol rows (home currency).

    Returns {"total_home", "invested_home", "cash_home", "mix": [...], "tiles": [...],
    "warnings": [...], "unpriced": [symbols]}."""
    cash_home = max(0.0, _f(cash_home) or 0.0)
    priced = [p for p in positions or [] if _f(p.get("value_home")) is not None and p["value_home"] > 0]
    unpriced = sorted({p["symbol"] for p in positions or [] if p not in priced})
    invested = sum(p["value_home"] for p in priced)
    total = invested + cash_home

    def pct(v: float) -> float | None:
        return _r(v / total * 100) if total > 0 else None

    by_class: dict[str, list[dict]] = {c: [] for c in CLASSES}
    tiles = []
    for p in sorted(priced, key=lambda x: -x["value_home"]):
        cls = classify(p["symbol"], p.get("name"), p.get("asset_type"))
        by_class[cls].append(p)
        tiles.append({
            "symbol": p["symbol"], "name": p.get("name"), "class": cls,
            "value_home": _r(p["value_home"]), "weight_pct": pct(p["value_home"]),
            "day_change_pct": _r(_f(p.get("change_pct"))),
            "total_gain_pct": _r(_f(p.get("gain_pct"))),
        })

    mix = []
    for cls in CLASSES:
        members = [{"symbol": p["symbol"], "value_home": _r(p["value_home"]), "pct": pct(p["value_home"])}
                   for p in by_class[cls]]
        value = sum(p["value_home"] for p in by_class[cls])
        if cls == "cash_like" and cash_home > 0:
            members.append({"symbol": None, "kind": "account_cash", "value_home": _r(cash_home),
                            "pct": pct(cash_home)})
            value += cash_home
        mix.append({"class": cls, "value_home": _r(value), "pct": pct(value) if total > 0 else None,
                    "members": members})

    warnings: list[dict] = []
    if total > 0:
        top3 = tiles[:3]
        top3_pct = sum(t["value_home"] for t in top3) / total * 100
        if len(tiles) and top3_pct > TOP3_LIMIT:
            warnings.append({"code": "top3_concentration",
                             "params": {"pct": _r(top3_pct), "limit": TOP3_LIMIT,
                                        "symbols": [t["symbol"] for t in top3]}})
        for t in tiles:
            if (t["weight_pct"] or 0) > SINGLE_LIMIT:
                warnings.append({"code": "single_holding",
                                 "params": {"symbol": t["symbol"], "pct": t["weight_pct"], "limit": SINGLE_LIMIT}})
        cls_pct = {m["class"]: m["pct"] or 0 for m in mix}
        if cls_pct["cash_like"] > CASH_LIKE_LIMIT:
            warnings.append({"code": "cash_like_high", "params": {"pct": cls_pct["cash_like"],
                                                                  "limit": CASH_LIKE_LIMIT}})
        if cls_pct["option_income_etfs"] > OPTION_INCOME_LIMIT:
            warnings.append({"code": "option_income_high",
                             "params": {"pct": cls_pct["option_income_etfs"], "limit": OPTION_INCOME_LIMIT}})
    return {"total_home": _r(total), "invested_home": _r(invested), "cash_home": _r(cash_home),
            "mix": mix, "tiles": tiles, "warnings": warnings, "unpriced": unpriced}


# ============================================================
# Targets
# ============================================================

def _422(code: str, message: str, **extra) -> Exception:
    return api_error(code, message, status.HTTP_422_UNPROCESSABLE_ENTITY, **extra)


def validate_targets(raw: Any) -> dict[str, float] | None:
    """Clean {class: pct} (every class present, 0 when omitted) or None (clear)."""
    if raw is None:
        return None
    if not isinstance(raw, dict) or not raw:
        raise _422("invalid_targets", "Targets must be an object like {\"broad_etfs\": 80, \"stocks\": 20}.",
                   classes=list(CLASSES))
    clean = {c: 0.0 for c in CLASSES}
    for k, v in raw.items():
        if k not in CLASSES:
            raise _422("invalid_targets", f"Unknown class '{k}'.", field=str(k), classes=list(CLASSES))
        f = _f(v)
        if f is None or f < 0 or f > 100:
            raise _422("invalid_targets", f"Target for {k} must be a number from 0 to 100.", field=str(k))
        clean[k] = round(f, 4)
    total = sum(clean.values())
    if abs(total - 100) > 0.01:
        raise _422("targets_sum", "Targets must add up to 100%.", sum=round(total, 4))
    return clean


# ============================================================
# Plan
# ============================================================

def default_buy(cls: str, home_currency: str) -> str | None:
    d = DEFAULT_BUYS.get(cls) or {}
    return d.get((home_currency or "").upper(), d.get("default"))


def build_plan(allocation: dict, targets: dict[str, float], amount: float, home_currency: str) -> dict:
    """Split `amount` across under-target classes (see the module docstring)."""
    total_after = (allocation.get("total_home") or 0.0) + amount
    values = {m["class"]: m["value_home"] or 0.0 for m in allocation.get("mix") or []}
    tiles = allocation.get("tiles") or []
    gaps = {}
    for cls in CLASSES:
        gap = (targets.get(cls) or 0.0) / 100 * total_after - values.get(cls, 0.0)
        if gap > 1e-9:
            gaps[cls] = gap
    gap_sum = sum(gaps.values())
    items = []
    for cls in CLASSES:
        current_pct = (values.get(cls, 0.0) / (allocation.get("total_home") or 0) * 100) \
            if allocation.get("total_home") else 0.0
        if cls not in gaps:
            continue
        put = min(gaps[cls], amount * gaps[cls] / gap_sum) if gap_sum > 0 else 0.0
        held = next((t for t in tiles if t["class"] == cls), None)  # tiles are sorted by value desc
        if held:
            buy, source, code = held["symbol"], "largest_holding", None
        else:
            buy = default_buy(cls, home_currency)
            source, code = ("default", None) if buy else (None, "no_default")
        items.append({
            "class": cls, "amount": _r(put), "gap_home": _r(gaps[cls]),
            "current_pct": _r(current_pct), "target_pct": targets.get(cls),
            "after_pct": _r((values.get(cls, 0.0) + put) / total_after * 100) if total_after > 0 else None,
            "buy": {"symbol": buy, "source": source, "code": code},
        })
    allocated = sum(i["amount"] or 0 for i in items)
    return {"amount": _r(amount), "allocated": _r(allocated), "unallocated": _r(max(0.0, amount - allocated)),
            "items": items}
