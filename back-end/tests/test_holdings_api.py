"""/api/v1/holdings — auth, user scoping, upsert merge, patch/delete, resolve.
DB (app.db.queries), yfinance and the holding-status refresh are mocked."""

import time
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import holdings as api
from app.core.config import settings
from app.core.security import create_access_token
from app.db import queries
from app.middleware import auth as auth_mw
from app.services import holdings_service as hs

U1, U2 = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"


def _auth(uid=U1):
    return {"Authorization": f"Bearer {create_access_token(uid, 'owner')}"}


class FakeDB:
    def __init__(self):
        self.rows: dict[str, dict] = {}

    def add(self, uid, symbol, **kw):
        hid = str(uuid.uuid4())
        self.rows[hid] = {"id": hid, "user_id": uid, "symbol": symbol, "created_at": time.time(), **kw}
        return hid

    def get_holdings(self, uid):
        return [dict(r) for r in self.rows.values() if r["user_id"] == uid]

    def upsert_holdings(self, uid, rows):
        keys = {tuple(sorted(r)) for r in rows}
        assert len(keys) == 1, "PostgREST bulk upsert needs identical keys"
        out = []
        for r in rows:
            cur = next((x for x in self.rows.values() if x["user_id"] == uid and x["symbol"] == r["symbol"]), None)
            if cur:
                cur.update(r)
            else:
                hid = self.add(uid, r["symbol"])
                self.rows[hid].update(r)
                cur = self.rows[hid]
            out.append(dict(cur))
        return out

    def update_holding(self, hid, uid, data):
        r = self.rows.get(hid)
        if not r or r["user_id"] != uid:
            return None
        r.update(data)
        return dict(r)

    def delete_holding(self, hid, uid):
        r = self.rows.get(hid)
        if not r or r["user_id"] != uid:
            return False
        del self.rows[hid]
        return True


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    monkeypatch.setattr(queries, "get_holdings", d.get_holdings)
    monkeypatch.setattr(queries, "upsert_holdings", d.upsert_holdings)
    monkeypatch.setattr(queries, "update_holding", d.update_holding)
    monkeypatch.setattr(queries, "delete_holding", d.delete_holding)
    monkeypatch.setattr(queries, "get_watchlist", lambda uid: [])
    monkeypatch.setattr(queries, "get_accounts", lambda uid: [])
    monkeypatch.setattr("app.services.price_cache.get_usdcad_rate", lambda: 1.4)
    d.quotes = {}   # SYMBOL -> shared live quote (no network)
    monkeypatch.setattr("app.services.quotes.get_quotes",
                        lambda syms: {s.upper(): dict(d.quotes[s.upper()]) for s in syms if s.upper() in d.quotes})
    return d


@pytest.fixture
def refreshes(monkeypatch):
    calls = []
    monkeypatch.setattr(api.holding_status, "kick", lambda uid: calls.append(uid) or True)
    return calls


@pytest.fixture
def client(monkeypatch, db, refreshes):
    monkeypatch.setattr(auth_mw, "is_token_blacklisted", lambda jti: False)
    monkeypatch.setattr(auth_mw, "insert_audit_log", lambda *a, **k: None)
    app = FastAPI()
    app.add_middleware(auth_mw.AuthMiddleware)
    app.include_router(api.router, prefix="/api/v1")
    with TestClient(app) as c:
        yield c


# ── auth ──

@pytest.mark.parametrize("method,path,body", [
    ("get", "/api/v1/holdings", None),
    ("post", "/api/v1/holdings", {"items": [{"symbol": "XEQT.TO"}]}),
    ("post", "/api/v1/holdings/resolve", {"text": "XEQT"}),
    ("patch", f"/api/v1/holdings/{uuid.uuid4()}", {"shares": 1}),
    ("delete", f"/api/v1/holdings/{uuid.uuid4()}", None),
])
def test_routes_require_auth(client, method, path, body):
    kw = {"json": body} if body is not None else {}
    assert getattr(client, method)(path, **kw).status_code == 401


# ── list ──

def test_list_is_user_scoped_with_math(client, db):
    db.add(U1, "XEQT.TO", currency="CAD", shares=100, avg_cost=25, holding_status={"price": 30.0},
           alert_state={"trend_break": False})
    db.add(U1, "NVDA", currency="USD", shares=10, holding_status={"price": 100.0})
    db.add(U2, "AAPL", currency="USD")
    body = client.get("/api/v1/holdings", headers=_auth()).json()
    assert body["count"] == 2
    assert {i["symbol"] for i in body["items"]} == {"XEQT.TO", "NVDA"}
    assert all("alert_state" not in i and "user_id" not in i for i in body["items"])
    assert body["totals"]["value_cad"] == 4400.0 and body["totals"]["currency"] == "CAD"
    x = next(i for i in body["items"] if i["symbol"] == "XEQT.TO")
    assert x["position"]["unrealized"] == 500.0
    assert body["review_all"]["allowed"] is False and body["review_running"] is False   # AI review: Advisor


def test_list_prices_with_live_quote_and_falls_back_to_last_close(client, db):
    db.add(U1, "XEQT.TO", currency="CAD", shares=100, avg_cost=25,
           holding_status={"price": 30.0, "prev_close": 29.0, "as_of": "2026-09-30", "ytd_pct": 20.0})
    db.add(U1, "NVDA", currency="USD", shares=10,
           holding_status={"price": 100.0, "prev_close": 98.0, "ytd_base": 80.0, "as_of": "2026-09-30"})
    db.add(U1, "ZZZ", currency="USD", shares=1)   # nothing prices it
    db.quotes["XEQT.TO"] = {"symbol": "XEQT.TO", "price": 32.0, "prev_close": 30.0, "currency": "CAD",
                            "as_of": "2026-10-01T15:00:00+00:00"}
    body = client.get("/api/v1/holdings", headers=_auth()).json()
    x = next(i for i in body["items"] if i["symbol"] == "XEQT.TO")
    n = next(i for i in body["items"] if i["symbol"] == "NVDA")
    z = next(i for i in body["items"] if i["symbol"] == "ZZZ")
    assert x["quote"] == {"price": 32.0, "prev_close": 30.0, "change_pct": pytest.approx(6.6667, abs=1e-4),
                          "change": 2.0, "as_of": "2026-10-01T15:00:00+00:00", "live": True,
                          "price_source": "quote", "ytd_pct_live": 28.0}   # base 30 / 1.2 = 25
    assert x["position"]["value"] == 3200.0 and x["position"]["unrealized"] == 700.0
    # no live quote: last close, and yesterday's move is NOT reported as today's
    assert n["quote"]["live"] is False and n["quote"]["price"] == 100.0
    assert n["quote"]["price_source"] == "last_close"
    assert n["quote"]["change"] is None and n["quote"]["change_pct"] is None and n["quote"]["prev_close"] is None
    assert n["quote"]["ytd_pct_live"] == 25.0
    assert body["totals"]["as_of"] == "2026-09-30"
    assert z["quote"] is None and z["position"]["value"] is None
    assert body["totals"]["value_cad"] == 3200.0 + 1000 * 1.4
    assert x["position"]["weight_pct"] == pytest.approx(3200 / 4600 * 100, abs=0.01)
    assert x["holding_status"]["price"] == 30.0   # the monitor's row is untouched


def test_symbol_weight_spans_accounts(client, db, monkeypatch):
    monkeypatch.setattr(settings, "holdings_max_weight_pct", 30.0)
    db.add(U1, "NVDA", currency="USD", shares=2, account_id="a1")
    db.add(U1, "NVDA", currency="USD", shares=2, account_id="a2")
    db.add(U1, "VFV.TO", currency="CAD", shares=10)
    db.quotes["NVDA"] = {"symbol": "NVDA", "price": 100.0, "prev_close": 100.0, "currency": "USD"}
    db.quotes["VFV.TO"] = {"symbol": "VFV.TO", "price": 100.0, "prev_close": 100.0, "currency": "CAD"}
    body = client.get("/api/v1/holdings", headers=_auth()).json()
    nv = [i["position"] for i in body["items"] if i["symbol"] == "NVDA"]
    # total = 560 + 1000; each NVDA lot is 17.9% (< 30) but NVDA is 35.9% (> 30)
    assert all(p["weight_pct"] == pytest.approx(17.95, abs=0.01) for p in nv)
    assert all(p["symbol_weight_pct"] == pytest.approx(35.9, abs=0.01) and p["overweight"] for p in nv)


def test_list_quotes_failure_falls_back(client, db, monkeypatch):
    def boom(syms):
        raise RuntimeError("yahoo down")
    monkeypatch.setattr("app.services.quotes.get_quotes", boom)
    db.add(U1, "XEQT.TO", currency="CAD", shares=10, holding_status={"price": 30.0})
    body = client.get("/api/v1/holdings", headers=_auth()).json()
    assert body["items"][0]["quote"]["live"] is False and body["totals"]["value_cad"] == 300.0


def test_table_missing_returns_503(client, monkeypatch):
    def boom(uid):
        raise RuntimeError('relation "holdings" does not exist')
    monkeypatch.setattr(queries, "get_holdings", boom)
    r = client.get("/api/v1/holdings", headers=_auth())
    assert r.status_code == 503 and r.json()["detail"]["code"] == "holdings_unavailable"


# ── upsert ──

def test_upsert_creates_and_never_wipes_known_values(client, db, refreshes):
    hid = db.add(U1, "NVDA", shares=17.99, avg_cost=120.0, currency="USD", account="TFSA")
    r = client.post("/api/v1/holdings", headers=_auth(), json={"items": [
        {"symbol": "nvda", "name": "NVIDIA"},
        {"symbol": "XEQT.TO", "input_symbol": "xeqt", "shares": 10, "asset_type": "ETF"},
    ]})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["created"] == 1 and body["updated"] == 1 and refreshes == [U1]
    nv = db.rows[hid]
    assert nv["shares"] == 17.99 and nv["avg_cost"] == 120.0 and nv["account"] == "TFSA" and nv["name"] == "NVIDIA"
    xe = next(r for r in db.rows.values() if r["symbol"] == "XEQT.TO")
    assert xe["currency"] == "CAD" and xe["input_symbol"] == "XEQT" and xe["user_id"] == U1


@pytest.mark.parametrize("item", [
    {"symbol": "BAD!!"}, {"symbol": "../etc/passwd"}, {"symbol": "NVDA", "shares": -1},
    {"symbol": "NVDA", "account": "LIRA"}, {"symbol": "NVDA", "currency": "usd"},
])
def test_upsert_validation(client, item):
    assert client.post("/api/v1/holdings", headers=_auth(), json={"items": [item]}).status_code == 422


# ── patch / delete ──

def test_patch_updates_and_can_clear(client, db):
    hid = db.add(U1, "NVDA", shares=5, avg_cost=100)
    r = client.patch(f"/api/v1/holdings/{hid}", headers=_auth(), json={"shares": 7.5, "avg_cost": None})
    assert r.status_code == 200
    assert db.rows[hid]["shares"] == 7.5 and db.rows[hid]["avg_cost"] is None


def test_patch_other_users_holding_is_404(client, db):
    hid = db.add(U2, "AAPL", shares=1)
    r = client.patch(f"/api/v1/holdings/{hid}", headers=_auth(U1), json={"shares": 9})
    assert r.status_code == 404 and db.rows[hid]["shares"] == 1


def test_patch_empty_body_400(client, db):
    hid = db.add(U1, "NVDA")
    assert client.patch(f"/api/v1/holdings/{hid}", headers=_auth(), json={}).status_code == 400


def test_delete_scoped(client, db):
    mine, theirs = db.add(U1, "NVDA"), db.add(U2, "AAPL")
    assert client.delete(f"/api/v1/holdings/{theirs}", headers=_auth()).status_code == 404
    assert client.delete(f"/api/v1/holdings/{mine}", headers=_auth()).status_code == 200
    assert mine not in db.rows and theirs in db.rows


def test_bad_uuid_422(client):
    assert client.delete("/api/v1/holdings/not-a-uuid", headers=_auth()).status_code == 422


# ── resolve ──

def test_resolve_endpoint(client, db, monkeypatch):
    db.add(U1, "NVDA")
    table = {"ENS.TO": {"symbol": "ENS.TO", "name": "E Split Corp.", "exchange": "TSX", "currency": "CAD",
                        "asset_type": "STOCK", "price": 17.0},
             "ENS": {"symbol": "ENS", "name": "EnerSys", "exchange": "NYSE", "currency": "USD",
                     "asset_type": "STOCK", "price": 110.0},
             "NVDA": {"symbol": "NVDA", "name": "NVIDIA", "exchange": "NASDAQ", "currency": "USD",
                      "asset_type": "STOCK", "price": 180.0}}
    monkeypatch.setattr(hs, "_lookup_listing", lambda s: table.get(s))
    monkeypatch.setattr("app.market.symbols.get_all_tickers", lambda: [])
    r = client.post("/api/v1/holdings/resolve", headers=_auth(), json={"text": "ENS 3 @ 15\nNVDA\nNOPE1"})
    body = r.json()
    assert r.status_code == 200
    assert body["counts"] == {"ok": 1, "ambiguous": 1, "not_found": 1, "invalid": 0}
    ens = body["lines"][0]
    assert ens["selected"]["symbol"] == "ENS.TO" and len(ens["alternatives"]) == 2
    assert (ens["shares"], ens["avg_cost"]) == (3.0, 15.0)
    assert body["lines"][1]["existing"] is True


def test_resolve_empty_text_400(client):
    assert client.post("/api/v1/holdings/resolve", headers=_auth(), json={"text": "# nothing"}).status_code == 400
