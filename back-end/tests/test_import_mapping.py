"""Importing any bank's or broker's CSV: inspect, suggested mapping, mapped
import (dry run, real, duplicates), saved mappings. Fictional data only."""

import pytest

from app.api.v1 import transactions as tx_api
from app.services import import_mapping as im
from tests.portfolio_fakes import U1, FakePortfolioDB, make_client

LEDGER = """Date,Transaction,Description,Amount,Balance,Currency
2026-05-01,CONT,Contribution,500.00,500.00,CAD
2026-05-03,BUY,SGN-B: bought 10 shares at 31.25,-312.50,187.50,CAD
2026-05-15,DIV,SGN-A: dividend 0.12 per share,1.20,188.70,CAD
2026-05-20,FXFEE,Currency conversion fee,-0.80,187.90,CAD
2026-05-28,SELL,SGN-B: sold 4 shares at 33.00,132.00,319.90,CAD
2026-05-31,BAL,Closing balance,,319.90,CAD
"""
TRADES = """Trade Date,Ticker,Quantity,Price,Commission,Net Amount,Account
05/14/2026,SGN-C,15,42.10,4.95,636.45,Margin
05/20/2026,SGN-D,-5,18.00,4.95,85.05,TFSA
"""
PT = """Data do Pregão;Tipo;Código;Quantidade;Preço;Valor;Corretagem
02/05/2026;Compra;SGNB3;100;12,34;1.234,00;4,90
15/05/2026;Venda;SGNB3;40;13,50;540,00;4,90
20/05/2026;Dividendo;SGNB3;;;22,15;
"""
TITLED = """Signa Bank - Account statement
Generated on 2026-06-01
,,,
Date,Type,Symbol,Quantity,Price,Amount,Currency
2026-05-02,Bought,SGN-E,10,5.50,55.00,USD
2026-05-09,Dividend,SGN-E,,,0.75,USD
"""


@pytest.fixture
def db(monkeypatch):
    d = FakePortfolioDB(monkeypatch)
    d.settings[U1] = {"user_id": U1, "home_currency": "CAD", "country": "CA"}
    monkeypatch.setattr(im, "saved_for", lambda uid, sig: None)
    saved = []
    monkeypatch.setattr(im, "save", lambda uid, sig, headers, name, mapping: saved.append((sig, name, mapping)))
    d.saved_mappings = saved
    im._files.clear()
    return d


def _inspect(c, text: str, encoding="utf-8"):
    r = c.post("/api/v1/transactions/import/inspect", files={"file": ("s.csv", text.encode(encoding), "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()


def _mapping(found: dict, **over) -> dict:
    s = found["suggested"]
    m = {"fields": s["fields"], "date_format": s["date_format"], "decimal": found["decimal"],
         "amount_sign": s["amount_sign"], "extract_from_description": s["extract_from_description"],
         "type_values": {t["value"]: t["suggested"] for t in s["type_values"] if t["suggested"]}}
    m.update(over)
    return m


def test_cash_ledger_with_symbols_in_the_description(monkeypatch, db):
    acct = db.add_account(U1, "Signa Bank", currency="CAD")
    c = make_client(monkeypatch, tx_api.router, level="free")
    found = _inspect(c, LEDGER)
    assert found["file_id"].startswith("imp_") and found["rows"] == 6 and found["signature"]
    assert found["suggested"]["fields"] == {"date": 0, "type": 1, "amount": 3, "currency": 5, "note": 2}
    assert found["suggested"]["amount_sign"] == "signed" and found["suggested"]["extract_from_description"]
    assert {t["value"]: t["suggested"] for t in found["suggested"]["type_values"]}["FXFEE"] is None
    assert "no_symbol_column" in found["warnings"] and found["saved_mapping"] is None
    assert found["columns"][2]["samples"][1] == "SGN-B: bought 10 shares at 31.25"
    mapping = _mapping(found, skip_type_values=["BAL"], account={"fixed_account_id": acct})
    mapping["type_values"]["FXFEE"] = "fee"
    body = {"file_id": found["file_id"], "dry_run": True, "mapping": mapping}
    dry = c.post("/api/v1/transactions/import", json=body).json()
    assert dry["dry_run"] is True and dry["summary"]["valid"] == 5 and dry["summary"]["skipped_by_mapping"] == 1
    rows = {r["data"]["type"]: r["data"] for r in dry["rows"]}
    assert (rows["buy"]["symbol"], rows["buy"]["quantity"], rows["buy"]["price"], rows["buy"]["amount"]) == \
        ("SGN-B", 10, 31.25, 312.5)
    assert (rows["sell"]["quantity"], rows["sell"]["price"]) == (4, 33.0)
    assert rows["dividend"]["symbol"] == "SGN-A" and rows["dividend"]["amount"] == 1.2
    assert rows["deposit"]["amount"] == 500 and rows["fee"]["amount"] == 0.8
    real = c.post("/api/v1/transactions/import", json={**body, "dry_run": False, "save_mapping": {"name": "Ledger"}})
    assert real.status_code == 200 and real.json()["imported"] == 5
    assert db.saved_mappings[0][1] == "Ledger" and db.saved_mappings[0][0] == found["signature"]
    # the file is gone after a real import
    again = c.post("/api/v1/transactions/import", json=body)
    assert again.status_code == 404 and again.json()["detail"]["code"] == "import_file_expired"
    # the same statement again: everything is a duplicate
    found2 = _inspect(c, LEDGER)
    dup = c.post("/api/v1/transactions/import", json={**body, "file_id": found2["file_id"]}).json()
    assert dup["summary"]["duplicates"] == 5 and dup["summary"]["valid"] == 0


def test_trades_file_without_a_type_column(monkeypatch, db):
    c = make_client(monkeypatch, tx_api.router, level="free")
    found = _inspect(c, TRADES)
    s = found["suggested"]
    assert s["fields"] == {"date": 0, "symbol": 1, "quantity": 2, "price": 3, "amount": 5, "fee": 4, "account": 6}
    assert s["date_format"] == "MM/DD/YYYY" and s["type_values"] == [] and found["account_names"] == ["Margin", "TFSA"]
    mapping = _mapping(found, account={"column": 6})
    dry = c.post("/api/v1/transactions/import", json={"file_id": found["file_id"], "mapping": mapping,
                                                      "create_missing_accounts": True}).json()
    by_sym = {r["data"]["symbol"]: r["data"] for r in dry["rows"]}
    assert by_sym["SGN-C"]["type"] == "buy" and by_sym["SGN-C"]["trade_date"] == "2026-05-14"
    assert by_sym["SGN-D"]["type"] == "sell" and by_sym["SGN-D"]["quantity"] == 5   # negative quantity = sale
    assert sorted(dry["summary"]["accounts_to_create"]) == ["Margin", "TFSA"]


def test_portuguese_file_with_semicolons_and_decimal_commas(monkeypatch, db):
    db.add_account(U1, "Signa Bank", currency="BRL")
    c = make_client(monkeypatch, tx_api.router, level="free")
    found = _inspect(c, PT, encoding="latin-1")
    assert (found["delimiter"], found["decimal"], found["encoding"]) == (";", ",", "latin-1")
    s = found["suggested"]
    assert s["date_format"] == "DD/MM/YYYY" and s["fields"]["symbol"] == 2 and s["fields"]["fee"] == 6
    assert [t["suggested"] for t in s["type_values"]] == ["buy", "sell", "dividend"]
    mapping = _mapping(found, default_currency="BRL")
    dry = c.post("/api/v1/transactions/import", json={"file_id": found["file_id"], "mapping": mapping}).json()
    buy = next(r["data"] for r in dry["rows"] if r["data"]["type"] == "buy")
    assert buy["amount"] == 1234.0 and buy["price"] == 12.34 and buy["fee"] == 4.9 and buy["trade_date"] == "2026-05-02"
    assert buy["currency"] == "BRL" and dry["summary"]["valid"] == 3


def test_title_lines_above_the_header(monkeypatch, db):
    c = make_client(monkeypatch, tx_api.router, level="free")
    found = _inspect(c, TITLED)
    assert found["header_row"] == 4 and found["rows"] == 2 and found["columns"][0]["header"] == "Date"
    dry = c.post("/api/v1/transactions/import", json={"file_id": found["file_id"], "mapping": _mapping(found)}).json()
    assert dry["summary"]["valid"] == 2 and {r["data"]["type"] for r in dry["rows"]} == {"buy", "dividend"}


def test_invalid_mappings_and_unknown_types(monkeypatch, db):
    c = make_client(monkeypatch, tx_api.router, level="free")
    found = _inspect(c, LEDGER)
    post = lambda m: c.post("/api/v1/transactions/import", json={"file_id": found["file_id"], "mapping": m})  # noqa: E731
    for m, field in (({"fields": {"type": 1, "amount": 3}}, "fields.date"),
                     ({"fields": {"date": 9, "amount": 3}}, "fields.date"),
                     ({"fields": {"date": 0, "type": 1}}, "fields.amount"),
                     ({"fields": {"date": 0, "amount": 3}, "type_values": {"X": "interest"}}, "type_values")):
        r = post(m)
        assert r.status_code == 422 and r.json()["detail"] == {**r.json()["detail"], "code": "invalid_mapping",
                                                               "field": field}, m
    # FXFEE not mapped: an error naming the value
    m = _mapping(found, skip_type_values=["BAL"])
    rows = post(m).json()["rows"]
    bad = next(r for r in rows if r["status"] == "error")
    assert bad["errors"][0]["code"] == "unknown_type" and "FXFEE" in bad["errors"][0]["message"]
    expired = c.post("/api/v1/transactions/import", json={"file_id": "imp_nope", "mapping": m})
    assert expired.status_code == 404 and expired.json()["detail"]["code"] == "import_file_expired"


def test_a_file_belongs_to_its_user(monkeypatch, db):
    c = make_client(monkeypatch, tx_api.router, level="free")
    found = _inspect(c, LEDGER)
    with pytest.raises(Exception) as e:
        im.get_file("someone-else", found["file_id"])
    assert e.value.detail["code"] == "import_file_expired"


def test_word_lists_and_description_patterns():
    for v, t in (("Achat", "buy"), ("VENTE", "sell"), ("Dividende", "dividend"), ("JCP", "dividend"),
                 ("Juros sobre capital próprio", "dividend"), ("Rendimento", "dividend"), ("Dépôt", "deposit"),
                 ("Retrait", "withdrawal"), ("Saque", "withdrawal"), ("Frais", "fee"), ("Taxa de custódia", "fee"),
                 ("Desdobramento", "split"), ("Intérêts", None), ("Juros", None), ("C", "buy"), ("V", "sell")):
        assert im.suggest_type(v) == t, v
    assert im.extract("SGN-B: achat de 10 actions à 31,25") == {"symbol": "SGN-B", "type": "buy", "quantity": "10",
                                                                 "price": "31,25"}
    assert im.extract("Compra de 100 ações de SGNB3 por 12,34")["symbol"] == "SGNB3"
    assert im.extract("Bought 5 units of SGN-E @ 5.50") == {"type": "buy", "quantity": "5", "symbol": "SGN-E",
                                                            "price": "5.50"}
    assert im.extract("Monthly account fee") == {}
    assert im.suggest_fields(["Data do Pregão", "Código", "Quantité", "Montant"]) == \
        {"date": 0, "symbol": 1, "quantity": 2, "amount": 3}


def test_template_import_skips_duplicates_too(monkeypatch, db):
    db.add_account(U1, "Signa Bank")
    c = make_client(monkeypatch, tx_api.router, level="free")
    csv_text = "date,type,symbol,quantity,price,amount,currency,fee,account,note\n" \
               "2026-01-16,buy,SGNF.TO,100,31.25,3125,CAD,0,Signa Bank,\n"
    up = lambda: c.post("/api/v1/transactions/import?dry_run=false",  # noqa: E731
                        files={"file": ("t.csv", csv_text.encode(), "text/csv")})
    assert up().json()["imported"] == 1
    r = up()
    assert r.status_code == 422 and r.json()["detail"]["summary"]["duplicates"] == 1
