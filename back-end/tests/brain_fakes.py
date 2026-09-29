"""In-memory stand-in for the Supabase client used by the brain tests.

Supports the chained-builder subset the brain uses: select / insert /
update / upsert / delete + eq / neq / in_ / gt / gte / lt / lte / is_ /
not_ / contains / order / limit / range, then .execute(). Filters are
applied for real, so status guards (`.eq("status", "OPEN")`) behave like
Postgres and tests can assert on the resulting table state.
"""

from __future__ import annotations

import copy
import itertools
import os
from contextlib import ExitStack
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("BRAIN_TOKEN_SECRET", "test-brain-secret-32chars-min-len-test")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("DEBUG", "true")

_ids = itertools.count(1)


class _Result:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class FakeQuery:
    def __init__(self, db: "FakeDB", table: str):
        self.db, self.table = db, table
        self.op, self.payload = "select", None
        self.filters: list = []
        self._negate = False
        self._limit = None

    # --- operations ---
    def select(self, *_a, **_k):
        return self

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def upsert(self, payload, **_k):
        self.op, self.payload = "upsert", payload
        return self

    def delete(self):
        self.op = "delete"
        return self

    # --- filters ---
    def _add(self, kind, col, val):
        self.filters.append((kind, col, val, self._negate))
        self._negate = False
        return self

    def eq(self, c, v): return self._add("eq", c, v)
    def neq(self, c, v): return self._add("neq", c, v)
    def in_(self, c, v): return self._add("in", c, list(v))
    def gt(self, c, v): return self._add("gt", c, v)
    def gte(self, c, v): return self._add("gte", c, v)
    def lt(self, c, v): return self._add("lt", c, v)
    def lte(self, c, v): return self._add("lte", c, v)
    def is_(self, c, v): return self._add("is", c, v)
    def contains(self, c, v): return self._add("contains", c, v)

    @property
    def not_(self):
        self._negate = True
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def range(self, a, b):
        self._range = (a, b)
        return self

    # --- evaluation ---
    @staticmethod
    def _ok(row, f):
        kind, col, val, neg = f
        cur = row.get(col)
        if kind == "eq":
            r = cur == val
        elif kind == "neq":
            r = cur != val
        elif kind == "in":
            r = cur in val
        elif kind == "is":
            r = cur is None if val == "null" else cur == val
        elif kind == "contains":
            r = isinstance(cur, dict) and all(cur.get(k) == v for k, v in val.items())
        else:
            if cur is None:
                return False
            r = {"gt": cur > val, "gte": cur >= val, "lt": cur < val, "lte": cur <= val}[kind]
        return (not r) if neg else r

    def _matched(self):
        rows = self.db.tables.setdefault(self.table, [])
        return [r for r in rows if all(self._ok(r, f) for f in self.filters)]

    def execute(self):
        self.db.calls.append((self.table, self.op, copy.deepcopy(self.payload), list(self.filters)))
        if self.table in self.db.fail_ops.get(self.op, set()):
            raise RuntimeError(f"forced {self.op} failure on {self.table}")
        rows = self.db.tables.setdefault(self.table, [])
        if self.op == "select":
            out = [copy.deepcopy(r) for r in self._matched()]
            if getattr(self, "_range", None):
                a, b = self._range
                out = out[a:b + 1]
            if self._limit is not None:
                out = out[: self._limit]
            return _Result(out, count=len(out))
        if self.op in ("insert", "upsert"):
            payload = self.payload if isinstance(self.payload, list) else [self.payload]
            out = []
            for p in payload:
                row = copy.deepcopy(p)
                row.setdefault("id", f"id-{next(_ids)}")
                rows.append(row)
                out.append(copy.deepcopy(row))
            return _Result(out)
        if self.op == "update":
            out = []
            for r in self._matched():
                r.update(copy.deepcopy(self.payload))
                out.append(copy.deepcopy(r))
            return _Result(out)
        if self.op == "delete":
            m = self._matched()
            self.db.tables[self.table] = [r for r in rows if r not in m]
            return _Result(m)
        raise AssertionError(self.op)


class FakeDB:
    def __init__(self, tables: dict | None = None):
        self.tables: dict[str, list[dict]] = copy.deepcopy(tables or {})
        self.calls: list = []
        self.fail_ops: dict[str, set[str]] = {}

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)

    def rows(self, table: str) -> list[dict]:
        return self.tables.get(table, [])

    def ops(self, table: str, op: str) -> list:
        return [c for c in self.calls if c[0] == table and c[1] == op]


USER_ID = "user-1"


def wallet_row(balance=10_000.0, collateral=0.0, deposited=10_000.0, peak=10_000.0):
    return {"id": "w1", "user_id": USER_ID, "balance": balance, "collateral_reserved": collateral,
            "initial_deposit": deposited, "total_deposited": deposited, "total_withdrawn": 0.0,
            "peak_equity": peak}


def patch_db(db: FakeDB, *, prices: dict | None = None, market_open: bool = True, fx: float | None = 1.0):
    """Patch every module-level get_client + network helper the brain uses."""
    stack = ExitStack()
    for target in (
        "app.services.virtual_portfolio.get_client",
        "app.services.wallet.get_client",
        "app.services.watchdog_service.get_client",
        "app.services.learning_service.get_client",
        "app.services.knowledge_events.get_client",
        "app.db.queries.get_client",
    ):
        stack.enter_context(patch(target, return_value=db))
    stack.enter_context(patch("app.db.queries.get_brain_user_id", return_value=USER_ID))
    price_map = {k: (v, 0.0) for k, v in (prices or {}).items()}
    fetch = lambda syms: {s: price_map.get(s, (None, None)) for s in syms}  # noqa: E731
    stack.enter_context(patch("app.services.virtual_portfolio._fetch_prices_batch", side_effect=fetch))
    stack.enter_context(patch("app.services.watchdog_service._fetch_prices_batch", side_effect=fetch))
    stack.enter_context(patch("app.services.virtual_portfolio._is_us_market_open", return_value=market_open))
    stack.enter_context(patch("app.services.virtual_portfolio._is_tradable_now",
                              side_effect=lambda s, m=None: s.endswith("-USD") or market_open))
    stack.enter_context(patch("app.services.virtual_portfolio.fx_to_usd",
                              side_effect=lambda s: 1.0 if not s.endswith(".TO") else fx))
    stack.enter_context(patch("app.services.watchdog_service._tg_send"))
    return stack
