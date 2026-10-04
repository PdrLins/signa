"""Stock suggestions without AI (migration 028): similar, also followed, gaps."""

import pytest

from app.db import queries
from app.services import suggestions as sg
from tests.portfolio_fakes import U1, FakePortfolioDB, make_client


def _p(symbol, qt="EQUITY", sector=None, industry=None, country=None, cap=None, dy=None, category=None, exch=None):
    return {"symbol": symbol, "name": symbol + " Inc", "quote_type": qt, "sector": sector, "industry": industry,
            "country": country, "market_cap": cap, "dividend_yield": dy, "category": category,
            "exchange": exch or ("TSX" if symbol.endswith(".TO") else "B3" if symbol.endswith(".SA") else "US")}


POOL = {p["symbol"]: p for p in [
    _p("ENB.TO", sector="Energy", industry="Oil & Gas Midstream", country="Canada", cap=1e11, dy=0.06),
    _p("TRP.TO", sector="Energy", industry="Oil & Gas Midstream", country="Canada", cap=6e10, dy=0.05),
    _p("PPL.TO", sector="Energy", industry="Oil & Gas Midstream", country="Canada", cap=3e10, dy=0.05),
    _p("KMI", sector="Energy", industry="Oil & Gas Midstream", country="United States", cap=1e11, dy=0.04),
    _p("SU.TO", sector="Energy", industry="Oil & Gas Integrated", country="Canada", cap=7e10, dy=0.04),
    _p("SHOP.TO", sector="Technology", industry="Software", country="Canada", cap=1.5e11),
    _p("XEI.TO", qt="ETF", category="Canadian Dividend & Income Equity", dy=0.05),
    _p("TQQQ", qt="ETF", category="Trading--Leveraged Equity"),
    _p("PETR4.SA", sector="Energy", industry="Oil & Gas Integrated", country="Brazil", cap=4e11, dy=0.1),
]}


# ---------------------------------------------------------------- similar (pure)

def test_similar_same_industry_first_and_kind_only():
    rows = sg.similar_to("ENB.TO", POOL, followed={"TRP.TO"}, home_exch="TSX", limit=10)
    syms = [r["symbol"] for r in rows]
    assert syms[:2] == ["TRP.TO", "PPL.TO"]                 # same industry, same country, home exchange
    assert "KMI" in syms and syms.index("KMI") > 1          # same industry, other country
    assert "SU.TO" in syms                                  # same sector only
    assert "XEI.TO" not in syms and "SHOP.TO" not in syms   # a fund / another sector never
    first = rows[0]
    assert first["reason"] == "same_industry" and first["params"] == {"industry": "Oil & Gas Midstream"}
    assert first["followed"] is True and rows[1]["followed"] is False


def test_similar_funds_use_curated_groups_first():
    rows = sg.similar_to("XEQT.TO", POOL, set(), "TSX", 10)
    assert rows[0]["reason"] == "same_fund_group" and rows[0]["symbol"] == "VEQT.TO"
    assert all(r["symbol"] != "XEQT.TO" for r in rows)


def test_unknown_symbol_has_no_similar():
    assert sg.similar_to("NOPE", POOL, set(), None, 10) == []


def test_home_exchange_by_country():
    assert (sg.home_exchange("BR"), sg.home_exchange("CA"), sg.home_exchange("US")) == ("B3", "TSX", "US")


def test_profile_from_info_yield_is_a_fraction():
    row = sg.profile_from_info("ENB.TO", {"longName": "Enbridge", "quoteType": "EQUITY", "sector": "Energy",
                                          "industry": "Oil & Gas Midstream", "dividendRate": 3.77,
                                          "regularMarketPrice": 62.8, "dividendYield": 6.0, "currency": "CAD"})
    assert row["exchange"] == "TSX" and row["currency"] == "CAD"
    assert row["dividend_yield"] == pytest.approx(0.06, abs=0.001)
    assert sg.profile_from_info("X", {}) is None


# ---------------------------------------------------------------- co-follows (pure)

def test_cofollows_need_min_users_and_name_nobody():
    rows = [{"user_id": f"u{i}", "symbol": s} for i in range(12) for s in ("ENB.TO", "TRP.TO")]
    rows += [{"user_id": f"v{i}", "symbol": s} for i in range(8) for s in ("ENB.TO", "SHOP.TO")]   # only 8
    pairs = sg.compute_cofollows(rows)
    assert {(r["symbol"], r["other"], r["users"]) for r in pairs} == {("ENB.TO", "TRP.TO", 12), ("TRP.TO", "ENB.TO", 12)}
    assert all(set(r) == {"symbol", "other", "users"} for r in pairs)


def test_only_real_returning_accounts_count():
    from datetime import datetime, timezone
    now = datetime(2026, 12, 1, tzinfo=timezone.utc)
    users = [{"id": "old_back", "created_at": "2026-10-01T00:00:00Z", "last_seen_at": "2026-11-20T00:00:00Z"},
             {"id": "new", "created_at": "2026-11-25T00:00:00Z", "last_seen_at": "2026-11-30T00:00:00Z"},
             {"id": "never_back", "created_at": "2026-10-01T00:00:00Z", "last_seen_at": "2026-10-02T00:00:00Z"}]
    assert sg.eligible_users(users, now) == {"old_back"}
    rows = [{"user_id": f"bot{i}", "symbol": s} for i in range(20) for s in ("AAPL", "PUMP")]
    assert sg.compute_cofollows(rows, eligible={"old_back"}) == []   # 20 fresh bots count for nothing


def test_also_followed_rounds_counts_and_skips_followed():
    rows = [{"symbol": "ENB.TO", "other": "TRP.TO", "users": 23}, {"symbol": "ENB.TO", "other": "SU.TO", "users": 12},
            {"symbol": "ENB.TO", "other": "PPL.TO", "users": 30}]
    out = sg.also_followed(["ENB.TO"], rows, exclude={"PPL.TO"}, followed={"PPL.TO"}, pool=POOL, limit=10)
    assert [(r["symbol"], r["params"]["users"]) for r in out] == [("TRP.TO", 20), ("SU.TO", 10)]
    assert out[0]["reason"] == "also_followed" and out[0]["params"]["via"] == "ENB.TO"


# ---------------------------------------------------------------- gaps (pure)

def _pos(symbol, value):
    return {"symbol": symbol, "value_home": value}


def test_gaps_heavy_position_sector_home_only():
    pos = [_pos("ENB.TO", 6000), _pos("TRP.TO", 2000), _pos("SU.TO", 1500), _pos("SHOP.TO", 500)]
    gaps = {g["code"]: g for g in sg.find_gaps(pos, POOL, "CAD", "CA")}
    assert gaps["single_position_heavy"]["params"] == {"symbol": "ENB.TO", "pct": 60.0}
    assert gaps["sector_heavy"]["params"] == {"sector": "Energy", "pct": 95.0}
    assert gaps["home_country_only"]["params"]["pct"] == 100.0
    assert [i["symbol"] for i in gaps["home_country_only"]["ideas"]] == ["XEQT.TO", "VEQT.TO", "XEF.TO"]
    assert "no_dividend_payers" not in gaps


def test_gaps_no_dividend_payers_and_brazil_ideas():
    pool = {**POOL, "AAA.SA": _p("AAA.SA", sector="Tech", country="Brazil", cap=1e9),
            "BBB.SA": _p("BBB.SA", sector="Health", country="Brazil", cap=1e9),
            "CCC.SA": _p("CCC.SA", sector="Retail", country="Brazil", cap=1e9)}
    gaps = {g["code"]: g for g in sg.find_gaps([_pos("AAA.SA", 100), _pos("BBB.SA", 100), _pos("CCC.SA", 100)],
                                              pool, "BRL", "BR")}
    assert [i["symbol"] for i in gaps["no_dividend_payers"]["ideas"]] == ["DIVO11.SA"]
    assert [i["symbol"] for i in gaps["home_country_only"]["ideas"]] == ["IVVB11.SA", "WRLD11.SA"]


def test_no_gaps_for_tiny_or_global_portfolios():
    assert sg.find_gaps([_pos("ENB.TO", 100)], POOL, "CAD", "CA") == []
    pos = [_pos("XEQT.TO", 5000), _pos("ENB.TO", 1000), _pos("XEI.TO", 1000)]
    codes = {g["code"] for g in sg.find_gaps(pos, POOL, "CAD", "CA")}
    assert "home_country_only" not in codes and "single_position_heavy" not in codes   # a fund isn't "one position"


# ---------------------------------------------------------------- endpoints

@pytest.fixture
def db(monkeypatch):
    d = FakePortfolioDB(monkeypatch)
    d.settings[U1] = {"user_id": U1, "home_currency": "CAD", "country": "CA"}
    monkeypatch.setattr(queries, "get_symbol_profiles", lambda: list(POOL.values()))
    monkeypatch.setattr(queries, "get_cofollows", lambda syms: [
        {"symbol": "ENB.TO", "other": s, "users": n}
        for s, n in (("TRP.TO", 40), ("SU.TO", 35), ("PPL.TO", 25), ("KMI", 15), ("SHOP.TO", 11))])
    monkeypatch.setattr("app.services.slots.followed_symbols", lambda uid: {"ENB.TO"})
    return d


def _client(monkeypatch, level):
    from app.api.v1 import suggestions as api
    return make_client(monkeypatch, api.router, level=level)


def test_stock_similar_free_gets_three_premium_ten(monkeypatch, db):
    free = _client(monkeypatch, "free").get("/api/v1/stocks/ENB.TO/similar").json()
    assert free["symbol"] == "ENB.TO" and len(free["similar"]) == 3 and len(free["also_followed"]) == 3
    assert free["more_locked"] is True and free["disclaimer"] == "ideas_not_advice"
    prem = _client(monkeypatch, "premium").get("/api/v1/stocks/ENB.TO/similar").json()
    assert len(prem["also_followed"]) == 5 and prem["more_locked"] is False


def test_portfolio_suggestions_gaps_premium_only(monkeypatch, db):
    a = db.add_account(U1, "Main", currency="CAD", cash_balance=0)
    for sym, shares in (("ENB.TO", 100), ("TRP.TO", 30), ("SU.TO", 20)):
        db.add_holding(U1, sym, a, shares=shares, avg_cost=50)
        db.quotes[sym] = {"symbol": sym, "price": 60.0, "prev_close": 60.0, "currency": "CAD",
                          "as_of": "2026-10-02T14:00:00+00:00"}
    monkeypatch.setattr("app.services.slots.followed_symbols", lambda uid: {"ENB.TO", "TRP.TO", "SU.TO"})
    free = _client(monkeypatch, "free").get("/api/v1/suggestions").json()
    assert free["gaps"] == [] and free["gaps_locked"] is True
    assert [r["symbol"] for r in free["also_followed"]] == ["PPL.TO", "KMI", "SHOP.TO"]   # followed ones left out
    prem = _client(monkeypatch, "premium").get("/api/v1/suggestions").json()
    assert prem["gaps_locked"] is False and {g["code"] for g in prem["gaps"]} >= {"single_position_heavy", "home_country_only"}


def test_migration_required_before_028(monkeypatch, db):
    def missing():
        raise RuntimeError('relation "public.symbol_profiles" does not exist (42P01)')
    monkeypatch.setattr(queries, "get_symbol_profiles", missing)
    r = _client(monkeypatch, "free").get("/api/v1/stocks/ENB.TO/similar")
    assert r.status_code == 503 and r.json()["detail"]["migration"] == "028_suggestions.sql"


def test_nightly_writes_pairs_and_refreshes_stale_profiles(monkeypatch):
    from datetime import datetime, timezone
    written = {}
    monkeypatch.setattr(queries, "get_follow_rows", lambda: [{"user_id": f"u{i}", "symbol": s}
                                                             for i in range(10) for s in ("ENB.TO", "TRP.TO")])
    monkeypatch.setattr(queries, "get_users_age", lambda: [
        {"id": f"u{i}", "created_at": "2026-08-01T00:00:00Z", "last_seen_at": "2026-09-20T00:00:00Z"}
        for i in range(10)])
    monkeypatch.setattr(queries, "replace_cofollows", lambda rows, stamp: written.setdefault("pairs", rows) and len(rows))
    monkeypatch.setattr(queries, "get_symbol_profiles", lambda: [
        {"symbol": "ENB.TO", "updated_at": "2026-10-02T00:00:00+00:00"}])   # fresh: not refetched
    monkeypatch.setattr(queries, "upsert_symbol_profiles", lambda rows: written.setdefault("profiles", rows))
    fetched = []
    monkeypatch.setattr(sg, "_fetch_info", lambda s: fetched.append(s) or {"longName": s, "quoteType": "EQUITY"})
    monkeypatch.setattr(sg, "_curated", lambda: {"XEQT.TO"})
    out = sg.run_nightly(datetime(2026, 10, 3, tzinfo=timezone.utc))
    assert out["pairs"] == 2 and out["profiles"] == 2
    assert sorted(fetched) == ["TRP.TO", "XEQT.TO"]


def test_fund_yield_from_yield_field_not_zero_trailing():
    schd = {"dividendRate": None, "trailingAnnualDividendRate": 0.0, "trailingAnnualDividendYield": 0.0,
            "dividendYield": 3.0, "yield": 0.03, "regularMarketPrice": 32.72}
    assert sg.dividend_yield_from_info(schd, 32.72) == pytest.approx(0.03)
    assert sg.dividend_yield_from_info({"dividendYield": 1.57}, 45.0) == pytest.approx(0.0157)
    assert sg.dividend_yield_from_info({"trailingAnnualDividendYield": 0.0}, 10.0) == 0.0
    assert sg.dividend_yield_from_info({}, 10.0) is None
