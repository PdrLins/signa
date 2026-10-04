"""Account IDs, invite-only sign-up and referral rewards (migration 019):
app/services/referrals.py, app/services/registration.py,
POST /auth/register, GET /auth/referral/{code}, GET /referrals, the slot
limit (15 + min(5 x rewarded, 25)) and the reward on the first follow."""

import asyncio

import bcrypt
import pytest

from app.core import access
from app.core.config import settings
from app.services import referrals, slots
from tests import referral_fakes as rf
from tests.portfolio_fakes import U1, FakePortfolioDB, make_client

TOKEN_KEYS = {"message", "session_token", "code_via", "access_token", "token_type", "expires_in",
              "last_login", "refresh_token", "session_id", "session_expires_at"}


@pytest.fixture
def rdb(monkeypatch):
    db = rf.use(monkeypatch)
    db.add_user("pedro", rf.REFERRER_CODE, uid=rf.REFERRER_ID)
    return db


@pytest.fixture
def api(monkeypatch, rdb):
    return rf.register_client(monkeypatch, rdb)


def _body(**kw):
    return {"username": "ana", "password": "correct horse", "referral_code": rf.REFERRER_CODE, **kw}


# ---------------------------------------------------------------- codes

def test_account_ids_use_the_unambiguous_alphabet():
    ids = {referrals.new_account_id() for _ in range(200)}
    assert len(ids) == 200
    assert all(len(i) == 8 and set(i) <= set(referrals.ALPHABET) for i in ids)
    assert not set("01OIL") & set(referrals.ALPHABET)
    assert referrals.normalize_code(" k7m2qx9a ") == "K7M2QX9A"
    assert referrals.normalize_code("K7M2QX9") is None and referrals.normalize_code("K7M2QX90") is None


def test_unique_account_id_skips_taken(monkeypatch, rdb):
    seq = iter([rf.REFERRER_CODE, "ABCDEFGH"])
    monkeypatch.setattr(referrals, "new_account_id", lambda: next(seq))
    assert referrals.unique_account_id() == "ABCDEFGH"


# ---------------------------------------------------------------- register

def test_register_web(api, rdb):
    r = api.post("/api/v1/auth/register", json=_body(username="  Ana.Silva_1 "))
    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) == TOKEN_KEYS
    assert body["access_token"] and body["token_type"] == "bearer" and body["refresh_token"] is None
    assert body["session_id"]                                   # web session (017), no refresh token
    user = rdb.user("ana.silva_1")                              # stored lower-cased
    assert user["access_level"] == "free" and user["telegram_chat_id"] is None and user["is_active"]
    assert bcrypt.checkpw(b"correct horse", user["password_hash"].encode())
    assert referrals.normalize_code(user["account_id"]) == user["account_id"]
    assert user["referred_by"] == rf.REFERRER_ID
    [ref] = rdb.tables["referrals"]
    assert ref["referrer_id"] == rf.REFERRER_ID and ref["referred_id"] == user["id"] and ref["status"] == "pending"


def test_register_ios_gets_refresh_token_and_device(monkeypatch, rdb):
    from app.core.security import decode_token
    from tests.test_sessions import MemDB
    sdb = MemDB()
    api = rf.register_client(monkeypatch, rdb, sdb)
    r = api.post("/api/v1/auth/register", json=_body(client="ios", device_name="Ana's iPhone",
                                                     referral_code="k7m2qx9a"))   # case-insensitive code
    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) == TOKEN_KEYS
    assert body["refresh_token"] and body["session_id"] and body["session_expires_at"]
    assert body["expires_in"] == 15 * 60
    assert decode_token(body["access_token"])["cli"] == "ios"
    assert sdb.tables["auth_sessions"][0]["device_name"] == "Ana's iPhone"


@pytest.mark.parametrize("override,code,status", [
    ({"referral_code": "ZZZZZZZZ"}, "invalid_referral", 422),
    ({"referral_code": "nope"}, "invalid_referral", 422),
    ({"referral_code": None}, "invalid_referral", 422),
    ({"username": "ab"}, "invalid_username", 422),
    ({"username": "a" * 31}, "invalid_username", 422),
    ({"username": "ana silva"}, "invalid_username", 422),
    ({"username": "ana@x"}, "invalid_username", 422),
    ({"password": "short"}, "weak_password", 422),
    ({"password": "é" * 37}, "weak_password", 422),            # 74 bytes > bcrypt's 72
])
def test_register_errors(api, rdb, override, code, status):
    r = api.post("/api/v1/auth/register", json=_body(**override))
    assert r.status_code == status, r.text
    assert r.json()["detail"]["code"] == code and r.json()["detail"]["message"]
    assert rdb.user("ana") is None and rdb.tables["referrals"] == []


def test_register_inactive_referrer_is_invalid(api, rdb):
    rdb.tables["users"][0]["is_active"] = False
    r = api.post("/api/v1/auth/register", json=_body())
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_referral"


def test_register_username_taken(api, rdb):
    rdb.add_user("ana", is_active=False)                       # any account, active or not
    r = api.post("/api/v1/auth/register", json=_body(username="ANA"))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "username_taken"
    assert rdb.tables["referrals"] == []


def test_register_race_on_insert_is_username_taken(monkeypatch, api, rdb):
    from app.services import registration
    monkeypatch.setattr(registration, "_username_exists", lambda u: False)
    rdb.add_user("ana")
    r = api.post("/api/v1/auth/register", json=_body())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "username_taken"


def test_register_before_migration(api, rdb):
    rdb.missing = True
    r = api.post("/api/v1/auth/register", json=_body())
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "migration_required"
    assert r.json()["detail"]["migration"] == "019_referrals.sql"
    assert api.get(f"/api/v1/auth/referral/{rf.REFERRER_CODE}").status_code == 503


def test_register_is_audited(monkeypatch, api, rdb):
    from app.db import queries
    events = []
    monkeypatch.setattr(queries, "insert_audit_log", lambda **k: events.append((k["event_type"], k["success"])))
    api.post("/api/v1/auth/register", json=_body(referral_code="ZZZZZZZZ"))
    api.post("/api/v1/auth/register", json=_body())
    assert ("REGISTER_FAILED", False) in events and ("USER_REGISTERED", True) in events


def test_register_rate_limit_counts_every_attempt(api, rdb):
    for i in range(5):                                          # successes count too
        assert api.post("/api/v1/auth/register", json=_body(username=f"user{i}")).status_code == 201
    r = api.post("/api/v1/auth/register", json=_body(username="user9"))
    assert r.status_code == 429
    assert rdb.user("user9") is None


def test_register_is_public_and_in_auth_tier():
    from app.middleware import auth as auth_mw
    from app.middleware import rate_limit
    assert "/api/v1/auth/register" in auth_mw.PUBLIC_PATHS
    assert rate_limit._get_tier("/api/v1/auth/register") == ("auth", 5, 900, False)
    assert rate_limit._get_tier("/api/v1/auth/referral/ABCDEFGH")[0] == "lookup"


# ---------------------------------------------------------------- code lookup

def test_referral_lookup(api, rdb):
    get = lambda c: api.get(f"/api/v1/auth/referral/{c}")  # noqa: E731
    assert get(rf.REFERRER_CODE).json() == {"valid": True}
    assert get("k7m2qx9a").json() == {"valid": True}           # case-insensitive
    assert get("ZZZZZZZZ").json() == {"valid": False}
    assert get("bad").json() == {"valid": False}
    rdb.tables["users"][0]["is_active"] = False
    assert get(rf.REFERRER_CODE).json() == {"valid": False}


def test_referral_lookup_rate_limited(api, rdb):
    for _ in range(20):
        assert api.get("/api/v1/auth/referral/ZZZZZZZZ").status_code == 200
    assert api.get("/api/v1/auth/referral/ZZZZZZZZ").status_code == 429


# ---------------------------------------------------------------- summary

def _friends(rdb, rewarded: int, pending: int, referrer=rf.REFERRER_ID):
    for i in range(rewarded + pending):
        u = rdb.add_user(f"friend{len(rdb.tables['users'])}")
        rdb.add_referral(referrer, u["id"], "rewarded" if i < rewarded else "pending")


def _referrals_client(monkeypatch, level="free", uid=rf.REFERRER_ID):
    from app.api.v1 import referrals as referrals_api
    return make_client(monkeypatch, referrals_api.router, level=level, uid=uid)


def test_summary_free(monkeypatch, rdb):
    _friends(rdb, rewarded=2, pending=1)
    body = _referrals_client(monkeypatch).get("/api/v1/referrals").json()
    assert body == {"code": rf.REFERRER_CODE, "share_url": None, "per_friend": 5, "max_bonus": 25,
                    "bonus_slots": 10, "invited": 3, "rewarded": 2, "pending": 1, "unlimited": False}


def test_summary_share_url(monkeypatch, rdb):
    monkeypatch.setattr(settings, "web_app_url", "https://signa.app/")
    body = _referrals_client(monkeypatch).get("/api/v1/referrals").json()
    assert body["share_url"] == f"https://signa.app/signup?code={rf.REFERRER_CODE}"


def test_summary_premium_unlimited(monkeypatch, rdb):
    _friends(rdb, rewarded=1, pending=0)
    body = _referrals_client(monkeypatch, "premium").get("/api/v1/referrals").json()
    assert body["unlimited"] is True and body["rewarded"] == 1 and body["bonus_slots"] == 5


def test_summary_before_migration(monkeypatch, rdb):
    rdb.missing = True
    r = _referrals_client(monkeypatch).get("/api/v1/referrals")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "migration_required"


def test_bonus_is_capped_at_25(monkeypatch, rdb):
    _friends(rdb, rewarded=7, pending=0)
    assert _referrals_client(monkeypatch).get("/api/v1/referrals").json()["bonus_slots"] == 25
    assert slots.limit_for({"user_id": rf.REFERRER_ID, "access_level": "free"}) == 40


# ---------------------------------------------------------------- slots

def test_me_slots_and_403_use_the_referral_limit(monkeypatch, rdb):
    from fastapi import HTTPException

    from app.api.v1 import auth
    db = FakePortfolioDB(monkeypatch)
    rdb.add_user("me", "MEMEMEME", uid=U1)
    _friends(rdb, rewarded=2, pending=1, referrer=U1)
    for i in range(12):
        db.add_holding(U1, f"S{i}")
    me = make_client(monkeypatch, auth.router, level="free").get("/api/v1/auth/me").json()
    assert me["slots"] == {"used": 12, "limit": 25, "remaining": 13}
    assert me["account_id"] == "MEMEMEME"
    for i in range(12, 25):
        db.add_holding(U1, f"S{i}")
    user = {"user_id": U1, "access_level": "free"}
    slots.check_new_symbols(user, ["S1"])
    with pytest.raises(HTTPException) as e:
        slots.check_new_symbols(user, ["NEW"])
    assert e.value.detail["code"] == "slot_limit" and e.value.detail["limit"] == 25


def test_no_referral_table_keeps_flat_10(monkeypatch):
    # conftest default: database without 019
    assert slots.limit_for({"user_id": U1, "access_level": "free"}) == 15
    assert referrals.account_id_for(U1) is None
    assert referrals.reward_first_follow(U1) is None


def test_account_id_in_profile(monkeypatch, rdb):
    from app.api.v1 import profile
    FakePortfolioDB(monkeypatch)
    rdb.add_user("me", "MEMEMEME", uid=U1)
    c = make_client(monkeypatch, profile.router, level="free")
    assert c.get("/api/v1/profile").json()["account_id"] == "MEMEMEME"
    assert c.put("/api/v1/profile", json={"display_name": "Me"}).json()["account_id"] == "MEMEMEME"


def test_account_id_null_before_migration(monkeypatch):
    from app.api.v1 import auth, profile
    FakePortfolioDB(monkeypatch)
    c = make_client(monkeypatch, auth.router, profile.router, level="free")
    assert c.get("/api/v1/auth/me").json()["account_id"] is None
    assert c.get("/api/v1/profile").json()["account_id"] is None


# ---------------------------------------------------------------- reward

@pytest.fixture
def invited(rdb):
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    # a real friend: signed up 10 days ago and came back 5 days later (referrals.earned)
    rdb.add_user("me", "MEMEMEME", uid=U1, referred_by=rf.REFERRER_ID,
                 created_at=(now - timedelta(days=10)).isoformat(),
                 last_seen_at=(now - timedelta(days=5)).isoformat())
    rdb.add_referral(rf.REFERRER_ID, U1)
    return rdb


def _ref(rdb):
    return next(r for r in rdb.tables["referrals"] if r["referred_id"] == U1)


def test_reward_on_first_holding(monkeypatch, invited):
    from app.api.v1 import holdings
    FakePortfolioDB(monkeypatch)
    monkeypatch.setattr(holdings.holding_status, "kick", lambda uid: False)
    sent = []
    monkeypatch.setattr(referrals, "notify_referrer", lambda rid: _record(sent, rid))
    assert referrals.rewarded_count(rf.REFERRER_ID) == 0       # cached...
    c = make_client(monkeypatch, holdings.router, level="free")
    assert c.post("/api/v1/holdings", json={"items": [{"symbol": "NVDA"}]}).status_code == 201
    assert _ref(invited)["status"] == "rewarded" and _ref(invited)["rewarded_at"]
    assert referrals.rewarded_count(rf.REFERRER_ID) == 1       # ...and invalidated on reward
    assert slots.limit_for({"user_id": rf.REFERRER_ID, "access_level": "free"}) == 20
    first = _ref(invited)["rewarded_at"]
    assert c.post("/api/v1/holdings", json={"items": [{"symbol": "MSFT"}]}).status_code == 201
    assert _ref(invited)["rewarded_at"] == first                 # once


async def _record(sent, rid):
    sent.append(rid)
    return True


def test_reward_on_first_watchlist_add(monkeypatch, invited):
    import yfinance

    from app.api.v1 import watchlist
    from app.db import queries
    FakePortfolioDB(monkeypatch)

    class T:
        info = {"regularMarketPrice": 1.0}
    monkeypatch.setattr(yfinance, "Ticker", lambda s: T())
    monkeypatch.setattr(queries, "add_to_watchlist", lambda uid, s, n=None: {"symbol": s})
    c = make_client(monkeypatch, watchlist.router, level="free")
    assert c.post("/api/v1/watchlist/NVDA").status_code == 201
    assert _ref(invited)["status"] == "rewarded"


def test_reward_is_idempotent_and_only_one_winner(invited):
    assert referrals.reward_first_follow(U1) == rf.REFERRER_ID
    referrals.clear_caches()                                    # even without the cache
    assert referrals.reward_first_follow(U1) is None
    assert [r["status"] for r in invited.tables["referrals"]] == ["rewarded"]


def test_user_without_referral_is_settled(rdb):
    rdb.add_user("solo", uid=U1)
    assert referrals.reward_first_follow(U1) is None
    rdb.missing = True                                          # cached: no DB call any more
    assert referrals.reward_first_follow(U1) is None


def test_after_follow_notifies_referrer_in_background(monkeypatch, invited):
    sent = []
    monkeypatch.setattr(referrals, "notify_referrer", lambda rid: _record(sent, rid))

    async def run():
        out = await referrals.after_follow(U1)
        await asyncio.gather(*referrals._tasks)
        return out
    assert asyncio.run(run()) == rf.REFERRER_ID
    assert sent == [rf.REFERRER_ID]


@pytest.mark.real_access
def test_notify_referrer_needs_telegram_feature_and_chat(monkeypatch):
    from app.services import telegram_notify
    defaults = {k: v[0] for k, v in access.FEATURE_CATALOG.items()}
    monkeypatch.setattr(access, "get_feature_levels", lambda: dict(defaults))
    level = {"v": "premium"}
    monkeypatch.setattr(access, "get_user_access", lambda uid: {"level": level["v"], "slot_bonus": 0})
    chat = {"v": "555"}
    monkeypatch.setattr(telegram_notify, "linked_chat", lambda uid: chat["v"])
    monkeypatch.setattr(telegram_notify, "user_language", lambda uid: "pt")
    sent = []

    async def fake_send(chat_id, text):
        sent.append((chat_id, text))
        return True
    monkeypatch.setattr(telegram_notify, "send", fake_send)

    assert asyncio.run(referrals.notify_referrer(rf.REFERRER_ID)) is True
    assert sent[0][0] == "555" and "Seu amigo entrou no Signa" in sent[0][1] and "+5" in sent[0][1]
    level["v"] = "free"                                         # no feature.telegram_alerts
    assert asyncio.run(referrals.notify_referrer(rf.REFERRER_ID)) is False
    level["v"], chat["v"] = "premium", None                     # no linked chat
    assert asyncio.run(referrals.notify_referrer(rf.REFERRER_ID)) is False
    assert len(sent) == 1


def test_english_message():
    from app.notifications.messages import msg_for
    assert msg_for("en", "user_tg_referral_rewarded", per_friend=5).startswith("🎉 <b>Your friend joined Signa</b>")


def test_signup_settings_from_locale():
    from app.services.profile_service import signup_settings as s
    assert s(None, None, None, "pt-BR") == {"country": "BR", "home_currency": "BRL", "language": "pt"}
    assert s("US", None, "en", "pt-BR") == {"country": "US", "home_currency": "USD", "language": "en"}
    assert s(None, "EUR", None, "de_DE") == {"country": "DE", "home_currency": "EUR", "language": "en"}
    assert s("XX", "ZZZ", "fr", None) == {}



def test_new_account_is_not_rewarded_yet(monkeypatch, rdb):
    """A brand-new friend (or a throwaway sign-up) doesn't pay out on the first follow."""
    from datetime import datetime, timezone
    rdb.add_user("fresh", "FRESHFRE", uid=U1, referred_by=rf.REFERRER_ID,
                 last_seen_at=datetime.now(timezone.utc).isoformat())
    rdb.add_referral(rf.REFERRER_ID, U1)
    assert referrals.reward_first_follow(U1) is None
    assert rdb.tables["referrals"][0]["status"] == "pending"


def test_earned_rule():
    from datetime import datetime, timezone
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    assert referrals.earned({"created_at": "2026-10-01T00:00:00Z", "last_seen_at": "2026-10-05T00:00:00Z"}, now)
    assert not referrals.earned({"created_at": "2026-10-01T00:00:00Z", "last_seen_at": "2026-10-02T00:00:00Z"}, now)
    assert not referrals.earned({"created_at": "2026-10-18T00:00:00Z", "last_seen_at": "2026-10-19T00:00:00Z"}, now)
