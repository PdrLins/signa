"""Goals (migration 026): CRUD, free limit, progress."""

import uuid

import pytest

from app.api.v1 import goals as api
from app.services import dividend_calendar
from app.services import goals as svc
from tests.portfolio_fakes import U1, FakePortfolioDB, make_client
from tests.test_portfolio_home import _setup


class Store:
    def __init__(self, monkeypatch):
        self.rows: dict[str, dict] = {}
        monkeypatch.setattr(svc, "list_goals", lambda uid: [r for r in self.rows.values() if r["user_id"] == uid])
        real_create = svc.create

        def insert(user, body, home):
            row = svc.clean(body)
            limit = svc.limit_for(user.get("access_level") or "free")
            if limit is not None and len(svc.list_goals(user["user_id"])) >= limit:
                return real_create(user, body, home)   # raises goal_limit (list_goals is faked)
            gid = str(uuid.uuid4())
            self.rows[gid] = {**row, "id": gid, "user_id": user["user_id"], "currency": home,
                              "title": row.get("title"), "target_date": row.get("target_date")}
            return dict(self.rows[gid])
        monkeypatch.setattr(svc, "create", insert)

        def update(uid, gid, body):
            data = svc.clean(body, partial=True)
            if gid not in self.rows:
                from app.core.api_errors import api_error
                raise api_error("goal_not_found", "Goal not found.", 404)
            self.rows[gid].update(data)
            return dict(self.rows[gid])
        monkeypatch.setattr(svc, "update", update)


@pytest.fixture
def env(monkeypatch):
    db = FakePortfolioDB(monkeypatch)
    db.settings[U1] = {"user_id": U1, "home_currency": "CAD"}
    _setup(db)

    async def profiles(symbols, fetch=None):
        return {"XEQT.TO": {"pays_dividend": True, "annual_rate": 1.2, "currency": "CAD"}}
    monkeypatch.setattr(dividend_calendar, "fetch_profiles", profiles)
    return Store(monkeypatch)


def test_progress_math():
    g = {"target": 1000}
    assert svc.progress(g, 250, False) == {"current": 250, "pct": 25.0, "remaining": 750, "reached": False,
                                           "estimated": False, "yield_pct": None, "avg_monthly_deposit": None}
    assert svc.progress(g, 1500, False)["pct"] == 100.0 and svc.progress(g, 1500, False)["reached"] is True
    assert svc.progress(g, None, True)["pct"] is None


@pytest.mark.parametrize("body,code", [
    ({"kind": "car", "target": 1}, "invalid_kind"),
    ({"kind": "portfolio_value", "target": 0}, "invalid_target"),
    ({"kind": "portfolio_value", "target": "x"}, "invalid_target"),
    ({"kind": "portfolio_value", "target": 5, "title": "t" * 61}, "invalid_title"),
    ({"kind": "portfolio_value", "target": 5, "target_date": "next year"}, "invalid_target_date"),
])
def test_validation(body, code):
    with pytest.raises(Exception) as e:
        svc.clean(body)
    assert e.value.detail["code"] == code


def test_free_user_one_goal_with_progress(monkeypatch, env):
    c = make_client(monkeypatch, api.router, level="free")
    r = c.post("/api/v1/goals", json={"kind": "portfolio_value", "target": 2260, "title": " House "})
    assert r.status_code == 201, r.text
    g = r.json()
    assert g["currency"] == "CAD" and g["title"] == "House"
    assert g["progress"]["current"] == pytest.approx(1130) and g["progress"]["pct"] == 50.0
    r2 = c.post("/api/v1/goals", json={"kind": "monthly_income", "target": 100})
    assert r2.status_code == 403 and r2.json()["detail"]["code"] == "goal_limit"
    assert r2.json()["detail"]["upgrade"] == {"feature": "feature.unlimited_goals", "plan": "premium"}
    body = c.get("/api/v1/goals").json()
    assert body["count"] == 1 and body["limit"] == 1 and body["currency"] == "CAD"


def test_premium_income_goal(monkeypatch, env):
    c = make_client(monkeypatch, api.router, level="premium")
    c.post("/api/v1/goals", json={"kind": "portfolio_value", "target": 5000})
    r = c.post("/api/v1/goals", json={"kind": "monthly_income", "target": 10})
    assert r.status_code == 201
    assert r.json()["progress"]["current"] == pytest.approx(10 * 1.2 / 12)   # 10 XEQT.TO x 1.20/yr / 12
    gid = r.json()["id"]
    p = c.patch(f"/api/v1/goals/{gid}", json={"target": 2})
    assert p.json()["progress"]["reached"] is False and p.json()["target"] == 2
    assert c.get("/api/v1/goals").json()["limit"] is None


# ---------------------------------------------------------------- projections (migration 034)

@pytest.mark.parametrize("field,value", [
    ("monthly_contribution", -1), ("monthly_contribution", "x"), ("monthly_contribution", True),
    ("expected_return_pct", 31), ("expected_return_pct", -20.5), ("expected_return_pct", "high"),
])
def test_projection_fields_are_validated(field, value):
    with pytest.raises(Exception) as e:
        svc.clean({"kind": "portfolio_value", "target": 5, field: value})
    assert e.value.detail["code"] == "invalid_input" and e.value.detail["field"] == field


def test_projection_fields_saved_and_cleared():
    row = svc.clean({"kind": "portfolio_value", "target": 5, "monthly_contribution": "500",
                     "expected_return_pct": -20})
    assert row["monthly_contribution"] == 500 and row["expected_return_pct"] == -20
    assert svc.clean({"monthly_contribution": None}, partial=True) == {"monthly_contribution": None}
    assert svc.clean({"expected_return_pct": 0}, partial=True) == {"expected_return_pct": 0}


def test_average_monthly_deposit():
    from datetime import date
    today = date(2026, 10, 10)
    txs = [{"type": "buy", "trade_date": "2025-06-01", "amount": 100, "currency": "CAD"},   # history > 12 months
           {"type": "deposit", "trade_date": "2025-12-01", "amount": 6000, "currency": "CAD"},
           {"type": "deposit", "trade_date": "2026-05-01", "amount": 100, "currency": "USD"},   # 140 CAD at 1.4
           {"type": "withdrawal", "trade_date": "2026-09-01", "amount": 1340, "currency": "CAD"},
           {"type": "deposit", "trade_date": "2025-01-01", "amount": 99999, "currency": "CAD"}]  # too old
    assert svc.avg_monthly_deposit(txs, "CAD", 1.4, today) == 400.0   # (6000 + 140 - 1340) / 12
    recent = [{"type": "deposit", "trade_date": "2026-09-20", "amount": 500, "currency": "CAD"}]
    assert svc.avg_monthly_deposit(recent, "CAD", 1.4, today) is None   # under 2 months of history
    assert svc.avg_monthly_deposit([], "CAD", 1.4, today) is None
    buys_only = [{"type": "buy", "trade_date": "2026-01-01", "amount": 100, "currency": "CAD"}]
    assert svc.avg_monthly_deposit(buys_only, "CAD", 1.4, today) is None


def test_goal_progress_has_projection_inputs(monkeypatch, env):
    c = make_client(monkeypatch, api.router, level="free")
    g = c.post("/api/v1/goals", json={"kind": "portfolio_value", "target": 2260, "monthly_contribution": 500,
                                       "expected_return_pct": 6}).json()
    assert g["monthly_contribution"] == 500 and g["expected_return_pct"] == 6
    # 10 XEQT.TO x C$1.20 a year over the holdings' market value (C$960: the C$1,130 total minus cash)
    assert g["progress"]["yield_pct"] == pytest.approx(12 / 960 * 100, abs=0.01)
    assert g["progress"]["avg_monthly_deposit"] is None   # no transactions
    p = c.patch(f"/api/v1/goals/{g['id']}", json={"monthly_contribution": None})
    assert p.status_code == 200 and p.json()["monthly_contribution"] is None
    assert c.patch(f"/api/v1/goals/{g['id']}", json={"expected_return_pct": 99}).status_code == 422


def test_before_migration_034_writes_drop_the_projection_fields(monkeypatch):
    from app.core.api_errors import MigrationRequired
    from app.db import queries
    monkeypatch.setattr(queries, "_missing_optional", set())
    calls = []

    def run(row):
        calls.append(dict(row))
        if "monthly_contribution" in row:
            raise MigrationRequired("column goals.monthly_contribution does not exist")
        return "ok"
    monkeypatch.setattr(queries, "_missing_schema", lambda e: isinstance(e, MigrationRequired))
    assert svc._write(run, {"target": 5, "monthly_contribution": 1}) == "ok" and calls[-1] == {"target": 5}
    with pytest.raises(Exception) as e:
        svc._write(run, {"monthly_contribution": 1})
    assert e.value.detail["code"] == "migration_required"
