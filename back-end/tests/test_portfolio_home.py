"""Portfolio summary / history / performance (fakes only: no network, no DB)."""

from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from app.api.v1 import portfolio_home
from app.services import portfolio_performance as perf
from tests.portfolio_fakes import U1, FakePortfolioDB, make_client

TODAY = perf.today_et()


@pytest.fixture(autouse=True)
def _clear():
    perf.clear_cache()
    yield
    perf.clear_cache()


@pytest.fixture
def db(monkeypatch):
    d = FakePortfolioDB(monkeypatch)
    d.settings[U1] = {"user_id": U1, "home_currency": "CAD"}
    return d


def _setup(db):
    a = db.add_account(U1, "Questrade", currency="CAD", cash_balance=100)
    b = db.add_account(U1, "IBKR", currency="USD", cash_balance=50)
    db.add_holding(U1, "XEQT.TO", a, shares=10, avg_cost=30)
    db.add_holding(U1, "NVDA", b, shares=2, avg_cost=100)
    db.add_holding(U1, "NVDA", a, shares=1, avg_cost=120)
    now = datetime.now(timezone.utc).isoformat()
    db.quotes["XEQT.TO"] = {"symbol": "XEQT.TO", "price": 33.0, "prev_close": 32.0, "currency": "CAD", "as_of": now}
    db.quotes["NVDA"] = {"symbol": "NVDA", "price": 150.0, "prev_close": 140.0, "currency": "USD",
                         "as_of": "2026-09-30T14:00:00+00:00"}
    return a, b


def _client(monkeypatch, level="owner"):
    return make_client(monkeypatch, portfolio_home.router, level=level)


def _closes(values, end=TODAY):
    idx = pd.bdate_range(end=pd.Timestamp(end), periods=len(values))
    return pd.Series(values, index=idx, dtype=float)


# ---------------------------------------------------------------- summary

def test_summary_math_without_transactions(monkeypatch, db):
    _setup(db)
    body = _client(monkeypatch).get("/api/v1/portfolio/summary").json()
    assert body["currency"] == "CAD"
    assert body["market_value"] == pytest.approx(330 + 3 * 150 * 1.4)
    assert body["cash"] == pytest.approx(100 + 50 * 1.4)
    assert body["total"] == pytest.approx(960 + 170)
    assert body["day_change"]["abs"] == pytest.approx(10 + 3 * 10 * 1.4)
    assert body["day_change"]["pct"] == pytest.approx(52 / 908 * 100, abs=0.01)
    tg = body["total_gain"]
    assert tg["abs"] == pytest.approx(212) and tg["dividends_included"] is False
    assert tg["pct"] == pytest.approx(212 / 748 * 100, abs=0.01)
    assert body["holdings_count"] == 2 and body["delayed_minutes"] == 15
    assert body["as_of"] == "2026-09-30T14:00:00+00:00"   # the oldest quote time
    assert body["estimated"] is False


@pytest.mark.parametrize("scope", ["", "account", "person"])
def test_holdings_value_matches_summary_market_value(monkeypatch, db, scope):
    from app.api.v1 import holdings as holdings_api
    a, b = _setup(db)
    p = db.insert_person(U1, {"name": "Ana"})["id"]
    db.accounts[b]["person_id"] = p
    db.add_holding(U1, "VFV.TO", None, shares=4, avg_cost=100,
                   holding_status={"price": 120.0, "prev_close": 119.0})   # no quote: last close
    # the monitor's stale close must not leak into the value
    for h in db.holdings.values():
        h.setdefault("holding_status", {"price": 1.0})
    qs = {"": "", "account": f"?account_id={a}", "person": f"?person_id={p}"}[scope]
    c = make_client(monkeypatch, portfolio_home.router, holdings_api.router)
    summary = c.get(f"/api/v1/portfolio/summary{qs}").json()
    hold = c.get(f"/api/v1/holdings{qs}").json()
    assert hold["totals"]["value_cad"] == pytest.approx(summary["market_value"], abs=0.01)
    items_sum = sum(i["position"]["value_cad"] for i in hold["items"] if i["position"]["value_cad"] is not None)
    assert items_sum == pytest.approx(summary["market_value"], abs=0.01 * len(hold["items"]))


def test_summary_day_change_ignores_last_close_positions(monkeypatch, db):
    _setup(db)
    a = next(iter(db.accounts))
    db.add_holding(U1, "OLD.TO", a, shares=10, holding_status={"price": 50.0, "prev_close": 40.0})
    body = _client(monkeypatch).get("/api/v1/portfolio/summary").json()
    assert body["market_value"] == pytest.approx(330 + 3 * 150 * 1.4 + 500)
    assert body["day_change"]["abs"] == pytest.approx(10 + 3 * 10 * 1.4)   # OLD.TO's +100 is yesterday's
    assert body["day_change"]["pct"] == pytest.approx(52 / 908 * 100, abs=0.01)


def test_summary_with_transactions_adds_realized_and_dividends(monkeypatch, db):
    a, b = _setup(db)
    db.insert_transactions(U1, [
        {"account_id": b, "symbol": "NVDA", "type": "buy", "trade_date": "2026-01-10", "quantity": 2, "price": 100,
         "amount": 200, "currency": "USD", "fee": 0},
        {"account_id": b, "symbol": "NVDA", "type": "sell", "trade_date": "2026-02-10", "quantity": 1, "price": 130,
         "amount": 130, "currency": "USD", "fee": 0},
        {"account_id": a, "symbol": "XEQT.TO", "type": "dividend", "trade_date": "2026-03-31", "quantity": 10,
         "price": None, "amount": 10, "currency": "CAD", "fee": 0},
    ])
    tg = _client(monkeypatch).get("/api/v1/portfolio/summary").json()["total_gain"]
    assert tg["dividends_included"] is True
    assert tg["realized"] == pytest.approx(30 * 1.4) and tg["dividends"] == pytest.approx(10)
    assert tg["abs"] == pytest.approx(212 + 42 + 10)


def test_summary_scope_and_estimated_flags(monkeypatch, db):
    a, _ = _setup(db)
    db.add_holding(U1, "ZZZ", a, shares=5)                     # no quote, no last close
    db.add_holding(U1, "OLD.TO", a, shares=4, holding_status={"price": 10.0, "as_of": "2026-09-29"})
    c = _client(monkeypatch)
    body = c.get(f"/api/v1/portfolio/summary?account_id={a}").json()
    assert body["market_value"] == pytest.approx(330 + 210 + 40)
    assert body["cash"] == 100
    f = body["estimated_flags"]
    assert body["estimated"] is True and f["unpriced"] == ["ZZZ"] and f["prices_from_last_close"] == ["OLD.TO"]
    assert "OLD.TO" in f["missing_cost"]


def test_summary_scope_errors(monkeypatch, db):
    _setup(db)
    c = _client(monkeypatch)
    r = c.get("/api/v1/portfolio/summary?account_id=00000000-0000-0000-0000-00000000000a")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "account_not_found"
    r = c.get("/api/v1/portfolio/summary?person_id=00000000-0000-0000-0000-00000000000b")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "person_not_found"


def test_summary_person_scope(monkeypatch, db):
    a, b = _setup(db)
    p = db.insert_person(U1, {"name": "Ray"})["id"]
    db.update_account(b, U1, {"person_id": p})
    body = _client(monkeypatch).get(f"/api/v1/portfolio/summary?person_id={p}").json()
    assert body["holdings_count"] == 1 and body["market_value"] == pytest.approx(2 * 150 * 1.4)


def test_summary_migration_missing(monkeypatch, db):
    db.missing = True
    r = _client(monkeypatch).get("/api/v1/portfolio/summary")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "migration_required"


# ---------------------------------------------------------------- history

def _one_holding(db):
    a = db.add_account(U1, "Main", currency="CAD", cash_balance=0)
    db.add_holding(U1, "XEQT.TO", a, shares=10, avg_cost=30)
    db.quotes["XEQT.TO"] = {"symbol": "XEQT.TO", "price": 40.0, "prev_close": 39.0, "currency": "CAD",
                            "as_of": "2026-09-30T14:00:00+00:00"}
    db.closes["XEQT.TO"] = _closes([20 + v / 3 for v in range(60)])   # 60 business days, rising
    db.closes["SPY"] = _closes([100.0 + v for v in range(60)])
    return a


def test_history_estimated_from_closes_and_compare_scaling(monkeypatch, db):
    _one_holding(db)
    body = _client(monkeypatch).get("/api/v1/portfolio/history?range=1M&compare=spy").json()
    assert body["estimated"] is True and body["estimated_reason"] == "no_snapshots"
    s = body["series"]
    assert s[-1] == {"t": TODAY.isoformat(), "value": 400.0}      # live total closes the series
    base = perf.range_start("1M", TODAY)
    assert date.fromisoformat(s[0]["t"]) <= base
    assert body["range_return_pct"] == pytest.approx((400 / s[0]["value"] - 1) * 100, abs=0.01)
    cmp_ = body["compare"]
    assert cmp_["symbol"] == "SPY" and cmp_["series"][0]["value"] == s[0]["value"]
    spy = db.closes["SPY"]
    spy0 = float(spy[spy.index <= pd.Timestamp(date.fromisoformat(s[0]["t"]))].iloc[-1])
    assert cmp_["range_return_pct"] == pytest.approx((159 / spy0 - 1) * 100, abs=0.01)
    assert body["delayed_minutes"] == 15 and body["interval"] == "1d"


def test_history_uses_snapshots(monkeypatch, db):
    _one_holding(db)
    base = perf.range_start("1M", TODAY)
    for i, d in enumerate([base - timedelta(days=1), base + timedelta(days=5)]):
        db.snapshots.append({"user_id": U1, "snapshot_date": d.isoformat(), "account_id": None,
                             "market_value": 300 + i * 10, "cash": 5})
    body = _client(monkeypatch).get("/api/v1/portfolio/history?range=1M").json()
    assert body["estimated"] is False and body["estimated_reason"] is None
    assert [p["value"] for p in body["series"]] == [305.0, 315.0, 400.0]
    assert body["sources"]["snapshots"] == 2


def test_history_partial_snapshots(monkeypatch, db):
    _one_holding(db)
    db.snapshots.append({"user_id": U1, "snapshot_date": (TODAY - timedelta(days=3)).isoformat(),
                         "account_id": None, "market_value": 390, "cash": 0})
    body = _client(monkeypatch).get("/api/v1/portfolio/history?range=1M").json()
    assert body["estimated_reason"] == "partial_snapshots"
    assert any(p["value"] == 390 for p in body["series"]) and body["series"][-1]["value"] == 400


def test_combine_daily_pure():
    est = [(date(2026, 9, 1), 100.0), (date(2026, 9, 2), 101.0), (date(2026, 9, 3), 102.0)]
    pts, reason = perf.combine_daily(est, {date(2026, 9, 3): 150.0}, date(2026, 9, 1), date(2026, 9, 4), 160.0)
    assert pts == [(date(2026, 9, 1), 100.0), (date(2026, 9, 2), 101.0), (date(2026, 9, 3), 150.0),
                   (date(2026, 9, 4), 160.0)] and reason == "partial_snapshots"
    assert perf.combine_daily([], {}, date(2026, 9, 1), date(2026, 9, 4), None) == ([], "no_history")


def test_scale_benchmark_pure():
    pts = [(1, 1000.0), (2, 1100.0), (3, 1050.0)]
    bench = [(0, 50.0), (2, 55.0), (3, 60.0)]
    out = perf.scale_benchmark(pts, bench)
    assert out == [(1, 1000.0), (2, 1100.0), (3, 1200.0)]
    assert perf.range_return(out) == pytest.approx(20.0)


def test_history_1d_interval_by_level(monkeypatch, db):
    _one_holding(db)
    seen = []
    t0 = datetime.combine(TODAY, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=14)

    def fake(symbols, interval, prepost=False):
        seen.append((tuple(symbols), interval, prepost))
        return {"XEQT.TO": [(t0, 39.5), (t0 + timedelta(minutes=5), 40.0)]}
    monkeypatch.setattr(perf, "_download_intraday", fake)
    body = _client(monkeypatch, "premium").get("/api/v1/portfolio/history?range=1D").json()
    assert body["interval"] == "5m" and [p["value"] for p in body["series"]] == [395.0, 400.0]
    assert body["estimated"] is False
    assert seen[-1][2] is True                        # Premium: pre/after-hours bars (migration 021)
    assert body["session"]["open"] < body["session"]["close"]
    perf.clear_cache()
    body = _client(monkeypatch, "free").get("/api/v1/portfolio/history?range=1d").json()
    # 5-minute bars for everyone since migration 022; pre/after-hours stay Premium
    assert body["interval"] == "5m" and seen[-1][1] == "5m" and seen[-1][2] is False
    # cached per symbol: a second call does not download again
    _client(monkeypatch, "free").get("/api/v1/portfolio/history?range=1D")
    assert len(seen) == 2


def test_history_1d_without_bars_is_estimated(monkeypatch, db):
    _one_holding(db)
    monkeypatch.setattr(perf, "_download_intraday", lambda s, i: {})
    body = _client(monkeypatch).get("/api/v1/portfolio/history?range=1D").json()
    assert body["estimated_reason"] == "no_intraday"
    assert [p["value"] for p in body["series"]] == [390.0, 400.0]


def test_history_all_needs_full_history(monkeypatch, db):
    _one_holding(db)
    r = _client(monkeypatch, "free").get("/api/v1/portfolio/history?range=ALL")
    assert r.status_code == 403 and r.json()["detail"]["feature"] == "feature.full_history"
    r = _client(monkeypatch, "free").get("/api/v1/portfolio/performance?range=ALL")
    assert r.status_code == 403
    assert _client(monkeypatch, "premium").get("/api/v1/portfolio/history?range=ALL").status_code == 200


def test_history_validation(monkeypatch, db):
    c = _client(monkeypatch)
    r = c.get("/api/v1/portfolio/history?range=2Y")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_range"
    r = c.get("/api/v1/portfolio/history?range=1M&compare=AAPL")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_compare"


def test_history_records_usage(monkeypatch, db):
    from app.services import usage_metrics
    _one_holding(db)
    _client(monkeypatch).get("/api/v1/portfolio/history?range=1M")
    assert any("requests.portfolio_history" in m for m in usage_metrics.pending().values())


# ---------------------------------------------------------------- performance

def test_modified_dietz_numeric():
    s, e = date(2026, 9, 1), date(2026, 10, 1)       # 30 days
    md = perf.modified_dietz(1000.0, 1200.0, [(date(2026, 9, 16), 100.0)], s, e)
    assert md["gain"] == pytest.approx(100.0) and md["weighted_flows"] == pytest.approx(50.0)
    assert md["return_pct"] == pytest.approx(100 / 1050 * 100)
    # withdrawal on the last day weighs nothing
    md = perf.modified_dietz(1000.0, 900.0, [(e, -150.0)], s, e)
    assert md["return_pct"] == pytest.approx(5.0)
    assert perf.modified_dietz(0.0, 10.0, [], s, e)["return_pct"] is None


def test_external_flows_basis():
    txs = [
        {"type": "buy", "symbol": "NVDA", "trade_date": "2026-09-10", "amount": 100, "fee": 1, "currency": "USD"},
        {"type": "sell", "symbol": "NVDA", "trade_date": "2026-09-20", "amount": 50, "fee": 1, "currency": "USD"},
        {"type": "dividend", "symbol": "NVDA", "trade_date": "2026-09-21", "amount": 2, "currency": "USD"},
        {"type": "buy", "symbol": "NVDA", "trade_date": "2026-08-01", "amount": 999, "currency": "USD"},
    ]
    f = perf.external_flows(txs, date(2026, 9, 1), date(2026, 9, 30), "CAD", 1.4)
    assert f["basis"] == "trades" and f["dividends"] == pytest.approx(2.8)
    assert [round(v, 2) for _, v in f["flows"]] == [141.4, -68.6]
    txs.append({"type": "deposit", "trade_date": "2026-09-05", "amount": 500, "currency": "CAD"})
    f = perf.external_flows(txs, date(2026, 9, 1), date(2026, 9, 30), "CAD", 1.4)
    assert f["basis"] == "deposits" and f["flows"] == [(date(2026, 9, 5), 500.0)]


def test_drivers_ordering():
    items = [{"symbol": s, "start_value": 100.0, "return": r}
             for s, r in [("A", 0.10), ("B", -0.20), ("C", 0.30), ("D", -0.05), ("E", 0.0)]]
    d = perf.compute_drivers(items, bench_return=0.05)
    assert [x["symbol"] for x in d["positive"]] == ["C", "A"]
    assert [x["symbol"] for x in d["negative"]] == ["B", "D"]
    assert d["positive"][0]["contribution_pts"] == pytest.approx(6.0)   # 20% weight x 30%
    vs = d["vs_benchmark"]
    assert [x["symbol"] for x in vs["positive"]] == ["C", "A"] and vs["negative"][0]["symbol"] == "B"
    assert vs["positive"][0]["vs_benchmark_pts"] == pytest.approx(0.2 * 0.25 * 100)


def test_performance_estimate_with_compare(monkeypatch, db):
    a = _one_holding(db)
    db.add_holding(U1, "NVDA", a, shares=1, avg_cost=100)
    db.quotes["NVDA"] = {"symbol": "NVDA", "price": 50.0, "prev_close": 55.0, "currency": "USD",
                         "as_of": "2026-09-30T14:00:00+00:00"}
    db.closes["NVDA"] = _closes([100.0] * 60)
    body = _client(monkeypatch).get("/api/v1/portfolio/performance?range=1M&compare=SPY").json()
    assert body["method"] == "estimate" and body["estimated"] is True and body["dividends_received"] is None
    assert body["return_pct"] == pytest.approx((body["end_value"] / body["start_value"] - 1) * 100, abs=0.01)
    assert body["drivers"]["positive"][0]["symbol"] == "XEQT.TO"
    assert body["drivers"]["negative"][0]["symbol"] == "NVDA"
    c = body["compare"]
    assert c["symbol"] == "SPY" and c["return_pct"] is not None
    assert c["difference_pts"] == pytest.approx(body["return_pct"] - c["return_pct"], abs=0.02)
    assert c["drivers"]["negative"][0]["symbol"] == "NVDA"


def test_performance_transactions_dietz(monkeypatch, db):
    a = _one_holding(db)
    d1 = (TODAY - timedelta(days=10)).isoformat()
    db.insert_transactions(U1, [
        {"account_id": a, "symbol": None, "type": "deposit", "trade_date": d1, "quantity": None, "price": None,
         "amount": 100, "currency": "CAD", "fee": 0},
        {"account_id": a, "symbol": "XEQT.TO", "type": "dividend", "trade_date": d1, "quantity": None,
         "price": None, "amount": 3, "currency": "CAD", "fee": 0},
    ])
    body = _client(monkeypatch).get("/api/v1/portfolio/performance?range=1M").json()
    assert body["method"] == "transactions" and body["flows_basis"] == "deposits"
    assert body["net_flows"] == 100 and body["dividends_received"] == 3
    v0, v1 = body["start_value"], body["end_value"]
    start, end = date.fromisoformat(body["start"]), date.fromisoformat(body["end"])
    w = (end - date.fromisoformat(d1)).days / (end - start).days
    assert body["return_pct"] == pytest.approx((v1 - v0 - 100) / (v0 + 100 * w) * 100, abs=0.01)


def test_performance_1d_uses_prev_close(monkeypatch, db):
    _one_holding(db)
    body = _client(monkeypatch).get("/api/v1/portfolio/performance?range=1D").json()
    assert body["start_value"] == 390 and body["end_value"] == 400
    assert body["return_pct"] == pytest.approx(400 / 390 * 100 - 100, abs=0.01)


def test_parse_intraday_frame():
    idx = pd.DatetimeIndex(["2026-09-30 09:30", "2026-09-30 09:35"]).tz_localize("America/New_York")
    cols = pd.MultiIndex.from_tuples([("Close", "A"), ("Close", "B")])
    df = pd.DataFrame([[1.0, None], [2.0, 5.0]], index=idx, columns=cols)
    out = perf.parse_intraday(df, ["A", "B", "C"])
    assert [v for _, v in out["A"]] == [1.0, 2.0] and len(out["B"]) == 1 and "C" not in out
    assert out["A"][0][0] == datetime(2026, 9, 30, 13, 30, tzinfo=timezone.utc)


def test_range_starts_for_3m_and_5y():
    from datetime import date
    d = date(2026, 9, 30)
    assert perf.range_start("3M", d) == date(2026, 6, 30)
    assert perf.range_start("5Y", d) == date(2021, 9, 30)
    assert perf.closes_period(perf.range_start("5Y", d), d) == "5y"
    assert perf.closes_period(perf.range_start("3M", d), d) == "1y"


def test_history_5y_needs_full_history_3m_is_free(monkeypatch, db):
    _one_holding(db)
    r = _client(monkeypatch, "free").get("/api/v1/portfolio/history?range=5Y")
    assert r.status_code == 403 and r.json()["detail"]["feature"] == "feature.full_history"
    assert _client(monkeypatch, "free").get("/api/v1/portfolio/history?range=3M").status_code == 200
    assert _client(monkeypatch, "premium").get("/api/v1/portfolio/history?range=5Y").status_code == 200
