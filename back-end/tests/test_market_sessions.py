"""app/market/sessions.py + the quotes job refreshing each exchange in its own session."""

from datetime import date, datetime, timezone

from app.core.market_calendar import is_daily_bar_complete, is_market_open, trading_days_until
from app.db import queries
from app.market import sessions
from app.services import quotes as quotes_svc

MON_14UTC = datetime(2026, 10, 5, 14, 0, tzinfo=timezone.utc)   # 10:00 New York, 11:00 São Paulo, 23:00 Tokyo


def test_sessions_by_exchange():
    assert sessions.is_open("US", MON_14UTC) and sessions.is_open("B3", MON_14UTC) and sessions.is_open("LSE", MON_14UTC)
    assert not sessions.is_open("Tokyo", MON_14UTC)
    assert sessions.label_for_symbol("PETR4.SA") == "B3" and sessions.label_for_symbol("AAPL") == "US"
    assert sessions.label_for_symbol("BTC-BRL") == "CRYPTO" and sessions.is_trading("BTC-USD", MON_14UTC)


def test_b3_holidays_and_calendar_helpers():
    assert not sessions.is_session_day("B3", date(2026, 2, 16))          # Carnaval
    assert not is_market_open("B3", date(2026, 9, 7))                    # Independence Day
    assert is_market_open("B3", date(2026, 10, 5))
    assert trading_days_until("B3", date(2026, 9, 8), date(2026, 9, 4)) == 1   # Fri -> Tue, Mon holiday
    close = sessions.close_of("B3", date(2026, 10, 5))
    assert not is_daily_bar_complete("B3", date(2026, 10, 5), MON_14UTC)
    assert is_daily_bar_complete("B3", date(2026, 10, 5), close)


def test_quotes_job_refreshes_only_open_exchanges(monkeypatch):
    monkeypatch.setattr(queries, "get_follow_rows", lambda: [
        {"user_id": "u", "symbol": s} for s in ("PETR4.SA", "7203.T", "AAPL", "VOD.L")])
    monkeypatch.setattr(queries, "get_users_activity", lambda: [{"id": "u", "access_level": "free",
                                                                 "last_seen_at": MON_14UTC.isoformat()}])
    monkeypatch.setattr("app.services.price_alerts.alert_follow_rows", lambda: [])
    monkeypatch.setattr(quotes_svc, "_last_refresh", {})
    asked = []
    monkeypatch.setattr(quotes_svc, "refresh_quotes", lambda syms: asked.append(sorted(syms)) or {})
    monkeypatch.setattr("app.services.price_alerts.evaluate_refreshed", lambda q, now: 0)
    quotes_svc.refresh_followed_quotes(now=MON_14UTC)
    assert asked == [["AAPL", "PETR4.SA", "VOD.L"]]                 # Tokyo is closed
    quotes_svc.clear_follow_cache()
    sunday_night = datetime(2026, 10, 5, 1, 0, tzinfo=timezone.utc)  # Sun 21:00 ET = Mon 10:00 Tokyo
    monkeypatch.setattr(quotes_svc, "_last_refresh", {})
    asked.clear()
    quotes_svc.refresh_followed_quotes(now=sunday_night)
    assert asked == [["7203.T"]]
