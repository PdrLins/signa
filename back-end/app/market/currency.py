"""Which currency a listing trades in, from its Yahoo symbol. Pure.

Yahoo symbols carry the exchange as a suffix (PETR4.SA = B3, VOD.L = London,
SAP.DE = XETRA ...); no suffix = a US listing. Crypto pairs end in the quote
currency (BTC-USD, BTC-BRL). A few exchanges quote in a sub-unit (London in
pence "GBp", Johannesburg in cents "ZAc", Tel Aviv in agorot "ILA"): prices
from those are divided by 100 into the main currency (SUB_UNIT_EXCHANGES).

currency_for(symbol)       -> ISO 4217 code of the listing ("BRL", "GBP", "USD" ...)
price_factor(symbol, ccy?) -> multiplier to turn a Yahoo price into currency_for(symbol)
                              (0.01 for pence/cents/agorot listings, else 1)
exchange_for_suffix(symbol)-> short exchange label ("B3", "LSE", "XETRA" ...) or None
"""

from __future__ import annotations

# suffix -> (currency, exchange label)
SUFFIXES: dict[str, tuple[str, str]] = {
    ".TO": ("CAD", "TSX"), ".V": ("CAD", "TSXV"), ".NE": ("CAD", "NEO"), ".CN": ("CAD", "CSE"),
    ".SA": ("BRL", "B3"),
    ".MX": ("MXN", "BMV"), ".BA": ("ARS", "BYMA"), ".SN": ("CLP", "Santiago"),
    ".L": ("GBP", "LSE"), ".IL": ("GBP", "LSE IOB"),
    ".DE": ("EUR", "XETRA"), ".F": ("EUR", "Frankfurt"), ".BE": ("EUR", "Berlin"), ".MU": ("EUR", "Munich"),
    ".SG": ("EUR", "Stuttgart"), ".DU": ("EUR", "Düsseldorf"), ".HM": ("EUR", "Hamburg"),
    ".PA": ("EUR", "Euronext Paris"), ".AS": ("EUR", "Euronext Amsterdam"), ".BR": ("EUR", "Euronext Brussels"),
    ".LS": ("EUR", "Euronext Lisbon"), ".MI": ("EUR", "Borsa Italiana"), ".MC": ("EUR", "BME"),
    ".IR": ("EUR", "Euronext Dublin"), ".VI": ("EUR", "Vienna"), ".HE": ("EUR", "Helsinki"),
    ".SW": ("CHF", "SIX"), ".ST": ("SEK", "Stockholm"), ".OL": ("NOK", "Oslo"), ".CO": ("DKK", "Copenhagen"),
    ".WA": ("PLN", "Warsaw"), ".PR": ("CZK", "Prague"), ".BD": ("HUF", "Budapest"), ".IS": ("TRY", "Borsa Istanbul"),
    ".T": ("JPY", "Tokyo"), ".HK": ("HKD", "HKEX"), ".SS": ("CNY", "Shanghai"), ".SZ": ("CNY", "Shenzhen"),
    ".KS": ("KRW", "KOSPI"), ".KQ": ("KRW", "KOSDAQ"), ".TW": ("TWD", "TWSE"), ".TWO": ("TWD", "TPEx"),
    ".SI": ("SGD", "SGX"), ".NS": ("INR", "NSE"), ".BO": ("INR", "BSE"), ".JK": ("IDR", "IDX"),
    ".KL": ("MYR", "Bursa Malaysia"), ".BK": ("THB", "SET"),
    ".AX": ("AUD", "ASX"), ".NZ": ("NZD", "NZX"),
    ".JO": ("ZAR", "JSE"), ".TA": ("ILS", "TASE"), ".SR": ("SAR", "Tadawul"),
}
# Yahoo prices on these are in the sub-unit (pence, cents, agorot).
SUB_UNIT_EXCHANGES = {".L", ".IL", ".JO", ".TA"}
SUB_UNIT_CODES = {"GBp": "GBP", "GBX": "GBP", "ZAc": "ZAR", "ZAC": "ZAR", "ILA": "ILS"}
CRYPTO_QUOTES = ("USD", "CAD", "BRL", "EUR", "GBP", "USDT", "JPY", "AUD")


def _suffix(symbol: str) -> str | None:
    s = (symbol or "").upper()
    if "." not in s:
        return None
    suf = "." + s.rsplit(".", 1)[1]
    return suf if suf in SUFFIXES else None


def is_crypto(symbol: str) -> bool:
    s = (symbol or "").upper()
    return "-" in s and s.rsplit("-", 1)[1] in CRYPTO_QUOTES and "." not in s


def currency_for(symbol: str | None) -> str:
    s = (symbol or "").upper()
    if is_crypto(s):
        q = s.rsplit("-", 1)[1]
        return "USD" if q == "USDT" else q
    suf = _suffix(s)
    return SUFFIXES[suf][0] if suf else "USD"


def normalize_currency(code: str | None) -> tuple[str | None, float]:
    """Yahoo currency code -> (ISO code, factor): "GBp" -> ("GBP", 0.01). Pure."""
    if not code:
        return None, 1.0
    if code in SUB_UNIT_CODES:
        return SUB_UNIT_CODES[code], 0.01
    return code.upper(), 1.0


def price_factor(symbol: str | None, yahoo_currency: str | None = None) -> float:
    """Multiplier from a Yahoo price to currency_for(symbol). When Yahoo's own
    currency code is known it decides (some London ETFs trade in USD/GBP)."""
    if yahoo_currency:
        return normalize_currency(yahoo_currency)[1]
    return 0.01 if _suffix(symbol or "") in SUB_UNIT_EXCHANGES else 1.0


def exchange_for_suffix(symbol: str | None) -> str | None:
    suf = _suffix(symbol or "")
    return SUFFIXES[suf][1] if suf else None


# Yahoo `info` fields given in the listing's quote unit (pence on London ...).
INFO_PRICE_KEYS = (
    "regularMarketPrice", "currentPrice", "previousClose", "regularMarketPreviousClose", "open",
    "regularMarketOpen", "dayHigh", "dayLow", "regularMarketDayHigh", "regularMarketDayLow",
    "fiftyTwoWeekLow", "fiftyTwoWeekHigh", "fiftyDayAverage", "twoHundredDayAverage", "bid", "ask",
    "dividendRate", "trailingAnnualDividendRate", "lastDividendValue", "navPrice",
    "targetMeanPrice", "targetHighPrice", "targetLowPrice",
)


def normalize_info(symbol: str | None, info: dict | None) -> tuple[dict, float]:
    """(info in the main currency, factor applied). London's pence prices and
    dividends become pounds and "GBp" becomes "GBP", like the quotes table. Pure."""
    info = dict(info or {})
    k = price_factor(symbol, info.get("currency"))
    if info.get("currency"):
        info["currency"] = normalize_currency(info["currency"])[0]
    if k != 1.0:
        for key in INFO_PRICE_KEYS:
            v = info.get(key)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                info[key] = v * k
    return info, k
