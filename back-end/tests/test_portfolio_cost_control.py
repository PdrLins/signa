"""Cost control (migration 014): honest quote timestamps, per-level quote
refresh for active users only, users.last_seen_at throttling, usage
counters + GET /admin/usage, and the shared scope loader. Fakes only."""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app.core import access
from app.core.config import settings
from app.db import queries
from app.services import portfolio_context as pc
from app.services import quotes, usage_metrics
from tests.portfolio_fakes import U1, FakePortfolioDB, make_client

ET = ZoneInfo("America/New_York")
UTC = timezone.utc


# ---------------------------------------------------------------- quote as_of

def test_as_of_is_fetch_time_while_the_daily_bar_is_open():
    now = datetime(2026, 9, 30, 14, 42, tzinfo=UTC)            # 10:42 ET
    as_of, src = quotes.resolve_as_of(pd.Timestamp("2026-09-30"), "XEQT.TO", now)
    assert src == "fetch" and as_of == now.isoformat()


def test_as_of_is_the_session_close_for_a_finished_bar():
    now = datetime(2026, 10, 1, 13, 0, tzinfo=UTC)
    as_of, src = quotes.resolve_as_of(pd.Timestamp("2026-09-30"), "NVDA", now)
    assert src == "close" and datetime.fromisoformat(as_of) == datetime(2026, 9, 30, 16, 0, tzinfo=ET)
    # fetched just after the close the same day: still the close, not the fetch time
    after = datetime(2026, 9, 30, 20, 5, tzinfo=UTC)            # 16:05 ET
    assert quotes.resolve_as_of(pd.Timestamp("2026-09-30"), "NVDA", after)[1] == "close"


def test_as_of_keeps_an_intraday_bar_time_and_crypto_uses_utc_days():
    now = datetime(2026, 9, 30, 15, 0, tzinfo=UTC)
    as_of, src = quotes.resolve_as_of(pd.Timestamp("2026-09-30 10:35", tz=ET), "NVDA", now)
    assert src == "bar" and datetime.fromisoformat(as_of) == datetime(2026, 9, 30, 10, 35, tzinfo=ET)
    assert quotes.resolve_as_of(pd.Timestamp("2026-09-30"), "BTC-USD", now)[1] == "fetch"
    assert quotes.resolve_as_of(pd.Timestamp("2026-09-29"), "BTC-USD", now)[1] == "close"


def test_parse_download_stores_a_real_time_not_midnight():
    idx = pd.to_datetime(["2026-09-29", "2026-09-30"])
    frame = pd.DataFrame({("Close", "NVDA"): [100.0, 110.0], ("High", "NVDA"): [101, 111],
                          ("Low", "NVDA"): [99, 109], ("Close", "AAPL"): [1.0, 2.0],
                          ("High", "AAPL"): [1, 2], ("Low", "AAPL"): [1, 2]}, index=idx)
    frame.columns = pd.MultiIndex.from_tuples(frame.columns)
    now_iso = datetime(2026, 9, 30, 14, 42, tzinfo=UTC).isoformat()
    q = quotes.parse_download(frame, ["NVDA", "AAPL"], now_iso)["NVDA"]
    assert q["as_of"] == now_iso and q["as_of_source"] == "fetch"
    assert not q["as_of"].startswith("2026-09-30T00:00")


class _Tbl:
    """Minimal PostgREST fake: fails when a column is unknown (before 014)."""

    def __init__(self, store, has_source):
        self.store, self.has_source, self.cols, self.payload = store, has_source, "", None

    def table(self, _):
        return self

    def select(self, cols):
        self.cols = cols
        return self

    def in_(self, *_):
        return self

    def upsert(self, rows, on_conflict=None):
        self.payload = rows
        return self

    def execute(self):
        if (("as_of_source" in self.cols and self.payload is None)
                or (self.payload and any("as_of_source" in r for r in self.payload))) and not self.has_source:
            self.payload, self.cols = None, ""
            raise RuntimeError("column quotes.as_of_source does not exist (42703)")
        if self.payload is not None:
            self.store.extend(self.payload)
            data, self.payload = self.payload, None
        else:
            data = [{"symbol": "NVDA", "price": 1}]
        return type("R", (), {"data": data})()


def test_quote_queries_work_before_migration_014(monkeypatch):
    stored: list[dict] = []
    monkeypatch.setattr(queries, "get_client", lambda: _Tbl(stored, has_source=False))
    monkeypatch.setattr(queries, "_quotes_no_source_at", None)
    assert queries.upsert_quotes([{"symbol": "NVDA", "price": 1, "as_of_source": "fetch"}]) == 1
    assert stored == [{"symbol": "NVDA", "price": 1}]
    assert queries.get_quote_rows(["NVDA"]) == [{"symbol": "NVDA", "price": 1}]


# ---------------------------------------------------------------- refresh by level

NOW = datetime(2026, 9, 30, 14, 0, tzinfo=UTC)   # 10:00 ET, session open
USERS = [
    {"id": "free1", "access_level": "free", "last_seen_at": (NOW - timedelta(days=1)).isoformat()},
    {"id": "prem1", "access_level": "premium", "last_seen_at": (NOW - timedelta(hours=2)).isoformat()},
    {"id": "gone", "access_level": "owner", "last_seen_at": (NOW - timedelta(days=30)).isoformat()},
    {"id": "old_login", "access_level": "free", "last_seen_at": None,
     "last_login": (NOW - timedelta(days=3)).isoformat()},
]
FOLLOWS = [
    {"user_id": "free1", "symbol": "XEQT.TO"}, {"user_id": "free1", "symbol": "NVDA"},
    {"user_id": "prem1", "symbol": "nvda"}, {"user_id": "gone", "symbol": "TSLA"},
    {"user_id": "old_login", "symbol": "ENB.TO"},
]


def test_follower_levels_best_level_of_active_followers_only():
    lv = quotes.follower_levels(FOLLOWS, USERS, NOW, 7)
    assert lv == {"XEQT.TO": "free", "NVDA": "premium", "ENB.TO": "free"}   # TSLA: follower inactive


def test_follower_levels_before_migration_011_treats_the_user_as_owner():
    users = [{"id": "u", "last_login": NOW.isoformat()}]
    assert quotes.follower_levels([{"user_id": "u", "symbol": "SPY"}], users, NOW, 7) == {"SPY": "premium"}


def test_due_symbols_by_tier():
    levels = {"NVDA": "premium", "XEQT.TO": "free"}
    t = NOW.timestamp()
    assert quotes.due_symbols(levels, {}, t, 900, 60) == ["NVDA", "XEQT.TO"]
    last = {"NVDA": t - 60, "XEQT.TO": t - 60}
    assert quotes.due_symbols(levels, last, t, 900, 60) == ["NVDA"]
    last = {"NVDA": t - 30, "XEQT.TO": t - 900}
    assert quotes.due_symbols(levels, last, t, 900, 60) == ["XEQT.TO"]


def test_refresh_job_follows_levels_and_force_refreshes_all(monkeypatch):
    fetched: list[list[str]] = []
    monkeypatch.setattr(queries, "get_follow_rows", lambda: FOLLOWS)
    monkeypatch.setattr(queries, "get_users_activity", lambda: USERS)
    monkeypatch.setattr(quotes, "_last_refresh", {})
    monkeypatch.setattr(quotes, "refresh_quotes",
                        lambda syms: fetched.append(list(syms)) or {s: {} for s in syms})
    r = quotes.refresh_followed_quotes(now=NOW)
    assert r == {"status": "ok", "followed": 3, "symbols": 3, "quotes": 3}
    r = quotes.refresh_followed_quotes(now=NOW + timedelta(seconds=60))
    assert fetched[-1] == ["NVDA"] and r["symbols"] == 1                  # premium only
    r = quotes.refresh_followed_quotes(now=NOW + timedelta(seconds=90))
    assert r["symbols"] == 0 and len(fetched) == 2                          # nothing due
    quotes.refresh_followed_quotes(now=NOW + timedelta(seconds=900))
    assert fetched[-1] == ["ENB.TO", "NVDA", "XEQT.TO"]                     # free due again
    quotes.refresh_followed_quotes(force=True, now=NOW + timedelta(seconds=901))
    assert fetched[-1] == ["ENB.TO", "NVDA", "XEQT.TO"]                     # after close: all
    assert usage_metrics.pending()[usage_metrics._today().isoformat()]["symbols_refreshed"] == 3 + 1 + 3 + 3


def test_quote_download_counts_provider_calls(monkeypatch):
    monkeypatch.setattr(quotes, "_download", lambda syms: None)
    monkeypatch.setattr(quotes, "QUOTE_BATCH", 2)
    quotes.fetch_quotes(["A", "B", "C"])
    assert usage_metrics.pending()[usage_metrics._today().isoformat()]["provider_calls.quotes"] == 2


def test_refresh_settings_defaults():
    assert settings.quotes_refresh_seconds_free == 900 and settings.quotes_refresh_seconds_premium == 60
    assert access.FEATURE_CATALOG["feature.intraday_chart"][0] == "free"   # migration 022
    assert access.FEATURE_CATALOG["feature.full_history"][0] == "premium"


# ---------------------------------------------------------------- last_seen_at

def test_last_seen_written_at_most_once_per_hour(monkeypatch):
    from app.api.v1 import profile as profile_api
    from app.middleware import auth as auth_mw

    FakePortfolioDB(monkeypatch)
    calls: list[str] = []

    class _Now:
        def __init__(self, target, name=None, daemon=None):
            self.target = target

        def start(self):
            self.target()
    monkeypatch.setattr("threading.Thread", _Now)
    monkeypatch.setattr(auth_mw, "touch_user_last_seen", lambda uid: calls.append(uid))
    c = make_client(monkeypatch, profile_api.router, level="free")
    c.get("/api/v1/profile")
    c.get("/api/v1/profile")
    assert calls == [U1]


def test_last_seen_failure_never_breaks_a_request(monkeypatch):
    from app.api.v1 import profile as profile_api
    from app.middleware import auth as auth_mw

    FakePortfolioDB(monkeypatch)

    def boom(uid):
        raise RuntimeError("column users.last_seen_at does not exist")
    monkeypatch.setattr(auth_mw, "touch_user_last_seen", boom)
    c = make_client(monkeypatch, profile_api.router, level="free")
    assert c.get("/api/v1/profile").status_code == 200


# ---------------------------------------------------------------- usage counters

def test_record_and_flush(monkeypatch):
    written: list[tuple] = []
    monkeypatch.setattr(queries, "increment_data_usage", lambda d, m, n: written.append((d, m, n)))
    d = date(2026, 9, 30)
    usage_metrics.record("provider_calls.intraday", today=d)
    usage_metrics.record("provider_calls.intraday", 2, today=d)
    usage_metrics.record("requests.portfolio_history", today=d)
    usage_metrics.record("ignored", 0, today=d)
    assert usage_metrics.flush() == {"status": "ok", "rows": 2, "failed": 0}
    assert sorted(written) == [("2026-09-30", "provider_calls.intraday", 3),
                               ("2026-09-30", "requests.portfolio_history", 1)]
    assert usage_metrics.pending() == {} and usage_metrics.flush() == {"status": "ok", "rows": 0}


def test_flush_keeps_counts_on_db_error_and_drops_before_014(monkeypatch):
    def down(*a):
        raise RuntimeError("connection reset")
    monkeypatch.setattr(queries, "increment_data_usage", down)
    usage_metrics.record("x", 5, today=date(2026, 9, 30))
    assert usage_metrics.flush()["failed"] == 1
    assert usage_metrics.pending() == {"2026-09-30": {"x": 5}}

    def missing(*a):
        raise RuntimeError("Could not find the function public.increment_data_usage (PGRST202) schema cache")
    monkeypatch.setattr(queries, "increment_data_usage", missing)
    assert usage_metrics.flush()["status"] == "unavailable" and usage_metrics.pending() == {}


def test_summarize_fills_every_day():
    rows = [{"usage_date": "2026-09-29", "metric": "a", "count": 2},
            {"usage_date": "2026-09-30", "metric": "a", "count": 3},
            {"usage_date": "2026-09-30", "metric": "b", "count": 1},
            {"usage_date": "2026-08-01", "metric": "a", "count": 99}]   # outside the window
    s = usage_metrics.summarize(rows, 3, date(2026, 9, 30))
    assert s["from"] == "2026-09-28" and [d["date"] for d in s["days"]] == ["2026-09-28", "2026-09-29", "2026-09-30"]
    assert s["days"][0]["metrics"] == {} and s["days"][2]["metrics"] == {"a": 3, "b": 1}
    assert s["totals"] == {"a": 5, "b": 1}


def test_admin_usage_owner_only(monkeypatch):
    from app.api.v1 import admin_usage

    monkeypatch.setattr(access, "get_feature_levels", lambda: {k: v[0] for k, v in access.FEATURE_CATALOG.items()})
    today = usage_metrics._today()
    monkeypatch.setattr(queries, "get_data_usage",
                        lambda since: [{"usage_date": today.isoformat(), "metric": "provider_calls.quotes",
                                        "count": 7}])
    now = datetime.now(UTC)
    monkeypatch.setattr(queries, "get_follow_rows", lambda: [
        {"user_id": "a", "symbol": "NVDA"}, {"user_id": "b", "symbol": "NVDA"}, {"user_id": "z", "symbol": "TSLA"}])
    monkeypatch.setattr(queries, "get_users_activity", lambda: [
        {"id": "a", "access_level": "free", "last_seen_at": now.isoformat()},
        {"id": "b", "access_level": "premium", "last_seen_at": now.isoformat()},
        {"id": "z", "access_level": "free", "last_seen_at": (now - timedelta(days=40)).isoformat()}])
    usage_metrics.record("requests.events_upcoming")
    assert make_client(monkeypatch, admin_usage.router, level="premium").get(
        "/api/v1/admin/usage").status_code == 403
    body = make_client(monkeypatch, admin_usage.router, level="owner").get("/api/v1/admin/usage?days=7").json()
    assert len(body["days"]) == 7 and body["totals"] == {"provider_calls.quotes": 7}
    assert body["followed_symbols"] == 2 and body["active_symbols"] == 1 and body["active_users"] == 2
    assert body["pending"][today.isoformat()]["requests.events_upcoming"] == 1
    assert body["refresh_seconds"] == {"free": 900, "premium": 60}
    bad = make_client(monkeypatch, admin_usage.router, level="owner").get("/api/v1/admin/usage?days=0")
    assert bad.status_code == 422


def test_admin_usage_before_014_is_migration_required(monkeypatch):
    from app.api.v1 import admin_usage

    def missing(since):
        raise RuntimeError('relation "public.data_usage_daily" does not exist (42P01)')
    monkeypatch.setattr(queries, "get_data_usage", missing)
    r = make_client(monkeypatch, admin_usage.router, level="owner").get("/api/v1/admin/usage")
    assert r.status_code == 503 and r.json()["detail"]["migration"] == "014_portfolio_insights.sql"


# ---------------------------------------------------------------- scope loader

ACCTS = [{"id": "a1", "person_id": "p1", "name": "TFSA", "currency": "CAD", "cash_balance": 100},
         {"id": "a2", "person_id": "p2", "name": "Joint", "currency": "USD", "cash_balance": 50}]
HOLD = [{"symbol": "NVDA", "account_id": "a1"}, {"symbol": "NVDA", "account_id": "a2"},
        {"symbol": "XEQT.TO", "account_id": None}]
TXS = [{"account_id": "a1", "type": "buy"}, {"account_id": None, "type": "deposit"}]


def test_scope_filter_by_account_person_and_mismatch():
    whole = pc.scope_filter(ACCTS, HOLD, TXS, None, None)
    assert whole["account_ids"] is None and len(whole["holdings"]) == 3
    one = pc.scope_filter(ACCTS, HOLD, TXS, "a1", None)
    assert [h["account_id"] for h in one["holdings"]] == ["a1"] and len(one["transactions"]) == 1
    person = pc.scope_filter(ACCTS, HOLD, TXS, None, "p2")
    assert person["account_ids"] == ["a2"] and [a["id"] for a in person["accounts"]] == ["a2"]
    with pytest.raises(Exception) as e:
        pc.scope_filter(ACCTS, HOLD, TXS, "nope", None)
    assert e.value.status_code == 404 and e.value.detail["code"] == "account_not_found"
    with pytest.raises(Exception) as e:
        pc.scope_filter(ACCTS, HOLD, TXS, "a1", "p2")
    assert e.value.status_code == 422 and e.value.detail["code"] == "invalid_scope"


def test_value_positions_convert_and_fall_back_to_last_close():
    quotes_map = {"NVDA": {"price": 100.0, "prev_close": 90.0, "currency": "USD", "as_of": "2026-09-30T14:00:00+00:00"}}
    rows = [{"symbol": "NVDA", "account_id": "a1", "shares": 2, "avg_cost": 50},
            {"symbol": "ENB.TO", "account_id": None, "shares": 10,
             "holding_status": {"price": 60.0, "prev_close": 59.0, "as_of": "2026-09-29"}},
            {"symbol": "BARC.L", "shares": 1, "currency": "GBP", "holding_status": {"price": 2.0}}]
    pos = pc.value_positions(rows, quotes_map, "CAD", 1.4)
    nv, enb, barc = pos
    assert nv["value_home"] == pytest.approx(280) and nv["cost_home"] == pytest.approx(140)
    assert nv["day_change_home"] == pytest.approx(28) and nv["gain_pct"] == 100.0
    assert enb["price_source"] == "last_close" and enb["value_home"] == 600
    assert barc["value_home"] is None and barc["converted"] is False
    meta = pc.price_meta(pos)
    assert meta["delayed_minutes"] == 15 and meta["as_of"] == "2026-09-29"   # the oldest price
    assert meta["estimated_prices"] == ["BARC.L", "ENB.TO"]
    merged = pc.merge_positions_by_symbol(pc.value_positions(
        [{"symbol": "NVDA", "account_id": "a1", "shares": 1, "avg_cost": 50},
         {"symbol": "NVDA", "account_id": "a2", "shares": 3, "avg_cost": 70}], quotes_map, "USD", 1.4))
    assert len(merged) == 1 and merged[0]["shares"] == 4 and merged[0]["value_home"] == 400
    assert merged[0]["cost_home"] == 260 and merged[0]["account_ids"] == ["a1", "a2"]


def test_load_scope_uses_profile_and_rejects_unknown_person(monkeypatch):
    db = FakePortfolioDB(monkeypatch)
    db.settings[U1] = {"user_id": U1, "country": "CA", "home_currency": "USD", "dividend_tax_view": "after"}
    aid = db.add_account(U1, "TFSA")
    db.add_holding(U1, "NVDA", aid, shares=1)
    db.quotes["NVDA"] = {"symbol": "NVDA", "price": 10.0}
    s = pc.load_scope({"user_id": U1, "access_level": "premium"})
    assert s["home_currency"] == "USD" and s["tax_view"] == "after" and s["tax_eligible"] is True
    assert s["usdcad"] == 1.4 and set(s["quotes"]) == {"NVDA"} and s["account_ids"] is None
    assert pc.load_scope({"user_id": U1, "access_level": "free"})["tax_view"] == "before"
    with pytest.raises(Exception) as e:
        pc.load_scope({"user_id": U1}, person_id="00000000-0000-0000-0000-00000000dead")
    assert e.value.detail["code"] == "person_not_found"


def test_scheduler_registers_insight_jobs():
    from app.scheduler.runner import init_scheduler
    jobs = {j.id for j in init_scheduler().get_jobs()}
    assert {"income_forecast_snapshots", "check_status_snapshots", "usage_flush"} <= jobs
