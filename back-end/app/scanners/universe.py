"""Ticker universe — all stocks Signa scans across TSX, NYSE, and NASDAQ."""

TSX_TICKERS = [
    # Banks
    "RY.TO", "TD.TO", "BNS.TO", "BMO.TO", "CM.TO", "NA.TO",
    # Insurance
    "MFC.TO", "SLF.TO", "IFC.TO", "FFH.TO",
    # Energy
    "ENB.TO", "TRP.TO", "CNQ.TO", "SU.TO", "CVE.TO", "IMO.TO",
    "ARX.TO", "TVE.TO", "BTE.TO", "WCP.TO", "ERF.TO",
    # Mining & Materials
    "ABX.TO", "FNV.TO", "WPM.TO", "NTR.TO", "CCO.TO",
    "FM.TO", "LUN.TO", "TECK.TO", "K.TO", "AGI.TO",
    # Tech
    "SHOP.TO", "CSU.TO", "OTEX.TO", "LSPD.TO", "BB.TO",
    "TIXT.TO", "KXS.TO", "DCBO.TO", "NVEI.TO",
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
    # ETFs
    "XIU.TO", "XIC.TO", "VFV.TO", "ZDV.TO", "XEI.TO",
    "ZWC.TO", "XDIV.TO", "VDY.TO",
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
    "XOM", "COP", "SLB", "EOG", "PXD", "MPC", "OXY",
    "PSX", "VLO", "HAL",
    # Healthcare
    "PFE", "BMY", "GILD", "AMGN", "ISRG", "SYK",
    "MDT", "ZTS", "CI", "HUM",
    # Industrials
    "CAT", "HON", "UPS", "RTX", "BA", "LMT", "GE",
    "MMM", "DE", "EMR",
    # Consumer
    "LOW", "TGT", "SBUX", "EL", "CL", "KMB", "GIS",
    "SJM", "K", "HSY",
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
    "PYPL", "SQ", "COIN", "SOFI", "AFRM", "HOOD",
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
    "ADA-USD", "AVAX-USD", "DOT-USD", "MATIC-USD", "ATOM-USD",
    # DeFi
    "LINK-USD", "UNI-USD", "AAVE-USD", "MKR-USD",
    # Meme / High Risk
    "DOGE-USD", "SHIB-USD", "PEPE-USD",
    # Other
    "LTC-USD", "NEAR-USD", "APT-USD",
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


def get_ticker_count() -> int:
    """Total unique tickers in the universe."""
    return len(get_all_tickers())
