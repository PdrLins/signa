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
                                           "estimated": False}
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
