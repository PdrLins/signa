"""Read-only DB inspection: figure out where the rogue source='watchlist' rows
came from when the user's actual watchlist only contains XEQT.TO.

Checks:
  1. Current contents of the `watchlist` table (all users)
  2. All `virtual_trades` rows tagged source='watchlist' (open + closed)
  3. Whether the rogue symbols (PNC, RBA.TO, SLF.TO) currently exist
     in `watchlist` or appear anywhere else that could explain the tag

Usage from back-end/:
    venv/bin/python -m scripts.inspect_watchlist_dupes
"""

from __future__ import annotations

import sys
sys.path.insert(0, ".")

from app.db.supabase import get_client


def main() -> int:
    db = get_client()

    print("=" * 100)
    print("1. CURRENT `watchlist` TABLE CONTENTS")
    print("=" * 100)
    wl = db.table("watchlist").select("user_id, symbol, added_at, notes").order("added_at", desc=True).execute()
    rows = wl.data or []
    print(f"Total rows: {len(rows)}\n")
    for r in rows:
        print(f"  user={r.get('user_id', '?')[:8]}  symbol={r['symbol']}  added={r.get('added_at')}  notes={r.get('notes')}")

    print()
    print("=" * 100)
    print("2. ALL `virtual_trades` ROWS WITH source='watchlist'")
    print("=" * 100)
    vt = (
        db.table("virtual_trades")
        .select("id, symbol, status, source, entry_date, exit_date, entry_price, exit_price, pnl_pct, is_win, exit_reason, user_id")
        .eq("source", "watchlist")
        .order("entry_date", desc=True)
        .execute()
    )
    rows = vt.data or []
    print(f"Total rows: {len(rows)}\n")
    for r in rows:
        print(f"  id={r['id'][:8]}  {r['symbol']:10}  status={r['status']:8}  user={(r.get('user_id') or 'NULL')[:8]}")
        print(f"    entry={r.get('entry_price')} @ {r.get('entry_date')}")
        print(f"    exit ={r.get('exit_price')} @ {r.get('exit_date')}")
        print(f"    pnl={r.get('pnl_pct')}  win={r.get('is_win')}  reason={r.get('exit_reason')}")
        print()

    print("=" * 100)
    print("3. SUSPECT SYMBOLS — currently in watchlist?")
    print("=" * 100)
    suspect_syms = ["PNC", "RBA.TO", "SLF.TO", "XEQT.TO"]
    wl_syms = {r["symbol"] for r in (db.table("watchlist").select("symbol").execute().data or [])}
    for s in suspect_syms:
        present = s in wl_syms
        marker = "✓" if present else "✗"
        print(f"  {marker} {s}: {'IN watchlist' if present else 'NOT in watchlist'}")

    print()
    print("=" * 100)
    print("4. ALL OPEN virtual_trades (full picture)")
    print("=" * 100)
    op = (
        db.table("virtual_trades")
        .select("id, symbol, source, entry_date, entry_price, entry_score, user_id")
        .eq("status", "OPEN")
        .order("entry_date", desc=True)
        .execute()
    )
    rows = op.data or []
    print(f"Total OPEN rows: {len(rows)}\n")
    for r in rows:
        print(f"  {r['symbol']:10}  source={r.get('source', '?'):10}  score={r.get('entry_score')}  user={(r.get('user_id') or 'NULL')[:8]}  entered={r.get('entry_date')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
