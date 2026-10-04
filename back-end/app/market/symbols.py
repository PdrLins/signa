"""Symbol input and resolution helpers. Pure except `recent_price` (yfinance)."""

from __future__ import annotations

import math
import re

from loguru import logger

from app.core.utils import validate_ticker
from app.market.universe import get_all_tickers, get_exchange


class InvalidSymbol(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def normalize_input(raw: str | None) -> str:
    """Uppercase / trim / strip a leading '$'; raises InvalidSymbol."""
    s = (raw or "").strip().upper().lstrip("$").strip()
    if not s or len(s) > 20 or not validate_ticker(s):
        raise InvalidSymbol("invalid_ticker", "Enter a ticker symbol like AAPL, XEQT or BTC.", 400)
    return s


# Where a bare ticker most likely trades for a user of each country.
COUNTRY_SUFFIX = {
    "CA": ".TO", "BR": ".SA", "GB": ".L", "DE": ".DE", "FR": ".PA", "NL": ".AS", "BE": ".BR", "IT": ".MI",
    "ES": ".MC", "PT": ".LS", "CH": ".SW", "AT": ".VI", "SE": ".ST", "NO": ".OL", "DK": ".CO", "FI": ".HE",
    "IE": ".IR", "PL": ".WA", "MX": ".MX", "AU": ".AX", "NZ": ".NZ", "JP": ".T", "HK": ".HK", "SG": ".SI",
    "IN": ".NS", "KR": ".KS", "ZA": ".JO", "IL": ".TA",
}
# B3 tickers: 4 letters + 1-2 digits (PETR4, ITUB4, HGLG11, BOVA11, AAPL34).
B3_TICKER = re.compile(r"^[A-Z]{4}\d{1,2}$")


def candidate_symbols(symbol: str, prefer_tsx: bool = False, country: str | None = None) -> list[str]:
    """Symbols to try, in order. An input that already carries a suffix
    (SHOP.TO, BRK-B, BTC-USD) is tried as-is only. Otherwise:
      the local listing first — .SA for a B3-style ticker (PETR4) anywhere,
      else the suffix of the user's country (BR .SA, GB .L ...; prefer_tsx
      = Canada) — then the bare (US) symbol, .TO, and SYMBOL-USD (crypto).
    A candidate in Signa's known-symbol list is tried first, so "BTC" means
    BTC-USD (not the US-listed BTC trust) and "XEQT" means XEQT.TO.
    """
    if "." in symbol or "-" in symbol:
        return [symbol]
    if prefer_tsx and not country:
        country = "CA"
    local = ".SA" if B3_TICKER.match(symbol) else COUNTRY_SUFFIX.get((country or "").upper())
    cands = ([symbol + local] if local else []) + [symbol, f"{symbol}.TO", f"{symbol}-USD"]
    cands = list(dict.fromkeys(cands))
    try:
        known = set(get_all_tickers())
    except Exception:
        known = set()
    preferred = [c for c in cands if c in known]
    return preferred + [c for c in cands if c not in preferred]


def exchange_for(symbol: str) -> str:
    """Exchange label: CRYPTO, TSX, NASDAQ/NYSE (known US symbols), or the
    suffix's market (B3, LSE, XETRA ... app/market/currency.py)."""
    from app.market.currency import exchange_for_suffix, is_crypto

    if is_crypto(symbol):
        return "CRYPTO"
    return exchange_for_suffix(symbol) or get_exchange(symbol)


def recent_price(symbol: str) -> float | None:
    """Last close from yfinance if the symbol traded in the last ~10 days."""
    import yfinance as yf

    try:
        df = yf.Ticker(symbol).history(period="10d")
    except Exception as e:
        logger.debug(f"symbols: history({symbol}) failed: {e}")
        return None
    if df is None or df.empty or "Close" not in df:
        return None
    closes = df["Close"].dropna()
    if closes.empty:
        return None
    try:
        price = float(closes.iloc[-1])
    except (TypeError, ValueError):
        return None
    return price if math.isfinite(price) and price > 0 else None
