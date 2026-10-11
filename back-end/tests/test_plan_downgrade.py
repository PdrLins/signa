"""Premium -> Free: what's above the free limit is kept, can be deleted, can't be
edited. And the owner's "View as" (X-View-As) reaches every Premium gate."""

import pytest

from app.api.v1 import goals as goals_api
from app.services import goals as goals_svc
from app.services import price_alerts
from tests.portfolio_fakes import U1, make_client
from tests import test_goals

env = test_goals.env   # goals in memory + a portfolio (fixture)


# ---------------------------------------------------------------- goals

def test_goals_above_the_limit_are_kept_deletable_not_editable(monkeypatch, env):
    premium = make_client(monkeypatch, goals_api.router, level="premium")
    ids = [premium.post("/api/v1/goals", json={"kind": "portfolio_value", "target": t}).json()["id"]
           for t in (1000, 2000)]
    free = make_client(monkeypatch, goals_api.router, level="free")
    listed = free.get("/api/v1/goals").json()
    assert listed["count"] == 2 and listed["limit"] == 1   # both kept
    r = free.patch(f"/api/v1/goals/{ids[0]}", json={"monthly_contribution": 100})
    assert r.status_code == 403
    d = r.json()["detail"]
    assert d["code"] == "goal_limit" and d["limit"] == 1 and d["count"] == 2 and d["upgrade"]["plan"] == "premium"
    # deleting brings the user back within the limit: editing works again
    monkeypatch.setattr(goals_svc, "delete", lambda uid, gid: env.rows.pop(gid) and {"deleted": True, "id": gid})
    assert free.delete(f"/api/v1/goals/{ids[1]}").status_code == 200
    assert free.patch(f"/api/v1/goals/{ids[0]}", json={"target": 1500}).status_code == 200


def test_create_limit_error_carries_the_count(monkeypatch, env):
    free = make_client(monkeypatch, goals_api.router, level="free")
    free.post("/api/v1/goals", json={"kind": "portfolio_value", "target": 1000})
    d = free.post("/api/v1/goals", json={"kind": "portfolio_value", "target": 5}).json()["detail"]
    assert d["code"] == "goal_limit" and d["limit"] == 1 and d["count"] == 1


# ---------------------------------------------------------------- alerts

@pytest.fixture
def alerts(monkeypatch):
    from app.db import queries
    rows = {f"a{i}": {"id": f"a{i}", "symbol": "AAPL", "kind": "price", "direction": "above", "target_price": 500,
                      "currency": "USD", "active": True} for i in range(5)}
    monkeypatch.setattr(queries, "get_price_alert", lambda aid, uid: dict(rows[aid]) if aid in rows else None)
    monkeypatch.setattr(queries, "count_active_price_alerts", lambda uid: sum(r["active"] for r in rows.values()))

    def update(aid, uid, data):
        rows[aid].update(data)
        return dict(rows[aid])
    monkeypatch.setattr(queries, "update_price_alert", update)
    monkeypatch.setattr(price_alerts, "_quotes_for", lambda syms: ({}, 1.4))
    return rows


def test_alerts_above_the_limit_can_be_turned_off_not_edited(alerts):
    free = {"user_id": U1, "access_level": "free"}   # 5 active, free limit 3
    with pytest.raises(Exception) as e:
        price_alerts.update_alert(free, "a0", {"target_price": 600})
    assert e.value.detail["code"] == "alert_limit" and e.value.detail["active"] == 5
    # turning alerts off is allowed (it's how to get back within the limit)
    price_alerts.update_alert(free, "a0", {"active": False})
    price_alerts.update_alert(free, "a1", {"active": False})
    assert price_alerts.update_alert(free, "a2", {"target_price": 600})["target_price"] == 600   # 3 active now
    premium = {"user_id": U1, "access_level": "premium"}
    alerts["a0"]["active"] = alerts["a1"]["active"] = True
    assert price_alerts.update_alert(premium, "a3", {"target_price": 700})["target_price"] == 700


# ---------------------------------------------------------------- View as

def test_view_as_free_reaches_every_premium_gate(monkeypatch, env):
    """An owner with dev tools sending X-View-As: free gets the free answers."""
    from app.api.v1 import auth, goals, portfolio_home, widgets
    from app.core.config import settings

    monkeypatch.setattr(settings, "dev_tools_enabled", True)
    c = make_client(monkeypatch, auth.router, portfolio_home.router, goals.router, widgets.router, level="owner")
    c.headers["X-View-As"] = "free"
    me = c.get("/api/v1/auth/me").json()
    assert me["access_level"] == "free" and me["real_access_level"] == "owner"
    for path, feature in (("/api/v1/portfolio/exposure", "feature.exposure"),
                          ("/api/v1/portfolio/history?range=ALL", "feature.full_history"),
                          ("/api/v1/portfolio/performance?range=5Y", "feature.full_history")):
        r = c.get(path)
        assert r.status_code == 403 and r.json()["detail"]["feature"] == feature, path
    assert c.get("/api/v1/goals").json()["limit"] == goals_svc.FREE_GOALS
    # without the header the same owner gets everything
    del c.headers["X-View-As"]
    assert c.get("/api/v1/auth/me").json()["access_level"] == "owner"
    assert c.get("/api/v1/goals").json()["limit"] is None
