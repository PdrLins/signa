"""/api/v1/check/compare — auth, validation (count, dupes after resolution,
unknown symbols), cache reuse vs the daily limit, concurrency queueing, job
lifecycle and the AI summary hand-off. The analysis and AI are mocked."""

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
from app.services import stock_compare as scmp

CID = "0" * 32
ALIASES = {"XEQT": "XEQT.TO", "XEQT.TO": "XEQT.TO", "AAPL": "AAPL", "MSFT": "MSFT", "NVDA": "NVDA",
           "VFV": "VFV.TO"}


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


class Fake:
    """resolve_symbol + run_check/run_long_check + AI summary stand-ins."""

    def __init__(self, monkeypatch, delay=0.1, ai=None):
        self.delay = delay
        self.runs: list[str] = []
        self.active = 0
        self.peak = 0
        self.ai_calls = 0
        self.ai = ai
        monkeypatch.setattr(sc, "resolve_symbol", self.resolve)
        monkeypatch.setattr(sc, "run_check", self.run_check)
        monkeypatch.setattr(api.long_term_check, "run_long_check", self.run_check)
        monkeypatch.setattr(scmp, "summarize", self.summarize)

    async def resolve(self, raw):
        s = sc.normalize_input(raw)
        if s not in ALIASES:
            raise sc.StockCheckError("not_found", f"No recent price data for {s}", 404)
        return {"input": s, "symbol": ALIASES[s], "exchange": "X", "price": 10.0}

    async def run_check(self, resolved, progress=None):
        self.runs.append(resolved["symbol"])
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            progress("market_data", 20)
            await asyncio.sleep(self.delay)
            progress("risk", 80)
        finally:
            self.active -= 1
        verdict = {"AAPL": "BUY_NOW", "MSFT": "WAIT"}.get(resolved["symbol"], "AVOID")
        return {"symbol": resolved["symbol"], "verdict": verdict, "levels": {"rr": 2.0},
                "checked_at": "2026-09-28T14:00:00+00:00", "cached": False}

    async def summarize(self, cmp):
        self.ai_calls += 1
        if self.ai is None:
            return scmp.fallback_summary(cmp)
        return self.ai


def _post(client, tickers, **kw):
    return client.post("/api/v1/check/compare", json={"tickers": tickers, **kw}, headers=_auth())


def _wait(client, cid, timeout=5.0):
    seen = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/v1/check/compare/{cid}", headers=_auth()).json()
        seen.append(body)
        if body["status"] == "done":
            return body, seen
        time.sleep(0.02)
    raise AssertionError(f"compare did not finish: {seen[-1]}")


# ── auth ──

def test_auth_required(client):
    assert client.post("/api/v1/check/compare", json={"tickers": ["AAPL", "MSFT"]}).status_code == 401
    assert client.get(f"/api/v1/check/compare/{CID}").status_code == 401


# ── validation ──

@pytest.mark.parametrize("tickers", [["AAPL"], ["AAPL", "MSFT", "NVDA", "VFV"], []])
def test_count_validation(client, monkeypatch, tickers):
    Fake(monkeypatch)
    r = _post(client, tickers)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "compare_count"


def test_duplicate_input(client, monkeypatch):
    Fake(monkeypatch)
    r = _post(client, ["aapl", "AAPL"])
    assert r.status_code == 400 and r.json()["detail"]["code"] == "compare_duplicate"


def test_duplicate_after_resolution(client, monkeypatch):
    fake = Fake(monkeypatch)
    r = _post(client, ["XEQT", "XEQT.TO"])
    d = r.json()["detail"]
    assert r.status_code == 400 and d["code"] == "compare_duplicate" and d["symbols"] == ["XEQT.TO"]
    assert fake.runs == [] and api._daily_count() == 0


def test_unknown_symbol(client, monkeypatch):
    Fake(monkeypatch)
    r = _post(client, ["AAPL", "ZZZZ"])
    d = r.json()["detail"]
    assert r.status_code == 404 and d["code"] == "compare_unknown" and d["inputs"] == ["ZZZZ"]
    assert api._daily_count() == 0


def test_invalid_ticker(client, monkeypatch):
    Fake(monkeypatch)
    r = _post(client, ["AAPL", "BAD$$"])
    assert r.status_code == 400 and r.json()["detail"]["code"] == "invalid_ticker"


def test_unknown_compare_404(client):
    for cid in (CID, "nope"):
        r = client.get(f"/api/v1/check/compare/{cid}", headers=_auth())
        assert r.status_code == 404 and r.json()["detail"]["code"] == "compare_not_found"


# ── lifecycle ──

def test_job_lifecycle(client, monkeypatch):
    fake = Fake(monkeypatch)
    r = _post(client, ["msft", "AAPL", "XEQT"])
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "running" and body["symbols"] == ["MSFT", "AAPL", "XEQT.TO"]
    assert body["remaining_today"] == settings.stock_check_daily_limit - 3
    final, seen = _wait(client, body["compare_id"])
    assert final["pct"] == 100 and final["phase"] == "done"
    assert all(it["status"] == "done" and it["cached"] is False for it in final["items"])
    assert set(final["results"]) == {"MSFT", "AAPL", "XEQT.TO"}
    assert final["comparison"]["symbols"] == ["MSFT", "AAPL", "XEQT.TO"]
    verdict = next(m for m in final["comparison"]["metrics"] if m["key"] == "verdict")
    assert verdict["best"] == ["AAPL"]
    assert final["summary"]["ranking"][0] == "AAPL" and final["summary"]["source"] == "deterministic"
    assert sorted(fake.runs) == ["AAPL", "MSFT", "XEQT.TO"] and fake.ai_calls == 1
    pcts = [b["pct"] for b in seen]
    assert pcts == sorted(pcts)
    assert "results" not in seen[0] or seen[0]["status"] == "done"


def test_long_mode_uses_long_pipeline(client, monkeypatch):
    fake = Fake(monkeypatch)
    calls = []

    async def short_should_not_run(*a, **k):
        calls.append("short")
        raise AssertionError
    monkeypatch.setattr(sc, "run_check", short_should_not_run)
    body = _post(client, ["AAPL", "VFV"], mode="long").json()
    final, _ = _wait(client, body["compare_id"])
    assert final["mode"] == "long" and calls == [] and sorted(fake.runs) == ["AAPL", "VFV.TO"]
    assert ("AAPL|long") in api._results


def test_ai_summary_passed_through(client, monkeypatch):
    ai = {"source": "ai", "ranking": ["MSFT", "AAPL"], "summary": "s", "per_symbol": {}, "caveats": [],
          "note": None, "provider": "claude-local-decision"}
    Fake(monkeypatch, ai=ai)
    final, _ = _wait(client, _post(client, ["AAPL", "MSFT"]).json()["compare_id"])
    assert final["summary"] == ai


def test_one_failure_still_compares_the_rest(client, monkeypatch):
    fake = Fake(monkeypatch)
    orig = fake.run_check

    async def flaky(resolved, progress=None):
        if resolved["symbol"] == "NVDA":
            raise RuntimeError("boom")
        return await orig(resolved, progress)
    monkeypatch.setattr(sc, "run_check", flaky)
    final, _ = _wait(client, _post(client, ["AAPL", "MSFT", "NVDA"]).json()["compare_id"])
    nv = next(it for it in final["items"] if it["symbol"] == "NVDA")
    assert nv["status"] == "failed" and nv["error"]["code"] == "internal"
    assert final["comparison"]["symbols"] == ["AAPL", "MSFT"] and fake.ai_calls == 1


# ── cache + daily limit ──

def test_cache_reuse_does_not_count(client, monkeypatch):
    fake = Fake(monkeypatch)
    first = client.post("/api/v1/check", json={"ticker": "AAPL"}, headers=_auth()).json()
    deadline = time.time() + 5
    while client.get(f"/api/v1/check/{first['job_id']}", headers=_auth()).json()["status"] == "running":
        assert time.time() < deadline
        time.sleep(0.02)
    assert api._daily_count() == 1

    body = _post(client, ["AAPL", "MSFT"]).json()
    assert body["remaining_today"] == settings.stock_check_daily_limit - 2
    aapl = next(it for it in body["items"] if it["symbol"] == "AAPL")
    assert aapl["status"] == "done" and aapl["cached"] is True
    final, _ = _wait(client, body["compare_id"])
    assert fake.runs == ["AAPL", "MSFT"]          # AAPL not re-run
    assert api._daily_count() == 2

    # Both cached now: a full re-compare is free.
    again = _post(client, ["MSFT", "AAPL"]).json()
    _wait(client, again["compare_id"])
    assert api._daily_count() == 2 and len(fake.runs) == 2

    # force bypasses the cache and counts.
    forced = _post(client, ["MSFT", "AAPL"], force=True).json()
    _wait(client, forced["compare_id"])
    assert api._daily_count() == 4 and len(fake.runs) == 4


def test_daily_limit_exceeded_errors_before_starting(client, monkeypatch):
    fake = Fake(monkeypatch)
    monkeypatch.setattr(settings, "stock_check_daily_limit", 2)
    api._daily.update({"date": api._et_today(), "count": 1})
    r = _post(client, ["AAPL", "MSFT"])
    d = r.json()["detail"]
    assert r.status_code == 429 and d["code"] == "daily_limit"
    assert d["needed"] == 2 and d["remaining"] == 1 and d["resets_at"]
    assert fake.runs == [] and api._daily_count() == 1 and not api._compares


def test_limit_counts_only_non_cached(client, monkeypatch):
    fake = Fake(monkeypatch)
    monkeypatch.setattr(settings, "stock_check_daily_limit", 2)
    api._results["AAPL"] = (time.time(), {"symbol": "AAPL", "verdict": "WAIT", "cached": False})
    api._daily.update({"date": api._et_today(), "count": 1})
    r = _post(client, ["AAPL", "MSFT"])      # needs 1, 1 remains
    assert r.status_code == 200
    _wait(client, r.json()["compare_id"])
    assert fake.runs == ["MSFT"] and api._daily_count() == 2


# ── concurrency ──

def test_runs_queue_within_max_concurrency(client, monkeypatch):
    fake = Fake(monkeypatch, delay=0.15)
    monkeypatch.setattr(settings, "stock_check_max_concurrent", 1)
    monkeypatch.setattr(api, "_QUEUE_POLL_S", 0.01)
    body = _post(client, ["AAPL", "MSFT", "NVDA"]).json()
    assert body["status"] == "running"
    final, seen = _wait(client, body["compare_id"])
    assert fake.peak == 1 and len(fake.runs) == 3
    assert any(any(it["status"] == "queued" for it in b["items"]) for b in seen)


def test_compare_runs_count_toward_single_check_busy(client, monkeypatch):
    Fake(monkeypatch, delay=0.3)
    monkeypatch.setattr(settings, "stock_check_max_concurrent", 2)
    _post(client, ["AAPL", "MSFT"])
    deadline = time.time() + 2
    while api._running() < 2:
        assert time.time() < deadline
        time.sleep(0.01)
    r = client.post("/api/v1/check", json={"ticker": "NVDA"}, headers=_auth())
    assert r.status_code == 429 and r.json()["detail"]["code"] == "busy"


def test_compares_expire(client, monkeypatch):
    Fake(monkeypatch)
    body = _post(client, ["AAPL", "MSFT"]).json()
    _wait(client, body["compare_id"])
    api._compares[body["compare_id"]].created -= settings.stock_check_job_ttl_minutes * 60 + 1
    assert client.get(f"/api/v1/check/compare/{body['compare_id']}", headers=_auth()).status_code == 404


# ── rate limit ──

def test_compare_post_strict_and_poll_exempt():
    assert rate_limit._get_tier("/api/v1/check/compare")[0] == "strict"
    assert rate_limit._CHECK_JOB_ROUTE.match(f"/api/v1/check/compare/{'a1' * 16}")
    assert not rate_limit._CHECK_JOB_ROUTE.match("/api/v1/check/compare/x")
