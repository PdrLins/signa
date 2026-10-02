"""Similar funds (Premium) — app/services/similar_funds.py."""

import pandas as pd

from app.services import similar_funds as sf


def test_groups_and_peers():
    assert sf.group_of("xeqt.to") == "all_in_one_equity"
    peers = [s for s, _ in sf.peers_for("XEQT.TO")]
    assert "XEQT.TO" not in peers and "VEQT.TO" in peers and len(peers) <= sf.MAX_PEERS
    assert sf.peers_for("META") == [] and not sf.has_peers("META")
    # every symbol sits in at most one group
    seen = [s for members in sf.PEER_GROUPS.values() for s, _ in members]
    assert len(seen) == len(set(seen))


def test_period_return():
    idx = pd.date_range("2021-10-01", "2026-10-01", freq="D")
    s = pd.Series(range(100, 100 + len(idx)), index=idx, dtype=float)
    assert sf.period_return(s, 1) == round((s.iloc[-1] / s[s.index <= idx[-1] - pd.DateOffset(years=1)].iloc[-1] - 1) * 100, 2)
    assert sf.period_return(s, 5) == round((s.iloc[-1] / s.iloc[0] - 1) * 100, 2)
    short = s[s.index >= "2025-01-01"]
    assert sf.period_return(short, 5) is None
    late = s[s.index >= "2021-10-05"]            # download starts 4 days after the 5-year mark
    assert sf.period_return(late, 5) is not None


def test_build_rows_puts_the_fund_first(monkeypatch):
    from app.services import price_cache
    idx = pd.date_range("2025-09-01", "2026-10-01", freq="D")
    monkeypatch.setattr(price_cache, "fetch_daily_closes",
                        lambda syms, period="5y": {s: pd.Series(100.0, index=idx) for s in syms})
    monkeypatch.setattr(sf, "_expense_ratio", lambda s: 0.2)
    rows = sf.build_rows("XEQT.TO", "iShares Core Equity")
    assert rows[0]["symbol"] == "XEQT.TO" and rows[0]["current"] is True
    assert all(r["expense_ratio"] == 0.2 and r["return_1y_pct"] == 0.0 for r in rows)
    assert not any(r["current"] for r in rows[1:])
    assert sf.build_rows("META", None) == []


def test_regions_for_fund_of_funds_and_single_region():
    from app.services.fund_regions import regions_for
    xeqt = {"fund_of_funds": True, "top_holdings": [
        {"symbol": "XTOT.TO", "weight": 29.68}, {"symbol": "XIC.TO", "weight": 25.64},
        {"symbol": "XEF.TO", "weight": 24.41}, {"symbol": "ITOT", "weight": 15.3}, {"symbol": "XEC.TO", "weight": 4.8}]}
    r = regions_for("XEQT.TO", xeqt)
    assert list(r)[0] == "us" and round(sum(r.values())) == 100
    assert r["canada"] == round(25.64 / 99.83 * 100, 1)
    assert regions_for("VFV.TO", {"fund_of_funds": False}) == {"us": 100.0}
    assert regions_for("ZWC.TO", {}) is None                       # covered-call: not a single region
    unknown = {"fund_of_funds": True, "top_holdings": [{"symbol": "AAA", "weight": 50}, {"symbol": "XIC.TO", "weight": 50}]}
    assert regions_for("ZZZ.TO", unknown) is None                  # < 80% mapped
