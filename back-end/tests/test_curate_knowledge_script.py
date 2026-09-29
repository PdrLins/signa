"""scripts/curate_brain_knowledge.py against the in-memory FakeDB (never a real DB)."""

import importlib.util
import json
from pathlib import Path

from tests.brain_fakes import FakeDB  # noqa: I001

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "curate_brain_knowledge.py"


def load_script():
    spec = importlib.util.spec_from_file_location("curate_brain_knowledge", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def seeded_db(mod):
    rid, rname, _ = mod.REMOVE_RULES[0]
    kid, kname, _ = mod.REMOVE_KNOWLEDGE[0]
    vid, vname, _ = mod.REVISE_KNOWLEDGE[0]
    tid = mod.RETIRE_THINKING[0][0]
    return FakeDB({
        "investment_rules": [
            {"id": rid, "name": rname, "is_active": True, "notes": None},
            {"id": "keep-rule", "name": "minimum_price", "is_active": True},
            # id matches a REVISE row but the name does not -> must be skipped
            {"id": mod.REVISE_RULES[0][0], "name": "someone_renamed_it", "is_active": True},
        ],
        "signal_knowledge": [
            {"id": kid, "key_concept": kname, "is_active": True, "notes": "old note"},
            {"id": vid, "key_concept": vname, "is_active": True, "explanation": "stale"},
        ],
        "signal_thinking": [
            {"id": tid, "status": "active", "notes": None},
            {"id": mod.KEEP_THINKING_ID, "status": "active"},
        ],
    })


def _writes(db):
    return [c for c in db.calls if c[1] in ("update", "insert", "upsert", "delete")]


def test_dry_run_makes_no_writes(tmp_path, capsys):
    mod = load_script()
    db = seeded_db(mod)
    before = json.dumps(db.tables, sort_keys=True, default=str)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mod, "get_client", lambda: db)
        assert mod.main(["--out-dir", str(tmp_path / "arch")]) == 0
    assert _writes(db) == []
    assert json.dumps(db.tables, sort_keys=True, default=str) == before
    assert not (tmp_path / "arch").exists()
    out = capsys.readouterr().out
    assert "DRY RUN" in out and mod.REMOVE_RULES[0][1] in out


def test_apply_archives_before_any_change(tmp_path):
    mod = load_script()
    db = seeded_db(mod)
    original = mod.write_and_verify_archive
    marker = {}

    def spy(snapshot, out_dir):
        marker["calls_at_archive"] = len(db.calls)
        assert _writes(db) == []           # nothing changed before the archive
        original(snapshot, out_dir)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mod, "get_client", lambda: db)
        mp.setattr(mod, "write_and_verify_archive", spy)
        assert mod.main(["--apply", "--out-dir", str(tmp_path)]) == 0

    writes = [i for i, c in enumerate(db.calls) if c[1] in ("update", "insert")]
    assert writes and min(writes) >= marker["calls_at_archive"]
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["counts"] == {"investment_rules": 3, "signal_knowledge": 2, "signal_thinking": 2}
    archived = json.loads((tmp_path / "signal_knowledge.json").read_text())
    assert {r["id"] for r in archived} == {mod.REMOVE_KNOWLEDGE[0][0], mod.REVISE_KNOWLEDGE[0][0]}
    assert all(r.get("is_active") is True for r in archived)       # pre-change state

    rules = {r["id"]: r for r in db.rows("investment_rules")}
    removed = rules[mod.REMOVE_RULES[0][0]]
    assert removed["is_active"] is False and "[2026-09 audit]" in removed["notes"]   # deactivated, not deleted
    assert rules["keep-rule"]["is_active"] is True
    assert rules[mod.REVISE_RULES[0][0]].get("description") is None                 # name mismatch -> skipped

    know = {r.get("key_concept"): r for r in db.rows("signal_knowledge")}
    assert know[mod.REMOVE_KNOWLEDGE[0][1]]["is_active"] is False
    assert know[mod.REMOVE_KNOWLEDGE[0][1]]["notes"].startswith("old note")
    assert know[mod.REVISE_KNOWLEDGE[0][1]]["explanation"] != "stale"
    for c in mod.build_prompt_core_rows():
        assert know[c["key_concept"]]["topic"] == "PROMPT_CORE"

    thinking = {r["id"]: r for r in db.rows("signal_thinking")}
    assert thinking[mod.RETIRE_THINKING[0][0]]["status"] == "retired"
    assert thinking[mod.KEEP_THINKING_ID]["status"] == "active"
    assert db.ops("investment_rules", "delete") == [] and db.ops("signal_knowledge", "delete") == []


def test_apply_is_idempotent(tmp_path):
    mod = load_script()
    db = seeded_db(mod)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mod, "get_client", lambda: db)
        assert mod.main(["--apply", "--out-dir", str(tmp_path / "a")]) == 0
        n_rows = len(db.rows("signal_knowledge"))
        db.calls.clear()
        assert mod.main(["--apply", "--out-dir", str(tmp_path / "b")]) == 0
    assert _writes(db) == []
    assert len(db.rows("signal_knowledge")) == n_rows


def test_failed_archive_verification_blocks_all_changes(tmp_path):
    mod = load_script()
    db = seeded_db(mod)

    def broken(snapshot, out_dir):
        raise RuntimeError("archive verification failed for investment_rules")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mod, "get_client", lambda: db)
        mp.setattr(mod, "write_and_verify_archive", broken)
        with pytest.raises(RuntimeError):
            mod.main(["--apply", "--out-dir", str(tmp_path)])
    assert _writes(db) == []
