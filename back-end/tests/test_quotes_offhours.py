"""Quotes outside the regular session (migration 021): crypto 24/7, US
pre-market / after-hours for Premium (app/services/quotes.py)."""

from datetime import datetime, timezone

import pandas as pd
import pytest

from app.services import quotes as q

UTC = timezone.utc


def test_market_phase_and_symbol_kinds():
    assert q.market_phase(datetime(2026, 10, 1, 11, 0, tzinfo=UTC)) == "pre"      # 7:00 ET
    assert q.market_phase(datetime(2026, 10, 1, 14, 0, tzinfo=UTC)) == "regular"
    assert q.market_phase(datetime(2026, 10, 1, 21, 0, tzinfo=UTC)) == "post"     # 17:00 ET
    assert q.market_phase(datetime(2026, 10, 2, 2, 0, tzinfo=UTC)) == "closed"    # 22:00 ET
    assert q.market_phase(datetime(2026, 10, 3, 15, 0, tzinfo=UTC)) == "closed"   # Saturday
    assert q.is_us_equity("META") and q.is_us_equity("BRK-B")
    assert not q.is_us_equity("XEQT.TO") and not q.is_us_equity("BTC-USD") and not q.is_us_equity("^GSPC")
    assert q.is_crypto("BTC-USD") and not q.is_crypto("META")


def test_parse_extended_takes_last_bar_only_outside_session():
    idx = pd.DatetimeIndex(["2026-10-01 19:50", "2026-10-01 20:00", "2026-10-01 23:55"]).tz_localize("UTC")
    frame = pd.DataFrame({("Close", "META"): [730.0, 729.0, 726.78], ("Close", "AAPL"): [331.0, 330.5, None]},
                         index=idx)
    frame.columns = pd.MultiIndex.from_tuples(frame.columns)
    out = q.parse_extended(frame, ["META", "AAPL"])
    assert out["META"]["ext_price"] == 726.78 and out["META"]["ext_session"] == "post"
    assert out["AAPL"]["ext_session"] == "post" and out["AAPL"]["ext_price"] == 330.5   # 16:00 ET bar


def test_extended_view_rules():
    quote = {"price": 738.79, "as_of": "2026-10-01T20:00:00+00:00"}
    ext = {"ext_price": 726.78, "ext_change_pct": -1.63, "ext_session": "post", "ext_as_of": "2026-10-01T23:55:00+00:00"}
    evening = datetime(2026, 10, 2, 0, 30, tzinfo=UTC)
    v = q.extended_view(quote, ext, evening)
    assert v == {"session": "post", "price": 726.78, "change_pct": -1.63, "as_of": "2026-10-01T23:55:00+00:00"}
    assert q.extended_view(quote, ext, datetime(2026, 10, 2, 14, 0, tzinfo=UTC)) is None        # regular session
    assert q.extended_view({**quote, "as_of": "2026-10-02T00:00:00+00:00"}, ext, evening) is None  # older than the price
    assert q.extended_view(quote, ext, datetime(2026, 10, 3, 0, 0, tzinfo=UTC)) is None          # > 20 h old
    assert q.extended_view(quote, None, evening) is None


def test_extended_payload_locks_for_free(monkeypatch):
    monkeypatch.setattr(q, "market_phase", lambda now=None: "post")
    v = {"session": "post", "price": 1.0, "change_pct": 0.1, "as_of": "x"}
    assert q.extended_payload("premium", "META", v) == {"extended": v, "extended_locked": False}
    assert q.extended_payload("free", "META", v) == {"extended": None, "extended_locked": True}
    assert q.extended_payload("free", "XEQT.TO", None)["extended_locked"] is False


def test_offhours_refreshes_crypto_by_plan_and_extended_for_premium(monkeypatch):
    from app.db import queries
    from app.services import price_alerts

    now = datetime(2026, 10, 1, 21, 0, tzinfo=UTC)   # 17:00 ET, after-hours
    monkeypatch.setattr(queries, "get_follow_rows", lambda: [
        {"user_id": "f", "symbol": "BTC-USD"}, {"user_id": "p", "symbol": "META"},
        {"user_id": "f", "symbol": "AAPL"}, {"user_id": "p", "symbol": "XEQT.TO"}])
    monkeypatch.setattr(queries, "get_users_activity", lambda: [
        {"id": "f", "access_level": "free", "last_seen_at": "2026-10-01T12:00:00+00:00"},
        {"id": "p", "access_level": "premium", "last_seen_at": "2026-10-01T12:00:00+00:00"}])
    monkeypatch.setattr(price_alerts, "alert_follow_rows", lambda: [])
    monkeypatch.setattr(price_alerts, "evaluate_refreshed", lambda got, now: 0)
    refreshed, extended, stored = [], [], {}
    monkeypatch.setattr(q, "refresh_quotes", lambda syms: (refreshed.append(list(syms)) or {s: {"price": 1} for s in syms}))
    monkeypatch.setattr(q, "fetch_extended", lambda syms: (extended.append(list(syms)) or {
        s: {"ext_price": 101.0, "ext_session": "post", "ext_as_of": now.isoformat()} for s in syms}))
    monkeypatch.setattr(q, "get_quotes", lambda syms: {s: {"price": 100.0} for s in syms})
    monkeypatch.setattr(queries, "update_quote_extended", lambda s, row: stored.__setitem__(s, row))
    q._last_offhours.clear()

    out = q.refresh_offhours(now)
    assert refreshed == [["BTC-USD"]]                         # crypto, free follower
    assert extended == [["META"]]                             # only US stocks a Premium user follows
    assert stored["META"]["ext_change_pct"] == pytest.approx(1.0)
    # free-tier crypto waits 15 min; extended waits quotes_refresh_seconds_extended
    q.refresh_offhours(datetime(2026, 10, 1, 21, 1, tzinfo=UTC))
    assert len(refreshed) == 1 and len(extended) == 1
    assert q.refresh_offhours(datetime(2026, 10, 1, 15, 0, tzinfo=UTC)) == {"status": "session"}
