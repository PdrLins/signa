"""Position derivation from transactions (average-cost method)."""

import pytest

from app.services.portfolio_ledger import derive_positions


def tx(typ, d, sym=None, qty=None, price=None, amount=None, fee=0, acct="A", ccy="USD", **kw):
    return {"type": typ, "trade_date": d, "symbol": sym, "quantity": qty, "price": price, "amount": amount,
            "fee": fee, "account_id": acct, "currency": ccy, **kw}


def _pos(result, sym, acct="A"):
    return next(p for p in result["positions"] if p["symbol"] == sym and p["account_id"] == acct)


def test_buys_average_cost_with_fees():
    r = derive_positions([
        tx("buy", "2026-01-02", "NVDA", 10, 100, fee=5),
        tx("buy", "2026-02-02", "NVDA", 10, 120, fee=5),
    ])
    p = _pos(r, "NVDA")
    assert p["shares"] == 20 and p["cost_basis"] == 2210 and p["avg_cost"] == pytest.approx(110.5)
    assert p["realized_pl"] == 0 and p["fees"] == 10 and p["open"] is True


def test_partial_sell_realizes_against_average():
    r = derive_positions([
        tx("buy", "2026-01-02", "NVDA", 10, 100),
        tx("buy", "2026-01-03", "NVDA", 10, 200),
        tx("sell", "2026-02-01", "NVDA", 5, 180, fee=2),
    ])
    p = _pos(r, "NVDA")
    # avg 150; proceeds 900 - fee 2 - cost 750 = 148
    assert p["shares"] == 15 and p["avg_cost"] == pytest.approx(150)
    assert p["realized_pl"] == pytest.approx(148) and p["cost_basis"] == pytest.approx(2250)


def test_full_sell_closes_and_oversell_warns():
    r = derive_positions([
        tx("buy", "2026-01-02", "AAPL", 2, 100),
        tx("sell", "2026-01-05", "AAPL", 3, 120),
    ])
    p = _pos(r, "AAPL")
    assert p["shares"] == 0 and p["avg_cost"] is None and p["open"] is False
    assert p["realized_pl"] == pytest.approx(2 * 120 - 200)
    assert r["warnings"][0]["code"] == "oversold"


def test_split_keeps_cost_basis():
    r = derive_positions([
        tx("buy", "2026-01-02", "NVDA", 10, 1000),
        tx("split", "2026-06-10", "NVDA", 10),
        tx("sell", "2026-07-01", "NVDA", 50, 120),
    ])
    p = _pos(r, "NVDA")
    # after split: 100 sh @ 100; sell 50 @ 120 -> +1000
    assert p["shares"] == 50 and p["avg_cost"] == pytest.approx(100) and p["realized_pl"] == pytest.approx(1000)


def test_reverse_split():
    p = _pos(derive_positions([tx("buy", "2026-01-02", "X", 100, 1), tx("split", "2026-02-01", "X", 0.1)]), "X")
    assert p["shares"] == 10 and p["avg_cost"] == pytest.approx(10)


def test_dividends_per_year_and_cash():
    r = derive_positions([
        tx("deposit", "2025-12-01", amount=5000, ccy="CAD"),
        tx("buy", "2025-12-02", "ENB.TO", 100, 40, fee=1, ccy="CAD"),
        tx("dividend", "2025-12-31", "ENB.TO", 100, amount=94, ccy="CAD"),
        tx("dividend", "2026-03-31", "ENB.TO", 100, amount=96.5, ccy="CAD"),
        tx("withdrawal", "2026-04-01", amount=100, ccy="CAD"),
        tx("fee", "2026-04-02", amount=10, ccy="CAD"),
    ])
    p = _pos(r, "ENB.TO")
    assert p["dividends_by_year"] == {2025: 94, 2026: 96.5} and p["dividends_total"] == 190.5
    assert p["cost_basis"] == 4001   # dividends don't touch cost
    cash = {(c["account_id"], c["currency"]): c["cash"] for c in r["cash"]}
    assert cash[("A", "CAD")] == pytest.approx(5000 - 4001 + 190.5 - 100 - 10)


def test_positions_are_per_account_and_order_by_date():
    r = derive_positions([
        tx("sell", "2026-03-01", "NVDA", 5, 150, acct="B"),   # listed first but happens later
        tx("buy", "2026-01-01", "NVDA", 10, 100, acct="A"),
        tx("buy", "2026-01-01", "NVDA", 10, 110, acct="B"),
    ])
    assert _pos(r, "NVDA", "A")["shares"] == 10
    b = _pos(r, "NVDA", "B")
    assert b["shares"] == 5 and b["realized_pl"] == pytest.approx(200) and not r["warnings"]


def test_amount_used_as_gross_when_present_and_symbol_fee():
    r = derive_positions([
        tx("buy", "2026-01-02", "VFV.TO", 10, None, amount=1000, ccy="CAD"),
        tx("fee", "2026-01-03", "VFV.TO", amount=5, ccy="CAD"),
    ])
    p = _pos(r, "VFV.TO")
    assert p["avg_cost"] == pytest.approx(100) and p["realized_pl"] == -5 and p["fees"] == 5


def test_mixed_currency_warning_and_empty_input():
    r = derive_positions([tx("buy", "2026-01-02", "X", 1, 1, ccy="USD"), tx("buy", "2026-01-03", "X", 1, 1, ccy="CAD")])
    assert r["warnings"][0]["code"] == "mixed_currency"
    assert derive_positions([]) == {"positions": [], "cash": [], "warnings": []}
