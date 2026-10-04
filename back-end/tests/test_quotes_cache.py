"""Stored quotes are read once per few seconds for everyone; a refresh replaces them."""

from app.db import queries
from app.services import quotes


def test_stored_quotes_shared_and_replaced_on_refresh(monkeypatch):
    reads = []
    table = {"AAPL": {"symbol": "AAPL", "price": 100.0}}

    def rows(syms):
        reads.append(list(syms))
        return [dict(table[s]) for s in syms if s in table]

    monkeypatch.setattr(queries, "get_quote_rows", rows)
    monkeypatch.setattr(queries, "upsert_quotes", lambda rows_: None)
    assert quotes.get_stored_quotes(["AAPL"])["AAPL"]["price"] == 100.0
    assert quotes.get_stored_quotes(["aapl"])["AAPL"]["price"] == 100.0
    assert reads == [["AAPL"]]

    table["AAPL"]["price"] = 101.0
    monkeypatch.setattr(quotes, "fetch_quotes", lambda syms: {"AAPL": {"symbol": "AAPL", "price": 101.0}})
    quotes.refresh_quotes(["AAPL"])
    assert quotes.get_stored_quotes(["AAPL"])["AAPL"]["price"] == 101.0


def test_missing_symbol_fetched_once_then_skipped(monkeypatch):
    fetched = []
    monkeypatch.setattr(queries, "get_quote_rows", lambda syms: [])
    monkeypatch.setattr(quotes, "refresh_quotes", lambda syms: fetched.append(list(syms)) or {})
    assert quotes.get_quotes(["NOPE.XX"]) == {}
    assert quotes.get_quotes(["NOPE.XX"]) == {}
    assert fetched == [["NOPE.XX"]]
