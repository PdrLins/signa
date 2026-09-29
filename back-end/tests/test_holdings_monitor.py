"""My holdings monitor — price status, state-change alerts + de-dup,
one free-path AI call per holding per day, prefer_free provider order.
yfinance / AI / DB / Telegram are all mocked."""

import asyncio
from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.ai import provider
from app.core.config import settings
from app.services import holdings_monitor as hm


@pytest.fixture(autouse=True)
def _reset():
    hm._reset_state()
    yield
    hm._reset_state()


def _series(values, end="2026-09-25"):
    idx = pd.bdate_range(end=end, periods=len(values))
    return pd.Series(values, index=idx, dtype=float)


# ── price status ──

def test_price_status_uptrend():
    s = _series(np.linspace(50, 100, 300))
    st = hm.compute_price_status(s)
    assert st["trend"] == "ok" and st["trend_break"] is False and st["death_cross"] is False
    assert st["price"] == 100.0 and st["drawdown_pct"] == 0.0
    assert st["day_change_pct"] > 0 and st["ytd_pct"] > 0 and st["change_1m_pct"] > 0
    assert st["as_of"] == "2026-09-25"


def test_price_status_trend_break_and_drawdown():
    vals = list(np.linspace(50, 120, 250)) + list(np.linspace(118, 70, 50))
    st = hm.compute_price_status(_series(vals))
    assert st["trend_break"] is True and st["trend"] == "break"
    assert st["drawdown_pct"] == pytest.approx((70 / 120 - 1) * 100, abs=0.01)
    assert st["pct_vs_sma200"] < 0


def test_price_status_short_history_unknown_trend():
    st = hm.compute_price_status(_series([10, 11, 12]))
    assert st["trend"] == "unknown" and st["sma200"] is None and st["trend_break"] is False


def test_price_status_no_data():
    assert hm.compute_price_status(None) == {"error": "no_data"}


# ── alert state machine ──

H = {"id": "h1", "symbol": "NVDA"}


def _st(trend_break=False, flags=None, earnings=None):
    return {"trend": "break" if trend_break else "ok", "trend_break": trend_break, "price": 90.0,
            "sma200": 100.0, "pct_vs_sma200": -10.0, "red_flags": flags or [], "earnings": earnings}


def test_first_snapshot_is_silent_baseline():
    flag = {"text": "SEC probe", "url": "https://x", "severity": "high", "category": "regulatory"}
    alerts, state = hm.evaluate_alerts(H, _st(True, [flag]), {"weight_pct": 40, "overweight": True}, None)
    assert alerts == []
    assert state["trend_break"] is True and state["overweight"] is True and len(state["red_flags"]) == 1


def test_new_trend_break_alerts_once():
    _, s0 = hm.evaluate_alerts(H, _st(False), None, None)
    a1, s1 = hm.evaluate_alerts(H, _st(True), None, s0)
    assert [a["type"] for a in a1] == ["trend_break"]
    a2, s2 = hm.evaluate_alerts(H, _st(True), None, s1)
    assert a2 == []
    _, s3 = hm.evaluate_alerts(H, _st(False), None, s2)       # recovers: resets silently
    a4, _ = hm.evaluate_alerts(H, _st(True), None, s3)        # breaks again: alerts again
    assert [a["type"] for a in a4] == ["trend_break"]


def test_unknown_trend_keeps_previous_state():
    _, s0 = hm.evaluate_alerts(H, _st(True), None, None)
    _, s1 = hm.evaluate_alerts(H, {"trend": "unknown", "trend_break": False}, None, s0)
    assert s1["trend_break"] is True


def test_red_flag_only_high_or_critical_alert_and_dedup():
    _, s0 = hm.evaluate_alerts(H, _st(), None, None)
    med = {"text": "fraud allegation", "url": "https://a", "severity": "medium", "category": "fraud"}
    hi = {"text": "Guidance cut", "url": "https://b", "severity": "critical", "category": "other"}
    a1, s1 = hm.evaluate_alerts(H, _st(flags=[med, hi]), None, s0)
    assert [a["type"] for a in a1] == ["red_flag"] and a1[0]["severity"] == "critical"
    a2, _ = hm.evaluate_alerts(H, _st(flags=[med, hi]), None, s1)
    assert a2 == []


def test_earnings_alert_within_three_trading_days_once_per_date():
    e_far = {"date": "2026-10-20", "days": 22, "trading_days": 16}
    e_near = {"date": "2026-10-01", "days": 3, "trading_days": 3}
    a0, s0 = hm.evaluate_alerts(H, _st(earnings=e_far), None, None)
    assert a0 == []
    a1, s1 = hm.evaluate_alerts(H, _st(earnings=e_near), None, None)   # even on baseline
    assert [a["type"] for a in a1] == ["earnings"] and s1["earnings_alerted"] == "2026-10-01"
    a2, _ = hm.evaluate_alerts(H, _st(earnings={**e_near, "trading_days": 2}), None, s1)
    assert a2 == []


def test_concentration_crossing(monkeypatch):
    monkeypatch.setattr(settings, "holdings_max_weight_pct", 15.0)
    _, s0 = hm.evaluate_alerts(H, _st(), {"weight_pct": 12.0, "overweight": False}, None)
    a1, s1 = hm.evaluate_alerts(H, _st(), {"weight_pct": 16.0, "overweight": True}, s0)
    assert [a["type"] for a in a1] == ["overweight"] and a1[0]["max_pct"] == 15.0
    a2, s2 = hm.evaluate_alerts(H, _st(), {"weight_pct": 17.0, "overweight": True}, s1)
    assert a2 == []
    a3, s3 = hm.evaluate_alerts(H, _st(), None, s2)      # shares removed: keep state
    assert a3 == [] and s3["overweight"] is True


# ── Telegram formatting / sending ──

def test_format_alerts_en_and_pt(monkeypatch):
    alerts = [{"type": "trend_break", "symbol": "NVDA", "price": 90, "sma200": 100, "pct": -10},
              {"type": "earnings", "symbol": "AMD", "date": "2026-10-01", "trading_days": 2},
              {"type": "red_flag", "symbol": "PLTR", "severity": "high", "text": "<b>x</b>", "url": "https://s"},
              {"type": "overweight", "symbol": "COST", "weight_pct": 18.2, "max_pct": 15}]
    monkeypatch.setattr(settings, "language", "en")
    en = hm.format_alerts(alerts)
    assert "My holdings" in en and "200-day" in en and "&lt;b&gt;x&lt;/b&gt;" in en and "18.2%" in en
    monkeypatch.setattr(settings, "language", "pt")
    pt = hm.format_alerts(alerts)
    assert "Minha carteira" in pt and "média de 200 dias" in pt


def test_send_alerts_respects_switch(monkeypatch):
    sent = []
    from app.notifications import telegram_bot
    monkeypatch.setattr(telegram_bot, "enqueue", lambda chat, text, **k: sent.append(text))
    monkeypatch.setattr(settings, "telegram_chat_id", "123")
    monkeypatch.setattr(settings, "holdings_alerts_enabled", False)
    assert hm.send_alerts([{"type": "earnings", "symbol": "A", "date": "d", "trading_days": 1}]) is False
    monkeypatch.setattr(settings, "holdings_alerts_enabled", True)
    assert hm.send_alerts([{"type": "earnings", "symbol": "A", "date": "d", "trading_days": 1}]) is True
    assert hm.send_alerts([]) is False
    assert len(sent) == 1


# ── red flags: free path, stocks only, once per day ──

class FakeSentiment:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or {"score": 40, "confidence": 0.7, "_provider": "gemini", "red_flags": [
            {"text": "Accounting restatement", "url": "https://news/x", "severity": "high", "category": "accounting"}]}

    async def __call__(self, ticker, market_cap=None, prefer_free=False, free_only=False):
        self.calls.append({"ticker": ticker, "prefer_free": prefer_free, "free_only": free_only})
        return dict(self.result)


@pytest.fixture
def fake_sent(monkeypatch):
    f = FakeSentiment()
    monkeypatch.setattr(provider, "analyze_sentiment", f)
    monkeypatch.setattr(hm, "_market_cap", lambda s: 1e9)
    monkeypatch.setattr(settings, "ai_enabled", True)
    monkeypatch.setattr(settings, "holdings_ai_red_flags", True)
    monkeypatch.setattr(settings, "holdings_sentiment_paid_fallback", False)
    return f


def test_red_flag_check_uses_free_path_once_per_day(fake_sent):
    h = {"symbol": "PLTR", "asset_type": "STOCK"}
    today = date(2026, 9, 28)
    flags, meta = asyncio.run(hm.red_flag_check(h, None, today))
    assert len(flags) == 1 and flags[0]["key"] and meta["checked_on"] == "2026-09-28"
    assert fake_sent.calls == [{"ticker": "PLTR", "prefer_free": True, "free_only": True}]
    # stored snapshot says checked today -> reused, no second call
    flags2, meta2 = asyncio.run(hm.red_flag_check(h, {"red_flags": flags, "sentiment": meta}, today))
    assert flags2 == flags and meta2.get("reused") and len(fake_sent.calls) == 1
    # even if the stored snapshot was lost, the in-process guard blocks a 2nd call
    asyncio.run(hm.red_flag_check(h, None, today))
    assert len(fake_sent.calls) == 1
    # next day: one new call
    asyncio.run(hm.red_flag_check(h, {"sentiment": meta}, date(2026, 9, 29)))
    assert len(fake_sent.calls) == 2


def test_red_flag_check_paid_fallback_setting(fake_sent, monkeypatch):
    monkeypatch.setattr(settings, "holdings_sentiment_paid_fallback", True)
    asyncio.run(hm.red_flag_check({"symbol": "AMD", "asset_type": "STOCK"}, None, date(2026, 9, 28)))
    assert fake_sent.calls[-1] == {"ticker": "AMD", "prefer_free": True, "free_only": False}


@pytest.mark.parametrize("sym,at", [("XEQT.TO", "ETF"), ("BTC-USD", "CRYPTO"), ("FBTC", "ETF")])
def test_red_flag_check_skips_etfs_and_crypto(fake_sent, sym, at):
    flags, meta = asyncio.run(hm.red_flag_check({"symbol": sym, "asset_type": at}, None, date(2026, 9, 28)))
    assert flags == [] and meta == {"skipped": "not_a_stock"} and fake_sent.calls == []


def test_red_flag_error_keeps_previous_flags(fake_sent):
    fake_sent.result = {"error": "All providers failed", "_provider": "none"}
    prev = {"red_flags": [{"text": "old", "url": "u", "key": "k"}], "sentiment": {"checked_on": "2026-09-27"}}
    flags, meta = asyncio.run(hm.red_flag_check({"symbol": "PLTR", "asset_type": "STOCK"}, prev, date(2026, 9, 28)))
    assert flags == prev["red_flags"] and meta["error"] == "unavailable"


# ── full monitor pass (mocked data) ──

def test_monitor_holdings_end_to_end(monkeypatch, fake_sent):
    up = _series(np.linspace(50, 100, 300))
    down = _series(list(np.linspace(50, 120, 250)) + list(np.linspace(118, 70, 50)))
    monkeypatch.setattr(hm, "fetch_closes", lambda syms: {"XEQT.TO": up, "PLTR": down})

    async def fake_earn(h, today=None):
        return {"date": "2026-09-30", "days": 2, "trading_days": 2} if h["symbol"] == "PLTR" else None
    monkeypatch.setattr(hm, "earnings_info", fake_earn)
    monkeypatch.setattr(settings, "holdings_max_weight_pct", 15.0)
    holdings = [
        {"id": "a", "user_id": "u", "symbol": "XEQT.TO", "asset_type": "ETF", "currency": "CAD", "shares": 100,
         "alert_state": {"trend_break": False, "overweight": False, "red_flags": []}},
        {"id": "b", "user_id": "u", "symbol": "PLTR", "asset_type": "STOCK", "currency": "USD", "shares": 1,
         "alert_state": {"trend_break": False, "overweight": False, "red_flags": []}},
    ]
    updates, alerts = asyncio.run(hm.monitor_holdings(holdings, usdcad=1.4, today=date(2026, 9, 28)))
    types = sorted(a["type"] for a in alerts)
    assert types == ["earnings", "overweight", "red_flag", "trend_break"]   # XEQT overweight; PLTR the rest
    by = {u["id"]: u for u in updates}
    assert by["a"]["holding_status"]["position"]["weight_pct"] > 90
    assert by["b"]["holding_status"]["trend_break"] is True
    assert len(fake_sent.calls) == 1                          # ETF skipped, stock once
    # second pass with the saved state: nothing new
    for h in holdings:
        h["alert_state"] = by[h["id"]]["alert_state"]
        h["holding_status"] = by[h["id"]]["holding_status"]
    _, alerts2 = asyncio.run(hm.monitor_holdings(holdings, usdcad=1.4, today=date(2026, 9, 28)))
    assert alerts2 == []
    assert len(fake_sent.calls) == 1


def test_run_holdings_monitor_persists_and_sends(monkeypatch):
    from app.db import queries
    saved, sent = [], []
    monkeypatch.setattr(queries, "get_all_holdings", lambda: [{"id": "a", "user_id": "u", "symbol": "XEQT.TO",
                                                               "asset_type": "ETF"}])
    monkeypatch.setattr(queries, "update_holding", lambda hid, uid, data: saved.append((hid, uid, data)) or {"id": hid})
    monkeypatch.setattr("app.services.price_cache.get_usdcad_rate", lambda: 1.4)
    monkeypatch.setattr(hm, "fetch_closes", lambda syms: {"XEQT.TO": _series(np.linspace(50, 100, 300))})

    async def no_earn(h, today=None):
        return None
    monkeypatch.setattr(hm, "earnings_info", no_earn)
    monkeypatch.setattr(hm, "send_alerts", lambda alerts: sent.append(alerts) or bool(alerts))
    out = asyncio.run(hm.run_holdings_monitor())
    assert out["status"] == "ok" and out["updated"] == 1
    hid, uid, data = saved[0]
    assert (hid, uid) == ("a", "u") and data["holding_status"]["price"] == 100.0
    assert data["alert_state"]["trend_break"] is False and "status_updated_at" in data


def test_run_holdings_monitor_table_missing(monkeypatch):
    from app.db import queries

    def boom():
        raise RuntimeError('relation "holdings" does not exist')
    monkeypatch.setattr(queries, "get_all_holdings", boom)
    assert asyncio.run(hm.run_holdings_monitor()) == {"status": "unavailable"}


# ── provider: prefer_free routing order ──

class FakeBudget:
    def __init__(self):
        self.recorded = []

    async def can_call(self, provider_name, call_type):
        return True, ""

    async def record_call(self, provider_name, call_type, ticker, success=True):
        self.recorded.append((provider_name, success))


@pytest.fixture
def routed(monkeypatch):
    order = []
    budget = FakeBudget()

    async def get_budget():
        return budget

    async def grok(ticker, market_cap=None):
        order.append("grok")
        return {"score": 60, "confidence": 0.8}

    async def gemini(ticker, market_cap=None):
        order.append("gemini")
        return {"score": 55, "confidence": 0.6}

    import app.ai.gemini_client as gc
    import app.ai.grok_client as xc
    monkeypatch.setattr(provider, "_get_budget", get_budget)
    monkeypatch.setattr(xc, "analyze_sentiment", grok)
    monkeypatch.setattr(gc, "analyze_sentiment", gemini)
    monkeypatch.setattr(settings, "xai_api_key", "x")
    monkeypatch.setattr(settings, "gemini_api_key", "g")
    monkeypatch.setattr(settings, "sentiment_providers", ["grok", "gemini"])
    return order, budget


def test_provider_order_helper(monkeypatch):
    monkeypatch.setattr(settings, "sentiment_providers", ["grok", "gemini"])
    assert provider.sentiment_provider_order() == ["grok", "gemini"]
    assert provider.sentiment_provider_order(prefer_free=True) == ["gemini", "grok"]
    assert provider.sentiment_provider_order(free_only=True) == ["gemini"]


def test_default_sentiment_still_grok_first(routed):
    order, _ = routed
    r = asyncio.run(provider.analyze_sentiment("NVDA"))
    assert order == ["grok"] and r["_provider"] == "grok"


def test_prefer_free_tries_gemini_first(routed):
    order, budget = routed
    r = asyncio.run(provider.analyze_sentiment("NVDA", prefer_free=True))
    assert order == ["gemini"] and r["_provider"] == "gemini" and budget.recorded == [("gemini", True)]


def test_prefer_free_falls_back_to_grok(routed, monkeypatch):
    order, _ = routed
    import app.ai.gemini_client as gc

    async def gemini_fail(ticker, market_cap=None):
        order.append("gemini")
        return {"error": "no grounding"}
    monkeypatch.setattr(gc, "analyze_sentiment", gemini_fail)
    r = asyncio.run(provider.analyze_sentiment("NVDA", prefer_free=True))
    assert order == ["gemini", "grok"] and r["_provider"] == "grok"


def test_free_only_never_calls_grok(routed, monkeypatch):
    order, _ = routed
    import app.ai.gemini_client as gc

    async def gemini_fail(ticker, market_cap=None):
        order.append("gemini")
        return {"error": "no grounding"}
    monkeypatch.setattr(gc, "analyze_sentiment", gemini_fail)
    r = asyncio.run(provider.analyze_sentiment("NVDA", free_only=True))
    assert order == ["gemini"] and r.get("error")


def test_free_path_reuses_cached_grok_and_does_not_pollute_scan_cache(routed):
    order, _ = routed
    asyncio.run(provider.analyze_sentiment("NVDA"))                 # scan: Grok, cached
    r = asyncio.run(provider.analyze_sentiment("NVDA", prefer_free=True))
    assert r["_cached"] is True and r["_provider"] == "grok" and order == ["grok"]
    asyncio.run(provider.analyze_sentiment("AMD", prefer_free=True))  # free path: Gemini
    r2 = asyncio.run(provider.analyze_sentiment("AMD"))              # scan must still ask Grok
    assert order == ["grok", "gemini", "grok"] and r2["_provider"] == "grok"
