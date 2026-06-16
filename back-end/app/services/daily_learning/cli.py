"""CLI for the Daily Learning Loop — offline replay + ad-hoc backfill.

============================================================
USAGE
============================================================

  python -m app.services.daily_learning.cli                         # today
  python -m app.services.daily_learning.cli --date 2026-06-04
  python -m app.services.daily_learning.cli --date 2026-06-04 --dry-run
  python -m app.services.daily_learning.cli --no-telegram
  python -m app.services.daily_learning.cli --date 2026-06-04 --force
  python -m app.services.daily_learning.cli --date 2026-06-04 --strict

============================================================
FLAGS
============================================================

  --date YYYY-MM-DD   target_date for the analysis. Default: today ET.
  --dry-run           compute everything, write NOTHING (no MD file,
                      no DB inserts, no Telegram). Stdout/log-only.
  --no-telegram       run normally but skip the Telegram digest.
                      Useful for replays where the digest would be
                      misleading on a non-current day.
  --force             bypass the idempotency lock (existing COMPLETE
                      for target_date). A new RUNNING+COMPLETE row
                      will be inserted alongside the previous one.
  --strict            return SKIPPED_NO_SCAN if AFTER_CLOSE didn't
                      complete on target_date (default: log warning
                      and continue with available data).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.services.daily_learning.orchestrator import run_daily_learning

ET = ZoneInfo("America/New_York")


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.services.daily_learning.cli",
        description="Daily Learning Loop — autonomous end-of-day analysis",
    )
    parser.add_argument("--date", type=_parse_date, default=None,
                        help="target_date YYYY-MM-DD (default: today ET)")
    parser.add_argument("--dry-run", action="store_true",
                        help="skip ALL writes (MD, DB, Telegram); stdout-only")
    parser.add_argument("--no-telegram", action="store_true",
                        help="suppress Telegram digest; still write MD + DB")
    parser.add_argument("--force", action="store_true",
                        help="bypass the idempotency lock")
    parser.add_argument("--strict", action="store_true",
                        help="abort if AFTER_CLOSE didn't run on target_date")
    args = parser.parse_args(argv)

    target_date = args.date or datetime.now(ET).date()

    result = asyncio.run(
        run_daily_learning(
            target_date=target_date,
            dry_run=args.dry_run,
            send_telegram=not args.no_telegram,
            force=args.force,
            strict=args.strict,
        )
    )
    # Make the result greppable from shell — single JSON line on stdout.
    print(json.dumps(result, indent=2, default=str))

    # Exit 0 on COMPLETE / SKIPPED_*; non-zero on FAILED.
    status = result.get("status", "")
    if status == "FAILED":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
