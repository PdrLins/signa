"""Live notification jobs follow price refreshes, not a fixed New York window."""

import asyncio

from app.scheduler import jobs
from app.services import quotes


def test_live_jobs_run_only_after_prices_moved(monkeypatch):
    calls = []

    async def fake_push(mode="events"):
        calls.append(mode)

    monkeypatch.setattr(jobs, "push_notifications", fake_push)
    monkeypatch.setattr(jobs, "_live_ran", {})
    monkeypatch.setattr(quotes, "_last_priced_at", 0.0)

    asyncio.run(jobs.push_notifications_live())
    assert calls == []                       # nothing priced yet (overnight, holiday)

    quotes.mark_priced(10**10)               # a refresh stored prices
    asyncio.run(jobs.push_notifications_live())
    assert calls == ["live"]

    monkeypatch.setattr(quotes, "_last_priced_at", 1.0)
    asyncio.run(jobs.push_notifications_live())
    assert calls == ["live"]                 # no new prices since that run


def test_nightly_cleanup_trims_growing_tables(monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from app.db import supabase

    calls = []

    class Q:
        def __init__(self, name):
            self.name = name
            self.not_ = self

        def delete(self, **kw):
            assert kw["returning"].value == "minimal"
            return self

        def lt(self, col, value):
            calls.append((self.name, col, value))
            return self

        def is_(self, col, value):
            calls.append((self.name, "used", value))
            return self

        def execute(self):
            return SimpleNamespace(count=2)

    monkeypatch.setattr(supabase, "get_client", lambda: SimpleNamespace(table=Q))
    out = jobs._cleanup_db(datetime(2026, 10, 3, tzinfo=timezone.utc))
    assert out["notification_deliveries"] == 2 and out["otps"] == 4
    assert ("check_status_daily", "check_date", "2026-08-04") in calls
    assert ("notification_deliveries", "sent_at", "2026-08-19T00:00:00+00:00") in calls
    assert ("audit_logs", "created_at", "2026-04-06T00:00:00+00:00") in calls


def test_live_candidates_only_movers_and_fired_alerts(monkeypatch):
    from datetime import date, datetime, timezone

    from app.db import queries
    from app.services import telegram_notify

    monkeypatch.setattr(queries, "get_mover_quotes", lambda pct: [
        {"symbol": "NVDA", "change_pct": 7.0, "as_of": "2026-10-02T19:59:00+00:00"},   # today (ET)
        {"symbol": "OLD", "change_pct": 9.0, "as_of": "2026-09-30T19:59:00+00:00"}])   # yesterday's move
    seen = {}
    monkeypatch.setattr(queries, "get_holder_ids", lambda syms: seen.setdefault("syms", syms) and {"u1"})
    monkeypatch.setattr(queries, "get_recent_alert_user_ids", lambda since: {"u2"})
    now = datetime(2026, 10, 2, 20, 0, tzinfo=timezone.utc)
    assert telegram_notify.live_candidates(date(2026, 10, 2), now) == {"u1", "u2"}
    assert seen["syms"] == ["NVDA"]

    def boom(pct):
        raise RuntimeError("db down")
    monkeypatch.setattr(queries, "get_mover_quotes", boom)
    assert telegram_notify.live_candidates(date(2026, 10, 2), now) is None   # fail open


def _deliver(monkeypatch, n_lines, send_ok=True, blocked=False):
    from datetime import date, datetime, timezone

    from app.core import access
    from app.db import queries
    from app.notifications import telegram_bot
    from app.services import telegram_notify as tn

    sent, recorded, unlinked = [], [], []
    monkeypatch.setattr(access, "get_user_access", lambda uid: {"level": "premium", "slot_bonus": 0})

    async def lines(user, mode, today, now):
        return "en", [("big_move", f"k{i}", "x" * 200) for i in range(n_lines)]
    monkeypatch.setattr(tn, "_lines_for", lines)
    monkeypatch.setattr(queries, "get_delivered_keys", lambda uid, keys: set())
    monkeypatch.setattr(queries, "insert_deliveries", lambda uid, items: recorded.extend(items))
    monkeypatch.setattr(queries, "delete_telegram_link", lambda uid: unlinked.append(uid))

    async def send(chat, text):
        sent.append(text)
        if blocked:
            telegram_bot.blocked_chats.add(chat)
        return send_ok
    monkeypatch.setattr(tn, "send", send)
    n = asyncio.run(tn.deliver_user({"user_id": "u1", "chat_id": "c1"}, "live", date(2026, 10, 2),
                                    datetime(2026, 10, 2, tzinfo=timezone.utc)))
    return n, sent, recorded, unlinked


def test_long_digest_is_cut_under_telegram_limit(monkeypatch):
    n, sent, recorded, _ = _deliver(monkeypatch, 60)
    assert len(sent[0]) <= 4000 and 0 < n < 60 and len(recorded) == n   # the rest goes next run


def test_blocked_bot_unlinks_the_chat(monkeypatch):
    n, _, recorded, unlinked = _deliver(monkeypatch, 2, send_ok=False, blocked=True)
    assert n == 0 and recorded == [] and unlinked == ["u1"]
