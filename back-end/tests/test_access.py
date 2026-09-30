"""Access levels: feature catalog, slots, route gating and the AI hard stop."""

import asyncio

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


def test_free_gets_tracker_not_brain():
    feats = set(access.allowed_features("free"))
    assert {"area.holdings", "action.holdings.edit", "area.watchlist"} <= feats
    assert not feats & {"area.brain", "area.signals", "action.check.run", "system.ai"}
    assert set(access.allowed_features("owner")) == set(DEFAULTS)


def test_db_override_moves_a_feature(monkeypatch):
    monkeypatch.setattr(access, "get_feature_levels", lambda: {**DEFAULTS, "area.check": "premium"})
    assert access.can("premium", "area.check") and not access.can("free", "area.check")


def test_slot_limits():
    assert access.slot_limit("free") == 10
    assert access.slot_limit("free", 10) == 10   # invite bonus no longer raises the free limit
    assert access.slot_limit("free", 999) == 10
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
    from app.api.v1 import stock_check
    _as(monkeypatch, "free")
    r = _client(monkeypatch, stock_check.router).post("/api/v1/check", json={"ticker": "MSFT"})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "upgrade_required"
    assert r.json()["detail"]["feature"] in ("area.check", "action.check.run")


def test_me_reports_level_features_and_slots(monkeypatch):
    from app.api.v1 import auth
    from app.services import slots
    _as(monkeypatch, "free", bonus=5)
    monkeypatch.setattr(slots, "followed_symbols", lambda _uid: {"MSFT", "ENB.TO"})
    body = _client(monkeypatch, auth.router).get("/api/v1/auth/me").json()
    assert body["access_level"] == "free"
    assert "area.holdings" in body["features"] and "area.brain" not in body["features"]
    assert {"key": "area.brain", "min_level": "owner"}.items() <= next(
        c for c in body["catalog"] if c["key"] == "area.brain").items()
    assert body["slots"] == {"used": 2, "limit": 10, "remaining": 8}


def test_slot_limit_blocks_only_new_symbols(monkeypatch):
    from fastapi import HTTPException

    from app.services import slots
    monkeypatch.setattr(slots, "followed_symbols", lambda _uid: {f"S{i}" for i in range(10)})
    free = {"user_id": "u", "access_level": "free", "slot_bonus": 5}
    slots.check_new_symbols(free, ["S1", "s2"])  # already followed: fine
    with pytest.raises(HTTPException) as e:
        slots.check_new_symbols(free, ["NEW"])
    assert e.value.status_code == 403 and e.value.detail["code"] == "slot_limit"
    assert e.value.detail["limit"] == 10 and e.value.detail["used"] == 10
    assert e.value.detail["upgrade"] == {"feature": "system.unlimited_slots", "plan": "premium"}
    slots.check_new_symbols({**free, "access_level": "premium"}, ["NEW"])
    slots.check_new_symbols({**free, "access_level": "owner"}, ["NEW"])


# Routes any signed-in user may call, whatever their level.
UNGATED = {
    ("POST", "/api/v1/auth/login"), ("POST", "/api/v1/auth/verify-otp"), ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/auth/refresh"), ("GET", "/api/v1/auth/me"),
    ("GET", "/api/v1/health"), ("GET", "/api/v1/symbols/search"),
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


# ---------------------------------------------------------------- AI hard stop

def test_ai_guard_blocks_free_requests_only():
    @access.ai_guarded("test call")
    async def call():
        return "ran"

    assert asyncio.run(call()) == "ran"  # no request (scheduler): allowed
    tok = access.set_request_level("free")
    try:
        with pytest.raises(access.AIAccessDenied):
            asyncio.run(call())
    finally:
        access.reset_request_level(tok)
    tok = access.set_request_level("owner")
    try:
        assert asyncio.run(call()) == "ran"
    finally:
        access.reset_request_level(tok)


def test_holdings_monitor_skips_grok_for_free(monkeypatch):
    from app.services import holdings_monitor as hm
    called = []

    async def fake_flags(*a, **k):
        called.append(1)
        return [], {}

    async def no_earnings(*a, **k):
        return None

    monkeypatch.setattr(hm, "red_flag_check", fake_flags)
    monkeypatch.setattr(hm, "earnings_info", no_earnings)
    monkeypatch.setattr(hm, "fetch_closes", lambda syms: {})
    h = {"id": "h1", "user_id": "u", "symbol": "MSFT"}
    updates, _ = asyncio.run(hm.monitor_holdings([h], ai_allowed=False))
    assert not called and updates[0]["holding_status"]["sentiment"] == {"skipped": "plan"}
    asyncio.run(hm.monitor_holdings([h], ai_allowed=True))
    assert called


def test_chart_hides_signal_markers_from_free(monkeypatch):
    import pandas as pd

    from app.api.v1 import tickers
    from app.db import queries

    idx = pd.date_range("2026-09-01", periods=3, freq="D")
    df = pd.DataFrame({"Open": [1, 2, 3], "High": [1, 2, 3], "Low": [1, 2, 3], "Close": [1, 2, 3],
                       "Volume": [10, 10, 10]}, index=idx)
    monkeypatch.setattr("yfinance.Ticker", lambda _t: type("T", (), {"history": lambda self, **k: df})())
    monkeypatch.setattr(queries, "get_signals_by_ticker",
                        lambda *a, **k: [{"created_at": "2026-09-02", "action": "BUY", "score": 80}])
    for level, expected in (("free", 0), ("owner", 1)):
        _as(monkeypatch, level)
        tickers._chart_cache.clear() if hasattr(tickers, "_chart_cache") else None
        body = _client(monkeypatch, tickers.router).get("/api/v1/tickers/MSFT/chart").json()
        assert len(body["signal_markers"]) == expected, (level, body)
