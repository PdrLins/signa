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
