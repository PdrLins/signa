"""/api/v1/insights/* — auth required, happy paths with mocked services."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import insights as insights_api
from app.core.security import create_access_token
from app.middleware import auth as auth_mw
from app.services import insights_service as svc

PATHS = ["/api/v1/insights/today", "/api/v1/insights/performance",
         "/api/v1/insights/backtest", "/api/v1/insights/signal/NVDA"]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth_mw, "is_token_blacklisted", lambda jti: False)
    monkeypatch.setattr(auth_mw, "insert_audit_log", lambda *a, **k: None)
    insights_api._cache.clear()
    app = FastAPI()
    app.add_middleware(auth_mw.AuthMiddleware)
    app.include_router(insights_api.router, prefix="/api/v1")
    return TestClient(app)


@pytest.mark.parametrize("path", PATHS)
def test_requires_auth(client, path):
    r = client.get(path)
    assert r.status_code == 401


@pytest.mark.parametrize("path", PATHS)
def test_rejects_bad_token(client, path):
    r = client.get(path, headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401


def _auth():
    return {"Authorization": f"Bearer {create_access_token('u1', 'owner')}"}


def test_authorized_calls(client, monkeypatch):
    async def no_spend():
        return None
    monkeypatch.setattr(insights_api, "_ai_spend", no_spend)
    monkeypatch.setattr(svc, "get_today", lambda spend=None: {"ok": "today"})
    monkeypatch.setattr(svc, "get_performance", lambda: {"ok": "perf"})
    monkeypatch.setattr(svc, "parse_backtests", lambda base=None: {"runs": [], "latest": None})
    monkeypatch.setattr(svc, "get_signal_trail", lambda sym: {"symbol": sym})
    h = _auth()
    assert client.get(PATHS[0], headers=h).json() == {"ok": "today"}
    assert client.get(PATHS[1], headers=h).json() == {"ok": "perf"}
    assert client.get(PATHS[2], headers=h).json() == {"runs": [], "latest": None}
    assert client.get("/api/v1/insights/signal/nvda", headers=h).json() == {"symbol": "NVDA"}


def test_invalid_ticker_400(client, monkeypatch):
    monkeypatch.setattr(svc, "get_signal_trail", lambda sym: pytest.fail("must not be called"))
    r = client.get("/api/v1/insights/signal/BAD$$TICKER", headers=_auth())
    assert r.status_code == 400


def test_unknown_ticker_404(client, monkeypatch):
    def missing(sym):
        raise svc.SignalNotFound(sym)
    monkeypatch.setattr(svc, "get_signal_trail", missing)
    r = client.get("/api/v1/insights/signal/ZZZZ", headers=_auth())
    assert r.status_code == 404


VID = "123e4567-e89b-12d3-a456-426614174000"


def test_verdicts_requires_auth(client):
    assert client.get(f"/api/v1/insights/verdicts?ids={VID}").status_code == 401


def test_verdicts_rejects_non_uuid(client, monkeypatch):
    from app.db import queries
    monkeypatch.setattr(queries, "get_signal_verdicts", lambda ids: pytest.fail("must not be called"))
    r = client.get("/api/v1/insights/verdicts?ids=abc,DROP TABLE", headers=_auth())
    assert r.status_code == 400


def test_verdicts_ok(client, monkeypatch):
    from app.db import queries
    rows = [{"id": VID, "ai_status": "validated", "ai_signal": "BUY", "p_win": 0.61,
             "decision_overturned": False, "tech_filter": {"passed": True, "reasons": []}},
            {"id": "x-no-cols", "ai_status": "skipped", "tech_filter": None}]
    monkeypatch.setattr(queries, "get_signal_verdicts", lambda ids: rows)
    body = client.get(f"/api/v1/insights/verdicts?ids={VID}", headers=_auth()).json()["verdicts"]
    assert body[VID] == {"ai_status": "validated", "ai_signal": "BUY", "p_win": 0.61,
                         "routine_ai_signal": None, "decision_overturned": False,
                         "tech_filter_passed": True}
    assert body["x-no-cols"]["tech_filter_passed"] is None
    assert body["x-no-cols"]["ai_signal"] is None
