"""Symbol search: local fuzzy + Yahoo (mocked), filtering, dedupe, labels,
caching, API auth. No network, no DB."""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import symbols as api
from app.core.security import create_access_token
from app.middleware import auth as auth_mw
from app.services import symbol_search as ss

LOCAL = [
    {"symbol": "TSLA", "name": "Tesla, Inc.", "exchange": "NASDAQ", "type_hint": "stock"},
    {"symbol": "RY.TO", "name": "Royal Bank of Canada", "exchange": "TSX", "type_hint": "stock"},
    {"symbol": "XEQT.TO", "name": "iShares Core Equity ETF Portfolio", "exchange": "TSX", "type_hint": "etf"},
    {"symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ", "type_hint": "stock"},
    {"symbol": "BTC-USD", "name": "Bitcoin", "exchange": None, "type_hint": "crypto"},
]

TSLA_Q = {"symbol": "TSLA", "shortname": "Tesla, Inc.", "longname": "Tesla, Inc.", "exchange": "NMS", "quoteType": "EQUITY"}


def _local():
    out = []
    for c in LOCAL:
        c = dict(c)
        c["words"] = ss._words(c["name"])
        c["base"] = ss.base_symbol(c["symbol"])
        out.append(c)
    return out


class FakeYahoo:
    def __init__(self, table: dict[str, list[dict]]):
        self.table = table
        self.calls: list[str] = []

    def __call__(self, q):
        self.calls.append(q)
        return list(self.table.get(q.lower(), []))


@pytest.fixture
def env(monkeypatch):
    ss._reset_caches()
    monkeypatch.setattr(ss, "_load_local", _local)

    def install(table):
        fake = FakeYahoo(table)
        monkeypatch.setattr(ss, "_yahoo_raw", fake)
        return fake

    yield install
    ss._reset_caches()


def run(q, limit=8):
    return asyncio.run(ss.search(q, limit))


# ── typo + names ──

def test_typo_matches_locally_and_requeries_yahoo_with_correction(env):
    fake = env({"tesla": [TSLA_Q]})
    res = run("telas")
    assert res[0]["symbol"] == "TSLA"
    assert res[0]["name"] == "Tesla, Inc."
    assert res[0]["exchange_label"] == "NASDAQ"
    assert fake.calls == ["telas", "tesla"]


def test_typo_without_local_candidate_has_no_correction(env):
    fake = env({})
    assert run("zzqxy") == []
    assert fake.calls == ["zzqxy"]


def test_name_search_via_yahoo(env):
    env({"dollarama": [
        {"symbol": "DOL.TO", "shortname": "DOLLARAMA INC", "longname": "Dollarama Inc.", "exchange": "TOR", "quoteType": "EQUITY"},
        {"symbol": "DLMAF", "shortname": "DOLLARAMA INC", "exchange": "PNK", "quoteType": "EQUITY"},
    ]})
    res = run("dollarama")
    assert [r["symbol"] for r in res] == ["DOL.TO", "DLMAF"]  # OTC last
    assert res[0]["exchange_label"] == "TSX"
    assert res[0]["type"] == "stock"
    assert res[0]["source"] == "yahoo"
    assert res[1]["exchange_label"] == "OTC"


def test_local_symbol_base_match(env):
    env({})
    res = run("xeqt")
    assert res[0]["symbol"] == "XEQT.TO"
    assert res[0]["type"] == "etf"
    assert res[0]["exchange_label"] == "TSX"
    assert res[0]["source"] == "signa"


def test_crypto_alias(env):
    env({})
    assert run("bitcoin")[0]["symbol"] == "BTC-USD"
    res = run("btc")
    assert res[0]["symbol"] == "BTC-USD"
    assert res[0]["exchange_label"] == "Crypto"
    assert res[0]["type"] == "crypto"


# ── filtering / dedupe / labels ──

def test_filters_futures_funds_foreign_and_non_usd_crypto(env):
    env({"gold": [
        {"symbol": "GC=F", "shortname": "Gold", "exchange": "CMX", "quoteType": "FUTURE"},
        {"symbol": "GLD", "shortname": "SPDR Gold", "exchange": "PCX", "quoteType": "ETF"},
        {"symbol": "GOLD.MU", "shortname": "Gold Corp", "exchange": "MUN", "quoteType": "EQUITY"},
        {"symbol": "GLDX.F", "shortname": "Gold X", "exchange": "FRA", "quoteType": "EQUITY"},
        {"symbol": "FGLDX", "shortname": "Gold fund", "exchange": "NAS", "quoteType": "MUTUALFUND"},
        {"symbol": "PAXG-EUR", "shortname": "Gold token", "exchange": "CCC", "quoteType": "CRYPTOCURRENCY"},
        {"symbol": "PAXG-USD", "shortname": "PAX Gold USD", "exchange": "CCC", "quoteType": "CRYPTOCURRENCY"},
    ]})
    res = run("gold")
    assert [r["symbol"] for r in res] == ["GLD", "PAXG-USD"]
    assert res[0]["exchange_label"] == "NYSE Arca" and res[0]["type"] == "etf"
    assert res[1]["exchange_label"] == "Crypto" and res[1]["type"] == "crypto"


def test_dedupe_local_and_yahoo(env):
    env({"tesla": [TSLA_Q, dict(TSLA_Q)]})
    res = run("tesla")
    assert [r["symbol"] for r in res].count("TSLA") == 1
    assert res[0]["symbol"] == "TSLA"
    assert res[0]["source"] == "signa"


def test_dual_listing_tsx_labelled_and_grouped(env):
    env({"royal bank": [
        {"symbol": "RY", "shortname": "Royal Bank Of Canada", "exchange": "NYQ", "quoteType": "EQUITY"},
        {"symbol": "RY.TO", "shortname": "ROYAL BANK OF CANADA", "exchange": "TOR", "quoteType": "EQUITY"},
        {"symbol": "RBSPF", "shortname": "Royal Bank of Scotland", "exchange": "PNK", "quoteType": "EQUITY"},
    ]})
    res = run("royal bank")
    assert [r["symbol"] for r in res[:2]] == ["RY.TO", "RY"]
    assert res[0]["exchange_label"] == "TSX"
    assert res[1]["exchange_label"] == "NYSE"
    assert res[-1]["symbol"] == "RBSPF"


def test_limit(env):
    env({"b": [{"symbol": f"B{i}", "shortname": f"B {i}", "exchange": "NYQ", "quoteType": "EQUITY"} for i in range(10)]})
    assert len(run("b", limit=3)) == 3


# ── caching ──

def test_yahoo_cached_per_normalized_query(env):
    fake = env({"tesla": [TSLA_Q]})
    run("tesla")
    run("  Tesla ")
    run("TESLA")
    assert fake.calls == ["tesla"]


def test_yahoo_failure_not_cached(env, monkeypatch):
    calls = []

    def boom(q):
        calls.append(q)
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(ss, "_yahoo_raw", boom)
    res = run("apple")
    assert res[0]["symbol"] == "AAPL"  # local still answers
    run("apple")
    assert len(calls) == 2


def test_local_candidates_loaded_once(env, monkeypatch):
    loads = []

    def load():
        loads.append(1)
        return _local()

    monkeypatch.setattr(ss, "_load_local", load)
    env({})
    run("tsla")
    run("aapl")
    assert len(loads) == 1


# ── query normalization ──

@pytest.mark.parametrize("q", ["", "   ", "!!!", "@#$%", None])
def test_empty_or_garbage_query(env, q):
    fake = env({})
    assert run(q) == []
    assert fake.calls == []


def test_normalize_query_caps_length_and_spaces():
    assert ss.normalize_query("  royal    bank  ") == "royal bank"
    assert len(ss.normalize_query("x" * 100)) == ss.MAX_QUERY_LEN


# ── API ──

@pytest.fixture
def client(env, monkeypatch):
    monkeypatch.setattr(auth_mw, "is_token_blacklisted", lambda jti: False)
    monkeypatch.setattr(auth_mw, "insert_audit_log", lambda *a, **k: None)
    env({"tesla": [TSLA_Q]})
    app = FastAPI()
    app.add_middleware(auth_mw.AuthMiddleware)
    app.include_router(api.router, prefix="/api/v1")
    with TestClient(app) as c:
        yield c


def _auth():
    return {"Authorization": f"Bearer {create_access_token('u1', 'owner')}"}


def test_api_requires_auth(client):
    assert client.get("/api/v1/symbols/search?q=tesla").status_code == 401


def test_api_returns_results(client):
    r = client.get("/api/v1/symbols/search", params={"q": "telas", "limit": 5}, headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "telas"
    assert body["results"][0] == {
        "symbol": "TSLA", "name": "Tesla, Inc.", "exchange": "NMS", "exchange_label": "NASDAQ",
        "type": "stock", "source": "signa",
    }


def test_api_empty_query(client):
    r = client.get("/api/v1/symbols/search", params={"q": "  "}, headers=_auth())
    assert r.status_code == 200
    assert r.json() == {"query": "", "results": []}


def test_api_rejects_bad_limit(client):
    assert client.get("/api/v1/symbols/search", params={"q": "a", "limit": 99}, headers=_auth()).status_code == 422


def test_irrelevant_yahoo_answer_triggers_corrected_requery(env):
    # Yahoo answers the typo with loosely related names; the correction wins.
    fake = env({
        "telas": [{"symbol": "TXN", "shortname": "Texas Instruments", "exchange": "NMS", "quoteType": "EQUITY"}],
        "tesla": [TSLA_Q],
    })
    res = run("telas")
    assert res[0]["symbol"] == "TSLA"
    assert "TXN" in [r["symbol"] for r in res]
    assert fake.calls == ["telas", "tesla"]


def test_transposition_beats_substitution_for_correction():
    cands = [
        {"symbol": "TPL", "name": "Texas Pacific Land", "words": ss._words("Texas Pacific Land"), "base": "TPL"},
        {"symbol": "TSLA", "name": "Tesla", "words": ["tesla"], "base": "TSLA"},
    ]
    scored, corrections = ss.score_local("telas", cands)
    assert corrections == {"telas": "tesla"}
    assert max(scored, key=lambda x: x[0])[1]["symbol"] == "TSLA"


def test_preferred_shares_rank_after_common(env):
    env({"royal bank": [
        {"symbol": "RY-PS.TO", "shortname": "Royal Bank of Canada Pref", "exchange": "TOR", "quoteType": "EQUITY"},
        {"symbol": "RY", "shortname": "Royal Bank Of Canada", "exchange": "NYQ", "quoteType": "EQUITY"},
    ]})
    syms = [r["symbol"] for r in run("royal bank")]
    assert syms.index("RY-PS.TO") > syms.index("RY")


def test_known_names_seed_local_candidates(monkeypatch):
    from app.db import queries
    monkeypatch.setattr(queries, "get_active_tickers", lambda: [{"symbol": "TSLA", "name": None, "exchange": "NASDAQ"}])
    monkeypatch.setattr(queries, "get_all_holdings", lambda: [{"symbol": "XEQT.TO", "name": "iShares Core Equity", "asset_type": "ETF"}])
    monkeypatch.setattr(queries, "get_all_watchlist_symbols", lambda: {"hood"})
    cands = {c["symbol"]: c for c in ss._load_local()}
    assert cands["TSLA"]["name"] == "Tesla"
    assert cands["XEQT.TO"]["name"] == "iShares Core Equity"  # DB name wins
    assert cands["XEQT.TO"]["type_hint"] == "ETF"
    assert "HOOD" in cands and "BTC-USD" in cands
