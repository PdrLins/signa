"""Approximate regions of an ETF (Yahoo has no regional breakdown).

Two cases Signa can answer:
  * a fund of funds (XEQT, VEQT, XGRO…): its top holdings are regional ETFs;
    each known one maps to a region (UNDERLYING), weights are summed and
    rescaled to the part we could map (needs >= 80% of the fund mapped).
  * a single-region index fund (S&P 500, TSX, Nasdaq…): 100% one region,
    from the similar-funds peer groups (similar_funds.PEER_GROUPS).
Keys: "us" | "canada" | "intl_developed" | "emerging" (PERCENT). None when
unknown. Pure.
"""

from __future__ import annotations

from typing import Optional

# underlying regional ETFs (as they appear in fund-of-funds top holdings)
UNDERLYING: dict[str, str] = {
    # US
    "XTOT": "us", "XUS": "us", "XUU": "us", "ITOT": "us", "IVV": "us", "VTI": "us", "VUN": "us", "VFV": "us",
    "ZSP": "us", "VOO": "us", "SPY": "us", "IJH": "us", "IJR": "us", "ZSP.U": "us", "VUS": "us", "ZUQ": "us",
    "HXS": "us", "ZEQT.U": "us", "SCHB": "us",
    # Canada
    "XIC": "canada", "VCN": "canada", "ZCN": "canada", "XIU": "canada", "HXT": "canada", "ZIU": "canada",
    # developed markets ex North America
    "XEF": "intl_developed", "VIU": "intl_developed", "ZEA": "intl_developed", "IEFA": "intl_developed",
    "VEA": "intl_developed", "VI": "intl_developed", "HXDM": "intl_developed",
    # emerging markets
    "XEC": "emerging", "VEE": "emerging", "ZEM": "emerging", "IEMG": "emerging", "VWO": "emerging",
}

SINGLE_REGION_GROUPS = {
    "sp500_cad": "us", "sp500_us": "us", "us_total": "us", "nasdaq100": "us", "us_dividend": "us",
    "canada_broad": "canada", "canada_dividend": "canada", "reits_ca": "canada",
    "intl_developed": "intl_developed", "emerging": "emerging",
}


def _base(symbol: Optional[str]) -> str:
    s = (symbol or "").upper()
    return s.rsplit(".", 1)[0] if s.endswith((".TO", ".NE", ".V")) else s


def regions_for(symbol: str, fund: Optional[dict]) -> Optional[dict[str, float]]:
    """{region: PERCENT} (largest first) or None. Pure."""
    from app.services.similar_funds import group_of

    fund = fund or {}
    holdings = fund.get("top_holdings") or []
    if fund.get("fund_of_funds") and holdings:
        total = mapped = 0.0
        acc: dict[str, float] = {}
        for h in holdings:
            w = h.get("weight")
            if not isinstance(w, (int, float)) or w <= 0:
                continue
            total += w
            region = UNDERLYING.get(_base(h.get("symbol")))
            if region:
                acc[region] = acc.get(region, 0.0) + w
                mapped += w
        if total and mapped / total >= 0.8:
            return {k: round(v / mapped * 100, 1) for k, v in sorted(acc.items(), key=lambda kv: -kv[1])}
    region = SINGLE_REGION_GROUPS.get(group_of(symbol) or "")
    return {region: 100.0} if region else None
