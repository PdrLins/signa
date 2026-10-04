"""Symbol input and resolution helpers. Pure except `recent_price` (yfinance)."""

from __future__ import annotations

import math

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


def candidate_symbols(symbol: str, prefer_tsx: bool = False) -> list[str]:
    """Symbols to try, in order: raw, .TO (TSX), -USD (crypto).

    An input that already carries a suffix (SHOP.TO, BRK-B, BTC-USD) is
    tried as-is only. A known symbol (market/universe.py) is tried first,
    so "BTC" means BTC-USD (not the US-listed BTC trust) and "XEQT" means
    XEQT.TO. prefer_tsx=True (a Canadian owner) tries .TO before the bare
    US symbol.
    """
    if "." in symbol or "-" in symbol:
        return [symbol]
    cands = ([f"{symbol}.TO", symbol, f"{symbol}-USD"] if prefer_tsx
             else [symbol, f"{symbol}.TO", f"{symbol}-USD"])
    try:
        known = set(get_all_tickers())
    except Exception:
        known = set()
    preferred = [c for c in cands if c in known]
    return preferred + [c for c in cands if c not in preferred]


def exchange_for(symbol: str) -> str:
    if symbol.endswith("-USD"):
        return "CRYPTO"
    return get_exchange(symbol)


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
