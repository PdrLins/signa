"""Holdings queries across migration 013: selects fall back without
account_id, upserts use the 010 on_conflict before 013 and match
(account_id, symbol) by hand after it."""

import pytest

from app.core.api_errors import MigrationRequired
from app.db import queries


class _Result:
    def __init__(self, data):
        self.data = data


class FakeClient:
    """Tiny PostgREST stand-in: records calls, answers from `holdings`."""

    def __init__(self, has_account_id: bool, rows=None):
        self.has_account_id = has_account_id
        self.rows = rows or []
        self.calls: list[tuple] = []

    def table(self, name):
        return _Query(self, name)


class _Query:
    def __init__(self, client, name):
        self.c, self.name, self.op, self.payload, self.cols, self.filters = client, name, None, None, "", {}
        self.on_conflict = None

    def select(self, cols, **_):
        self.op, self.cols = "select", cols
        return self

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def upsert(self, payload, on_conflict=None):
        self.op, self.payload, self.on_conflict = "upsert", payload, on_conflict
        return self

    def eq(self, k, v):
        self.filters[k] = v
        return self

    def order(self, *a, **k):
        return self

    def range(self, *a):   # paging (queries._select_all_pages): one short page
        return self

    def limit(self, *a):
        return self

    def execute(self):
        self.c.calls.append((self.op, self.cols, self.on_conflict, self.payload))
        if "account_id" in (self.cols or "") and not self.c.has_account_id:
            raise RuntimeError("column holdings.account_id does not exist (42703)")
        if self.op == "select":
            return _Result([r for r in self.c.rows if all(r.get(k) == v for k, v in self.filters.items())])
        if self.op == "update":
            return _Result([{"id": self.filters.get("id"), **self.payload}])
        payload = self.payload if isinstance(self.payload, list) else [self.payload]
        return _Result([{"id": f"new{i}", **r} for i, r in enumerate(payload)])


@pytest.fixture(autouse=True)
def _reset_probe(monkeypatch):
    monkeypatch.setattr(queries, "_holdings_no_account_id_at", None)


def test_select_falls_back_before_013(monkeypatch):
    fake = FakeClient(False, [{"id": "h1", "user_id": "u", "symbol": "NVDA"}])
    monkeypatch.setattr(queries, "get_client", lambda: fake)
    rows = queries.get_holdings("u")
    assert rows == [{"id": "h1", "user_id": "u", "symbol": "NVDA", "account_id": None}]
    assert not queries.holdings_have_account_id()     # remembered: next call skips the probe
    queries.get_holdings("u")
    assert sum(1 for c in fake.calls if "account_id" in (c[1] or "")) == 1


def test_select_includes_account_id_after_013(monkeypatch):
    fake = FakeClient(True, [{"id": "h1", "user_id": "u", "symbol": "NVDA", "account_id": "a"}])
    monkeypatch.setattr(queries, "get_client", lambda: fake)
    assert queries.get_holdings("u")[0]["account_id"] == "a"


def test_upsert_before_013_uses_legacy_conflict(monkeypatch):
    fake = FakeClient(False)
    monkeypatch.setattr(queries, "get_client", lambda: fake)
    queries.upsert_holdings("u", [{"symbol": "NVDA", "account_id": None, "shares": 1}])
    op, _, conflict, payload = fake.calls[-1]
    assert op == "upsert" and conflict == "user_id,symbol" and "account_id" not in payload[0]
    with pytest.raises(MigrationRequired):
        queries.upsert_holdings("u", [{"symbol": "NVDA", "account_id": "a"}])


def test_upsert_after_013_matches_account_and_symbol(monkeypatch):
    fake = FakeClient(True, [{"id": "h1", "user_id": "u", "symbol": "NVDA", "account_id": "a"}])
    monkeypatch.setattr(queries, "get_client", lambda: fake)
    out = queries.upsert_holdings("u", [
        {"symbol": "NVDA", "account_id": "a", "shares": 2},     # existing lot -> update
        {"symbol": "NVDA", "account_id": "b", "shares": 3},     # same stock, other account -> insert
    ])
    ops = [c[0] for c in fake.calls]
    assert ops == ["select", "upsert", "insert"] and len(out) == 2   # one bulk upsert for existing lots
    assert fake.calls[1][3][0]["id"] == "h1" and fake.calls[1][3][0]["shares"] == 2
    assert fake.calls[2][3] == [{"symbol": "NVDA", "account_id": "b", "shares": 3, "user_id": "u"}]


def test_run_db_retries_dropped_connection(monkeypatch):
    import asyncio

    import pytest
    from fastapi import HTTPException

    from app.core import api_errors
    from app.db import supabase as sb

    resets = []
    monkeypatch.setattr(sb, "reset_client", lambda: resets.append(1))
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("Server disconnected")
        return "ok"

    assert asyncio.run(api_errors.run_db(flaky)) == "ok" and calls["n"] == 3 and len(resets) == 2

    def always_down():
        raise RuntimeError("Server disconnected")

    with pytest.raises(HTTPException) as e:
        asyncio.run(api_errors.run_db(always_down))
    assert e.value.detail["code"] == "storage_unavailable"

    def other_error():
        raise RuntimeError("boom")

    calls["n"] = 0
    with pytest.raises(HTTPException):
        asyncio.run(api_errors.run_db(other_error))
