"""Dividends logged automatically (migration 032, app/services/auto_dividends.py)."""

from datetime import date

from app.services import auto_dividends as ad

TODAY = date(2026, 10, 20)
PROFILE = {"ENB.TO": {"pays_dividend": True, "currency": "CAD",
                      "upcoming": [{"ex_date": "2026-11-14", "pay_date": "2026-12-01"}],   # gap 17 days
                      "last_payments": [{"ex_date": "2026-09-20", "amount": 0.97},          # paid 2026-10-07
                                        {"ex_date": "2026-06-14", "amount": 0.94}]}}       # too old


def _holding(created="2026-01-10", shares=100, account="a1"):
    return {"user_id": "u1", "symbol": "ENB.TO", "account_id": account, "shares": shares,
            "created_at": f"{created}T12:00:00+00:00"}


def test_records_a_recent_payment_from_the_holding():
    rows, remove = ad.plan([_holding()], [], PROFILE, TODAY, set())
    assert remove == [] and len(rows) == 1
    r = rows[0]
    assert (r["symbol"], r["type"], r["trade_date"], r["quantity"], r["amount"], r["currency"], r["source"]) == \
        ("ENB.TO", "dividend", "2026-10-07", 100, 97.0, "CAD", "auto")
    assert r["auto_ref"] == "auto:a1:ENB.TO:2026-09-20"


def test_no_back_fill_for_a_holding_added_after_the_ex_date():
    assert ad.plan([_holding(created="2026-09-25")], [], PROFILE, TODAY, set())[0] == []


def test_shares_come_from_trades_when_there_are_any():
    trades = [{"type": "buy", "symbol": "ENB.TO", "account_id": "a1", "trade_date": "2026-03-01", "quantity": 40},
              {"type": "buy", "symbol": "ENB.TO", "account_id": "a1", "trade_date": "2026-09-25", "quantity": 60}]
    rows, _ = ad.plan([_holding()], trades, PROFILE, TODAY, set())
    assert rows[0]["quantity"] == 40 and rows[0]["amount"] == 38.8   # the later buy missed the ex-date


def test_real_records_win_and_dismissed_or_known_are_skipped():
    real = [{"type": "dividend", "symbol": "ENB.TO", "account_id": "a1", "trade_date": "2026-10-09",
             "source": "csv", "amount": 95}]
    assert ad.plan([_holding()], real, PROFILE, TODAY, set())[0] == []
    assert ad.plan([_holding()], [], PROFILE, TODAY, {"auto:a1:ENB.TO:2026-09-20"})[0] == []
    known = [{"id": "t1", "type": "dividend", "symbol": "ENB.TO", "account_id": "a1", "trade_date": "2026-10-07",
              "source": "auto", "auto_ref": "auto:a1:ENB.TO:2026-09-20"}]
    assert ad.plan([_holding()], known, PROFILE, TODAY, set())[0] == []


def test_an_estimate_is_removed_when_the_real_record_arrives():
    txs = [{"id": "t1", "type": "dividend", "symbol": "ENB.TO", "account_id": "a1", "trade_date": "2026-10-07",
            "source": "auto", "auto_ref": "auto:a1:ENB.TO:2026-09-20"},
           {"id": "t2", "type": "dividend", "symbol": "ENB.TO", "account_id": "a1", "trade_date": "2026-10-08",
            "source": "manual", "amount": 96}]
    rows, remove = ad.plan([_holding()], txs, PROFILE, TODAY, set())
    assert rows == [] and remove == ["t1"]


def test_future_payments_wait_until_paid():
    early = date(2026, 10, 1)   # ex-date passed, pay date (10-07) not yet
    assert ad.plan([_holding()], [], PROFILE, early, set())[0] == []


# ---------------------------------------------------------------- user actions

def test_deleting_an_estimate_remembers_it_and_editing_confirms_it(monkeypatch):
    from app.services import transactions_service as ts
    from tests.portfolio_fakes import U1, FakePortfolioDB
    db = FakePortfolioDB(monkeypatch)
    db.settings[U1] = {"user_id": U1, "home_currency": "CAD"}
    a = db.add_account(U1, "Main", currency="CAD", cash_balance=0)
    [row] = db.insert_transactions(U1, [{"account_id": a, "symbol": "ENB.TO", "type": "dividend",
                                         "trade_date": "2026-09-10", "quantity": 100, "price": 0.97, "amount": 97,
                                         "currency": "CAD", "fee": 0, "note": ad.NOTE, "source": "auto",
                                         "auto_ref": "auto:x:ENB.TO:2026-09-20", "import_batch_id": None}])
    dismissed = []
    monkeypatch.setattr("app.db.queries.add_dismissed_auto_ref", lambda uid, ref: dismissed.append(ref))
    out = ts.update_transaction(U1, row["id"], {"amount": 82.45})
    assert out["source"] == "manual" and out["estimated"] is False
    db.txs[row["id"]]["source"] = "auto"
    ts.delete_transaction(U1, row["id"])
    assert dismissed == ["auto:x:ENB.TO:2026-09-20"]


def test_profile_has_the_switch(monkeypatch):
    from app.services import profile_service as ps
    assert ps.DEFAULTS["auto_dividends"] is True
    clean = ps.validate_update({"user_id": "u", "access_level": "free"}, None, {"auto_dividends": False})
    assert clean == {"auto_dividends": False}
