"""People, accounts and holdings-in-accounts (migration 013): CRUD rules,
account-type gating by level and country, delete with move/force, the same
stock in two accounts, filters, slots and pre-migration degradation."""

import uuid

import pytest

from app.api.v1 import accounts as accounts_api
from app.api.v1 import holdings as holdings_api
from app.services import accounts_service
from tests.portfolio_fakes import U1, U2, FakePortfolioDB, make_client


@pytest.fixture
def db(monkeypatch):
    d = FakePortfolioDB(monkeypatch)
    monkeypatch.setattr(holdings_api, "_kick_refresh", lambda uid: True)
    holdings_api._reset_state()
    return d


def _client(monkeypatch, level="free", uid=U1):
    return make_client(monkeypatch, accounts_api.people_router, accounts_api.router, holdings_api.router,
                       level=level, uid=uid)


# ---------------------------------------------------------------- migration missing

def test_accounts_and_people_503_before_migration(monkeypatch, db):
    db.missing = True
    c = _client(monkeypatch)
    for r in (c.get("/api/v1/accounts"), c.post("/api/v1/accounts", json={"name": "WS"}),
              c.get("/api/v1/people"), c.post("/api/v1/people", json={"name": "Me"})):
        assert r.status_code == 503 and r.json()["detail"]["code"] == "migration_required"


def test_holdings_still_work_before_migration(monkeypatch, db):
    """No accounts table: holdings list/upsert work; account filters/ids need 013."""
    c = _client(monkeypatch)

    def no_accounts(uid):
        raise RuntimeError('relation "public.accounts" does not exist')
    monkeypatch.setattr("app.db.queries.get_accounts", no_accounts)
    db.add_holding(U1, "NVDA", shares=1)
    body = c.get("/api/v1/holdings").json()
    assert body["count"] == 1 and body["items"][0]["account_id"] is None and body["items"][0]["account_name"] is None
    assert c.post("/api/v1/holdings", json={"items": [{"symbol": "XEQT.TO"}]}).status_code == 201
    r = c.post("/api/v1/holdings", json={"items": [{"symbol": "VFV.TO", "account_id": str(uuid.uuid4())}]})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "migration_required"
    r = c.get(f"/api/v1/holdings?account_id={uuid.uuid4()}")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "migration_required"


# ---------------------------------------------------------------- people

def test_people_crud(monkeypatch, db):
    c = _client(monkeypatch)
    r = c.post("/api/v1/people", json={"name": " Ray ", "color": "#aa00ff"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert r.json()["name"] == "Ray" and r.json()["color"] == "#AA00FF"
    assert c.post("/api/v1/people", json={"name": "ray"}).json()["detail"]["code"] == "duplicate_name"
    assert c.post("/api/v1/people", json={"name": "X", "color": "red"}).json()["detail"]["code"] == "invalid_color"
    assert c.post("/api/v1/people", json={"name": ""}).json()["detail"]["code"] == "invalid_name"
    assert c.patch(f"/api/v1/people/{pid}", json={"name": "Raymond"}).json()["name"] == "Raymond"
    assert c.patch(f"/api/v1/people/{pid}", json={}).status_code == 400
    aid = c.post("/api/v1/accounts", json={"name": "Ray WS", "person_id": pid}).json()["id"]
    people = c.get("/api/v1/people").json()
    assert people["count"] == 1 and people["items"][0]["accounts_count"] == 1
    assert c.delete(f"/api/v1/people/{pid}").json()["deleted"] is True
    assert db.accounts[aid]["person_id"] is None   # account survives
    assert c.delete(f"/api/v1/people/{pid}").status_code == 404


def test_people_are_user_scoped(monkeypatch, db):
    pid = db.insert_person(U2, {"name": "Theirs"})["id"]
    c = _client(monkeypatch)
    assert c.get("/api/v1/people").json()["count"] == 0
    assert c.patch(f"/api/v1/people/{pid}", json={"name": "Mine"}).status_code == 404
    assert c.delete(f"/api/v1/people/{pid}").status_code == 404
    r = c.post("/api/v1/accounts", json={"name": "A", "person_id": pid})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_person"


# ---------------------------------------------------------------- accounts

def test_no_default_accounts(monkeypatch, db):
    body = _client(monkeypatch).get("/api/v1/accounts").json()
    assert body["items"] == [] and body["count"] == 0


def test_account_crud(monkeypatch, db):
    db.settings[U1] = {"user_id": U1, "home_currency": "USD"}
    c = _client(monkeypatch)
    r = c.post("/api/v1/accounts", json={"name": "Wealthsimple", "cash_balance": "1250.5"})
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["currency"] == "USD" and a["cash_balance"] == 1250.5 and a["account_type"] is None
    assert c.post("/api/v1/accounts", json={"name": "wealthsimple"}).json()["detail"]["code"] == "duplicate_name"
    assert c.post("/api/v1/accounts", json={"name": "Q", "currency": "dollars"}).json()["detail"]["code"] \
        == "invalid_currency"
    assert c.post("/api/v1/accounts", json={"name": "Q", "cash_balance": "lots"}).json()["detail"]["code"] \
        == "invalid_cash_balance"
    r = c.patch(f"/api/v1/accounts/{a['id']}", json={"name": "WS", "currency": "cad"})
    assert r.status_code == 200 and r.json()["name"] == "WS" and r.json()["currency"] == "CAD"
    assert c.patch(f"/api/v1/accounts/{uuid.uuid4()}", json={"name": "Z"}).status_code == 404
    assert c.delete(f"/api/v1/accounts/{a['id']}").json()["deleted"] is True
    assert c.get("/api/v1/accounts").json()["count"] == 0


def test_accounts_are_user_scoped(monkeypatch, db):
    theirs = db.add_account(U2, "Theirs")
    c = _client(monkeypatch)
    assert c.get("/api/v1/accounts").json()["count"] == 0
    assert c.patch(f"/api/v1/accounts/{theirs}", json={"name": "Mine"}).status_code == 404
    assert c.delete(f"/api/v1/accounts/{theirs}").status_code == 404


# ---------------------------------------------------------------- account type gating

@pytest.mark.parametrize("level,country,atype,status,code", [
    ("free", "CA", "TFSA", 403, "upgrade_required"),
    ("premium", "BR", "TFSA", 422, "account_type_unavailable"),
    ("premium", None, "OTHER", 422, "account_type_unavailable"),
    ("premium", "US", "TFSA", 422, "invalid_account_type"),
    ("premium", "CA", "ROTH_IRA", 422, "invalid_account_type"),
    ("premium", "CA", "LIRA", 422, "invalid_account_type"),
    ("premium", "CA", "tfsa", 201, None),
    ("premium", "CA", "RESP", 201, None),
    ("premium", "US", "401K", 201, None),
    ("owner", "US", "ROTH_IRA", 201, None),
    ("free", "BR", None, 201, None),
])
def test_account_type_rules(monkeypatch, db, level, country, atype, status, code):
    db.settings[U1] = {"user_id": U1, "country": country}
    r = _client(monkeypatch, level).post("/api/v1/accounts", json={"name": "Acct", "account_type": atype})
    assert r.status_code == status, r.text
    if code:
        assert r.json()["detail"]["code"] == code
    else:
        assert r.json()["account_type"] == (atype.upper() if atype else None)


def test_account_type_patch_gated_and_clearable(monkeypatch, db):
    db.settings[U1] = {"user_id": U1, "country": "CA"}
    aid = db.add_account(U1, "WS", account_type="TFSA")
    c = _client(monkeypatch, "free")
    assert c.patch(f"/api/v1/accounts/{aid}", json={"account_type": "RRSP"}).status_code == 403
    r = c.patch(f"/api/v1/accounts/{aid}", json={"account_type": None})
    assert r.status_code == 200 and r.json()["account_type"] is None


def test_account_types_meta(monkeypatch, db):
    db.settings[U1] = {"user_id": U1, "country": "US"}
    meta = _client(monkeypatch).get("/api/v1/accounts").json()["account_types"]
    assert meta["country"] == "US" and "ROTH_IRA" in meta["types"] and "TFSA" not in meta["types"]


# ---------------------------------------------------------------- delete with holdings

def test_delete_account_with_holdings_409(monkeypatch, db):
    aid = db.add_account(U1, "WS")
    db.add_holding(U1, "NVDA", account_id=aid, shares=2)
    r = _client(monkeypatch).delete(f"/api/v1/accounts/{aid}")
    assert r.status_code == 409 and r.json()["detail"] == {**r.json()["detail"], "code": "account_has_holdings",
                                                           "holdings": 1}
    assert aid in db.accounts


def test_delete_account_move_to_merges_same_symbol(monkeypatch, db):
    src, dst = db.add_account(U1, "Old"), db.add_account(U1, "New")
    h1 = db.add_holding(U1, "NVDA", account_id=src, shares=10, avg_cost=100)
    h2 = db.add_holding(U1, "NVDA", account_id=dst, shares=30, avg_cost=200)
    h3 = db.add_holding(U1, "XEQT.TO", account_id=src, shares=5)
    db.txs["t1"] = {"id": "t1", "user_id": U1, "account_id": src}
    c = _client(monkeypatch)
    assert c.delete(f"/api/v1/accounts/{src}?move_to={src}").json()["detail"]["code"] == "invalid_move_to"
    r = c.delete(f"/api/v1/accounts/{src}?move_to={dst}")
    assert r.status_code == 200, r.text
    assert r.json()["moved_holdings"] == 1 and r.json()["merged_holdings"] == 1
    assert h1 not in db.holdings
    assert db.holdings[h2]["shares"] == 40 and db.holdings[h2]["avg_cost"] == 175
    assert db.holdings[h3]["account_id"] == dst
    assert db.txs["t1"]["account_id"] == dst and src not in db.accounts


def test_delete_account_force_unassigns(monkeypatch, db):
    aid = db.add_account(U1, "WS")
    hid = db.add_holding(U1, "NVDA", account_id=aid, shares=1)
    r = _client(monkeypatch).delete(f"/api/v1/accounts/{aid}?force=true")
    assert r.status_code == 200 and r.json()["moved_to"] is None
    assert db.holdings[hid]["account_id"] is None


def test_merge_holding_math():
    m = accounts_service.merge_holding
    assert m({"shares": 10, "avg_cost": 10}, {"shares": 10, "avg_cost": 20}) == \
        {"shares": 20, "avg_cost": 15, "notes": None}
    assert m({"shares": 10, "avg_cost": 10}, {"shares": 5})["avg_cost"] is None   # unknown lot cost
    assert m({}, {"shares": 5, "avg_cost": 3, "notes": "n"}) == {"shares": 5, "avg_cost": 3, "notes": "n"}


# ---------------------------------------------------------------- holdings in two accounts

def test_same_stock_in_two_accounts(monkeypatch, db):
    ws, qt = db.add_account(U1, "Wealthsimple"), db.add_account(U1, "Questrade")
    pid = db.insert_person(U1, {"name": "Ray"})["id"]
    db.accounts[qt]["person_id"] = pid
    c = _client(monkeypatch)
    r = c.post("/api/v1/holdings", json={"items": [
        {"symbol": "NVDA", "account_id": ws, "shares": 10, "avg_cost": 100},
        {"symbol": "NVDA", "account_id": qt, "shares": 5, "avg_cost": 120},
    ]})
    assert r.status_code == 201, r.text
    assert r.json()["created"] == 2
    assert {i["account_name"] for i in r.json()["items"]} == {"Wealthsimple", "Questrade"}
    # upsert again into WS only updates that lot
    r = c.post("/api/v1/holdings", json={"items": [{"symbol": "NVDA", "account_id": ws, "shares": 12}]})
    assert r.json()["created"] == 0 and r.json()["updated"] == 1
    lots = sorted((h["account_id"], h["shares"]) for h in db.holdings.values())
    assert lots == sorted([(ws, 12), (qt, 5)])
    assert all("account" not in h for h in db.holdings.values())   # deprecated column not written
    body = c.get("/api/v1/holdings").json()
    assert body["count"] == 2
    assert c.get(f"/api/v1/holdings?account_id={ws}").json()["count"] == 1
    by_person = c.get(f"/api/v1/holdings?person_id={pid}").json()
    assert by_person["count"] == 1 and by_person["items"][0]["account_name"] == "Questrade"
    assert by_person["filter"]["person_id"] == pid


def test_second_account_does_not_use_a_slot(monkeypatch, db):
    a, b = db.add_account(U1, "A"), db.add_account(U1, "B")
    for i in range(5):
        db.add_holding(U1, f"S{i}", account_id=a)
    c = _client(monkeypatch, "free")   # 5 slots, all used
    assert c.post("/api/v1/holdings", json={"items": [{"symbol": "S1", "account_id": b}]}).status_code == 201
    r = c.post("/api/v1/holdings", json={"items": [{"symbol": "NEW", "account_id": b}]})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "slot_limit"


def test_holding_with_foreign_account_422(monkeypatch, db):
    theirs = db.add_account(U2, "Theirs")
    r = _client(monkeypatch).post("/api/v1/holdings", json={"items": [{"symbol": "NVDA", "account_id": theirs}]})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_account"


def test_patch_moves_holding_between_accounts(monkeypatch, db):
    a, b = db.add_account(U1, "A"), db.add_account(U1, "B")
    h1 = db.add_holding(U1, "NVDA", account_id=a, shares=1)
    db.add_holding(U1, "NVDA", account_id=b, shares=2)
    h3 = db.add_holding(U1, "AAPL", account_id=a, shares=3)
    c = _client(monkeypatch)
    r = c.patch(f"/api/v1/holdings/{h1}", json={"account_id": b})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "duplicate_holding"
    r = c.patch(f"/api/v1/holdings/{h3}", json={"account_id": b})
    assert r.status_code == 200 and r.json()["account_name"] == "B" and db.holdings[h3]["account_id"] == b
    r = c.patch(f"/api/v1/holdings/{h3}", json={"account_id": None})
    assert r.status_code == 200 and db.holdings[h3]["account_id"] is None
    # the legacy field alone is ignored -> nothing to update
    assert c.patch(f"/api/v1/holdings/{h3}", json={"account": "TFSA"}).status_code == 400


def test_dividend_calendar_merges_accounts():
    from app.services.holdings_service import merge_by_symbol
    rows = merge_by_symbol([
        {"symbol": "ENB.TO", "shares": 10, "avg_cost": 50, "account_id": "a"},
        {"symbol": "ENB.TO", "shares": 30, "avg_cost": 60, "account_id": "b"},
        {"symbol": "NVDA", "shares": 1, "account_id": "a"},
    ])
    enb = next(r for r in rows if r["symbol"] == "ENB.TO")
    assert len(rows) == 2 and enb["shares"] == 40 and enb["avg_cost"] == 57.5 and enb["account_id"] is None
