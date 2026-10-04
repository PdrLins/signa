"""Fixed income entered by hand + CDI (migration 032, app/services/fixed_income.py)."""

from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from app.services import fixed_income as fi


def _bdays(start, end):
    d, out = start, []
    while d < end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


START, TODAY = date(2025, 10, 1), date(2026, 10, 1)
CDI = {d: 0.050788 for d in _bdays(START, TODAY + timedelta(days=5))}   # ~13.6% a year


def test_cdi_110_compounds_daily():
    a = {"indexer": "cdi", "rate": 110, "principal": 10000, "start_date": START.isoformat(), "tax_exempt": False}
    v = fi.value(a, TODAY, {"CDI": CDI})
    n = len([d for d in CDI if START <= d < TODAY])
    assert v["value"] == pytest.approx(10000 * (1 + 0.00050788 * 1.10) ** n, abs=0.01)
    assert v["tax_rate"] == 0.175 and v["net_value"] < v["value"] and not v["estimated"]


def test_lci_is_tax_exempt_and_maturity_stops_accrual():
    a = {"indexer": "cdi", "rate": 95, "principal": 5000, "start_date": START.isoformat(),
         "maturity_date": (START + timedelta(days=100)).isoformat(), "tax_exempt": True}
    v = fi.value(a, TODAY, {"CDI": CDI})
    assert v["net_value"] == v["value"] and v["matured"] and v["days"] == 100


def test_prefixado_and_ipca():
    pre = fi.value({"indexer": "pre", "rate": 12, "principal": 1000, "start_date": START.isoformat()},
                   TODAY, {"CDI": CDI})
    n = len([d for d in CDI if START <= d < TODAY])
    assert pre["value"] == pytest.approx(1000 * 1.12 ** (n / 252), abs=0.01)
    ipca = {date(2025, 10, 1): 0.5, date(2025, 11, 1): 0.4, date(2026, 9, 1): 0.3}
    v = fi.value({"indexer": "ipca", "rate": 6, "principal": 1000, "start_date": START.isoformat()},
                 TODAY, {"CDI": CDI, "IPCA": ipca})
    assert v["value"] == pytest.approx(1000 * 1.06 ** (n / 252) * 1.005 * 1.004 * 1.003, abs=0.01)


def test_without_rates_the_value_is_the_principal_and_estimated():
    v = fi.value({"indexer": "cdi", "rate": 100, "principal": 1000, "start_date": START.isoformat()}, TODAY, {})
    assert v["value"] == 1000 and v["estimated"] is True


def test_tax_table():
    assert [fi.tax_rate(d) for d in (30, 181, 400, 800)] == [0.225, 0.20, 0.175, 0.15]


@pytest.mark.parametrize("body,code", [
    ({"kind": "cdb", "indexer": "cdi", "rate": 500, "principal": 1, "start_date": "2026-01-01"}, "invalid_rate"),
    ({"kind": "cdb", "indexer": "cdi", "rate": 100, "principal": 0, "start_date": "2026-01-01"}, "invalid_principal"),
    ({"kind": "poupanca", "indexer": "cdi", "rate": 100, "principal": 1, "start_date": "2026-01-01"}, "invalid_kind"),
    ({"kind": "cdb", "indexer": "cdi", "rate": 100, "principal": 1, "start_date": "2099-01-01"}, "invalid_start_date"),
    ({"kind": "cdb", "indexer": "cdi", "rate": 100, "principal": 1, "start_date": "2026-01-01",
      "maturity_date": "2025-01-01"}, "invalid_maturity_date"),
])
def test_validation(body, code):
    with pytest.raises(HTTPException) as e:
        fi.validate({"name": "CDB Banco X", **body})
    assert e.value.detail["code"] == code


def test_defaults_tesouro_indexer_and_lci_exempt():
    v = fi.validate({"name": "Tesouro Selic 2029", "kind": "tesouro_selic", "rate": 100, "principal": 500,
                     "start_date": "2026-01-02"})
    assert v["indexer"] == "selic" and v["tax_exempt"] is False and v["currency"] == "BRL"
    assert fi.validate({"name": "LCI", "kind": "lci", "indexer": "cdi", "rate": 92, "principal": 500,
                        "start_date": "2026-01-02"})["tax_exempt"] is True


def test_summary_total_includes_fixed_income(monkeypatch):
    from app.services import portfolio_performance as perf
    from tests.portfolio_fakes import U1, FakePortfolioDB
    from app.services import portfolio_context as pc
    db = FakePortfolioDB(monkeypatch)
    db.settings[U1] = {"user_id": U1, "home_currency": "BRL"}
    row = {"id": "f1", "account_id": None, "name": "CDB", "kind": "cdb", "indexer": "pre", "rate": 0,
           "principal": 1000, "currency": "BRL", "start_date": "2026-01-02", "tax_exempt": False}
    monkeypatch.setattr(fi, "rows_for", lambda uid: [row])
    scope = pc.load_scope({"user_id": U1, "access_level": "free"}, None, None, False)
    body = perf.summary_body(scope)
    assert body["fixed_income"]["value"] == 1000 and body["fixed_income"]["count"] == 1
    assert body["total"] == 1000


def test_cdi_benchmark_series(monkeypatch):
    from app.market import br_rates
    from app.services import price_cache
    monkeypatch.setattr(br_rates, "series", lambda name, since: {date(2026, 9, 29): 0.05, date(2026, 9, 30): 0.05})
    s = price_cache.fetch_daily_closes(["CDI"], "1y")["CDI"]
    assert list(s) == [100.0, pytest.approx(100.05)]
