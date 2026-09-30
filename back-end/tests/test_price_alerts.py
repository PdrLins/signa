"""Price alerts (migration 015): limits, crossing logic, currency, deactivation,
the quotes-job hook and the Coming up feed items. DB and quotes are faked."""

from datetime import datetime, timezone

import pytest

from app.api.v1 import alerts as alerts_api
from app.api.v1 import events as events_api
from app.db import queries
from app.services import dividends, events_feed
from app.services import price_alerts as pa
from app.services import quotes as quotes_svc
from tests.portfolio_fakes import U1, U2, FakePortfolioDB, make_client

pytestmark = pytest.mark.real_access
NOW = datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(monkeypatch):
    d = FakePortfolioDB(monkeypatch)
    d.quotes["ENB.TO"] = {"symbol": "ENB.TO", "price": 69.0, "prev_close": 68.0, "currency": "CAD",
                          "as_of": "2026-09-30T14:00:00+00:00"}
    d.quotes["NVDA"] = {"symbol": "NVDA", "price": 100.0, "prev_close": 99.0, "currency": "USD"}
    return d


def _client(monkeypatch, level="free", uid=U1):
    return make_client(monkeypatch, alerts_api.router, events_api.router, level=level, uid=uid)


# ---------------------------------------------------------------- pure crossing logic

@pytest.mark.parametrize("direction,target,price,crossed", [
    ("above", 100, 100.0, True), ("above", 100, 99.99, False), ("above", 100, 120, True),
    ("below", 50, 50.0, True), ("below", 50, 50.01, False), ("below", 50, 12, True),
    ("above", 100, None, False),
])
def test_is_crossed(direction, target, price, crossed):
    assert pa.is_crossed(direction, target, price) is crossed


def test_distance_pct():
    assert pa.distance_pct(50, 69) == -27.54
    assert pa.distance_pct(80, 64) == 25.0
    assert pa.distance_pct(50, None) is None


def test_evaluate_converts_usd_cad_and_skips_unconvertible():
    alerts = [
        {"id": "1", "symbol": "NVDA", "direction": "above", "target_price": 135, "currency": "CAD", "active": True},
        {"id": "2", "symbol": "NVDA", "direction": "above", "target_price": 145, "currency": "CAD", "active": True},
        {"id": "3", "symbol": "SAP.DE", "direction": "below", "target_price": 1000, "currency": "USD", "active": True},
        {"id": "4", "symbol": "NVDA", "direction": "below", "target_price": 200, "currency": "USD", "active": False},
    ]
    quotes = {"NVDA": {"price": 100.0, "currency": "USD"}, "SAP.DE": {"price": 200.0, "currency": "EUR"}}
    fired = pa.evaluate(alerts, quotes, usdcad=1.4, now=NOW)
    assert [(f["id"], f["last_price"]) for f in fired] == [("1", 140.0)]   # 100 USD = 140 CAD >= 135
    assert fired[0]["triggered_at"] == NOW.isoformat()
    assert pa.evaluate(alerts[:1], quotes, usdcad=None) == []               # no FX rate: never guess


# ---------------------------------------------------------------- API: CRUD + limits

def test_create_list_and_distance(monkeypatch, db):
    c = _client(monkeypatch)
    r = c.post("/api/v1/alerts", json={"symbol": "enb.to", "direction": "below", "target_price": 50,
                                       "note": " buy more "})
    assert r.status_code == 201, r.text
    a = r.json()
    assert (a["symbol"], a["direction"], a["target_price"], a["currency"]) == ("ENB.TO", "below", 50.0, "CAD")
    assert a["note"] == "buy more" and a["active"] is True and a["triggered_at"] is None
    assert a["current_price"] == 69.0 and a["distance_pct"] == -27.54
    body = c.get("/api/v1/alerts?symbol=ENB.TO").json()
    assert body["count"] == 1 and body["active"] == 1 and body["limit"] == 3 and body["remaining"] == 2
    assert c.get("/api/v1/alerts?symbol=NVDA").json()["count"] == 0
    # another user sees nothing and can't touch it
    other = _client(monkeypatch, uid=U2)
    assert other.get("/api/v1/alerts").json()["count"] == 0
    assert other.delete(f"/api/v1/alerts/{a['id']}").json()["detail"]["code"] == "alert_not_found"


def test_free_limit_is_three_active_with_upgrade_hint(monkeypatch, db):
    c = _client(monkeypatch)
    for target in (60, 55, 50):
        assert c.post("/api/v1/alerts", json={"symbol": "ENB.TO", "direction": "below",
                                              "target_price": target}).status_code == 201
    r = c.post("/api/v1/alerts", json={"symbol": "NVDA", "direction": "above", "target_price": 150})
    assert r.status_code == 403
    d = r.json()["detail"]
    assert d["code"] == "alert_limit" and d["limit"] == 3 and d["active"] == 3
    assert d["upgrade"] == {"feature": "feature.unlimited_alerts", "plan": "premium"}
    # a fired (inactive) alert frees a slot; re-arming it counts again
    first = next(iter(db.alerts.values()))
    first.update({"active": False, "triggered_at": NOW.isoformat(), "last_price": 59.0})
    assert c.post("/api/v1/alerts", json={"symbol": "NVDA", "direction": "above",
                                          "target_price": 150}).status_code == 201
    r = c.patch(f"/api/v1/alerts/{first['id']}", json={"active": True})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "alert_limit"


@pytest.mark.parametrize("level", ["premium", "owner"])
def test_premium_and_owner_are_unlimited(monkeypatch, db, level):
    c = _client(monkeypatch, level)
    for i in range(5):
        assert c.post("/api/v1/alerts", json={"symbol": "NVDA", "direction": "above",
                                              "target_price": 150 + i}).status_code == 201
    assert c.get("/api/v1/alerts").json()["limit"] is None


def test_validation_and_already_crossed(monkeypatch, db):
    c = _client(monkeypatch)
    bad = [({"symbol": "NVDA", "direction": "sideways", "target_price": 1}, "invalid_direction"),
           ({"symbol": "NVDA", "direction": "above", "target_price": -5}, "invalid_price"),
           ({"symbol": "NVDA", "direction": "above", "target_price": "x"}, "invalid_price"),
           ({"symbol": "NVDA", "direction": "above", "target_price": 150, "currency": "US"}, "invalid_currency"),
           ({"symbol": "BAD$$", "direction": "above", "target_price": 150}, "invalid_symbol")]
    for body, code in bad:
        r = c.post("/api/v1/alerts", json=body)
        assert r.status_code == 422 and r.json()["detail"]["code"] == code, (body, r.text)
    r = c.post("/api/v1/alerts", json={"symbol": "NVDA", "direction": "above", "target_price": 90})
    assert r.status_code == 422
    assert {"code": "already_crossed", "current_price": 100.0, "currency": "USD"}.items() <= r.json()["detail"].items()
    # a CAD target on a USD listing compares in CAD (100 USD = 140 CAD)
    r = c.post("/api/v1/alerts", json={"symbol": "NVDA", "direction": "below", "target_price": 150,
                                       "currency": "CAD"})
    assert r.status_code == 422 and r.json()["detail"]["current_price"] == 140.0


def test_patch_rearms_and_delete(monkeypatch, db):
    c = _client(monkeypatch)
    a = c.post("/api/v1/alerts", json={"symbol": "NVDA", "direction": "above", "target_price": 150}).json()
    db.alerts[a["id"]].update({"active": False, "triggered_at": NOW.isoformat(), "last_price": 151.0})
    r = c.patch(f"/api/v1/alerts/{a['id']}", json={"active": True, "target_price": 175})
    assert r.status_code == 200, r.text
    assert r.json()["active"] is True and r.json()["triggered_at"] is None and r.json()["target_price"] == 175
    assert c.patch(f"/api/v1/alerts/{a['id']}", json={}).json()["detail"]["code"] == "nothing_to_update"
    assert c.delete(f"/api/v1/alerts/{a['id']}").json() == {"deleted": True, "id": a["id"]}
    assert c.delete(f"/api/v1/alerts/{a['id']}").status_code == 404


def test_migration_missing_is_503(monkeypatch, db):
    db.missing = True
    r = _client(monkeypatch).get("/api/v1/alerts")
    assert r.status_code == 503
    assert r.json()["detail"] == {"code": "migration_required", "migration": pa.MIGRATION,
                                  "message": r.json()["detail"]["message"]}


def test_writes_need_action_alerts_edit(monkeypatch, db):
    from app.core import access
    defaults = {k: v[0] for k, v in access.FEATURE_CATALOG.items()}
    monkeypatch.setattr(access, "get_feature_levels", lambda: {**defaults, "action.alerts.edit": "premium"})
    c = _client(monkeypatch)
    assert c.get("/api/v1/alerts").status_code == 200
    r = c.post("/api/v1/alerts", json={"symbol": "NVDA", "direction": "above", "target_price": 150})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "upgrade_required"


# ---------------------------------------------------------------- quotes job: fire + deactivate

def test_quotes_job_fires_deactivates_once_and_refreshes_alert_symbols(monkeypatch, db):
    up = db.insert_price_alert(U1, {"symbol": "NVDA", "direction": "above", "target_price": 105, "currency": "USD"})
    down = db.insert_price_alert(U1, {"symbol": "NVDA", "direction": "below", "target_price": 90, "currency": "USD"})
    other = db.insert_price_alert(U2, {"symbol": "ENB.TO", "direction": "above", "target_price": 80,
                                       "currency": "CAD"})
    monkeypatch.setattr(queries, "get_follow_rows", lambda: [])   # NVDA is followed only through the alerts
    monkeypatch.setattr(queries, "get_users_activity", lambda: [
        {"id": U1, "access_level": "free", "last_seen_at": NOW.isoformat()},
        {"id": U2, "access_level": "free", "last_seen_at": NOW.isoformat()}])
    monkeypatch.setattr(quotes_svc, "_last_refresh", {})
    refreshed: list[list[str]] = []
    live = {"NVDA": {"symbol": "NVDA", "price": 107.5, "currency": "USD"},
            "ENB.TO": {"symbol": "ENB.TO", "price": 70.0, "currency": "CAD"}}
    monkeypatch.setattr(quotes_svc, "refresh_quotes",
                        lambda syms: refreshed.append(list(syms)) or {s: live[s] for s in syms})

    r = quotes_svc.refresh_followed_quotes(force=True, now=NOW)
    assert refreshed == [["ENB.TO", "NVDA"]]
    assert r["alerts_triggered"] == 1
    assert db.alerts[up["id"]]["active"] is False and db.alerts[up["id"]]["last_price"] == 107.5
    assert db.alerts[up["id"]]["triggered_at"] == NOW.isoformat()
    assert db.alerts[down["id"]]["active"] is True and db.alerts[other["id"]]["active"] is True

    # a second run never fires the same alert again
    r = quotes_svc.refresh_followed_quotes(force=True, now=NOW)
    assert "alerts_triggered" not in r and db.alerts[up["id"]]["last_price"] == 107.5
    # inactive alerts no longer pull their symbol into the refresh
    assert {row["symbol"] for row in pa.alert_follow_rows()} == {"NVDA", "ENB.TO"}


def test_evaluate_refreshed_before_migration_is_a_noop(monkeypatch):
    def boom(symbols):
        raise RuntimeError('relation "public.price_alerts" does not exist')
    monkeypatch.setattr(queries, "get_active_price_alerts", boom)
    assert pa.evaluate_refreshed({"NVDA": {"price": 1.0}}) == 0


# ---------------------------------------------------------------- Coming up feed

def test_triggered_alerts_show_in_upcoming_as_recent(monkeypatch, db):
    from datetime import date
    monkeypatch.setattr(dividends, "today_et", lambda: date(2026, 9, 30))
    events_feed.clear_cache()

    async def no_profiles(symbols):
        return {s: None for s in symbols}

    async def no_earnings(item, today):
        return None
    monkeypatch.setattr(events_feed, "fetch_profiles", no_profiles)
    monkeypatch.setattr(events_feed, "fetch_earnings", no_earnings)
    monkeypatch.setattr(events_feed, "fetch_upgrades", lambda sym: [])

    fresh = db.insert_price_alert(U1, {"symbol": "NVDA", "direction": "above", "target_price": 105,
                                       "currency": "USD"})
    db.alerts[fresh["id"]].update({"active": False, "triggered_at": datetime.now(timezone.utc).isoformat(),
                                   "last_price": 107.5})
    old = db.insert_price_alert(U1, {"symbol": "NVDA", "direction": "below", "target_price": 50, "currency": "USD"})
    db.alerts[old["id"]].update({"active": False, "triggered_at": "2026-01-01T15:00:00+00:00", "last_price": 49})

    body = _client(monkeypatch).get("/api/v1/events/upcoming?days=30").json()
    assert body["sources"]["price_alerts"] == "ok"
    items = [i for i in body["items"] if i["type"] == "price_alert"]
    assert len(items) == 1
    it = items[0]
    assert it["recent"] is True and it["symbol"] == "NVDA" and it["alert_id"] == fresh["id"]
    assert (it["direction"], it["target_price"], it["last_price"], it["currency"]) == ("above", 105.0, 107.5, "USD")

    # an account scope has no price alerts (like the watchlist)
    acc = db.add_account(U1, "TFSA")
    scoped = _client(monkeypatch).get(f"/api/v1/events/upcoming?account_id={acc}").json()
    assert "price_alerts" not in scoped["sources"]
    assert not [i for i in scoped["items"] if i["type"] == "price_alert"]
