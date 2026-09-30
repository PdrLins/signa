"""long_term_check.run_long_check end to end with every network / AI / DB
call mocked; provider.assess_long_term routing (claude_local); the
/check `mode` param and per-mode cache keys."""

import asyncio
import sys
import time
import types
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ai import provider
from app.api.v1 import stock_check as api
from app.core.config import settings
from app.core.security import create_access_token
from app.middleware import auth as auth_mw
from app.services import long_term_check as lt
from app.services import stock_check as sc


def run(coro):
    return asyncio.run(coro)


def _geo(years, cagr, start="2012-01-03"):
    idx = pd.date_range(start, pd.Timestamp(start) + pd.DateOffset(years=years), freq="B")
    t = (idx - idx[0]).days / 365.25
    return pd.Series(100 * (1 + cagr) ** t, index=idx)


ETF_PROFILE = {
    "info": {"quoteType": "ETF", "longName": "iShares Core Equity ETF Portfolio", "currency": "CAD",
             "netExpenseRatio": 0.2, "totalAssets": 2.2e10, "yield": 0.0157, "trailingPE": 20.6},
    "fund": {"expense_ratio_raw": 0.002, "holdings": [
        {"symbol": "XTOT.TO", "name": "iShares Core S&P Total U.S. Stk Mkt ETF", "weight": 45.0},
        {"symbol": "XIC.TO", "name": "iShares Core S&P/TSX Cap Composite ETF", "weight": 25.0},
        {"symbol": "XEF.TO", "name": "iShares Core MSCI EAFE IMI ETF", "weight": 25.0}]},
    "income": [],
}
STOCK_PROFILE = {
    "info": {"quoteType": "EQUITY", "longName": "Acme Corp", "currency": "USD", "marketCap": 1e11,
             "trailingPE": 18.0, "freeCashflow": 5e9, "returnOnEquity": 0.2, "operatingMargins": 0.2,
             "debtToEquity": 60.0, "currentRatio": 1.8, "sector": "Industrials"},
    "fund": {}, "income": [{"year": 2022, "revenue": 100.0, "net_income": 10.0},
                           {"year": 2025, "revenue": 130.0, "net_income": 14.0}],
}


class Harness:
    def __init__(self, symbol="XEQT.TO", profile=ETF_PROFILE, ai_result=None, ai_raises=False):
        self.symbol = symbol
        self.profile = profile
        self.histories = {symbol: _geo(12, 0.09), "VT": _geo(14, 0.085), "SPY": _geo(14, 0.10),
                          "CAD=X": _geo(14, 0.0) * 0 + 1.3, "BTC-USD": _geo(14, 0.5)}
        self.ai = AsyncMock(side_effect=RuntimeError("boom")) if ai_raises else AsyncMock(return_value=ai_result)
        self.sent = AsyncMock(return_value={"confidence": 60, "red_flags": [
            {"text": "Accounting restatement", "url": "https://news/x", "severity": "high", "category": "accounting"}]})
        self.enrich = AsyncMock(return_value={"eps_revision_momentum": 2.0})

    def run(self):
        with ExitStack() as st:
            st.enter_context(patch.object(lt, "_fetch_history", side_effect=lambda s: self.histories.get(s, pd.Series(dtype=float))))
            st.enter_context(patch.object(lt, "_fetch_profile", return_value=self.profile))
            st.enter_context(patch.object(provider, "assess_long_term", self.ai))
            st.enter_context(patch.object(provider, "analyze_sentiment", self.sent))
            st.enter_context(patch("app.scanners.enrichment.get_enrichment", self.enrich))
            return run(lt.run_long_check({"symbol": self.symbol, "input": self.symbol, "price": 45.0}))


AI_OK = {"verdict": "SOLID", "summary": "Broad and cheap.", "strengths": ["0.20% fee"], "concerns": [],
         "what_to_watch": [], "dca_note": "Personal choice.", "confidence": 70, "_provider": "claude-local-decision"}


def test_etf_result_shape_and_no_grok():
    h = Harness(ai_result=dict(AI_OK))
    r = h.run()
    assert r["mode"] == "long" and r["asset_type"] == "ETF" and r["currency"] == "CAD"
    assert r["benchmark"] == "VT"
    assert r["verdict"] == "SOLID" and r["verdict_source"] == "ai"
    assert r["ai"]["provider"] == "claude-local-decision"
    assert "_provider" not in r["ai_assessment"]
    assert [row["period"] for row in r["returns"]] == ["1y", "3y", "5y", "10y"]
    # VT converted to CAD with a flat FX: excess ~ 9% - 8.5%
    assert r["returns"][-1]["excess_cagr"] == pytest.approx(0.5, abs=0.1)
    assert r["fund"]["expense_ratio"] == pytest.approx(0.2) and r["fundamentals"] is None
    assert {s["key"] for s in r["scorecard"]} == {"cost", "diversification", "track_record", "valuation", "risk", "quality",
                                               "dividend"}
    assert r["drawdowns"]["max"] is not None and r["data_as_of"]
    assert any(c["code"] == "not_advice" for c in r["caveats"])
    h.sent.assert_not_called()          # no Grok for ETFs
    h.enrich.assert_not_called()
    prompt = h.ai.call_args.args[1]
    assert "<untrusted_data" in prompt and "not financial advice" in prompt.lower()


def test_ai_failure_falls_back_to_scorecard():
    for kw in ({"ai_result": None}, {"ai_raises": True}):
        r = Harness(**kw).run()
        assert r["verdict_source"] == "scorecard"
        assert r["verdict"] == r["scorecard_verdict"] == "SOLID"
        assert r["ai_assessment"] is None and r["ai"]["status"] == "failed"
        assert any(n["code"] == "ai_unavailable" for n in r["notes"])


def test_ai_disabled_makes_no_ai_calls(monkeypatch):
    monkeypatch.setattr(settings, "ai_enabled", False)
    h = Harness(symbol="ACME", profile=STOCK_PROFILE)
    r = h.run()
    h.ai.assert_not_called()
    h.sent.assert_not_called()
    assert r["ai"]["status"] == "disabled" and r["verdict_source"] == "scorecard"


def test_stock_uses_grok_red_flags_and_fundamentals():
    h = Harness(symbol="ACME", profile=STOCK_PROFILE, ai_result=None)
    r = h.run()
    assert r["asset_type"] == "STOCK" and r["benchmark"] == "SPY"
    h.sent.assert_awaited_once()
    assert r["red_flags"][0]["category"] == "accounting"
    assert r["verdict"] == "NOT_A_GOOD_FIT"   # integrity red flag in fallback
    assert r["fundamentals"]["valuation"]["fcf_yield"] == 5.0
    assert r["fundamentals"]["estimates"]["revision_momentum"] == 2.0
    assert any(c["code"] == "single_stock" for c in r["caveats"])


def test_crypto_high_risk_and_no_grok():
    h = Harness(symbol="BTC-USD", profile={"info": {"quoteType": "CRYPTOCURRENCY"}, "fund": {}, "income": []},
                ai_result=None)
    r = h.run()
    assert r["asset_type"] == "CRYPTO" and r["benchmark"] is None
    assert r["returns"][0]["benchmark_cagr"] is None
    assert r["caveats"][0]["code"] == "crypto_high_risk"
    assert r["verdict"] == "NOT_A_GOOD_FIT"
    h.sent.assert_not_called()


def test_insufficient_history_raises():
    h = Harness()
    h.histories["XEQT.TO"] = _geo(0, 0.0)[:10]
    with pytest.raises(sc.StockCheckError) as e:
        h.run()
    assert e.value.code == "insufficient_data"


def test_long_check_never_writes_to_db():
    from tests.brain_fakes import FakeDB, patch_db

    db = FakeDB({})
    from app.db import queries
    forbidden = {n: MagicMock(side_effect=AssertionError(n)) for n in dir(queries)
                 if n.startswith(("insert_", "update_", "upsert_", "delete_"))}
    with ExitStack() as st:
        st.enter_context(patch_db(db))
        for n, m in forbidden.items():
            st.enter_context(patch.object(queries, n, m))
        Harness(symbol="ACME", profile=STOCK_PROFILE, ai_result=dict(AI_OK)).run()
    assert [c for c in db.calls if c[1] in ("insert", "update", "upsert", "delete")] == []
    for m in forbidden.values():
        m.assert_not_called()


# ============================================================
# provider.assess_long_term routing
# ============================================================

class _Budget:
    def __init__(self):
        self.recorded = []

    async def can_call(self, *a):
        return True, "ok"

    async def record_call(self, *a, **k):
        self.recorded.append(a)


@pytest.fixture
def ai_calls(monkeypatch):
    seen = []
    budget = _Budget()

    async def cli(prompt, json_schema=None, tier="routine", **k):
        seen.append(("cli", tier))
        return {"verdict": "SOLID", "summary": "ok", "strengths": [], "concerns": [], "what_to_watch": [],
                "dca_note": "x", "confidence": 150}

    async def api_call(prompt, schema, tier="routine"):
        seen.append(("api", tier))
        return {"verdict": "NOT_A_GOOD_FIT", "summary": "no", "strengths": [], "concerns": [],
                "what_to_watch": [], "dca_note": "x", "confidence": 40}

    async def get_budget():
        return budget

    monkeypatch.setattr(provider, "_get_budget", get_budget)
    monkeypatch.setitem(sys.modules, "app.ai.claude_local_client", types.SimpleNamespace(call_with_prompt=cli))
    monkeypatch.setitem(sys.modules, "app.ai.claude_client", types.SimpleNamespace(create_structured=api_call))
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")
    return seen, budget


def test_local_mode_uses_cli_decision_tier_only(monkeypatch, ai_calls):
    seen, budget = ai_calls
    monkeypatch.setattr(settings, "claude_local", True)
    r = run(provider.assess_long_term("XEQT.TO", "prompt"))
    assert seen == [("cli", "decision")]
    assert r["verdict"] == "SOLID" and r["confidence"] == 100 and r["_provider"] == "claude-local-decision"
    # Only the free local-CLI usage entry — never a paid provider.
    assert [rec[:2] for rec in budget.recorded] == [("claude-local", "long_term")]


def test_local_mode_failure_never_falls_to_api(monkeypatch, ai_calls):
    seen, _ = ai_calls

    async def bad_cli(*a, **k):
        seen.append(("cli", k.get("tier")))
        return None
    monkeypatch.setitem(sys.modules, "app.ai.claude_local_client", types.SimpleNamespace(call_with_prompt=bad_cli))
    monkeypatch.setattr(settings, "claude_local", True)
    assert run(provider.assess_long_term("XEQT.TO", "prompt")) is None
    assert seen == [("cli", "decision")]


def test_api_mode_uses_api_decision_tier_and_records_budget(monkeypatch, ai_calls):
    seen, budget = ai_calls
    monkeypatch.setattr(settings, "claude_local", False)
    r = run(provider.assess_long_term("XEQT.TO", "prompt"))
    assert seen == [("api", "decision")]
    assert r["verdict"] == "NOT_A_GOOD_FIT" and r["_provider"] == "claude-decision"
    assert budget.recorded and budget.recorded[0][:2] == ("claude", "decision")


def test_invalid_shape_is_rejected(monkeypatch, ai_calls):
    seen, _ = ai_calls

    async def junk(*a, **k):
        return {"verdict": "BUY", "summary": "x"}
    monkeypatch.setitem(sys.modules, "app.ai.claude_local_client", types.SimpleNamespace(call_with_prompt=junk))
    monkeypatch.setattr(settings, "claude_local", True)
    assert run(provider.assess_long_term("X", "p")) is None


def test_cli_args_use_decision_model():
    from app.ai.claude_local_client import build_cli_args
    args = build_cli_args({"type": "object"}, tier="decision")
    assert args[args.index("--model") + 1] == settings.claude_decision_model


# ============================================================
# API: mode param + cache key separation
# ============================================================

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


@pytest.fixture
def fake(monkeypatch):
    runs = {"short": 0, "long": 0}

    async def resolve(raw):
        return {"input": raw.upper(), "symbol": "XEQT.TO", "exchange": "TSX", "price": 45.0}

    async def short(resolved, progress=None):
        runs["short"] += 1
        await asyncio.sleep(0.02)
        return {"symbol": resolved["symbol"], "verdict": "WAIT", "cached": False}

    async def long(resolved, progress=None):
        runs["long"] += 1
        progress("history", 10)
        await asyncio.sleep(0.02)
        return {"mode": "long", "symbol": resolved["symbol"], "verdict": "SOLID", "cached": False}

    monkeypatch.setattr(sc, "resolve_symbol", resolve)
    monkeypatch.setattr(sc, "run_check", short)
    monkeypatch.setattr(lt, "run_long_check", long)
    return runs


def _wait(client, job_id):
    deadline = time.time() + 5
    while time.time() < deadline:
        b = client.get(f"/api/v1/check/{job_id}", headers=_auth()).json()
        if b["status"] != "running":
            return b
        time.sleep(0.02)
    raise AssertionError("timeout")


def test_mode_defaults_to_short_and_rejects_unknown(client, fake):
    b = client.post("/api/v1/check", json={"ticker": "XEQT"}, headers=_auth()).json()
    assert b["mode"] == "short"
    assert _wait(client, b["job_id"])["result"]["verdict"] == "WAIT"
    assert fake == {"short": 1, "long": 0}
    r = client.post("/api/v1/check", json={"ticker": "XEQT", "mode": "medium"}, headers=_auth())
    assert r.status_code == 422


def test_long_mode_runs_long_pipeline_and_caches_separately(client, fake):
    s = client.post("/api/v1/check", json={"ticker": "XEQT"}, headers=_auth()).json()
    _wait(client, s["job_id"])
    lg = client.post("/api/v1/check", json={"ticker": "XEQT", "mode": "long"}, headers=_auth()).json()
    assert lg["status"] == "running" and lg["mode"] == "long"   # short cache does not answer long
    done = _wait(client, lg["job_id"])
    assert done["result"]["mode"] == "long" and done["mode"] == "long"
    assert fake == {"short": 1, "long": 1}
    assert set(api._results) == {"XEQT.TO", "XEQT.TO|long"}
    # both now cached independently; daily limit shared (2 runs)
    again = client.post("/api/v1/check", json={"ticker": "XEQT", "mode": "long"}, headers=_auth()).json()
    assert again["cached"] is True and again["result"]["verdict"] == "SOLID"
    again_s = client.post("/api/v1/check", json={"ticker": "XEQT"}, headers=_auth()).json()
    assert again_s["cached"] is True and again_s["result"]["verdict"] == "WAIT"
    assert api._daily_count() == 2


def test_long_cache_uses_hours_ttl(client, fake, monkeypatch):
    lg = client.post("/api/v1/check", json={"ticker": "XEQT", "mode": "long"}, headers=_auth()).json()
    _wait(client, lg["job_id"])
    at, res = api._results["XEQT.TO|long"]
    # older than the short TTL but within 24h -> still cached
    api._results["XEQT.TO|long"] = (at - settings.stock_check_cache_minutes * 60 - 5, res)
    assert client.post("/api/v1/check", json={"ticker": "XEQT", "mode": "long"}, headers=_auth()).json()["cached"]
    api._results["XEQT.TO|long"] = (at - settings.stock_check_long_cache_hours * 3600 - 5, res)
    b = client.post("/api/v1/check", json={"ticker": "XEQT", "mode": "long"}, headers=_auth()).json()
    assert b["status"] == "running"
    _wait(client, b["job_id"])
    assert fake["long"] == 2


def test_long_mode_shares_daily_limit(client, fake, monkeypatch):
    monkeypatch.setattr(settings, "stock_check_daily_limit", 1)
    s = client.post("/api/v1/check", json={"ticker": "XEQT"}, headers=_auth()).json()
    _wait(client, s["job_id"])
    r = client.post("/api/v1/check", json={"ticker": "XEQT", "mode": "long"}, headers=_auth())
    assert r.status_code == 429 and r.json()["detail"]["code"] == "daily_limit"
