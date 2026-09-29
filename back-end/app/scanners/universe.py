"""Ticker universe — all stocks Signa scans across TSX, NYSE, and NASDAQ."""

TSX_TICKERS = [
    # Banks
    "RY.TO", "TD.TO", "BNS.TO", "BMO.TO", "CM.TO", "NA.TO",
    # Insurance
    "MFC.TO", "SLF.TO", "IFC.TO", "FFH.TO",
    # Energy
    "ENB.TO", "TRP.TO", "CNQ.TO", "SU.TO", "CVE.TO", "IMO.TO",
    "ARX.TO", "TVE.TO", "BTE.TO", "WCP.TO",
    # Mining & Materials
    "ABX.TO", "FNV.TO", "WPM.TO", "NTR.TO", "CCO.TO",
    "FM.TO", "LUN.TO", "AGI.TO",
    # Tech
    "SHOP.TO", "CSU.TO", "OTEX.TO", "LSPD.TO", "BB.TO",
    "KXS.TO", "DCBO.TO",
    # Telecom
    "T.TO", "BCE.TO", "RCI-B.TO", "QBR-B.TO",
    # Utilities
    "FTS.TO", "EMA.TO", "AQN.TO", "CPX.TO", "BEP-UN.TO",
    # REITs
    "REI-UN.TO", "HR-UN.TO", "CAR-UN.TO", "AP-UN.TO",
    "GRT-UN.TO", "CRT-UN.TO", "DIR-UN.TO",
    # Consumer
    "L.TO", "ATD.TO", "MRU.TO", "DOL.TO", "QSR.TO",
    "NWC.TO", "EMP-A.TO", "WN.TO",
    # Industrials
    "CNR.TO", "CP.TO", "WSP.TO", "TIH.TO", "STN.TO",
    "TFII.TO", "WFG.TO", "RBA.TO",
    # Cannabis
    "WEED.TO", "ACB.TO", "TLRY.TO", "CRON.TO", "OGI.TO",
    # ETFs — All-in-one
    "XEQT.TO", "XGRO.TO", "XBAL.TO", "VEQT.TO", "VGRO.TO", "VBAL.TO",
    # ETFs — Canadian Equity
    "XIU.TO", "XIC.TO", "VCN.TO", "ZCN.TO",
    # ETFs — US / S&P 500
    "VFV.TO", "ZSP.TO", "XUS.TO",
    # ETFs — Dividend / Income
    "XEI.TO", "ZDV.TO", "VDY.TO", "CDZ.TO", "XDIV.TO",
    # ETFs — Covered Call
    "ZWC.TO", "ZWB.TO",
    # ETFs — Tech / Growth
    "TEC.TO", "QQC-F.TO",
    # ETFs — International
    "XEF.TO", "VIU.TO", "ZEA.TO",
    # ETFs — Bonds
    "ZAG.TO", "VAB.TO", "XBB.TO",
    # ETFs — Sector
    "XEG.TO", "ZEB.TO", "XRE.TO",
]

NYSE_TICKERS = [
    # Mega Cap
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    "BRK-B", "V", "JPM", "UNH", "JNJ", "WMT", "PG", "MA",
    "HD", "CVX", "MRK", "ABBV", "PEP", "KO", "COST",
    "LLY", "TMO", "DHR", "ABT", "MCD", "NKE", "DIS",
    # Financials
    "BAC", "WFC", "GS", "MS", "C", "AXP", "BLK", "SCHW",
    "USB", "PNC", "TFC",
    # Energy
    "XOM", "COP", "SLB", "EOG", "MPC", "OXY",
    "PSX", "VLO", "HAL",
    # Healthcare
    "PFE", "BMY", "GILD", "AMGN", "ISRG", "SYK",
    "MDT", "ZTS", "CI", "HUM",
    # Industrials
    "CAT", "HON", "UPS", "RTX", "BA", "LMT", "GE",
    "MMM", "DE", "EMR",
    # Consumer
    "LOW", "TGT", "SBUX", "EL", "CL", "KMB", "GIS",
    "SJM", "HSY",
    # REITs
    "AMT", "PLD", "CCI", "EQIX", "SPG", "O", "WELL",
    "DLR", "AVB", "PSA",
    # Utilities
    "NEE", "DUK", "SO", "D", "AEP", "EXC", "SRE",
    # Dividend
    "MO", "PM", "IBM", "VZ", "T",
]

NASDAQ_TICKERS = [
    # Big tech
    "AVGO", "ADBE", "CRM", "NFLX", "AMD", "INTC", "QCOM",
    "TXN", "AMAT", "LRCX", "KLAC", "MRVL", "MU",
    # Biotech
    "MRNA", "REGN", "VRTX", "BIIB", "ILMN", "DXCM",
    "ALGN", "IDXX",
    # Fintech
    "PYPL", "COIN", "SOFI", "AFRM", "HOOD",
    # Cloud / SaaS
    "SNOW", "NET", "DDOG", "ZS", "CRWD", "PANW", "FTNT",
    "OKTA", "MDB", "TEAM",
    # E-commerce
    "MELI", "PDD", "JD", "BIDU", "BABA",
    # EV / Clean energy
    "RIVN", "LCID", "ENPH", "SEDG", "FSLR",
    # Momentum / Small cap
    "PLTR", "RKLB", "IONQ", "SMCI", "ARM", "MSTR",
    "SOUN", "HIMS", "CELH",
    # Semis
    "ASML", "TSM", "ON", "SWKS", "MCHP",
    # ETFs
    "QQQ", "TQQQ", "SQQQ",
]

CRYPTO_TICKERS = [
    # Major
    "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD",
    # Layer 1 / Layer 2
    "ADA-USD", "AVAX-USD", "DOT-USD", "ATOM-USD",
    # DeFi
    "LINK-USD", "AAVE-USD", "MKR-USD",
    # Meme / High Risk
    "DOGE-USD", "SHIB-USD",
    # Other
    "LTC-USD", "NEAR-USD",
]


def get_all_tickers() -> list[str]:
    """Get the full scanning universe with duplicates removed."""
    seen = set()
    tickers = []
    for t in TSX_TICKERS + NYSE_TICKERS + NASDAQ_TICKERS + CRYPTO_TICKERS:
        if t not in seen:
            seen.add(t)
            tickers.append(t)
    return tickers


def get_stock_tickers() -> list[str]:
    """Get only stock tickers (no crypto)."""
    seen = set()
    tickers = []
    for t in TSX_TICKERS + NYSE_TICKERS + NASDAQ_TICKERS:
        if t not in seen:
            seen.add(t)
            tickers.append(t)
    return tickers


def get_crypto_tickers() -> list[str]:
    """Get crypto tickers only."""
    return list(CRYPTO_TICKERS)


_NASDAQ_SET = frozenset(NASDAQ_TICKERS)
_CRYPTO_SET = frozenset(CRYPTO_TICKERS)


def get_exchange(ticker: str) -> str:
    """Determine which exchange a ticker belongs to."""
    if ticker.endswith("-USD") and ticker in _CRYPTO_SET:
        return "CRYPTO"
    if ticker.endswith(".TO"):
        return "TSX"
    if ticker in _NASDAQ_SET:
        return "NASDAQ"
    return "NYSE"


# Known ETF tickers across all exchanges
_ETF_TICKERS = {
    # TSX ETFs
    "XEQT.TO", "XGRO.TO", "XBAL.TO", "VEQT.TO", "VGRO.TO", "VBAL.TO",
    "XIU.TO", "XIC.TO", "VCN.TO", "ZCN.TO",
    "VFV.TO", "ZSP.TO", "XUS.TO",
    "XEI.TO", "ZDV.TO", "VDY.TO", "CDZ.TO", "XDIV.TO",
    "ZWC.TO", "ZWB.TO",
    "TEC.TO", "QQC-F.TO",
    "XEF.TO", "VIU.TO", "ZEA.TO",
    "ZAG.TO", "VAB.TO", "XBB.TO",
    "XEG.TO", "ZEB.TO", "XRE.TO",
    # US ETFs
    "QQQ", "SPY", "TQQQ", "SQQQ",
}


# Leveraged / inverse products. These decay daily and are pure trading
# vehicles — they must NEVER land in SAFE_INCOME (TQQQ/SQQQ used to,
# because they are in _ETF_TICKERS and the classifier treated every
# known ETF as safe).
LEVERAGED_INVERSE_ETFS = frozenset({
    "TQQQ", "SQQQ", "QLD", "QID", "PSQ", "SSO", "SDS", "UPRO", "SPXU",
    "SPXL", "SPXS", "SH", "SDOW", "UDOW", "DOG", "DXD", "DDM", "TNA",
    "TZA", "SOXL", "SOXS", "TECL", "TECS", "FAS", "FAZ", "LABU", "LABD",
    "NUGT", "DUST", "JNUG", "JDST", "FNGU", "FNGD", "UVXY", "SVXY",
    "UVIX", "SVIX", "VXX", "TMF", "TMV", "TBT", "UBT", "BOIL", "KOLD",
    "UCO", "SCO", "YINN", "YANG", "BITX", "BITI", "NVDL", "NVDS", "TSLL",
    "TSLQ", "TSLS", "MSTU", "MSTX", "CONL", "ETHU", "SBIT", "UPW",
    "HQU.TO", "HQD.TO", "HXU.TO", "HXD.TO", "HSU.TO", "HSD.TO",
    "HOU.TO", "HOD.TO", "HNU.TO", "HND.TO", "HGU.TO", "HGD.TO",
})

_LEVERAGED_NAME_PATTERNS = (
    r"\b[2-5]x\b", r"-[1-5]x\b", r"\bultrapro\b", r"\bultrashort\b",
    r"\bultra\b", r"\bleveraged\b", r"\binverse\b", r"\bdaily bear\b",
    r"\bdaily bull\b", r"\bbetapro\b", r"\bproshares short\b",
)


def is_leveraged_or_inverse(ticker: str, fundamentals: dict | None = None) -> bool:
    """True for leveraged/inverse ETFs, by known symbol or fund name."""
    import re
    if ticker in LEVERAGED_INVERSE_ETFS:
        return True
    fundamentals = fundamentals or {}
    qt = (fundamentals.get("quote_type") or "").upper()
    name = (fundamentals.get("company_name") or "").lower()
    if qt == "ETF" and name:
        return any(re.search(p, name) for p in _LEVERAGED_NAME_PATTERNS)
    return False


def get_asset_class(ticker: str) -> str:
    """Classify a ticker as ETF, CRYPTO, or STOCK."""
    if ticker.endswith("-USD"):
        return "CRYPTO"
    if ticker in _ETF_TICKERS:
        return "ETF"
    return "STOCK"


def get_ticker_count() -> int:
    """Total unique tickers in the universe."""
    return len(get_all_tickers())


def discover_tickers() -> list[str]:
    """Discover new tickers from Yahoo Finance screeners.

    Queries undervalued_large_caps and growth_technology_stocks (plus
    most_actives only when settings.discovery_include_most_actives).
    Returns tickers NOT already in the core universe.

    `day_gainers` was removed: injecting today's top gainers into every
    scan fed the pipeline names whose move had already happened
    (move-chasing). `most_actives` has the same bias and is opt-in.
    """
    import yfinance as yf
    from loguru import logger
    from app.core.config import settings

    core = set(get_all_tickers())
    discovered = set()

    queries = [
        "undervalued_large_caps",
        "growth_technology_stocks",
    ]
    if settings.discovery_include_most_actives:
        queries.insert(0, "most_actives")

    for query in queries:
        try:
            result = yf.screen(query)
            quotes = result.get("quotes", []) if isinstance(result, dict) else []
            for q in quotes:
                symbol = q.get("symbol", "")
                # Skip OTC, warrants, preferred shares, non-US/CA
                if not symbol or "." in symbol and not symbol.endswith(".TO"):
                    continue
                # Skip small/micro caps — discovery works best with established names
                market_cap = q.get("marketCap", 0) or 0
                if market_cap < settings.discovery_min_market_cap:
                    continue
                if symbol not in core:
                    discovered.add(symbol)
        except Exception as e:
            logger.debug(f"Screener query '{query}' failed: {e}")

    discovered_list = sorted(discovered)
    if discovered_list:
        logger.info(f"Discovery: found {len(discovered_list)} new tickers: {discovered_list[:20]}")

    return discovered_list
