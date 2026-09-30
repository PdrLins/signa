"""Holdings monitor: a symbol held in two accounts is processed once
(prices, earnings, red flags, alerts) and both rows get the same state."""

import asyncio

import numpy as np
import pandas as pd
import pytest

from app.services import holdings_monitor as hm


@pytest.fixture(autouse=True)
def _reset():
    hm._reset_state()
    yield
    hm._reset_state()


def _series(values, end="2026-09-25"):
    return pd.Series(values, index=pd.bdate_range(end=end, periods=len(values)), dtype=float)


@pytest.fixture
def calls(monkeypatch):
    c = {"fetch": [], "earnings": [], "flags": []}
    # uptrend then a fall below the 200-day SMA -> trend break
    broken = _series(list(np.linspace(50, 120, 250)) + list(np.linspace(118, 70, 50)))

    def fetch(syms):
        c["fetch"].append(list(syms))
        return {s: broken for s in syms}

    async def earnings(h, today=None):
        c["earnings"].append(h["symbol"])
        return {"date": None, "days": None, "trading_days": None}

    async def flags(h, prev, today=None):
        c["flags"].append(h["symbol"])
        return [], {"checked_on": "2026-09-25"}

    monkeypatch.setattr(hm, "fetch_closes", fetch)
    monkeypatch.setattr(hm, "earnings_info", earnings)
    monkeypatch.setattr(hm, "red_flag_check", flags)
    return c


PREV_STATE = {"trend_break": False, "overweight": False, "red_flags": [], "earnings_alerted": None}


def test_same_symbol_in_two_accounts_is_processed_once(calls):
    rows = [
        {"id": "a", "user_id": "u", "symbol": "NVDA", "account_id": "acc1", "shares": 10, "avg_cost": 50,
         "alert_state": dict(PREV_STATE)},
        {"id": "b", "user_id": "u", "symbol": "NVDA", "account_id": "acc2", "shares": 5, "avg_cost": 60,
         "alert_state": None},
        {"id": "c", "user_id": "u", "symbol": "MSFT", "account_id": "acc1", "shares": 1, "avg_cost": 10,
         "alert_state": dict(PREV_STATE)},
    ]
    updates, alerts = asyncio.run(hm.monitor_holdings(rows, usdcad=1.4))
    assert calls["fetch"] == [["NVDA", "MSFT"]]
    assert sorted(calls["earnings"]) == ["MSFT", "NVDA"] and sorted(calls["flags"]) == ["MSFT", "NVDA"]
    trend = [a for a in alerts if a["type"] == "trend_break"]
    assert sorted(a["symbol"] for a in trend) == ["MSFT", "NVDA"]      # one per symbol, not per row
    by_id = {u["id"]: u for u in updates}
    assert set(by_id) == {"a", "b", "c"}
    assert by_id["a"]["alert_state"] == by_id["b"]["alert_state"]
    assert by_id["a"]["alert_state"]["trend_break"] is True
    assert by_id["a"]["holding_status"]["price"] == by_id["b"]["holding_status"]["price"]
    # each row keeps its own lot's position figures
    assert by_id["a"]["holding_status"]["position"]["book_value"] == 500
    assert by_id["b"]["holding_status"]["position"]["book_value"] == 300


def test_concentration_is_judged_on_the_merged_symbol(calls, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "holdings_max_weight_pct", 60.0)
    rows = [  # each NVDA lot alone is < 60% of the book, together 2/3
        {"id": "a", "user_id": "u", "symbol": "NVDA", "shares": 1, "alert_state": dict(PREV_STATE)},
        {"id": "b", "user_id": "u", "symbol": "NVDA", "shares": 1, "alert_state": dict(PREV_STATE)},
        {"id": "c", "user_id": "u", "symbol": "MSFT", "shares": 1, "alert_state": dict(PREV_STATE)},
    ]
    _updates, alerts = asyncio.run(hm.monitor_holdings(rows, usdcad=1.4))
    ow = [a for a in alerts if a["type"] == "overweight"]
    assert [a["symbol"] for a in ow] == ["NVDA"] and ow[0]["weight_pct"] == pytest.approx(66.67, abs=0.01)


def test_first_snapshot_of_all_rows_is_a_silent_baseline(calls):
    rows = [{"id": "a", "user_id": "u", "symbol": "NVDA", "shares": 1},
            {"id": "b", "user_id": "u", "symbol": "NVDA", "shares": 2}]
    updates, alerts = asyncio.run(hm.monitor_holdings(rows))
    assert alerts == [] and all(u["alert_state"]["trend_break"] for u in updates)
