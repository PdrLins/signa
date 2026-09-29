"""scripts/reset_brain.py against the in-memory FakeDB (never a real DB)."""

import importlib.util
import json
from pathlib import Path

from tests.brain_fakes import USER_ID, FakeDB, patch_db, wallet_row  # noqa: I001

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "reset_brain.py"


def load_script():
    spec = importlib.util.spec_from_file_location("reset_brain", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def seeded_db():
    return FakeDB({
        "brain_wallet": [wallet_row(balance=4_321.0)],
        "virtual_trades": [{"id": "t1", "symbol": "AAA", "status": "CLOSED", "source": "brain"}],
        "wallet_transactions": [{"id": "w1", "trade_id": "t1"}],
        "trade_outcomes": [{"id": "o1"}],
        "virtual_snapshots": [{"id": "s1"}],
        "daily_learning_runs": [{"id": "r1"}],
        "brain_suggestions": [{"id": "b1"}],
        "brain_decisions": [{"id": "d1"}],
        "watchdog_events": [{"id": "x1"}],
        "signal_knowledge": [{"id": "k-seed", "source_type": "seed"},
                             {"id": "k-learned", "source_type": "learned_from_thinking"}],
        "signal_thinking": [
            {"id": "h-auto", "created_by": "auto_analyzer", "status": "graduated", "graduated_to": "k-learned"},
            {"id": "h-human", "created_by": "claude", "status": "graduated", "graduated_to": "k-learned",
             "observations_supporting": 7, "observations_contradicting": 1},
        ],
        "knowledge_events": [
            {"id": "e1", "trade_id": "t1", "event_type": "thinking_observation_added", "triggered_by": "brain_close_hook"},
            {"id": "e2", "event_type": "thinking_created", "triggered_by": "seed_brain_py", "thinking_id": "h-human"},
        ],
        "users": [{"id": USER_ID}], "tickers": [{"id": "tk"}], "signals": [{"id": "sg"}],
        "investment_rules": [{"id": "ir"}],
    })


def test_dry_run_changes_nothing(capsys):
    mod = load_script()
    db = seeded_db()
    before = json.dumps(db.tables, sort_keys=True, default=str)
    with patch_db(db), pytest.MonkeyPatch.context() as mp:
        mp.setattr(mod, "get_client", lambda: db)
        mp.setattr("sys.argv", ["reset_brain.py"])
        assert mod.main() == 0
    assert json.dumps(db.tables, sort_keys=True, default=str) == before
    assert "DRY RUN" in capsys.readouterr().out


def test_confirm_archives_then_wipes_and_reseeds(tmp_path):
    mod = load_script()
    db = seeded_db()
    with patch_db(db), pytest.MonkeyPatch.context() as mp:
        mp.setattr(mod, "get_client", lambda: db)
        mp.setattr("sys.argv", ["reset_brain.py", "--confirm", "--out-dir", str(tmp_path),
                                "--starting-capital", "10000"])
        assert mod.main() == 0

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["counts"]["virtual_trades"] == 1
    assert json.loads((tmp_path / "wallet_transactions.json").read_text())[0]["id"] == "w1"

    for t in ("virtual_trades", "trade_outcomes", "virtual_snapshots", "daily_learning_runs",
              "brain_suggestions", "brain_decisions", "watchdog_events"):
        assert db.rows(t) == [], t
    # learning-loop artefacts gone, human/seed rows kept (and reset)
    assert [k["id"] for k in db.rows("signal_knowledge")] == ["k-seed"]
    (human,) = db.rows("signal_thinking")
    assert human["id"] == "h-human" and human["status"] == "active"
    assert human["observations_supporting"] == 0 and human["graduated_to"] is None
    assert [e["id"] for e in db.rows("knowledge_events")] == ["e2"]
    # untouched tables
    for t in ("users", "tickers", "signals", "investment_rules"):
        assert len(db.rows(t)) == 1
    # wallet re-seeded at starting capital with a DEPOSIT ledger row
    (w,) = db.rows("brain_wallet")
    assert w["balance"] == pytest.approx(10_000.0) and w["peak_equity"] == 10_000.0
    assert [tx["transaction_type"] for tx in db.rows("wallet_transactions")] == ["DEPOSIT"]
