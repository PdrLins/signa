"""Percentage alerts (migration 031): kind percent (N% from when it was set)
and day_move (the day's move reaches N%, once a day, stays active)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.api.v1 import alerts as alerts_api
from app.services import price_alerts as pa
from tests.portfolio_fakes import U1, FakePortfolioDB, make_client

NOW = datetime.now(timezone.utc)


@pytest.fixture
def db(monkeypatch):
    d = FakePortfolioDB(monkeypatch)
    d.quotes["RY.TO"] = {"symbol": "RY.TO", "price": 171.06, "prev_close": 170.0, "change_pct": 0.62,
                         "currency": "CAD", "as_of": NOW.isoformat()}
    return d


def _c(monkeypatch, level="premium"):
    return make_client(monkeypatch, alerts_api.router, level=level)


# ---------------------------------------------------------------- create / list / patch

def test_percent_alert_stores_reference_and_target(monkeypatch, db):
    r = _c(monkeypatch).post("/api/v1/alerts", json={"symbol": "RY.TO", "kind": "percent", "direction": "above",
                                                     "percent": 10})
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["kind"] == "percent" and a["percent"] == 10 and a["reference_price"] == 171.06
    assert a["target_price"] == pytest.approx(188.166) and a["direction"] == "above"
    below = _c(monkeypatch).post("/api/v1/alerts", json={"symbol": "RY.TO", "kind": "percent",
                                                         "direction": "below", "percent": 5}).json()
    assert below["target_price"] == pytest.approx(162.507)


def test_patching_percent_rebases_on_the_current_price(monkeypatch, db):
    c = _c(monkeypatch)
    a = c.post("/api/v1/alerts", json={"symbol": "RY.TO", "kind": "percent", "direction": "above", "percent": 10}).json()
    db.quotes["RY.TO"]["price"] = 180.0
    b = c.patch(f"/api/v1/alerts/{a['id']}", json={"percent": 5}).json()
    assert b["reference_price"] == 180.0 and b["target_price"] == pytest.approx(189.0)
    assert c.patch(f"/api/v1/alerts/{a['id']}", json={"target_price": 200}).json()["detail"]["code"] == "invalid_price"
    assert c.patch(f"/api/v1/alerts/{a['id']}", json={"kind": "price"}).json()["detail"]["code"] == "invalid_kind"


def test_day_move_hidden_from_old_clients_unless_kinds_all(monkeypatch, db):
    c = _c(monkeypatch)
    c.post("/api/v1/alerts", json={"symbol": "RY.TO", "target_price": 200, "direction": "above"})
    d = c.post("/api/v1/alerts", json={"symbol": "RY.TO", "kind": "day_move", "direction": "either", "percent": 5})
    assert d.status_code == 201 and d.json()["target_price"] is None and d.json()["kind"] == "day_move"
    old = c.get("/api/v1/alerts").json()
    assert [a["kind"] for a in old["items"]] == ["price"]
    new = c.get("/api/v1/alerts?kinds=all").json()
    assert sorted(a["kind"] for a in new["items"]) == ["day_move", "price"]
    assert new["active"] == 2   # both count toward the limit


def test_percent_needs_a_current_price(monkeypatch, db):
    db.quotes.pop("RY.TO")
    r = _c(monkeypatch).post("/api/v1/alerts", json={"symbol": "RY.TO", "kind": "percent", "direction": "above",
                                                     "percent": 10})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "data_unavailable"


@pytest.mark.parametrize("body,code", [
    ({"kind": "percent", "direction": "above", "percent": 0.4}, "invalid_percent"),
    ({"kind": "percent", "direction": "below", "percent": 100}, "invalid_percent"),   # below: max 99
    ({"kind": "day_move", "direction": "up", "percent": 101}, "invalid_percent"),
    ({"kind": "day_move", "direction": "above", "percent": 5}, "invalid_direction"),
    ({"kind": "percent", "direction": "either", "percent": 5}, "invalid_direction"),
    ({"kind": "trailing", "direction": "up", "percent": 5}, "invalid_kind"),
    ({"kind": "price", "direction": "above", "target_price": 200, "percent": 5}, "invalid_percent"),
    ({"kind": "percent", "direction": "above", "percent": 5, "target_price": 9}, "invalid_price"),
])
def test_validation(monkeypatch, db, body, code):
    r = _c(monkeypatch).post("/api/v1/alerts", json={"symbol": "RY.TO", **body})
    assert r.status_code == 422 and r.json()["detail"]["code"] == code
    if code == "invalid_percent" and "max" in r.json()["detail"]:
        assert r.json()["detail"]["min"] == 0.5


def test_new_kinds_count_toward_the_free_limit(monkeypatch, db):
    c = _c(monkeypatch, level="free")
    for p in (5, 6, 7):
        assert c.post("/api/v1/alerts", json={"symbol": "RY.TO", "kind": "day_move", "percent": p}).status_code == 201
    r = c.post("/api/v1/alerts", json={"symbol": "RY.TO", "kind": "percent", "direction": "above", "percent": 9})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "alert_limit"


# ---------------------------------------------------------------- firing

def _day_alert(direction="either", pct=5.0, last=None):
    return {"id": "d1", "user_id": U1, "symbol": "RY.TO", "kind": "day_move", "direction": direction,
            "percent": pct, "currency": "CAD", "active": True, "last_triggered_on": last}


@pytest.mark.parametrize("direction,change,fires", [
    ("up", 5.2, True), ("up", -6.0, False), ("down", -5.0, True), ("down", 5.5, False),
    ("either", -5.3, True), ("either", 4.9, False),
])
def test_day_move_directions(direction, change, fires):
    q = {"RY.TO": {"price": 160.0, "change_pct": change, "currency": "CAD", "as_of": NOW.isoformat()}}
    fired = pa.evaluate([_day_alert(direction)], q, None, NOW)
    assert bool(fired) is fires
    if fires:
        assert fired[0]["keep_active"] and fired[0]["change_pct"] == change


def test_day_move_once_a_day_and_never_on_yesterdays_quote():
    today = pa._et_date(NOW).isoformat()
    q = {"RY.TO": {"price": 160.0, "change_pct": -6.0, "currency": "CAD", "as_of": NOW.isoformat()}}
    assert pa.evaluate([_day_alert(last=today)], q, None, NOW) == []          # already fired today
    yesterday = (pa._et_date(NOW) - timedelta(days=1)).isoformat()
    assert pa.evaluate([_day_alert(last=yesterday)], q, None, NOW) != []      # re-armed next session
    old = {"RY.TO": {**q["RY.TO"], "as_of": (NOW - timedelta(days=2)).isoformat()}}
    assert pa.evaluate([_day_alert()], old, None, NOW) == []                  # stale quote: no


def test_day_move_stays_active_after_firing(monkeypatch, db):
    c = _c(monkeypatch)
    a = c.post("/api/v1/alerts", json={"symbol": "RY.TO", "kind": "day_move", "direction": "down", "percent": 5}).json()
    db.quotes["RY.TO"].update(price=160.0, change_pct=-6.1, as_of=NOW.isoformat())
    assert pa.evaluate_refreshed({"RY.TO": db.quotes["RY.TO"]}, NOW) == 1
    assert pa.evaluate_refreshed({"RY.TO": db.quotes["RY.TO"]}, NOW) == 0    # not twice the same day
    row = db.alerts[a["id"]]
    assert row["active"] is True and row["last_change_pct"] == -6.1
    assert row["last_triggered_on"] == pa._et_date(NOW).isoformat()


def test_day_move_created_after_todays_move_starts_tomorrow(monkeypatch, db):
    db.quotes["RY.TO"].update(change_pct=-7.0, as_of=NOW.isoformat())
    a = _c(monkeypatch).post("/api/v1/alerts", json={"symbol": "RY.TO", "kind": "day_move", "percent": 5}).json()
    assert a["last_triggered_on"] == pa._et_date(NOW).isoformat()


def test_percent_alert_fires_and_deactivates_like_price(monkeypatch, db):
    c = _c(monkeypatch)
    a = c.post("/api/v1/alerts", json={"symbol": "RY.TO", "kind": "percent", "direction": "above", "percent": 10}).json()
    db.quotes["RY.TO"]["price"] = 190.0
    assert pa.evaluate_refreshed({"RY.TO": db.quotes["RY.TO"]}, NOW) == 1
    assert db.alerts[a["id"]]["active"] is False


def test_feed_items_carry_the_new_fields():
    rows = [{"id": "d1", "symbol": "RY.TO", "kind": "day_move", "direction": "down", "percent": 5,
             "last_change_pct": -5.3, "currency": "CAD", "triggered_at": NOW.isoformat()}]
    item = pa.feed_items(rows)[0]
    assert item["alert_kind"] == "day_move" and item["change_pct"] == -5.3 and item["target_price"] is None
    assert item["title"] == "RY.TO moved -5.3% today"
