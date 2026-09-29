"""Correlation gate wired into the brain entry path (FakeDB, no network)."""

from unittest.mock import patch

import numpy as np
import pandas as pd

from app.core.config import settings
from app.services import virtual_portfolio as vp
from tests.brain_fakes import USER_ID, FakeDB, patch_db, wallet_row
from tests.test_brain_entry_gate import brain_trades, make_sig

N = 130


def _closes(rets: dict[str, np.ndarray]) -> dict[str, pd.Series]:
    idx = pd.bdate_range("2026-03-02", periods=N + 1)
    return {s: pd.Series(100 * np.cumprod(np.r_[1.0, 1 + r]), index=idx) for s, r in rets.items()}


def _open_row(i, symbol, sector):
    return {"id": f"t{i}", "symbol": symbol, "source": "brain", "status": "OPEN", "direction": "LONG",
            "entry_price": 10.0, "shares": 50, "position_size_usd": 500.0, "is_wallet_trade": True,
            "sector": sector, "entry_score": 80, "user_id": USER_ID}


def run_with_history(closes, sig, loader_calls=None):
    db = FakeDB({"brain_wallet": [wallet_row(balance=9_000.0)],
                 "virtual_trades": [_open_row(1, "HELD1", "Energy"), _open_row(2, "HELD2", "Utilities")]})

    def loader(syms):
        if loader_calls is not None:
            loader_calls.append(list(syms))
        return {s: closes[s] for s in syms if s in closes}

    with patch_db(db), patch("app.services.portfolio_risk._load_closes", side_effect=loader):
        vp.process_virtual_trades([sig], set(), [])
    return db


def _series(seed=0):
    rng = np.random.default_rng(seed)
    base = rng.standard_normal(N) * 0.01
    return {
        "HELD1": base,
        "HELD2": rng.standard_normal(N) * 0.01,
        "TWIN": base * 1.2 + rng.standard_normal(N) * 0.001,   # ~0.99 corr with HELD1
        "INDEP": rng.standard_normal(N) * 0.01,
    }


def _new_trades(db):
    return [t for t in brain_trades(db) if t["id"] not in ("t1", "t2")]


def test_correlated_candidate_skipped_with_reason_and_details():
    db = run_with_history(_closes(_series()), make_sig("TWIN", sector="Technology"))
    assert _new_trades(db) == []
    (d,) = db.rows("brain_decisions")
    assert d["decision"] == "SKIP" and d["reason"] == "correlation_limit"
    corr = d["details"]["correlation"]
    assert corr["rule"] == "pairwise"
    assert corr["max_corr_symbol"] == "HELD1" and corr["max_corr"] > 0.95
    assert set(corr["corr"]) == {"HELD1", "HELD2"}


def test_uncorrelated_candidate_enters_and_logs_check():
    db = run_with_history(_closes(_series()), make_sig("INDEP", sector="Technology"))
    assert len(_new_trades(db)) == 1
    (d,) = db.rows("brain_decisions")
    assert d["decision"] == "ENTER"
    assert d["details"]["correlation"]["status"] == "checked"


def test_missing_history_does_not_block():
    db = run_with_history({}, make_sig("TWIN", sector="Technology"))
    assert len(_new_trades(db)) == 1
    (d,) = db.rows("brain_decisions")
    assert d["decision"] == "ENTER"
    assert d["details"]["correlation"]["status"] == "skipped"


def test_disabled_flag_unchanged_behavior(monkeypatch):
    monkeypatch.setattr(settings, "brain_correlation_check_enabled", False)
    calls = []
    db = run_with_history(_closes(_series()), make_sig("TWIN", sector="Technology"), calls)
    assert calls == []  # no history fetch at all
    assert len(_new_trades(db)) == 1
    (d,) = db.rows("brain_decisions")
    assert d["decision"] == "ENTER" and "correlation" not in d["details"]


def test_gate_runs_after_existing_limits():
    """A candidate already rejected by an earlier gate never triggers a fetch."""
    calls = []
    db = run_with_history(_closes(_series()), make_sig("TWIN", stop=94.0, target=108.0), calls)
    assert calls == []
    assert db.rows("brain_decisions")[0]["reason"].startswith("rr_below_min")
