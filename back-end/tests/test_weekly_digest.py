"""Sunday "your week" push (app/services/weekly_digest.py)."""

from datetime import date, datetime, timezone

from app.services import weekly_digest as wd
from app.services.telegram_notify import money


def _d(pct=1.234, abs_=540.0, received=32.0, payments=3, expected=85.0, ccy="CAD"):
    return {"currency": ccy, "change": {"abs": abs_, "pct": pct}, "dividends_received": received,
            "next_week": {"payments": payments, "expected": expected}}


def test_push_text_en_pt_and_hidden():
    assert wd.push_text(_d(), money, "en") == \
        "Your week: +1.2% (+C$540.00) · C$32.00 in dividends · next week: 3 dividends (C$85.00)"
    pt = wd.push_text(_d(ccy="BRL"), money, "pt")
    assert pt.startswith("Sua semana: +1,2% (+R$") and "em dividendos" in pt and "próxima semana: 3 dividendos" in pt
    assert wd.push_text(_d(), money, "en", hide_amounts=True) == "Your weekly summary is ready."


def test_push_text_without_a_change_or_anything():
    d = _d(pct=None, abs_=None, received=None, payments=1, expected=None)
    assert wd.push_text(d, money, "en") == "Your week: next week: 1 dividend"
    empty = _d(pct=None, abs_=None, received=None, payments=0, expected=None)
    assert wd.push_text(empty, money, "en") == "A quiet week."


def test_week_key_is_iso_week():
    assert wd.week_key(date(2026, 10, 11)) == "push:weekly:2026-W41"


def test_catch_up_window_for_the_weekly_push():
    from app.scheduler import health
    sunday_noon = datetime(2026, 10, 11, 16, 0, tzinfo=timezone.utc)      # 12:00 ET
    assert health.last_due("weekly_digest", sunday_noon).date() == date(2026, 10, 11)
    assert health.overdue("weekly_digest", None, sunday_noon) is True
    monday_evening = datetime(2026, 10, 12, 23, 0, tzinfo=timezone.utc)
    assert health.overdue("weekly_digest", None, monday_evening) is False


def test_run_sends_once_per_week_and_skips_opted_out(monkeypatch):
    import asyncio

    from app.db import queries
    from app.services import notification_prefs, push
    from app.services import portfolio_context as pc

    monkeypatch.setattr(push, "active_devices", lambda: [{"user_id": "a", "token": "t1"}, {"user_id": "b", "token": "t2"}])
    prefs = {"a": {"weekly_digest": {"enabled": True}}, "b": {"weekly_digest": {"enabled": False}}}
    monkeypatch.setattr(notification_prefs, "get_prefs", lambda uid: {"prefs": prefs[uid]})
    delivered = set()
    monkeypatch.setattr(queries, "get_delivered_keys", lambda uid, keys: {k for k in keys if (uid, k) in delivered})
    monkeypatch.setattr(queries, "insert_deliveries", lambda uid, items: delivered.update((uid, k) for _, k in items))
    monkeypatch.setattr("app.core.access.get_user_access", lambda uid: {"level": "free", "slot_bonus": 0})
    monkeypatch.setattr(pc, "load_scope", lambda *a, **k: {"holdings": [{"symbol": "X"}], "home_currency": "CAD"})
    monkeypatch.setattr(wd, "build", lambda scope, today, upcoming: _d())

    async def no_events(scope):
        return []
    monkeypatch.setattr("app.services.recap.next_month_events", no_events)
    monkeypatch.setattr("app.services.telegram_notify.user_language", lambda uid: "en")
    sent = []

    async def notify(uid, title, body, data=None):
        sent.append((uid, body))
        return 1
    monkeypatch.setattr(push, "notify_user", notify)
    out = asyncio.run(wd.run(date(2026, 10, 11)))
    assert out["sent"] == 1 and [u for u, _ in sent] == ["a"]
    assert asyncio.run(wd.run(date(2026, 10, 11)))["sent"] == 0      # same week: never twice


def test_build_with_a_real_scope(monkeypatch):
    from datetime import timedelta

    import pandas as pd

    from app.services import portfolio_context as pc
    from app.services import portfolio_performance as perf
    from tests.portfolio_fakes import U1, FakePortfolioDB

    perf.clear_cache()
    db = FakePortfolioDB(monkeypatch)
    db.settings[U1] = {"user_id": U1, "home_currency": "CAD"}
    a = db.add_account(U1, "Main", currency="CAD", cash_balance=0)
    db.add_holding(U1, "XEQT.TO", a, shares=100, avg_cost=30)
    today = perf.today_et()
    db.quotes["XEQT.TO"] = {"symbol": "XEQT.TO", "price": 33.0, "prev_close": 32.0, "currency": "CAD",
                            "as_of": datetime.now(timezone.utc).isoformat()}
    idx = pd.bdate_range(end=pd.Timestamp(today), periods=30)
    db.closes["XEQT.TO"] = pd.Series([30.0] * 29 + [33.0], index=idx)
    db.insert_transactions(U1, [{"account_id": a, "symbol": None, "type": "dividend", "trade_date":
                                 (today - timedelta(days=2)).isoformat(), "quantity": None, "price": None,
                                 "amount": 25, "currency": "CAD", "fee": 0}])
    scope = pc.load_scope({"user_id": U1, "access_level": "free"}, None, None, True)
    upcoming = [{"owned": True, "date": (today + timedelta(days=3)).isoformat(), "expected_cash": 12.5, "currency": "CAD"},
                {"owned": True, "date": (today + timedelta(days=20)).isoformat(), "expected_cash": 99, "currency": "CAD"}]
    d = wd.build(scope, today, upcoming)
    assert d["dividends_received"] == 25.0
    assert d["next_week"] == {"payments": 1, "expected": 12.5}
    assert d["change"]["pct"] is not None
    perf.clear_cache()
