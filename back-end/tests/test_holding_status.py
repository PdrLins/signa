"""app/services/holding_status.py: the daily price snapshot on each holding."""

import asyncio

import pandas as pd

from app.db import queries
from app.services import holding_status as hst


def _closes(n=260, start=100.0, step=0.1, end="2026-10-02"):
    idx = pd.bdate_range(end=end, periods=n)
    return pd.Series([start + i * step for i in range(n)], index=idx)


def test_price_status_fields():
    st = hst.compute_price_status(_closes())
    assert st["price"] == round(100 + 259 * 0.1, 4) and st["prev_close"] == round(100 + 258 * 0.1, 4)
    assert st["trend"] == "ok" and st["trend_break"] is False and st["death_cross"] is False
    assert st["ytd_base"] and st["ytd_pct"] > 0 and st["as_of"] == "2026-10-02"
    assert hst.compute_price_status(None) == {"error": "no_data"}
    assert hst.compute_price_status(_closes(n=1)) == {"error": "no_data"}


def test_refresh_writes_one_download_for_all_users(monkeypatch):
    rows = [{"id": "h1", "user_id": "u1", "symbol": "MSFT"}, {"id": "h2", "user_id": "u2", "symbol": "msft"},
            {"id": "h3", "user_id": "u2", "symbol": "NOPE"}]
    downloads, saved = [], {}
    monkeypatch.setattr(queries, "get_all_holdings", lambda: rows)
    monkeypatch.setattr(hst, "fetch_closes", lambda syms: downloads.append(syms) or {"MSFT": _closes()})
    monkeypatch.setattr(queries, "set_symbol_status", lambda sym, data, uid=None: saved.setdefault(sym, (uid, data)))
    out = asyncio.run(hst.refresh())
    assert downloads == [["MSFT", "NOPE"]]
    assert out == {"status": "ok", "holdings": 3, "symbols": 2, "updated": 2}
    assert set(saved) == {"MSFT"} and saved["MSFT"][0] is None   # one write for both users' MSFT
    assert "holding_status" in saved["MSFT"][1] and "status_updated_at" in saved["MSFT"][1]
    assert "alert_state" not in saved["MSFT"][1]


def test_daily_run_waits_for_a_user_refresh(monkeypatch):
    monkeypatch.setattr(queries, "get_all_holdings", lambda: [])
    monkeypatch.setattr(queries, "get_holdings", lambda uid: [])

    async def scenario():
        await hst._run_lock.acquire()          # a user refresh is running
        daily = asyncio.create_task(hst.refresh())
        busy = await hst.refresh("u1")         # another user refresh: skipped
        hst._run_lock.release()
        return busy, await daily

    busy, daily = asyncio.run(scenario())
    assert busy == {"status": "busy"} and daily["status"] == "ok"
