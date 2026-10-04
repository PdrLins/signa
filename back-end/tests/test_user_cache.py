"""Per-user row cache: read once, cleared by the user's writes, no stale refill."""

from app.core import user_cache


def test_reads_once_and_returns_copies():
    calls = []

    def load():
        calls.append(1)
        return [{"symbol": "AAPL"}]

    a = user_cache.get("u1", "holdings", load)
    a[0]["symbol"] = "CHANGED"
    b = user_cache.get("u1", "holdings", load)
    assert calls == [1] and b == [{"symbol": "AAPL"}]


def test_write_clears_and_blocks_older_read_from_storing():
    rows = {"v": 1}

    def slow_load():
        value = [rows["v"]]
        user_cache.invalidate("u2")      # a write lands while this read runs
        return value

    assert user_cache.get("u2", "accounts", slow_load) == [1]
    rows["v"] = 2
    assert user_cache.get("u2", "accounts", lambda: [rows["v"]]) == [2]   # old read wasn't kept


def test_write_request_clears_the_user_entry(monkeypatch):
    user_cache.get("u3", "holdings", lambda: [1])
    user_cache.invalidate("u3")
    assert user_cache.get("u3", "holdings", lambda: [2]) == [2]
