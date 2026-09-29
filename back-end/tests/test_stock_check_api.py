"""/api/v1/check — auth, job lifecycle, result cache + force, daily limit,
concurrency, rate-limit tiering. The analysis itself is mocked."""

import asyncio
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import stock_check as api
from app.core.config import settings
from app.core.security import create_access_token
from app.middleware import auth as auth_mw
from app.middleware import rate_limit
from app.services import stock_check as sc

JOB = "0" * 32


def _auth():
    return {"Authorization": f"Bearer {create_access_token('u1', 'owner')}"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth_mw, "is_token_blacklisted", lambda jti: False)
    monkeypatch.setattr(auth_mw, "insert_audit_log", lambda *a, **k: None)
    api._reset_state()
    app = FastAPI()
    app.add_middleware(auth_mw.AuthMiddleware)
    app.include_router(api.router, prefix="/api/v1")
    with TestClient(app) as c:
        yield c
    api._reset_state()


class FakePipeline:
    """resolve_symbol + run_check stand-ins; counts runs."""

    def __init__(self, monkeypatch, symbol="XEQT.TO", delay=0.15, fail: Exception | None = None):
        self.symbol, self.delay, self.fail = symbol, delay, fail
        self.runs = 0
        monkeypatch.setattr(sc, "resolve_symbol", self.resolve)
        monkeypatch.setattr(sc, "run_check", self.run_check)

    async def resolve(self, raw):
        if self.fail:
            raise self.fail
        return {"input": raw.upper(), "symbol": self.symbol, "exchange": "TSX", "price": 31.0}

    async def run_check(self, resolved, progress=None):
        self.runs += 1
        for phase, pct in (("market_data", 10), ("filter", 25), ("sentiment", 40), ("synthesis", 55),
                           ("decision", 72), ("risk", 88)):
            progress(phase, pct)
            await asyncio.sleep(self.delay / 6)
        return {"symbol": resolved["symbol"], "verdict": "WAIT", "checked_at": "2026-09-28T14:00:00+00:00",
                "cached": False}


def _wait_done(client, job_id, timeout=5.0):
    seen = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/v1/check/{job_id}", headers=_auth()).json()
        seen.append((body["status"], body["phase"], body["pct"]))
        if body["status"] != "running":
            return body, seen
        time.sleep(0.02)
    raise AssertionError(f"job did not finish: {seen[-3:]}")


# ── auth ──

def test_post_requires_auth(client):
    assert client.post("/api/v1/check", json={"ticker": "XEQT"}).status_code == 401


def test_get_requires_auth(client):
    assert client.get(f"/api/v1/check/{JOB}").status_code == 401


def test_bad_token_rejected(client):
    r = client.post("/api/v1/check", json={"ticker": "XEQT"}, headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


# ── validation ──

def test_invalid_ticker_400(client, monkeypatch):
    FakePipeline(monkeypatch)
    r = client.post("/api/v1/check", json={"ticker": "BAD$$"}, headers=_auth())
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "invalid_ticker"


def test_unknown_job_404(client):
    for jid in (JOB, "not-a-job"):
        r = client.get(f"/api/v1/check/{jid}", headers=_auth())
        assert r.status_code == 404
        assert r.json()["detail"]["code"] == "job_not_found"


# ── lifecycle ──

def test_job_progress_lifecycle(client, monkeypatch):
    fake = FakePipeline(monkeypatch)
    r = client.post("/api/v1/check", json={"ticker": "xeqt"}, headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "running" and body["input"] == "XEQT"
    assert body["remaining_today"] == settings.stock_check_daily_limit - 1
    final, seen = _wait_done(client, body["job_id"])
    assert final["status"] == "done" and final["pct"] == 100 and final["phase"] == "done"
    assert final["result"]["verdict"] == "WAIT" and final["cached"] is False
    assert final["symbol"] == "XEQT.TO"
    pcts = [p for _, _, p in seen]
    assert pcts == sorted(pcts)  # monotonic progress
    assert any(ph not in ("resolving", "done") for _, ph, _ in seen)
    assert fake.runs == 1


def test_not_found_fails_job_and_is_not_counted(client, monkeypatch):
    FakePipeline(monkeypatch, fail=sc.StockCheckError("not_found", "No recent price data for ZZZZ", 404))
    body = client.post("/api/v1/check", json={"ticker": "ZZZZ"}, headers=_auth()).json()
    final, _ = _wait_done(client, body["job_id"])
    assert final["status"] == "failed"
    assert final["error"]["code"] == "not_found" and final["error"]["status"] == 404
    assert api._daily_count() == 0


def test_internal_error_is_sanitized(client, monkeypatch):
    fake = FakePipeline(monkeypatch)

    async def boom(resolved, progress=None):
        raise RuntimeError("/app/secret/path Traceback")
    monkeypatch.setattr(sc, "run_check", boom)
    body = client.post("/api/v1/check", json={"ticker": "XEQT"}, headers=_auth()).json()
    final, _ = _wait_done(client, body["job_id"])
    assert final["status"] == "failed" and final["error"]["code"] == "internal"
    assert "secret" not in final["error"]["message"]
    assert fake.runs == 0


# ── cache ──

def test_repeat_check_is_cached_and_force_bypasses(client, monkeypatch):
    fake = FakePipeline(monkeypatch)
    first = client.post("/api/v1/check", json={"ticker": "XEQT"}, headers=_auth()).json()
    _wait_done(client, first["job_id"])

    again = client.post("/api/v1/check", json={"ticker": "xeqt"}, headers=_auth()).json()
    assert again["status"] == "done" and again["cached"] is True
    assert again["result"]["cached"] is True
    assert again["result"]["checked_at"] == "2026-09-28T14:00:00+00:00"
    assert fake.runs == 1
    assert api._daily_count() == 1  # cache hits are free

    forced = client.post("/api/v1/check", json={"ticker": "XEQT", "force": True}, headers=_auth()).json()
    assert forced["status"] == "running"
    final, _ = _wait_done(client, forced["job_id"])
    assert final["cached"] is False
    assert fake.runs == 2
    assert api._daily_count() == 2


def test_cache_hit_via_other_spelling_is_refunded(client, monkeypatch):
    fake = FakePipeline(monkeypatch)
    first = client.post("/api/v1/check", json={"ticker": "XEQT"}, headers=_auth()).json()
    _wait_done(client, first["job_id"])
    # "XEQT.TO" has no alias yet -> starts a job, resolves to the cached symbol
    second = client.post("/api/v1/check", json={"ticker": "XEQT.TO"}, headers=_auth()).json()
    final, _ = _wait_done(client, second["job_id"])
    assert final["cached"] is True
    assert fake.runs == 1
    assert api._daily_count() == 1


def test_cache_expires(client, monkeypatch):
    fake = FakePipeline(monkeypatch)
    first = client.post("/api/v1/check", json={"ticker": "XEQT"}, headers=_auth()).json()
    _wait_done(client, first["job_id"])
    at, res = api._results["XEQT.TO"]
    api._results["XEQT.TO"] = (at - settings.stock_check_cache_minutes * 60 - 1, res)
    again = client.post("/api/v1/check", json={"ticker": "XEQT"}, headers=_auth()).json()
    assert again["status"] == "running"
    _wait_done(client, again["job_id"])
    assert fake.runs == 2


# ── limits ──

def test_daily_limit(client, monkeypatch):
    FakePipeline(monkeypatch)
    monkeypatch.setattr(settings, "stock_check_daily_limit", 1)
    first = client.post("/api/v1/check", json={"ticker": "XEQT"}, headers=_auth()).json()
    _wait_done(client, first["job_id"])
    r = client.post("/api/v1/check", json={"ticker": "XEQT", "force": True}, headers=_auth())
    assert r.status_code == 429
    d = r.json()["detail"]
    assert d["code"] == "daily_limit" and d["limit"] == 1 and d["resets_at"]
    # a cached answer is still served once the limit is hit
    cached = client.post("/api/v1/check", json={"ticker": "XEQT"}, headers=_auth())
    assert cached.status_code == 200 and cached.json()["cached"] is True


def test_daily_limit_resets_on_new_et_day(client, monkeypatch):
    FakePipeline(monkeypatch)
    monkeypatch.setattr(settings, "stock_check_daily_limit", 1)
    api._daily.update({"date": "2000-01-01", "count": 1})
    r = client.post("/api/v1/check", json={"ticker": "XEQT"}, headers=_auth())
    assert r.status_code == 200


def test_concurrency_limit(client, monkeypatch):
    FakePipeline(monkeypatch)
    for i in range(settings.stock_check_max_concurrent):
        j = api.Job(id=f"{i:032x}", input=f"T{i}", force=False)
        api._jobs[j.id] = j
    r = client.post("/api/v1/check", json={"ticker": "XEQT"}, headers=_auth())
    assert r.status_code == 429
    assert r.json()["detail"]["code"] == "busy"
    assert api._daily_count() == 0


def test_jobs_expire(client, monkeypatch):
    FakePipeline(monkeypatch)
    body = client.post("/api/v1/check", json={"ticker": "XEQT"}, headers=_auth()).json()
    _wait_done(client, body["job_id"])
    api._jobs[body["job_id"]].created -= settings.stock_check_job_ttl_minutes * 60 + 1
    r = client.get(f"/api/v1/check/{body['job_id']}", headers=_auth())
    assert r.status_code == 404


# ── rate-limit tiering ──

def test_post_is_strict_tier_and_polling_is_exempt():
    assert rate_limit._get_tier("/api/v1/check")[0] == "strict"
    assert rate_limit._CHECK_JOB_ROUTE.match(f"/api/v1/check/{'a1' * 16}")
    assert not rate_limit._CHECK_JOB_ROUTE.match("/api/v1/check/../../auth/login")
    assert not rate_limit._CHECK_JOB_ROUTE.match("/api/v1/check/abc")
