"""Second audit fixes: body size limit, request ids, error handling, circuit
breaker, public symbol guard, Yahoo failure memory, rate-limit keys."""

import asyncio
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------- body limit

def _app_with_body_limit():
    from app.middleware.body_limit import BodyLimitMiddleware
    app = FastAPI()

    @app.post("/api/v1/auth/login")
    async def login(body: dict):
        return {"ok": True}

    @app.post("/api/v1/transactions/import")
    async def imp(request_body: dict | None = None):
        return {"ok": True}
    app.add_middleware(BodyLimitMiddleware)
    return TestClient(app)


def test_oversized_body_is_refused_before_reading():
    c = _app_with_body_limit()
    assert c.post("/api/v1/auth/login", json={"username": "a"}).status_code == 200
    r = c.post("/api/v1/auth/login", content=b"x" * (70 * 1024), headers={"content-type": "application/json"})
    assert r.status_code == 413 and r.json()["detail"]["code"] == "request_too_large"


def test_imports_get_a_bigger_limit():
    from app.middleware import body_limit
    assert body_limit.limit_for("/api/v1/transactions/import") == 3 * 1024 * 1024
    assert body_limit.limit_for("/api/v1/auth/register") == 64 * 1024


# ---------------------------------------------------------------- request ids + errors

def test_request_id_and_unhandled_errors():
    from app.middleware.audit import AuditMiddleware, short_ip
    app = FastAPI()

    @app.get("/boom")
    async def boom():
        raise RuntimeError("secret detail")

    @app.get("/fine/{symbol}")
    async def fine(symbol: str):
        return {"ok": True}
    app.add_middleware(AuditMiddleware)
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/fine/AAPL")
    assert r.status_code == 200 and len(r.headers["x-request-id"]) == 16
    r = c.get("/boom")
    body = r.json()["detail"]
    assert r.status_code == 500 and body["code"] == "internal_error"
    assert body["request_id"] == r.headers["x-request-id"] and "secret" not in r.text
    assert short_ip("203.0.113.77") == "203.0.113.0/24" and short_ip("nope") == "unknown"


# ---------------------------------------------------------------- circuit breaker

def test_breaker_fails_fast_after_repeated_timeouts(monkeypatch):
    from app.db.supabase import _Breaker
    b = _Breaker()
    for _ in range(b.BREAK_AFTER):
        b.failure(httpx.ConnectTimeout("slow"))
    with pytest.raises(httpx.ConnectError):
        b.check()                                    # open: no 20 s wait
    b._open_until = time.time() - 1
    b.check()                                        # closed again
    b.failure(ValueError("not a connection problem"))
    assert b._failures == []


# ---------------------------------------------------------------- public pages

def test_public_page_refuses_unknown_symbols(monkeypatch):
    import main
    from app.services import stock_page
    monkeypatch.setattr(stock_page, "is_known", lambda sym: False)
    r = TestClient(main.app).get("/api/v1/public/stocks/ZZZQQ")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "not_found"


def test_yahoo_failure_answers_waiters_at_once(monkeypatch):
    from app.services import stock_page
    stock_page.clear_cache()
    calls = []

    def fetch(sym):
        calls.append(sym)
        return {"history": None, "info": {}, "error": True}
    monkeypatch.setattr(stock_page, "_fetch_market", fetch)

    async def many():
        return await asyncio.gather(*[stock_page.get_shared_page("ABC") for _ in range(5)],
                                    return_exceptions=True)
    results = asyncio.run(many())
    assert all(isinstance(r, stock_page.StockPageError) and r.status == 503 for r in results)
    assert len(calls) <= 3        # one try per candidate symbol, not one per waiting user
    stock_page.clear_cache()


# ---------------------------------------------------------------- rate limits

def test_public_tier_and_proxy_never_blocked():
    from app.core.config import settings
    from app.middleware import rate_limit
    assert rate_limit._get_tier("/api/v1/public/stocks/ENB.TO")[0] == "public"
    assert rate_limit._get_tier("/api/v1/public/stocks/ENB.TO")[1] == 30
    assert "127.0.0.1" in settings.trusted_proxies


def test_fx_bad_print_is_ignored(monkeypatch):
    from app.services import price_cache
    price_cache._fx_cache.clear()
    price_cache._last_good.clear()
    price_cache._last_good["BRL"] = 5.40
    monkeypatch.setattr(price_cache, "_download_fx", lambda codes: {"BRL": 0.54})   # 10x off
    assert price_cache.usd_rates(["BRL"])["BRL"] == 5.40
    price_cache._fx_cache.clear()
    monkeypatch.setattr(price_cache, "_download_fx", lambda codes: {"BRL": 5.55})   # normal move
    assert price_cache.usd_rates(["BRL"])["BRL"] == 5.55
    price_cache._fx_cache.clear()
    price_cache._last_good.clear()


# ---------------------------------------------------------------- job health

def test_missed_jobs_are_caught_up_only_when_still_right():
    from datetime import datetime, timezone

    from app.scheduler import health
    # Tuesday 2026-10-06, 20:00 ET; snapshots were due 16:30 ET today
    now = datetime(2026, 10, 7, 0, 0, tzinfo=timezone.utc)
    yesterday_ok = datetime(2026, 10, 5, 21, 0, tzinfo=timezone.utc)
    assert health.overdue("portfolio_snapshots", yesterday_ok, now) is True
    assert health.overdue("portfolio_snapshots", now, now) is False
    # next morning: yesterday's market-close snapshot is no longer right to take
    assert health.overdue("portfolio_snapshots", yesterday_ok, datetime(2026, 10, 7, 13, 0, tzinfo=timezone.utc)) is False
    # monthly recap: missed on the 1st, caught up during the first week only
    assert health.overdue("monthly_recap_push", None, datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)) is True
    assert health.overdue("monthly_recap_push", None, datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)) is False


def test_tracked_job_records_failures_and_alerts_on_the_second(monkeypatch):
    from app.scheduler import health
    alerts, saved = [], []

    async def alert(job_id, error):
        alerts.append(job_id)
    monkeypatch.setattr(health, "_alert_owner", alert)
    monkeypatch.setattr(health, "_save", lambda row: saved.append(row))
    health._state.clear()

    @health.tracked("portfolio_snapshots")
    async def job():
        try:
            raise RuntimeError("db down")
        except Exception as e:
            health.fail("portfolio_snapshots", e)

    asyncio.run(job())
    assert alerts == [] and health._state["portfolio_snapshots"]["failures"] == 1
    asyncio.run(job())
    assert alerts == ["portfolio_snapshots"] and saved[-1]["last_error"].startswith("RuntimeError")
    health._state.clear()
