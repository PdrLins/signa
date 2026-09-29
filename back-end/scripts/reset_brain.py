"""Archive, then reset ALL brain state (paper wallet, trades, learned stats).

Usage (from back-end/):
    venv/bin/python scripts/reset_brain.py                 # dry run: prints what would happen
    venv/bin/python scripts/reset_brain.py --confirm       # archive + wipe + re-seed wallet
    venv/bin/python scripts/reset_brain.py --confirm --starting-capital 25000

Prerequisite: apply app/db/migrations/006_brain_reset.sql first.

WHAT IT DOES (with --confirm)
  1. Reads every row it is about to delete and writes it to JSON under
     back-end/docs/archive/<YYYY-MM-DD>/<table>.json (+ manifest.json).
     The Supabase Python client (PostgREST) cannot CREATE TABLE, so the
     archive is JSON files, not *_archive_<date> tables. Deletion only
     starts after every archive file is written and re-read successfully.
  2. Deletes, in FK-safe order:
       knowledge_events   rows created by the learning loop / trade closes
                          (trade_id set, observation/graduation/rejection
                          events, or tied to the rows below)
       brain_decisions, watchdog_events, wallet_transactions,
       trade_outcomes, virtual_snapshots, daily_learning_runs,
       brain_suggestions  (all rows)
       signal_knowledge   rows with source_type='learned_from_thinking'
       signal_thinking    rows with created_by='auto_analyzer'
       virtual_trades     (all rows, brain + watchlist tracks)
       brain_wallet       (the brain user's row)
  3. Resets the remaining (human-written) hypotheses in signal_thinking:
     counters → 0, status graduated → active, graduated_to → NULL.
  4. Re-seeds the wallet with --starting-capital (default
     settings.wallet_starting_balance) via wallet.deposit, sets
     peak_equity to the same amount, and runs reconcile_wallet().

NEVER TOUCHES: users, tickers, signals (history), investment_rules, seed
signal_knowledge, positions, portfolio, watchlist, and the markdown
reports in docs/daily-reports/ (they are git history, not DB state).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings  # noqa: E402
from app.db import queries  # noqa: E402
from app.db.supabase import get_client  # noqa: E402
from postgrest.exceptions import APIError  # noqa: E402

PAGE = 1000
DELETE_CHUNK = 100

# Tables wiped completely (archived first). Order matters for FKs:
# wallet_transactions + knowledge_events reference virtual_trades.
FULL_TABLES = [
    "brain_decisions",
    "watchdog_events",
    "wallet_transactions",
    "trade_outcomes",
    "virtual_snapshots",
    "daily_learning_runs",
    "brain_suggestions",
]
LEARNING_EVENT_TYPES = {
    "thinking_observation_added",
    "thinking_graduated",
    "thinking_rejected",
    "thesis_invalidated_exit",
}
LEARNING_TRIGGERS = {"daily_learning", "brain_close_hook", "thesis_tracker", "graduation_logic"}


def fetch_all(db, table: str, filters: list[tuple[str, str, object]] | None = None) -> list[dict]:
    """Page through a table (PostgREST caps a response at 1000 rows)."""
    rows: list[dict] = []
    start = 0
    while True:
        q = db.table(table).select("*")
        for op, col, val in filters or []:
            q = getattr(q, op)(col, val)
        try:
            batch = q.range(start, start + PAGE - 1).execute().data or []
        except APIError as e:
            # Table not created yet (e.g. brain_decisions before migration
            # 006): nothing to archive or delete.
            if getattr(e, "code", None) == "PGRST205":
                print(f"  (skipping {table}: table does not exist yet)")
                return rows
            raise
        rows.extend(batch)
        if len(batch) < PAGE:
            return rows
        start += PAGE


def delete_ids(db, table: str, ids: list[str]) -> int:
    n = 0
    for i in range(0, len(ids), DELETE_CHUNK):
        chunk = ids[i:i + DELETE_CHUNK]
        db.table(table).delete().in_("id", chunk).execute()
        n += len(chunk)
    return n


def collect(db) -> dict[str, list[dict]]:
    """Everything the reset would remove, keyed by table."""
    plan: dict[str, list[dict]] = {t: fetch_all(db, t) for t in FULL_TABLES}
    plan["virtual_trades"] = fetch_all(db, "virtual_trades")
    plan["signal_knowledge"] = fetch_all(db, "signal_knowledge", [("eq", "source_type", "learned_from_thinking")])
    all_thinking = fetch_all(db, "signal_thinking")
    plan["signal_thinking"] = [r for r in all_thinking if r.get("created_by") == "auto_analyzer"]
    plan["_signal_thinking_reset"] = [r for r in all_thinking if r.get("created_by") != "auto_analyzer"]

    auto_ids = {r["id"] for r in plan["signal_thinking"]}
    learned_ids = {r["id"] for r in plan["signal_knowledge"]}
    events = fetch_all(db, "knowledge_events")
    plan["knowledge_events"] = [
        e for e in events
        if e.get("trade_id")
        or e.get("thinking_id") in auto_ids
        or e.get("knowledge_id") in learned_ids
        or e.get("event_type") in LEARNING_EVENT_TYPES
        or e.get("triggered_by") in LEARNING_TRIGGERS
    ]
    uid = queries.get_brain_user_id()
    plan["brain_wallet"] = fetch_all(db, "brain_wallet", [("eq", "user_id", uid)]) if uid else []
    return plan


def write_archive(plan: dict[str, list[dict]], out_dir: Path) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for table, rows in plan.items():
        name = table.lstrip("_")
        path = out_dir / f"{name}.json"
        path.write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")
        reread = json.loads(path.read_text(encoding="utf-8"))
        if len(reread) != len(rows):
            raise RuntimeError(f"archive verification failed for {path}")
        counts[name] = len(rows)
    manifest = {
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "counts": counts,
        "note": "Pre-reset brain state. signal_thinking_reset.json = human hypotheses whose "
                "counters/status were reset (rows kept in DB).",
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return counts


def execute_reset(db, plan: dict[str, list[dict]], starting_capital: float) -> None:
    ids = lambda t: [r["id"] for r in plan[t] if r.get("id")]  # noqa: E731

    print(f"  knowledge_events      deleted {delete_ids(db, 'knowledge_events', ids('knowledge_events'))}")
    for t in FULL_TABLES:
        print(f"  {t:<21} deleted {delete_ids(db, t, ids(t))}")

    learned = set(ids("signal_knowledge"))
    for r in plan["_signal_thinking_reset"] + plan["signal_thinking"]:
        if r.get("graduated_to") in learned:
            db.table("signal_thinking").update({"graduated_to": None}).eq("id", r["id"]).execute()
    print(f"  signal_knowledge      deleted {delete_ids(db, 'signal_knowledge', list(learned))}")
    print(f"  signal_thinking       deleted {delete_ids(db, 'signal_thinking', ids('signal_thinking'))}")
    for r in plan["_signal_thinking_reset"]:
        patch = {"observations_supporting": 0, "observations_contradicting": 0,
                 "observations_neutral": 0, "last_evaluated_at": None, "graduated_to": None}
        if r.get("status") == "graduated":
            patch["status"] = "active"
        db.table("signal_thinking").update(patch).eq("id", r["id"]).execute()
    print(f"  signal_thinking       reset {len(plan['_signal_thinking_reset'])} human hypotheses")

    print(f"  virtual_trades        deleted {delete_ids(db, 'virtual_trades', ids('virtual_trades'))}")
    print(f"  brain_wallet          deleted {delete_ids(db, 'brain_wallet', ids('brain_wallet'))}")

    from app.services import wallet as wallet_svc
    uid = queries.get_brain_user_id()
    if not uid:
        print("  !! no brain user — wallet NOT re-seeded")
        return
    wallet_svc.get_wallet(uid)  # lazy-creates a zeroed row
    wallet_svc.deposit(uid, starting_capital, note="Brain reset — starting capital")
    try:
        db.table("brain_wallet").update({"peak_equity": starting_capital}).eq("user_id", uid).execute()
    except Exception as e:
        print(f"  !! peak_equity not set (is migration 006 applied?): {e}")
    try:  # clear any drawdown-breaker pause (migration 009)
        db.table("brain_wallet").update({"breaker_tripped_at": None}).eq("user_id", uid).execute()
    except Exception as e:
        print(f"  !! breaker_tripped_at not cleared (is migration 009 applied?): {e}")
    print(f"  brain_wallet          re-seeded with ${starting_capital:,.2f}")
    print(f"  reconcile_wallet ->   {wallet_svc.reconcile_wallet(uid)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--confirm", action="store_true", help="actually archive + delete + re-seed")
    ap.add_argument("--starting-capital", type=float, default=settings.wallet_starting_balance)
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="archive directory (default docs/archive/<today>)")
    args = ap.parse_args()

    if args.starting_capital <= 0:
        print("starting capital must be > 0")
        return 2
    out_dir = args.out_dir or BACKEND_DIR / "docs" / "archive" / datetime.now(timezone.utc).strftime("%Y-%m-%d")

    db = get_client()
    plan = collect(db)
    print("Brain reset plan" + ("" if args.confirm else " (DRY RUN — nothing will change)"))
    for table, rows in plan.items():
        verb = "reset counters" if table.startswith("_") else "archive + delete"
        print(f"  {table.lstrip('_'):<21} {len(rows):>6} rows  ({verb})")
    print(f"  wallet re-seed: ${args.starting_capital:,.2f}   archive dir: {out_dir}")
    print("  untouched: users, tickers, signals, investment_rules, seed knowledge, "
          "positions, watchlist, docs/daily-reports/*.md")
    if not args.confirm:
        print("\nRe-run with --confirm to execute.")
        return 0

    counts = write_archive(plan, out_dir)
    print(f"\nArchived {sum(counts.values())} rows to {out_dir}")
    execute_reset(db, plan, args.starting_capital)
    print("\nDone. The next scan starts from a clean brain.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
