"""In-memory fake of the portfolio queries (migration 013) + a test client.

`FakePortfolioDB(monkeypatch)` replaces the app.db.queries functions used by
profile / people / accounts / holdings / transactions / notification prefs.
`db.missing = True` makes every call fail like a database without
migration 013 ("relation ... does not exist").
"""

from __future__ import annotations

import time
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import access
from app.core.security import create_access_token
from app.db import queries
from app.middleware import auth as auth_mw

U1 = "11111111-1111-1111-1111-111111111111"
U2 = "22222222-2222-2222-2222-222222222222"


class FakePortfolioDB:
    def __init__(self, monkeypatch):
        self.settings: dict[str, dict] = {}
        self.people: dict[str, dict] = {}
        self.accounts: dict[str, dict] = {}
        self.holdings: dict[str, dict] = {}
        self.txs: dict[str, dict] = {}
        self.prefs: dict[str, dict] = {}
        self.missing = False
        self.followed: dict[str, set[str]] = {}
        self.snapshots: list[dict] = []          # portfolio_snapshots rows (+ user_id)
        self.income_snaps: dict[tuple, dict] = {}  # (user_id, date) -> row
        self.check_rows: dict[tuple, dict] = {}    # (symbol, date) -> row
        self.watchlist: dict[str, list[dict]] = {}
        self.quotes: dict[str, dict] = {}          # SYMBOL -> quote row (no network)
        self.closes: dict[str, object] = {}        # SYMBOL -> pandas Series of daily closes
        for name in (
            "get_profile_settings", "upsert_profile_settings", "get_user_email",
            "get_people", "insert_person", "update_person", "delete_person",
            "get_accounts", "insert_accounts", "update_account", "delete_account", "move_account_transactions",
            "get_holdings", "upsert_holdings", "update_holding", "delete_holding",
            "list_transactions", "get_transaction", "insert_transactions", "update_transaction",
            "delete_transaction", "delete_transaction_batch",
            "get_notification_prefs", "upsert_notification_prefs",
            # Phase 2 (migration 014)
            "get_all_transactions", "get_portfolio_snapshot_rows", "get_income_snapshots",
            "upsert_income_snapshot", "get_check_status_rows", "upsert_check_status_rows",
            "get_allocation_targets", "set_allocation_targets",
        ):
            monkeypatch.setattr(queries, name, self._wrap(getattr(self, name)))
        monkeypatch.setattr(queries, "get_holdings_review_all_at", lambda uid: None)
        monkeypatch.setattr(queries, "set_holdings_review_all_at", lambda uid, at: None)
        monkeypatch.setattr(queries, "get_watchlist", lambda uid: [dict(w) for w in self.watchlist.get(uid, [])])
        monkeypatch.setattr("app.services.price_cache.get_usdcad_rate", lambda *a, **k: 1.4)
        monkeypatch.setattr("app.services.quotes.get_quotes",
                            lambda syms: {s.upper(): dict(self.quotes[s.upper()]) for s in syms
                                          if s and s.upper() in self.quotes})
        monkeypatch.setattr("app.services.price_cache.fetch_daily_closes",
                            lambda syms, period="1y": {s: self.closes[s] for s in syms if s in self.closes})
        from app.services import slots
        monkeypatch.setattr(slots, "followed_symbols",
                            lambda uid: {h["symbol"] for h in self.holdings.values() if h["user_id"] == uid}
                            | self.followed.get(uid, set()))

    def _wrap(self, fn):
        def inner(*a, **k):
            if self.missing:
                raise RuntimeError('relation "public.accounts" does not exist (42P01)')
            return fn(*a, **k)
        inner.__name__ = fn.__name__
        return inner

    @staticmethod
    def _id() -> str:
        return str(uuid.uuid4())

    # ---- profile
    def get_profile_settings(self, uid):
        return dict(self.settings[uid]) if uid in self.settings else None

    def upsert_profile_settings(self, uid, data):
        self.settings.setdefault(uid, {"user_id": uid}).update(data)
        return dict(self.settings[uid])

    def get_user_email(self, uid):
        return None

    # ---- people
    def get_people(self, uid):
        return [dict(p) for p in self.people.values() if p["user_id"] == uid]

    def insert_person(self, uid, data):
        pid = self._id()
        self.people[pid] = {"id": pid, "user_id": uid, "created_at": time.time(), **data}
        return dict(self.people[pid])

    def update_person(self, pid, uid, data):
        p = self.people.get(pid)
        if not p or p["user_id"] != uid:
            return None
        p.update(data)
        return dict(p)

    def delete_person(self, pid, uid):
        p = self.people.get(pid)
        if not p or p["user_id"] != uid:
            return False
        del self.people[pid]
        for a in self.accounts.values():
            if a.get("person_id") == pid:
                a["person_id"] = None
        return True

    # ---- accounts
    def add_account(self, uid, name, **kw):
        return self.insert_accounts(uid, [{"name": name, "currency": kw.pop("currency", "CAD"), **kw}])[0]["id"]

    def get_accounts(self, uid):
        return [dict(a) for a in self.accounts.values() if a["user_id"] == uid]

    def insert_accounts(self, uid, rows):
        out = []
        for r in rows:
            aid = self._id()
            self.accounts[aid] = {"id": aid, "user_id": uid, "person_id": None, "account_type": None,
                                  "cash_balance": 0, "created_at": time.time(), **r}
            out.append(dict(self.accounts[aid]))
        return out

    def update_account(self, aid, uid, data):
        a = self.accounts.get(aid)
        if not a or a["user_id"] != uid:
            return None
        a.update(data)
        return dict(a)

    def delete_account(self, aid, uid):
        a = self.accounts.get(aid)
        if not a or a["user_id"] != uid:
            return False
        for h in self.holdings.values():
            if h.get("account_id") == aid:
                h["account_id"] = None
        del self.accounts[aid]
        return True

    def move_account_transactions(self, uid, src, dst):
        for t in self.txs.values():
            if t["user_id"] == uid and t.get("account_id") == src:
                t["account_id"] = dst

    # ---- holdings
    def add_holding(self, uid, symbol, account_id=None, **kw):
        hid = self._id()
        self.holdings[hid] = {"id": hid, "user_id": uid, "symbol": symbol, "account_id": account_id,
                              "created_at": time.time(), **kw}
        return hid

    def get_holdings(self, uid):
        return [dict(h) for h in self.holdings.values() if h["user_id"] == uid]

    def upsert_holdings(self, uid, rows):
        assert len({tuple(sorted(r)) for r in rows}) == 1, "bulk rows need identical keys"
        out = []
        for r in rows:
            cur = next((h for h in self.holdings.values() if h["user_id"] == uid and h["symbol"] == r["symbol"]
                        and (h.get("account_id") or None) == (r.get("account_id") or None)), None)
            if cur is None:
                cur = self.holdings[self.add_holding(uid, r["symbol"])]
            cur.update(r)
            out.append(dict(cur))
        return out

    def update_holding(self, hid, uid, data):
        h = self.holdings.get(hid)
        if not h or h["user_id"] != uid:
            return None
        h.update(data)
        return dict(h)

    def delete_holding(self, hid, uid):
        h = self.holdings.get(hid)
        if not h or h["user_id"] != uid:
            return False
        del self.holdings[hid]
        return True

    # ---- transactions
    def list_transactions(self, uid, filters, limit, offset):
        rows = [t for t in self.txs.values() if t["user_id"] == uid]
        for k in ("account_id", "symbol", "type"):
            if filters.get(k):
                rows = [t for t in rows if t.get(k) == filters[k]]
        if filters.get("from"):
            rows = [t for t in rows if t["trade_date"] >= filters["from"]]
        if filters.get("to"):
            rows = [t for t in rows if t["trade_date"] <= filters["to"]]
        rows.sort(key=lambda t: (t["trade_date"], t["created_at"]), reverse=True)
        return [dict(t) for t in rows[offset:offset + limit]], len(rows)

    def get_transaction(self, tid, uid):
        t = self.txs.get(tid)
        return dict(t) if t and t["user_id"] == uid else None

    def insert_transactions(self, uid, rows, chunk=500):
        assert len({tuple(sorted(r)) for r in rows}) == 1, "bulk rows need identical keys"
        out = []
        for r in rows:
            tid = self._id()
            self.txs[tid] = {"id": tid, "user_id": uid, "created_at": time.time(), **r}
            out.append(dict(self.txs[tid]))
        return out

    def update_transaction(self, tid, uid, data):
        t = self.txs.get(tid)
        if not t or t["user_id"] != uid:
            return None
        t.update(data)
        return dict(t)

    def delete_transaction(self, tid, uid):
        t = self.txs.get(tid)
        if not t or t["user_id"] != uid:
            return False
        del self.txs[tid]
        return True

    def delete_transaction_batch(self, uid, batch_id):
        ids = [k for k, t in self.txs.items() if t["user_id"] == uid and t.get("import_batch_id") == batch_id]
        for k in ids:
            del self.txs[k]
        return len(ids)

    # ---- phase 2 (migration 014)
    def get_all_transactions(self, uid):
        rows = [dict(t) for t in self.txs.values() if t["user_id"] == uid]
        rows.sort(key=lambda t: (str(t["trade_date"]), t["created_at"]))
        return rows

    def get_portfolio_snapshot_rows(self, uid, since=None, account_ids=None):
        rows = [dict(r) for r in self.snapshots if r["user_id"] == uid
                and (r.get("account_id") is None if account_ids is None else r.get("account_id") in account_ids)
                and (since is None or str(r["snapshot_date"]) >= since)]
        return sorted(rows, key=lambda r: str(r["snapshot_date"]))

    def get_income_snapshots(self, uid, since=None):
        rows = [dict(r) for (u, d), r in self.income_snaps.items() if u == uid and (since is None or d >= since)]
        return sorted(rows, key=lambda r: r["snapshot_date"])

    def upsert_income_snapshot(self, uid, snapshot_date, row):
        self.income_snaps[(uid, snapshot_date)] = {**row, "snapshot_date": snapshot_date}
        return 1

    def get_check_status_rows(self, symbols, since=None):
        rows = [dict(r) for (sym, d), r in self.check_rows.items() if sym in symbols and (since is None or d >= since)]
        return sorted(rows, key=lambda r: r["check_date"])

    def upsert_check_status_rows(self, rows, chunk=500):
        for r in rows:
            self.check_rows[(r["symbol"], r["check_date"])] = dict(r)
        return len(rows)

    def get_allocation_targets(self, uid):
        return (self.settings.get(uid) or {}).get("allocation_targets")

    def set_allocation_targets(self, uid, targets):
        self.settings.setdefault(uid, {"user_id": uid})["allocation_targets"] = targets
        return targets

    # ---- notification prefs
    def get_notification_prefs(self, uid):
        return dict(self.prefs[uid]) if uid in self.prefs else None

    def upsert_notification_prefs(self, uid, prefs):
        self.prefs[uid] = {"prefs": prefs, "updated_at": "2026-09-30T00:00:00Z"}
        return dict(self.prefs[uid])


def set_level(monkeypatch, level: str) -> None:
    fn = lambda _uid: {"level": level, "slot_bonus": 0}  # noqa: E731
    monkeypatch.setattr(access, "get_user_access", fn)
    monkeypatch.setattr(auth_mw, "get_user_access", fn)


def make_client(monkeypatch, *routers, level: str = "owner", uid: str = U1) -> TestClient:
    monkeypatch.setattr(auth_mw, "is_token_blacklisted", lambda _jti: False)
    monkeypatch.setattr(auth_mw, "insert_audit_log", lambda *a, **k: None)
    set_level(monkeypatch, level)
    app = FastAPI()
    app.add_middleware(auth_mw.AuthMiddleware)
    for r in routers:
        app.include_router(r, prefix="/api/v1")
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {create_access_token(uid, 'u')}"
    return c
