"""Transactions (migration 013): CRUD validation, CSV import dry run /
per-row errors / real import / batch undo, number and date parsing, template."""

import uuid
from datetime import date

import pytest

from app.api.v1 import transactions as tx_api
from app.services import transactions_service as svc
from tests.portfolio_fakes import U1, U2, FakePortfolioDB, make_client


@pytest.fixture
def db(monkeypatch):
    return FakePortfolioDB(monkeypatch)


def _client(monkeypatch, level="free"):
    return make_client(monkeypatch, tx_api.router, level=level)


def _post(c, **body):
    return c.post("/api/v1/transactions", json=body)


# ---------------------------------------------------------------- CRUD

def test_503_before_migration(monkeypatch, db):
    db.missing = True
    c = _client(monkeypatch)
    assert c.get("/api/v1/transactions").json()["detail"]["code"] == "migration_required"
    r = _post(c, type="deposit", trade_date="2026-01-02", amount=100)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "migration_required"


def test_create_buy_defaults(monkeypatch, db):
    aid = db.add_account(U1, "WS", currency="CAD")
    c = _client(monkeypatch)
    r = _post(c, type="buy", trade_date="2026-01-16", symbol="xeqt.to", quantity=100, price=31.25, account_id=aid)
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["symbol"] == "XEQT.TO" and t["amount"] == 3125 and t["currency"] == "CAD" and t["fee"] == 0
    assert t["source"] == "manual" and t["account_name"] == "WS" and "user_id" not in t
    # currency from the listing when there is no account
    t2 = _post(c, type="buy", trade_date="2026-01-16", symbol="NVDA", quantity=1, amount=100).json()
    assert t2["currency"] == "USD" and t2["price"] == 100


@pytest.mark.parametrize("body,code", [
    ({"type": "swap", "trade_date": "2026-01-02"}, "invalid_type"),
    ({"type": "buy", "trade_date": "2099-01-02", "symbol": "NVDA", "quantity": 1, "price": 1}, "date_in_future"),
    ({"type": "buy", "symbol": "NVDA", "quantity": 1, "price": 1}, "invalid_date"),
    ({"type": "buy", "trade_date": "2026-01-02", "quantity": 1, "price": 1}, "symbol_required"),
    ({"type": "buy", "trade_date": "2026-01-02", "symbol": "BAD!!", "quantity": 1, "price": 1}, "invalid_symbol"),
    ({"type": "buy", "trade_date": "2026-01-02", "symbol": "NVDA", "price": 1}, "quantity_required"),
    ({"type": "sell", "trade_date": "2026-01-02", "symbol": "NVDA", "quantity": 1}, "price_required"),
    ({"type": "deposit", "trade_date": "2026-01-02", "symbol": "NVDA", "amount": 5}, "symbol_not_allowed"),
    ({"type": "deposit", "trade_date": "2026-01-02"}, "amount_required"),
    ({"type": "dividend", "trade_date": "2026-01-02", "symbol": "ENB.TO"}, "amount_required"),
    ({"type": "split", "trade_date": "2026-01-02", "symbol": "NVDA", "quantity": 1}, "invalid_split_ratio"),
    ({"type": "fee", "trade_date": "2026-01-02", "amount": 5, "currency": "dollars"}, "invalid_currency"),
    ({"type": "fee", "trade_date": "2026-01-02", "amount": 5, "note": "x" * 501}, "note_too_long"),
    ({"type": "fee", "trade_date": "2026-01-02", "amount": 5, "account_id": str(uuid.uuid4())}, "unknown_account"),
])
def test_create_validation(monkeypatch, db, body, code):
    r = _post(_client(monkeypatch), **body)
    assert r.status_code == 422, r.text
    d = r.json()["detail"]
    assert d["code"] == code and d["message"] and any(e["code"] == code for e in d["errors"])


def test_other_types_null_irrelevant_fields(monkeypatch, db):
    c = _client(monkeypatch)
    t = _post(c, type="deposit", trade_date="2026-01-02", amount=-500, quantity=3, price=2).json()
    assert t["amount"] == 500 and t["quantity"] is None and t["price"] is None and t["symbol"] is None
    s = _post(c, type="split", trade_date="2026-01-02", symbol="NVDA", quantity=10, amount=5).json()
    assert s["quantity"] == 10 and s["amount"] is None


def test_list_filters_and_paging(monkeypatch, db):
    c = _client(monkeypatch)
    aid = db.add_account(U1, "WS")
    for i, (typ, sym) in enumerate([("buy", "NVDA"), ("buy", "AAPL"), ("dividend", "NVDA"), ("deposit", None)]):
        body = {"type": typ, "trade_date": f"2026-01-0{i + 1}", "amount": 10, "account_id": aid}
        if sym:
            body.update(symbol=sym, quantity=1, price=10)
        assert _post(c, **body).status_code == 201
    db.insert_transactions(U2, [{"type": "deposit", "trade_date": "2026-01-01", "amount": 1}])
    all_ = c.get("/api/v1/transactions").json()
    assert all_["total"] == 4 and all_["items"][0]["trade_date"] == "2026-01-04"
    assert c.get("/api/v1/transactions?symbol=nvda").json()["total"] == 2
    assert c.get("/api/v1/transactions?type=buy").json()["total"] == 2
    assert c.get("/api/v1/transactions?from=2026-01-02&to=2026-01-03").json()["total"] == 2
    assert c.get(f"/api/v1/transactions?account_id={aid}").json()["total"] == 4
    page = c.get("/api/v1/transactions?limit=3&offset=0").json()
    assert page["count"] == 3 and page["has_more"] is True
    assert c.get("/api/v1/transactions?type=bogus").status_code == 422


def test_patch_revalidates_and_recomputes(monkeypatch, db):
    c = _client(monkeypatch)
    t = _post(c, type="buy", trade_date="2026-01-02", symbol="NVDA", quantity=2, price=10).json()
    r = c.patch(f"/api/v1/transactions/{t['id']}", json={"quantity": 3})
    assert r.status_code == 200 and r.json()["amount"] == 30
    r = c.patch(f"/api/v1/transactions/{t['id']}", json={"type": "deposit"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "symbol_not_allowed"
    assert c.patch(f"/api/v1/transactions/{t['id']}", json={}).status_code == 400
    assert c.patch(f"/api/v1/transactions/{uuid.uuid4()}", json={"note": "x"}).status_code == 404


def test_delete_scoped(monkeypatch, db):
    theirs = db.insert_transactions(U2, [{"type": "deposit", "trade_date": "2026-01-01", "amount": 1}])[0]["id"]
    c = _client(monkeypatch)
    assert c.delete(f"/api/v1/transactions/{theirs}").status_code == 404
    mine = _post(c, type="deposit", trade_date="2026-01-02", amount=5).json()["id"]
    assert c.delete(f"/api/v1/transactions/{mine}").json() == {"deleted": True, "id": mine}


# ---------------------------------------------------------------- parsing

@pytest.mark.parametrize("s,dc,expected", [
    ("1234.56", False, 1234.56), ("1,234.56", False, 1234.56), ("1.234,56", False, 1234.56),
    ("12,5", False, 12.5), ("1,234", False, 1234.0), ("0,500", False, 0.5), ("1,234", True, 1.234),
    ("1.500", True, 1500.0), ("0.005", True, 0.005), ("$1 000", False, 1000.0), ("C$ 12.30", False, 12.3),
    ("(12.5)", False, -12.5), ("", False, None), ("1.234.567", False, 1234567.0),
])
def test_parse_number(s, dc, expected):
    assert svc.parse_number(s, dc) == expected


@pytest.mark.parametrize("s", ["abc", "1.2.3,4,5", "12a"])
def test_parse_number_rejects(s):
    with pytest.raises(ValueError):
        svc.parse_number(s)


@pytest.mark.parametrize("s,order,expected", [
    ("2026-09-30", "dmy", date(2026, 9, 30)), ("2026/09/30", "mdy", date(2026, 9, 30)),
    ("2026-09-30T10:00:00", "dmy", date(2026, 9, 30)), ("30/09/2026", "dmy", date(2026, 9, 30)),
    ("09/30/2026", "mdy", date(2026, 9, 30)), ("05.04.26", "dmy", date(2026, 4, 5)),
    ("Sep 30, 2026", "dmy", date(2026, 9, 30)), ("30 September 2026", "mdy", date(2026, 9, 30)),
])
def test_parse_date(s, order, expected):
    assert svc.parse_date(s, order) == expected


def test_infer_date_order():
    assert svc.infer_date_order(["01/02/2026", "30/01/2026"]) == "dmy"
    assert svc.infer_date_order(["01/02/2026", "01/30/2026"]) == "mdy"
    assert svc.infer_date_order(["01/02/2026", "2026-05-05"]) is None
    assert svc.infer_date_order(["13/01/2026", "01/13/2026"]) == "conflict"


# ---------------------------------------------------------------- CSV import

CSV = """date,type,symbol,quantity,price,amount,currency,fee,account,note
2026-01-15,deposit,,,,5000,CAD,0,Wealthsimple,First deposit
2026-01-16,buy,XEQT.TO,100,31.25,3125,CAD,0,wealthsimple,
2026-03-31,dividend,XEQT.TO,100,,18.40,CAD,0,Wealthsimple,Quarterly
"""


def _import(c, text, **params):
    q = "&".join(f"{k}={str(v).lower()}" for k, v in params.items())
    return c.post(f"/api/v1/transactions/import?{q}", files={"file": ("t.csv", text.encode(), "text/csv")})


def test_import_dry_run_writes_nothing(monkeypatch, db):
    db.add_account(U1, "Wealthsimple")
    r = _import(_client(monkeypatch), CSV, dry_run=True)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["dry_run"] is True and b["summary"]["valid"] == 3 and b["summary"]["invalid"] == 0
    assert b["summary"]["by_type"] == {"deposit": 1, "buy": 1, "dividend": 1}
    assert b["summary"]["date_range"] == {"from": "2026-01-15", "to": "2026-03-31"}
    assert b["rows"][1]["data"]["account_name"] == "Wealthsimple" and b["rows"][1]["line"] == 3
    assert db.txs == {}


def test_import_unknown_account_and_row_errors(monkeypatch, db):
    text = CSV + "2026-04-01,buy,NVDA,abc,10,,USD,0,Questrade,\n2026-04-02,sell,,1,10,,USD,0,,\n"
    c = _client(monkeypatch)
    b = _import(c, text, dry_run=True).json()
    assert b["summary"]["valid"] == 0 and b["summary"]["invalid"] == 5
    codes = {e["code"] for row in b["errors"] for e in row["errors"]}
    assert {"unknown_account", "invalid_number", "symbol_required"} <= codes
    r = _import(c, text, dry_run=False)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "import_has_errors" and db.txs == {}


def test_import_create_missing_accounts_and_undo(monkeypatch, db):
    c = _client(monkeypatch)
    dry = _import(c, CSV, dry_run=True, create_missing_accounts=True).json()
    assert dry["summary"]["accounts_to_create"] == ["Wealthsimple"] and not db.accounts
    r = _import(c, CSV, dry_run=False, create_missing_accounts=True)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["imported"] == 3 and b["skipped"] == 0 and [a["name"] for a in b["accounts_created"]] == ["Wealthsimple"]
    aid = b["accounts_created"][0]["id"]
    assert len(db.accounts) == 1
    assert all(t["account_id"] == aid and t["source"] == "csv" and t["import_batch_id"] == b["import_batch_id"]
               for t in db.txs.values())
    # undo
    manual = _post(c, type="deposit", trade_date="2026-05-01", amount=1).json()["id"]
    u = c.delete(f"/api/v1/transactions/import/{b['import_batch_id']}")
    assert u.json() == {"deleted": 3, "import_batch_id": b["import_batch_id"]}
    assert list(db.txs) == [manual]
    assert c.delete(f"/api/v1/transactions/import/{b['import_batch_id']}").status_code == 404


def test_import_skip_errors(monkeypatch, db):
    db.add_account(U1, "Wealthsimple")
    text = CSV + "2026-04-01,buy,BAD!!,1,10,,USD,0,,\n"
    b = _import(_client(monkeypatch), text, dry_run=False, skip_errors=True).json()
    assert b["imported"] == 3 and b["skipped"] == 1 and b["errors"][0]["line"] == 5


def test_import_semicolon_decimal_comma_and_dmy(monkeypatch, db):
    text = ("date;type;symbol;quantity;price;amount;currency;fee;account;note\n"
            "31/01/2026;compra;PETR4.SA;1.500;36,50;;BRL;4,90;;\n"
            "01/02/2026;dividend;PETR4.SA;;;120,00;BRL;;;\n")
    b = _import(_client(monkeypatch), text, dry_run=True).json()
    assert b["summary"]["valid"] == 2 and b["summary"]["date_format"] == "dmy" and b["summary"]["delimiter"] == ";"
    buy = b["rows"][0]["data"]
    assert buy["type"] == "buy" and buy["quantity"] == 1500 and buy["price"] == 36.5 and buy["fee"] == 4.9
    assert buy["amount"] == 54750 and b["rows"][1]["data"]["trade_date"] == "2026-02-01"


def test_import_ambiguous_dates_use_country(monkeypatch, db):
    text = "date,type,amount\n01/02/2026,deposit,10\n"
    c = _client(monkeypatch)
    assert _import(c, text, dry_run=True).json()["rows"][0]["data"]["trade_date"] == "2026-02-01"
    db.settings[U1] = {"user_id": U1, "country": "US"}
    assert _import(c, text, dry_run=True).json()["rows"][0]["data"]["trade_date"] == "2026-01-02"
    assert _import(c, text, dry_run=True, date_format="dmy").json()["rows"][0]["data"]["trade_date"] == "2026-02-01"
    bad = "date,type,amount\n13/01/2026,deposit,10\n01/13/2026,deposit,10\n"
    assert _import(c, bad, dry_run=True).json()["detail"]["code"] == "ambiguous_dates"


@pytest.mark.parametrize("text,code", [
    ("", "empty_file"),
    ("symbol,amount\nNVDA,1\n", "invalid_header"),
    ("date,type\n", "nothing_to_import"),
])
def test_import_file_errors(monkeypatch, db, text, code):
    r = _import(_client(monkeypatch), text or " ", dry_run=True)
    assert r.status_code == 422 and r.json()["detail"]["code"] == code


def test_import_rejects_more_than_5000_rows(monkeypatch, db):
    text = "date,type,amount\n" + "2026-01-01,deposit,1\n" * 5001
    r = _import(_client(monkeypatch), text, dry_run=True)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "too_many_rows"


def test_import_rejects_big_file(monkeypatch, db):
    r = _import(_client(monkeypatch), "x" * (svc.MAX_IMPORT_BYTES + 10), dry_run=True)
    assert r.status_code == 413 and r.json()["detail"]["code"] == "file_too_large"


def test_import_is_all_or_nothing_on_db_failure(monkeypatch, db):
    db.add_account(U1, "Wealthsimple")
    calls = {"n": 0}
    real = db.insert_transactions

    def flaky(uid, rows, chunk=500):
        calls["n"] += 1
        real(uid, rows[:1])
        raise RuntimeError("connection reset")
    monkeypatch.setattr("app.db.queries.insert_transactions", flaky)
    r = _import(_client(monkeypatch), CSV, dry_run=False)
    assert r.status_code == 503 and db.txs == {}


def test_template(monkeypatch, db):
    c = _client(monkeypatch)
    r = c.get("/api/v1/transactions/template")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[0] == "date,type,symbol,quantity,price,amount,currency,fee,account,note" and len(lines) == 4
    j = c.get("/api/v1/transactions/template?format=json").json()
    assert j["columns"][0] == "date" and len(j["examples"]) == 3
    # no real bank or broker names in what users see
    assert all(row[8] == "Signa Bank" for row in j["examples"]) and "Wealthsimple" not in r.text
    assert j["column_help"]["account"] == "Your account's name, e.g. Signa Bank"
    # the template itself imports cleanly
    b = _import(c, r.text, dry_run=True, create_missing_accounts=True).json()
    assert b["summary"]["valid"] == 3
