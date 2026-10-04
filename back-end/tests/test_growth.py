"""Where users come from and whether they stay (migration 029): sign-up
sources, open sign-up, Apple Search Ads attribution, the funnel report."""

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.db import queries
from app.services import growth
from tests import referral_fakes as rf


# ---------------------------------------------------------------- sources (pure)

def test_clean_source_keeps_known_fields_only():
    out = growth.clean_source({"utm_source": " Instagram ", "utm_campaign": "launch BR/2026!",
                               "heard_from": "YouTube", "asa_token": "x" * 40, "evil": "drop me"})
    assert out == {"utm_source": "instagram", "utm_campaign": "launch_br_2026", "heard_from": "youtube",
                   "asa_token": "x" * 40, "asa_status": "pending"}
    assert growth.clean_source({"heard_from": "my cousin", "asa_token": "short"}) == {}
    assert growth.clean_source(None) == {} and growth.clean_source("nope") == {}


def test_channel_and_campaign_precedence():
    assert growth.channel_of({"asa_status": "attributed", "utm_source": "ig"}) == "apple_search_ads"
    assert growth.channel_of({"utm_source": "instagram", "heard_from": "friend"}) == "instagram"
    assert growth.channel_of({"heard_from": "youtube"}) == "youtube"
    assert growth.channel_of({"invite": "friend"}) == "friend_invite"
    assert growth.channel_of(None) == "unknown"
    assert growth.campaign_of({"asa_status": "attributed", "asa_campaign_id": 42}) == "apple_search_ads:42"
    assert growth.campaign_of({"utm_source": "meta", "utm_campaign": "br_launch"}) == "meta:br_launch"


# ---------------------------------------------------------------- open sign-up

@pytest.fixture
def rdb(monkeypatch):
    db = rf.use(monkeypatch)
    db.add_user("pedro", rf.REFERRER_CODE, uid=rf.REFERRER_ID)
    return db


def test_signup_without_code_only_when_open(monkeypatch, rdb):
    saved = []
    monkeypatch.setattr(queries, "insert_signup_source", lambda row: saved.append(row))
    api = rf.register_client(monkeypatch, rdb)
    body = {"username": "ana", "password": "correct horse", "country": "BR",
            "source": {"utm_source": "instagram", "heard_from": "instagram"}}
    r = api.post("/api/v1/auth/register", json=body)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_referral"   # invite-only default

    monkeypatch.setattr(settings, "signup_invite_required", False)
    r = api.post("/api/v1/auth/register", json=body)
    assert r.status_code == 201, r.text
    user = rdb.user("ana")
    assert user["referred_by"] is None and rdb.tables["referrals"] == []
    assert saved[-1]["user_id"] == user["id"] and saved[-1]["utm_source"] == "instagram"
    assert saved[-1]["invite"] == "none" and saved[-1]["country"] == "BR" and saved[-1]["platform"] == "web"

    r = api.post("/api/v1/auth/register", json={**body, "username": "bia", "referral_code": "WRONGCOD"})
    assert r.status_code == 422   # a typed code must still be valid

    r = api.get("/api/v1/auth/signup-config")
    assert r.status_code == 200 and r.json()["invite_required"] is False and "instagram" in r.json()["heard_from"]


def test_signup_with_friend_code_records_invite(monkeypatch, rdb):
    saved = []
    monkeypatch.setattr(queries, "insert_signup_source", lambda row: saved.append(row))
    api = rf.register_client(monkeypatch, rdb)
    r = api.post("/api/v1/auth/register", json={"username": "ana", "password": "correct horse",
                                                "referral_code": rf.REFERRER_CODE, "client": "ios"})
    assert r.status_code == 201
    assert saved[-1]["invite"] == "friend" and saved[-1]["platform"] == "ios"


def test_source_failure_never_breaks_signup(monkeypatch, rdb):
    def boom(row):
        raise RuntimeError('relation "signup_sources" does not exist')
    monkeypatch.setattr(queries, "insert_signup_source", boom)
    api = rf.register_client(monkeypatch, rdb)
    r = api.post("/api/v1/auth/register", json={"username": "ana", "password": "correct horse",
                                                "referral_code": rf.REFERRER_CODE})
    assert r.status_code == 201


# ---------------------------------------------------------------- attribution later

def test_attribution_first_touch_wins(monkeypatch):
    row = {"user_id": "u1", "utm_source": "instagram", "asa_status": None}
    updates = []
    monkeypatch.setattr(queries, "get_signup_source", lambda uid: dict(row))
    monkeypatch.setattr(queries, "update_signup_source", lambda uid, data: updates.append(data))
    out = growth.add_attribution("u1", {"utm_source": "google", "utm_campaign": "x", "asa_token": "t" * 30})
    assert out == {"saved": ["asa_status", "asa_token", "utm_campaign"]}
    assert "utm_source" not in updates[0]


# ---------------------------------------------------------------- Apple Search Ads

def test_parse_asa():
    assert growth.parse_asa({"attribution": False}) == {"asa_status": "organic", "asa_token": None}
    got = growth.parse_asa({"attribution": True, "orgId": 1, "campaignId": 542370539, "adGroupId": 542317095,
                            "keywordId": 87675432, "countryOrRegion": "BR", "clickDate": "2026-10-01T17:17Z"})
    assert got["asa_status"] == "attributed" and got["asa_campaign_id"] == 542370539
    assert got["asa_country"] == "BR" and got["asa_keyword_id"] == 87675432


def test_resolve_asa_statuses(monkeypatch):
    now = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
    rows = [{"user_id": "a", "asa_token": "A" * 30, "created_at": "2026-10-04T11:00:00+00:00"},
            {"user_id": "b", "asa_token": "B" * 30, "created_at": "2026-10-04T11:00:00+00:00"},
            {"user_id": "c", "asa_token": "C" * 30, "created_at": "2026-10-04T11:00:00+00:00"},
            {"user_id": "d", "asa_token": "D" * 30, "created_at": "2026-10-02T11:00:00+00:00"}]   # > 24 h
    monkeypatch.setattr(queries, "get_pending_asa", lambda: rows)
    updates = {}
    monkeypatch.setattr(queries, "update_signup_source", lambda uid, data: updates.setdefault(uid, data))
    answers = {"A": (200, {"attribution": True, "campaignId": 7}), "B": (200, {"attribution": False}),
               "C": (404, {})}

    def post(tok):
        code, payload = answers[tok[0]]
        return SimpleNamespace(status_code=code, json=lambda: payload)
    out = growth.resolve_asa(now, post)
    assert out == {"pending": 4, "attributed": 1, "organic": 1, "failed": 1, "waiting": 1}
    assert updates["a"]["asa_campaign_id"] == 7 and updates["b"]["asa_status"] == "organic"
    assert "c" not in updates and updates["d"]["asa_status"] == "failed"


# ---------------------------------------------------------------- funnel

def test_funnel_rates_by_channel():
    today = date(2026, 10, 30)
    users = [{"id": "u1", "created_at": "2026-10-01T10:00:00+00:00", "access_level": "premium"},
             {"id": "u2", "created_at": "2026-10-02T10:00:00+00:00", "access_level": "free"},
             {"id": "u3", "created_at": "2026-10-03T10:00:00+00:00", "access_level": "free"},
             {"id": "u4", "created_at": "2026-10-25T10:00:00+00:00", "access_level": "free"}]   # too new for week 2
    sources = {"u1": {"asa_status": "attributed", "asa_campaign_id": 1},
               "u2": {"asa_status": "attributed", "asa_campaign_id": 1},
               "u3": {"heard_from": "instagram"}, "u4": {"heard_from": "instagram"}}
    holdings = [{"user_id": "u1", "created_at": f"2026-10-0{d}T12:00:00+00:00"} for d in (1, 2, 3)] + \
               [{"user_id": "u2", "created_at": "2026-10-20T12:00:00+00:00"},          # after 7 days
                {"user_id": "u3", "created_at": "2026-10-03T12:00:00+00:00"}]
    activity = [{"user_id": "u1", "day": "2026-10-09"}, {"user_id": "u3", "day": "2026-10-05"}]
    rows = {r["key"]: r for r in growth.build_funnel(users, sources, holdings, activity, "channel", today)}
    asa, ig = rows["apple_search_ads"], rows["instagram"]
    assert (asa["signups"], asa["activated"], asa["activated_3"], asa["week2"], asa["premium"]) == (2, 1, 1, 1, 1)
    assert asa["activated_pct"] == 50.0 and asa["week2_pct"] == 50.0
    assert (ig["signups"], ig["activated"], ig["week2_eligible"], ig["week2"]) == (2, 1, 1, 0)
    weeks = growth.build_funnel(users, sources, holdings, activity, "week", today)
    assert [w["key"] for w in weeks] == ["2026-09-28", "2026-10-19"]   # Mondays


def test_admin_growth_owner_only_and_validates(monkeypatch):
    from app.api.v1 import growth as api
    from tests.portfolio_fakes import make_client
    monkeypatch.setattr(queries, "get_users_created", lambda a, b: [])
    owner = make_client(monkeypatch, api.router, level="owner")
    r = owner.get("/api/v1/admin/growth?group=channel")
    assert r.status_code == 200 and r.json()["rows"] == [] and r.json()["totals"]["signups"] == 0
    assert owner.get("/api/v1/admin/growth?group=nope").status_code == 422
    assert owner.get("/api/v1/admin/growth?from=2026-10-10&to=2026-10-01").status_code == 422
    free = make_client(monkeypatch, api.router, level="free")
    assert free.get("/api/v1/admin/growth").status_code == 403


def test_activity_written_once_a_day(monkeypatch):
    calls = []
    monkeypatch.setattr(queries, "add_activity_day", lambda uid, day: calls.append((uid, day)))
    growth._activity_written.clear()
    for _ in range(3):
        growth.record_activity("u1", date(2026, 10, 4))
    growth.record_activity("u1", date(2026, 10, 5))
    assert calls == [("u1", "2026-10-04"), ("u1", "2026-10-05")]


def test_public_stock_needs_no_sign_in(monkeypatch):
    from fastapi.testclient import TestClient

    import main
    from app.services import stock_page

    async def page(sym):
        return {"symbol": sym.upper(), "name": "Enbridge"}
    monkeypatch.setattr(stock_page, "get_shared_page", page)
    r = TestClient(main.app).get("/api/v1/public/stocks/enb.to")
    assert r.status_code == 200 and r.json() == {"symbol": "ENB.TO", "name": "Enbridge"}
    assert r.headers["cache-control"] == "public, max-age=300"
