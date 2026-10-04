"""Access levels: feature catalog, slots and route gating."""

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.core import access
from app.core.security import create_access_token
from app.middleware import auth as auth_mw

pytestmark = pytest.mark.real_access

DEFAULTS = {k: v[0] for k, v in access.FEATURE_CATALOG.items()}


@pytest.fixture(autouse=True)
def _catalog(monkeypatch):
    monkeypatch.setattr(access, "get_feature_levels", lambda: dict(DEFAULTS))
    access.clear_access_cache()


def _as(monkeypatch, level: str, bonus: int = 0):
    fn = lambda _uid: {"level": level, "slot_bonus": bonus}  # noqa: E731
    monkeypatch.setattr(access, "get_user_access", fn)
    monkeypatch.setattr(auth_mw, "get_user_access", fn)


# ---------------------------------------------------------------- catalog

def test_levels_are_ordered():
    assert access.level_allows("owner", "premium") and access.level_allows("premium", "free")
    assert not access.level_allows("free", "premium")
    assert access.normalize_level("admin") == "free"  # unknown level -> lowest


def test_unknown_feature_requires_owner():
    assert not access.can("premium", "area.does_not_exist")
    assert access.can("owner", "area.does_not_exist")


def test_free_gets_tracker_not_premium():
    feats = set(access.allowed_features("free"))
    assert {"area.holdings", "action.holdings.edit", "area.watchlist"} <= feats
    assert not feats & {"feature.full_history", "feature.allocation_plan", "area.admin"}
    assert set(access.allowed_features("owner")) == set(DEFAULTS)


def test_catalog_has_no_advisor_features():
    brain = ("area.brain", "area.signals", "area.today", "area.check", "area.positions", "area.performance",
             "area.logs", "area.integrations", "action.check.run", "action.scan.trigger", "system.ai")
    assert not set(brain) & set(DEFAULTS)


def test_db_override_moves_a_feature(monkeypatch):
    monkeypatch.setattr(access, "get_feature_levels", lambda: {**DEFAULTS, "feature.similar_funds": "free"})
    assert access.can("free", "feature.similar_funds")


def test_db_rows_for_unknown_keys_are_ignored(monkeypatch):
    class _Q:
        def table(self, _name):
            return self

        def select(self, _cols):
            return self

        def execute(self):
            rows = [{"key": "area.brain", "min_level": "free"}, {"key": "feature.tax_view", "min_level": "free"}]
            return type("R", (), {"data": rows})()

    monkeypatch.undo()   # the real get_feature_levels (the autouse fixture patches it)
    access.clear_access_cache()
    monkeypatch.setattr("app.db.supabase.get_client", lambda: _Q())
    levels = access.get_feature_levels()
    access.clear_access_cache()
    assert "area.brain" not in levels and levels["feature.tax_view"] == "free"


def test_slot_limits():
    assert access.slot_limit("free") == 15
    assert access.slot_limit("free", 10) == 15   # users.slot_bonus is ignored
    assert access.slot_limit("free", 999) == 15
    # migration 019: +5 per rewarded referral, at most +25
    assert access.slot_limit("free", rewarded_referrals=1) == 20
    assert access.slot_limit("free", rewarded_referrals=5) == 40
    assert access.slot_limit("free", rewarded_referrals=9) == 40
    assert access.slot_limit("premium", rewarded_referrals=3) is None
    assert access.slot_limit("premium") is None
    assert access.slot_limit("owner") is None
    assert DEFAULTS["system.unlimited_slots"] == "premium"


def test_alert_limits():
    assert access.alert_limit("free") == access.FREE_ALERT_LIMIT == 3
    assert access.alert_limit("premium") is None and access.alert_limit("owner") is None
    assert DEFAULTS["feature.unlimited_alerts"] == "premium" and DEFAULTS["action.alerts.edit"] == "free"


# ---------------------------------------------------------------- DB lookup

class _FakeDB:
    def __init__(self, exc=None, row=None):
        self.exc, self.row = exc, row

    def table(self, _):
        return self

    def select(self, *_):
        return self

    def eq(self, *_):
        return self

    def limit(self, *_):
        return self

    def execute(self):
        if self.exc:
            raise self.exc
        return type("R", (), {"data": [self.row] if self.row else []})()


@pytest.mark.parametrize("exc,row,expected", [
    (None, {"access_level": "premium", "slot_bonus": 5}, "premium"),
    (None, {"access_level": "bogus"}, "free"),
    (Exception('column users.access_level does not exist (42703)'), None, "owner"),  # before 011
    (Exception("connection reset"), None, "free"),  # fail closed
])
def test_get_user_access(monkeypatch, exc, row, expected):
    monkeypatch.setattr("app.db.supabase.get_client", lambda: _FakeDB(exc, row))
    assert access.get_user_access("u1")["level"] == expected


# ---------------------------------------------------------------- API gating

def _client(monkeypatch, *routers):
    from app.middleware import rate_limit
    monkeypatch.setattr(auth_mw, "is_token_blacklisted", lambda _jti: False)
    monkeypatch.setattr(auth_mw, "insert_audit_log", lambda **_: None)
    if hasattr(rate_limit, "_buckets"):
        rate_limit._buckets.clear()
    app = FastAPI()
    app.add_middleware(auth_mw.AuthMiddleware)
    for r in routers:
        app.include_router(r, prefix="/api/v1")
    c = TestClient(app)
    token = create_access_token("11111111-1111-1111-1111-111111111111", "u")
    c.headers["Authorization"] = f"Bearer {token}"
    return c


def test_free_user_gets_403_upgrade_required(monkeypatch):
    from app.api.v1 import admin_usage
    _as(monkeypatch, "free")
    r = _client(monkeypatch, admin_usage.router).get("/api/v1/admin/usage")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "upgrade_required"
    assert r.json()["detail"]["feature"] == "area.admin"


def test_me_reports_level_features_and_slots(monkeypatch):
    from app.api.v1 import auth
    from app.services import slots
    _as(monkeypatch, "free", bonus=5)
    monkeypatch.setattr(slots, "followed_symbols", lambda _uid: {"MSFT", "ENB.TO"})
    body = _client(monkeypatch, auth.router).get("/api/v1/auth/me").json()
    assert body["access_level"] == "free"
    assert "area.holdings" in body["features"] and "area.admin" not in body["features"]
    assert {"key": "area.admin", "min_level": "owner"}.items() <= next(
        c for c in body["catalog"] if c["key"] == "area.admin").items()
    assert body["slots"] == {"used": 2, "limit": 15, "remaining": 13}


def test_slot_limit_blocks_only_new_symbols(monkeypatch):
    from fastapi import HTTPException

    from app.services import slots
    monkeypatch.setattr(slots, "followed_symbols", lambda _uid: {f"S{i}" for i in range(15)})
    free = {"user_id": "u", "access_level": "free", "slot_bonus": 5}
    slots.check_new_symbols(free, ["S1", "s2"])  # already followed: fine
    with pytest.raises(HTTPException) as e:
        slots.check_new_symbols(free, ["NEW"])
    assert e.value.status_code == 403 and e.value.detail["code"] == "slot_limit"
    assert e.value.detail["limit"] == 15 and e.value.detail["used"] == 15
    assert e.value.detail["upgrade"] == {"feature": "system.unlimited_slots", "plan": "premium"}
    slots.check_new_symbols({**free, "access_level": "premium"}, ["NEW"])
    slots.check_new_symbols({**free, "access_level": "owner"}, ["NEW"])


# Routes any signed-in user may call, whatever their level.
UNGATED = {
    ("POST", "/api/v1/auth/login"), ("POST", "/api/v1/auth/verify-otp"), ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/auth/refresh"), ("GET", "/api/v1/auth/me"),
    ("POST", "/api/v1/auth/token/refresh"), ("GET", "/api/v1/auth/sessions"),
    ("DELETE", "/api/v1/auth/sessions/{session_id}"), ("POST", "/api/v1/auth/sessions/revoke-others"),
    ("POST", "/api/v1/auth/register"), ("GET", "/api/v1/auth/referral/{code}"),   # public (migration 019)
    ("GET", "/api/v1/auth/signup-config"), ("GET", "/api/v1/public/stocks/{symbol}"),   # public (029)
    ("GET", "/api/v1/health"), ("GET", "/api/v1/version"), ("GET", "/api/v1/symbols/search"),
    ("GET", "/api/v1/stats/user-settings"), ("PUT", "/api/v1/stats/user-settings"),
    ("GET", "/api/v1/tickers/{ticker}/chart"),
    ("POST", "/api/v1/telegram/webhook"), ("GET", "/"),
}


def test_every_route_is_gated_or_explicitly_free():
    """A new endpoint must declare its feature (or be added to UNGATED)."""
    import main

    missing = []
    for route in main.app.routes:
        if not isinstance(route, APIRoute):
            continue
        deps = {d.call.__name__ for d in route.dependant.dependencies if getattr(d, "call", None)}
        gated = any(n.startswith("require_") for n in deps)
        for m in route.methods - {"HEAD"}:
            if not gated and (m, route.path) not in UNGATED:
                missing.append(f"{m} {route.path}")
    assert not missing, f"routes without require_feature: {missing}"


def test_chart_has_no_signal_markers(monkeypatch):
    import pandas as pd

    from app.api.v1 import tickers

    idx = pd.date_range("2026-09-01", periods=3, freq="D")
    df = pd.DataFrame({"Open": [1, 2, 3], "High": [1, 2, 3], "Low": [1, 2, 3], "Close": [1, 2, 3],
                       "Volume": [10, 10, 10]}, index=idx)
    monkeypatch.setattr("yfinance.Ticker", lambda _t: type("T", (), {"history": lambda self, **k: df})())
    for level in ("free", "owner"):
        _as(monkeypatch, level)
        body = _client(monkeypatch, tickers.router).get("/api/v1/tickers/MSFT/chart").json()
        assert body["signal_markers"] == [] and body["count"] == 3


def test_view_as_only_for_owner_with_dev_tools(monkeypatch):
    from app.core.config import settings
    from app.middleware.auth import effective_level
    monkeypatch.setattr(settings, "dev_tools_enabled", False)
    assert effective_level("owner", "free") == "owner"          # production: ignored
    monkeypatch.setattr(settings, "dev_tools_enabled", True)
    assert effective_level("owner", "free") == "free"
    assert effective_level("owner", "premium") == "premium"
    assert effective_level("owner", "admin") == "owner"         # unknown value ignored
    assert effective_level("free", "owner") == "free"           # never an escalation
    assert effective_level("premium", "owner") == "premium"


def test_me_reports_view_as(monkeypatch):
    from app.api.v1 import auth
    from app.core.config import settings
    from app.services import slots
    monkeypatch.setattr(settings, "dev_tools_enabled", True)
    monkeypatch.setattr(slots, "followed_symbols", lambda _uid: set())
    _as(monkeypatch, "owner")
    c = _client(monkeypatch, auth.router)
    body = c.get("/api/v1/auth/me", headers={"X-View-As": "free"}).json()
    assert body["access_level"] == "free" and body["real_access_level"] == "owner" and body["dev_tools"] is True
    assert "area.admin" not in body["features"]
    _as(monkeypatch, "free")
    body = c.get("/api/v1/auth/me", headers={"X-View-As": "owner"}).json()
    assert body["access_level"] == "free" and body["dev_tools"] is False
