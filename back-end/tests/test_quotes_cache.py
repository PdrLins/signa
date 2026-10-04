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


def test_intraday_bars_downloaded_once_for_concurrent_users(monkeypatch):
    import threading
    import time
    from datetime import datetime, timezone

    from app.services import portfolio_performance as perf

    perf.clear_cache()
    calls = []
    bar = [(datetime(2026, 10, 2, 14, 0, tzinfo=timezone.utc), 10.0)]

    def slow(symbols, interval, prepost=False):
        calls.append(list(symbols))
        time.sleep(0.2)
        return {s: bar for s in symbols}
    monkeypatch.setattr(perf, "_download_intraday", slow)
    results = []
    threads = [threading.Thread(target=lambda: results.append(perf.get_intraday_bars(["VOD.L"], "5m")))
               for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert calls == [["VOD.L"]]
    assert all(r == {"VOD.L": bar} for r in results)
    perf.clear_cache()


def test_daily_closes_scaled_from_pence():
    import pandas as pd

    from app.services.price_cache import _close_series_from_download

    idx = pd.date_range("2026-09-28", periods=2, freq="D")
    s = _close_series_from_download(pd.DataFrame({"Close": [7200.0, 7300.0]}, index=idx), "VOD.L", False)
    assert list(s) == [72.0, 73.0]
    s = _close_series_from_download(pd.DataFrame({"Close": [10.0, 11.0]}, index=idx), "AAPL", False)
    assert list(s) == [10.0, 11.0]
