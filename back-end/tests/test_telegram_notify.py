"""Per-user Telegram notifications (migration 016) — fakes only, no network."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest

from app.api.v1 import notifications
from app.core.config import settings
from app.db import queries
from app.services import telegram_notify as tn
from tests.portfolio_fakes import U1, U2, FakePortfolioDB, make_client, set_level

TODAY = date(2026, 10, 7)  # a Wednesday
NOW = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)


class FakeTelegramDB:
    """In-memory telegram_links / telegram_link_codes / notification_deliveries."""

    def __init__(self, monkeypatch):
        self.links: dict[str, dict] = {}
        self.codes: dict[str, dict] = {}
        self.deliveries: set[tuple[str, str]] = set()
        self.missing = False
        for name in ("get_telegram_link", "get_telegram_links", "upsert_telegram_link", "delete_telegram_link",
                     "replace_telegram_link_code", "get_pending_telegram_link_code", "consume_telegram_link_code",
                     "get_delivered_keys", "insert_deliveries"):
            monkeypatch.setattr(queries, name, self._wrap(getattr(self, name)))

    def _wrap(self, fn):
        def inner(*a, **k):
            if self.missing:
                raise RuntimeError('relation "public.telegram_links" does not exist (42P01)')
            return fn(*a, **k)
        return inner

    def get_telegram_link(self, uid):
        return dict(self.links[uid]) if uid in self.links else None

    def get_telegram_links(self):
        return [dict(v) for v in self.links.values()]

    def upsert_telegram_link(self, uid, chat_id, username):
        for other in [u for u, v in self.links.items() if v["chat_id"] == chat_id and u != uid]:
            del self.links[other]
        self.links[uid] = {"user_id": uid, "chat_id": chat_id, "username": username,
                           "linked_at": "2026-10-07T15:00:00+00:00"}
        return self.links[uid]

    def delete_telegram_link(self, uid):
        self.links.pop(uid, None)

    def replace_telegram_link_code(self, uid, code_hash, expires_at):
        for h in [h for h, c in self.codes.items() if c["user_id"] == uid and not c["used_at"]]:
            del self.codes[h]
        self.codes[code_hash] = {"user_id": uid, "expires_at": expires_at, "used_at": None}

    def get_pending_telegram_link_code(self, uid, now_iso):
        rows = [c for c in self.codes.values() if c["user_id"] == uid and not c["used_at"]
                and c["expires_at"] > now_iso]
        return {"expires_at": max(r["expires_at"] for r in rows)} if rows else None

    def consume_telegram_link_code(self, code_hash, now_iso):
        c = self.codes.get(code_hash)
        if not c or c["used_at"] or c["expires_at"] <= now_iso:
            return None
        c["used_at"] = now_iso
        return c["user_id"]

    def get_delivered_keys(self, uid, keys):
        return {k for k in keys if (uid, k) in self.deliveries}

    def insert_deliveries(self, uid, items):
        for _kind, key in items:
            self.deliveries.add((uid, key))


@pytest.fixture
def db(monkeypatch):
    d = FakePortfolioDB(monkeypatch)
    d.settings[U1] = {"user_id": U1, "home_currency": "CAD", "language": "en"}
    return d


@pytest.fixture
def tg(monkeypatch):
    return FakeTelegramDB(monkeypatch)


@pytest.fixture
def sent(monkeypatch):
    out: list[tuple[str, str]] = []

    async def fake_send(chat_id, text):
        out.append((chat_id, text))
        return True

    monkeypatch.setattr(tn, "send", fake_send)
    monkeypatch.setattr(settings, "telegram_bot_token", "123:abc")
    monkeypatch.setattr(settings, "telegram_bot_username", "SignaBot")
    monkeypatch.setattr(settings, "telegram_notifications_enabled", True)
    return out


def _client(monkeypatch, level="premium", uid=U1):
    return make_client(monkeypatch, notifications.router, level=level, uid=uid)


# ---------------------------------------------------------------- API

def test_status_unlinked_shape(monkeypatch, db, tg, sent):
    body = _client(monkeypatch).get("/api/v1/notifications/telegram").json()
    assert body == {"available": True, "linked": False, "username": None, "linked_at": None,
                    "bot_username": "SignaBot", "pending": None}


def test_status_free_user_is_not_available(monkeypatch, db, tg, sent):
    body = _client(monkeypatch, level="free").get("/api/v1/notifications/telegram").json()
    assert body["available"] is False and body["linked"] is False


def test_link_issues_one_time_url_and_status_shows_pending(monkeypatch, db, tg, sent):
    c = _client(monkeypatch)
    r = c.post("/api/v1/notifications/telegram/link")
    assert r.status_code == 200
    body = r.json()
    assert len(body["code"]) >= 16
    assert body["url"] == f"https://t.me/SignaBot?start={body['code']}"
    assert tn.hash_code(body["code"]) in tg.codes and body["code"] not in tg.codes  # only the hash is stored
    status_ = c.get("/api/v1/notifications/telegram").json()
    assert status_["pending"] == {"expires_at": body["expires_at"]}


def test_new_code_invalidates_the_older_one(monkeypatch, db, tg, sent):
    c = _client(monkeypatch)
    first = c.post("/api/v1/notifications/telegram/link").json()["code"]
    second = c.post("/api/v1/notifications/telegram/link").json()["code"]
    assert tn.hash_code(first) not in tg.codes and tn.hash_code(second) in tg.codes


def test_link_and_test_need_premium(monkeypatch, db, tg, sent):
    c = _client(monkeypatch, level="free")
    for path in ("/api/v1/notifications/telegram/link", "/api/v1/notifications/telegram/test"):
        r = c.post(path)
        assert r.status_code == 403 and r.json()["detail"]["code"] == "upgrade_required"


def test_link_without_bot_is_not_configured(monkeypatch, db, tg, sent):
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    r = _client(monkeypatch).post("/api/v1/notifications/telegram/link")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "telegram_not_configured"


def test_test_message_409_then_200(monkeypatch, db, tg, sent):
    c = _client(monkeypatch)
    r = c.post("/api/v1/notifications/telegram/test")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_linked"
    tg.upsert_telegram_link(U1, "555", "@pedro")
    r = c.post("/api/v1/notifications/telegram/test")
    assert r.status_code == 200 and r.json() == {"sent": True}
    assert sent[-1][0] == "555" and "Signa test" in sent[-1][1]


def test_test_message_send_failure_is_502(monkeypatch, db, tg, sent):
    async def failing(chat_id, text):
        return False
    monkeypatch.setattr(tn, "send", failing)
    tg.upsert_telegram_link(U1, "555", "@pedro")
    r = _client(monkeypatch).post("/api/v1/notifications/telegram/test")
    assert r.status_code == 502 and r.json()["detail"]["code"] == "telegram_send_failed"


def test_unlink_works_even_after_downgrade(monkeypatch, db, tg, sent):
    tg.upsert_telegram_link(U1, "555", "@pedro")
    r = _client(monkeypatch, level="free").delete("/api/v1/notifications/telegram")
    assert r.status_code == 200 and r.json() == {"unlinked": True} and U1 not in tg.links


def test_endpoints_before_migration_016(monkeypatch, db, tg, sent):
    tg.missing = True
    r = _client(monkeypatch).get("/api/v1/notifications/telegram")
    assert r.status_code == 503
    assert r.json()["detail"] == {**r.json()["detail"], "code": "migration_required",
                                  "migration": "016_telegram_notifications.sql"}


# ---------------------------------------------------------------- webhook /start

def _start(code, chat_id=777, username="pedro", lang="en", chat_type="private"):
    return asyncio.run(tn.handle_start(code, {"id": chat_id, "type": chat_type},
                                       {"username": username, "language_code": lang}))


def test_start_with_valid_code_links_the_chat(monkeypatch, db, tg, sent):
    code = _client(monkeypatch).post("/api/v1/notifications/telegram/link").json()["code"]
    assert _start(code) is True
    assert tg.links[U1]["chat_id"] == "777" and tg.links[U1]["username"] == "@pedro"
    assert sent[-1][0] == "777" and "connected" in sent[-1][1]
    # single use
    assert _start(code, chat_id=888) is True
    assert "expired" in sent[-1][1] and tg.links[U1]["chat_id"] == "777"


def test_start_with_expired_or_unknown_code(monkeypatch, db, tg, sent):
    tg.codes[tn.hash_code("old-code-old-code-1")] = {"user_id": U1, "used_at": None,
                                                    "expires_at": "2000-01-01T00:00:00+00:00"}
    assert _start("old-code-old-code-1", lang="pt") is True
    assert "expirou" in sent[-1][1] and U1 not in tg.links
    assert _start("never-issued-code-xyz") is True and U1 not in tg.links


def test_start_ignores_group_chats(monkeypatch, db, tg, sent):
    assert _start("whatever-code-123456", chat_type="group") is False and not sent


def test_linking_a_chat_from_another_account_moves_it(monkeypatch, db, tg, sent):
    db.settings[U2] = {"user_id": U2, "home_currency": "CAD"}
    tg.upsert_telegram_link(U1, "777", "@pedro")
    code = _client(monkeypatch, uid=U2).post("/api/v1/notifications/telegram/link").json()["code"]
    _start(code, chat_id=777)
    assert U1 not in tg.links and tg.links[U2]["chat_id"] == "777"


# ---------------------------------------------------------------- line builders

def _prefs(**overrides):
    from app.services.notification_prefs import DEFAULTS
    p = {k: dict(v) for k, v in DEFAULTS.items()}
    for k, v in overrides.items():
        p[k].update(v)
    return p


def _items():
    d = lambda n: (TODAY + timedelta(days=n)).isoformat()  # noqa: E731
    return [
        {"type": "ex_dividend", "date": d(1), "symbol": "ENB.TO", "owned": True, "shares": 100,
         "cash_home": 94.25, "cash": 94.25, "currency": "CAD", "estimated": False},
        {"type": "ex_dividend", "date": d(1), "symbol": "AAPL", "owned": False, "shares": None},
        {"type": "dividend_payment", "date": d(0), "symbol": "BNS.TO", "owned": True, "shares": 10,
         "cash_home": 11.0, "estimated": False},
        {"type": "dividend_payment", "date": d(0), "symbol": "TD.TO", "owned": True, "shares": 10,
         "cash_home": 10.2, "estimated": True},
        {"type": "earnings", "date": d(2), "symbol": "MSFT", "owned": True, "trading_days": 2,
         "avg_abs_move_pct": 4.3},
        {"type": "analyst", "date": d(-1), "symbol": "MSFT", "owned": True, "firm": "Mizuho",
         "action": "up", "from_grade": "Neutral", "to_grade": "Buy"},
        {"type": "check_changed", "date": d(0), "symbol": "ENB.TO", "owned": True,
         "changes": [{"key": "uptrend", "from": "pass", "to": "warn"}]},
        {"type": "economy", "date": d(1), "symbol": None, "code": "boc_rate", "title": "BoC"},
    ]


def test_event_lines_every_kind_with_defaults():
    lines = tn.event_lines(_items(), _prefs(analyst_ratings={"enabled": True}), TODAY, "en", "CAD")
    kinds = [k for k, _, _ in lines]
    assert kinds == ["exdiv_reminder", "dividend_paid", "earnings", "analyst_ratings", "check_changed", "economy"]
    text = "\n".join(t for _, _, t in lines)
    assert "ENB.TO</b> goes ex-dividend tomorrow · C$94.25" in text
    assert "AAPL" not in text and "TD.TO" not in text  # not owned / projected pay date
    assert "usually moves ±4.3%" in text and "Mizuho upgraded (Neutral → Buy)" in text
    assert "Bank of Canada rate decision tomorrow" in text


def test_event_lines_respect_each_pref():
    for kind in ("exdiv_reminder", "dividend_paid", "earnings", "check_changed", "economy"):
        lines = tn.event_lines(_items(), _prefs(**{kind: {"enabled": False}}), TODAY, "en", "CAD")
        assert kind not in {k for k, _, _ in lines}
    # analyst ratings are off by default
    assert "analyst_ratings" not in {k for k, _, _ in tn.event_lines(_items(), _prefs(), TODAY, "en", "CAD")}


def test_event_lines_in_portuguese():
    text = "\n".join(t for _, _, t in tn.event_lines(_items(), _prefs(), TODAY, "pt", "CAD"))
    assert "fica ex-dividendo amanhã" in text and "Decisão de juros do Banco do Canadá amanhã" in text


def test_dividend_change_raise_and_cut():
    profiles = {
        "ENB.TO": {"currency": "CAD", "last_payments": [{"ex_date": TODAY.isoformat(), "amount": 0.9775},
                                                        {"ex_date": "2026-07-14", "amount": 0.9425}]},
        "XYZ": {"currency": "USD", "last_payments": [{"ex_date": (TODAY - timedelta(days=1)).isoformat(),
                                                      "amount": 0.25}, {"ex_date": "2026-07-01", "amount": 0.5}]},
        "OLD": {"last_payments": [{"ex_date": "2026-06-01", "amount": 2}, {"ex_date": "2026-03-01", "amount": 1}]},
    }
    lines = tn.dividend_change_lines(profiles, {"ENB.TO", "XYZ", "OLD"}, _prefs(), TODAY, "en")
    text = "\n".join(t for _, _, t in lines)
    assert "ENB.TO</b> raised its dividend +3.7%" in text and "XYZ</b> cut its dividend −50.0%" in text
    assert "OLD" not in text
    assert tn.dividend_change_lines(profiles, {"ENB.TO"}, _prefs(dividend_change={"enabled": False}), TODAY, "en") == []


def test_big_move_threshold_and_todays_quote_only():
    today_iso = "2026-10-07T15:00:00+00:00"
    positions = [
        {"symbol": "NVDA", "shares": 3, "change_pct": -6.2, "price_source": "quote", "as_of": today_iso},
        {"symbol": "MSFT", "shares": 2, "change_pct": 2.0, "price_source": "quote", "as_of": today_iso},
        {"symbol": "OLD", "shares": 2, "change_pct": 9.0, "price_source": "quote", "as_of": "2026-10-06T19:00:00+00:00"},
    ]
    lines = tn.big_move_lines(positions, _prefs(), TODAY, "en")
    assert [k for _, k, _ in lines] == ["bigmove:NVDA:2026-10-07"] and "−6.2%" in lines[0][2]
    assert [k for _, k, _ in tn.big_move_lines(positions, _prefs(big_move={"threshold_pct": 1.5}), TODAY, "en")] \
        == ["bigmove:NVDA:2026-10-07", "bigmove:MSFT:2026-10-07"]
    assert tn.big_move_lines(positions, _prefs(big_move={"enabled": False}), TODAY, "en") == []


def test_price_alert_lines_last_24h_only():
    rows = [
        {"id": "a1", "symbol": "ENB.TO", "direction": "below", "target_price": 50, "last_price": 49.8,
         "currency": "CAD", "triggered_at": (NOW - timedelta(hours=2)).isoformat()},
        {"id": "a2", "symbol": "AAPL", "direction": "above", "target_price": 250, "last_price": 251,
         "currency": "USD", "triggered_at": (NOW - timedelta(days=3)).isoformat()},
    ]
    lines = tn.alert_lines(rows, "en", NOW)
    assert [k for _, k, _ in lines] == [f"alert:a1:{rows[0]['triggered_at'][:19]}"]   # one key per firing
    assert "fell to C$50.00 (now C$49.80)" in lines[0][2]


def test_percent_and_day_move_alert_text():
    pct = {"id": "p", "symbol": "RY.TO", "kind": "percent", "direction": "above", "percent": 10,
           "last_price": 188.2, "currency": "CAD", "triggered_at": NOW.isoformat()}
    assert tn.alert_message(pct, "en") == "🎯 <b>RY.TO</b> is up 10% since you set the alert (C$188.20)"
    assert tn.alert_message(pct, "en", hide_amounts=True) == "🎯 <b>RY.TO</b> is up 10% since you set the alert"
    day = {"id": "d", "symbol": "RY.TO", "kind": "day_move", "direction": "either", "percent": 5,
           "last_change_pct": -5.3, "currency": "CAD", "triggered_at": NOW.isoformat()}
    assert tn.alert_message(day, "en") == "📈 <b>RY.TO</b> moved −5.3% today"
    assert tn.alert_message(day, "pt") == "📈 <b>RY.TO</b> variou −5,3% hoje"
    price = {"id": "x", "symbol": "ENB.TO", "direction": "below", "target_price": 50, "last_price": 49.8,
             "currency": "CAD"}
    assert "C$" not in tn.alert_message(price, "en", hide_amounts=True)


# ---------------------------------------------------------------- delivery job

def _stub_lines(monkeypatch, lines):
    async def fake(user, mode, today, now):
        return "en", list(lines)
    monkeypatch.setattr(tn, "_lines_for", fake)


def test_delivery_sends_once_then_dedupes(monkeypatch, db, tg, sent):
    set_level(monkeypatch, "premium")
    tg.upsert_telegram_link(U1, "555", "@pedro")
    _stub_lines(monkeypatch, [("economy", "economy:boc_rate:2026-10-08", "🏦 BoC tomorrow"),
                              ("economy", "economy:boc_rate:2026-10-08", "🏦 BoC tomorrow")])
    r = asyncio.run(tn.run_delivery("events", TODAY, NOW))
    assert r["lines"] == 1 and len(sent) == 1 and sent[0][1].count("BoC") == 1
    r = asyncio.run(tn.run_delivery("events", TODAY, NOW))
    assert r["lines"] == 0 and len(sent) == 1


def test_delivery_stops_after_downgrade(monkeypatch, db, tg, sent):
    set_level(monkeypatch, "free")
    tg.upsert_telegram_link(U1, "555", "@pedro")
    _stub_lines(monkeypatch, [("economy", "k1", "line")])
    assert asyncio.run(tn.run_delivery("events", TODAY, NOW))["lines"] == 0 and not sent


def test_failed_send_is_retried_next_run(monkeypatch, db, tg, sent):
    set_level(monkeypatch, "premium")
    tg.upsert_telegram_link(U1, "555", "@pedro")
    _stub_lines(monkeypatch, [("economy", "k1", "line")])

    async def failing(chat_id, text):
        return False
    monkeypatch.setattr(tn, "send", failing)
    assert asyncio.run(tn.run_delivery("events", TODAY, NOW))["lines"] == 0 and not tg.deliveries


def test_delivery_skips_before_migration(monkeypatch, db, tg, sent):
    tg.missing = True
    assert asyncio.run(tn.run_delivery("events", TODAY, NOW))["status"] == "migration_required"


def test_lines_for_events_uses_feed_and_language(monkeypatch, db, tg, sent):
    db.settings[U1]["language"] = "pt"
    from app.services import events_feed

    async def feed(scope, watchlist, days, today=None, price_alerts=None):
        return {"items": _items()}

    async def profiles(symbols):
        return {}

    monkeypatch.setattr(events_feed, "build_upcoming", feed)
    monkeypatch.setattr(events_feed, "fetch_profiles", profiles)
    lang, lines = asyncio.run(tn._lines_for({"user_id": U1, "access_level": "premium"}, "events", TODAY, NOW))
    assert lang == "pt" and "economy" in {k for k, _, _ in lines}
