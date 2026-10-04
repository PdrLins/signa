"""My holdings — position math (CAD conversion, concentration)."""

import pytest

from app.core.config import settings
from app.services import holdings_service as hs


def _h(hid, sym, price, shares=None, cost=None, ccy=None, **extra):
    return {"id": hid, "symbol": sym, "currency": ccy, "shares": shares, "avg_cost": cost,
            "holding_status": {"price": price} if price is not None else None, **extra}


# ── currency ──

def test_to_cad():
    assert hs.to_cad(100.0, "CAD", None) == 100.0
    assert hs.to_cad(100.0, "USD", 1.40) == pytest.approx(140.0)
    assert hs.to_cad(100.0, "USD", None) is None


def test_holding_currency_from_suffix():
    assert hs.holding_currency({"symbol": "XEQT.TO"}) == "CAD"
    assert hs.holding_currency({"symbol": "NVDA"}) == "USD"
    assert hs.holding_currency({"symbol": "NVDA", "currency": "CAD"}) == "CAD"


# ── portfolio math ──

def test_portfolio_math_cad_totals_and_weights():
    rows = [
        _h("a", "XEQT.TO", 30.0, shares=100, cost=25.0, ccy="CAD"),     # 3000 CAD, book 2500
        _h("b", "NVDA", 100.0, shares=10, cost=50.0, ccy="USD"),        # 1000 USD = 1400 CAD, book 700 CAD
        _h("c", "COST", 900.0, ccy="USD"),                              # no shares
    ]
    per, tot = hs.portfolio_math(rows, usdcad=1.4, max_weight_pct=50)
    assert per["a"]["value_cad"] == 3000.0
    assert per["b"]["value"] == 1000.0 and per["b"]["value_cad"] == 1400.0
    assert per["b"]["unrealized"] == 500.0 and per["b"]["unrealized_pct"] == 100.0
    assert per["c"]["value"] is None and per["c"]["weight_pct"] is None
    assert tot["value_cad"] == 4400.0
    assert tot["book_value_cad"] == pytest.approx(3200.0)
    assert tot["unrealized_cad"] == pytest.approx(1200.0)
    assert per["a"]["weight_pct"] == pytest.approx(68.18, abs=0.01)
    assert per["a"]["overweight"] is True and per["b"]["overweight"] is False
    assert tot["count_with_shares"] == 2 and tot["currency"] == "CAD"


def test_portfolio_math_uses_setting_default(monkeypatch):
    monkeypatch.setattr(settings, "holdings_max_weight_pct", 15.0)
    rows = [_h("a", "A.TO", 10.0, shares=20, ccy="CAD"), _h("b", "B.TO", 10.0, shares=80, ccy="CAD")]
    per, tot = hs.portfolio_math(rows, None)
    assert per["a"]["weight_pct"] == 20.0 and per["a"]["overweight"] is True
    assert tot["max_weight_pct"] == 15.0


def test_portfolio_math_missing_fx_excludes_usd_and_flags():
    rows = [_h("a", "A.TO", 10.0, shares=10, ccy="CAD"), _h("b", "NVDA", 100.0, shares=1, ccy="USD")]
    per, tot = hs.portfolio_math(rows, None)
    assert per["b"]["value"] == 100.0 and per["b"]["value_cad"] is None
    assert tot["fx_missing"] is True and tot["value_cad"] == 100.0
    assert per["a"]["weight_pct"] == 100.0


def test_portfolio_math_without_any_shares():
    per, tot = hs.portfolio_math([_h("a", "XEQT.TO", 30.0)], 1.4)
    assert tot["value_cad"] is None and per["a"]["weight_pct"] is None


def test_portfolio_math_in_brl_home_with_b3_and_us(monkeypatch):
    from app.services import price_cache
    monkeypatch.setattr(price_cache, "_download_fx", lambda codes: {"BRL": 5.0, "EUR": 0.9})
    quotes = {"PETR4.SA": {"price": 38.0, "currency": "BRL"}, "AAPL": {"price": 200.0, "currency": "USD"}}
    rows = [_h("a", "PETR4.SA", None, shares=100, cost=30.0, ccy="BRL"),
            _h("b", "AAPL", None, shares=10, cost=150.0, ccy="USD")]
    per, tot = hs.portfolio_math(rows, 1.4, quotes=quotes, home="BRL")
    assert per["a"]["value_home"] == 3800.0 and per["b"]["value_home"] == 10000.0   # 2000 USD x 5
    assert tot["home_currency"] == "BRL" and tot["value_home"] == 13800.0 and tot["fx_missing"] is False
    assert per["b"]["weight_pct"] == round(10000 / 13800 * 100, 2)
    assert tot["unrealized_home"] == 800.0 + 2500.0
    assert per["a"]["value_cad"] == round(3800 / 5 * 1.4, 2)        # BRL -> USD -> CAD (scope rate)


def test_unpriceable_currency_flags_fx_missing(monkeypatch):
    quotes = {"SAP.DE": {"price": 200.0, "currency": "EUR"}}
    per, tot = hs.portfolio_math([_h("a", "SAP.DE", None, shares=1, ccy="EUR")], 1.4, quotes=quotes, home="CAD")
    assert per["a"]["value_home"] is None and tot["fx_missing"] is True and tot["value_home"] is None
