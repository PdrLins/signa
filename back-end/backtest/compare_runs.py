"""Compare backtest runs -- regression tracking.

Shows a comparison table of all backtest results over time.
Run with: python -m backtest.compare_runs
"""

import json
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "reports" / "output"


def load_summaries() -> list[dict]:
    """Load all backtest summary JSON files, sorted by date."""
    summaries = []
    for f in sorted(OUTPUT_DIR.glob("backtest_summary_*.json")):
        try:
            with open(f) as fh:
                data = json.load(fh)
                data["_file"] = f.name
                data["_date"] = f.stem.replace("backtest_summary_", "")
                summaries.append(data)
        except (json.JSONDecodeError, OSError):
            pass
    return summaries


def print_comparison():
    """Print a comparison table of all backtest runs."""
    runs = load_summaries()
    if not runs:
        print("No backtest summaries found.")
        return

    print(f"\n{'=' * 100}")
    print(f"  BACKTEST REGRESSION TRACKER -- {len(runs)} runs")
    print(f"{'=' * 100}\n")

    header = (
        f"{'Run Date':<20} {'Signals':>8} {'BUYs':>6} "
        f"{'WR 10d':>8} {'Ret 10d':>8} {'WR 20d':>8} {'Ret 20d':>8} "
        f"{'SAFE WR':>8} {'RISK WR':>8}"
    )
    print(header)
    print("-" * len(header))

    baseline_wr = None
    for run in runs:
        date = run.get("_date", "?")
        counts = run.get("signal_counts", {})
        total = counts.get("total", 0)
        buys = counts.get("buy_count", 0)

        overall = run.get("overall", {})
        wr_10d = overall.get("win_rate_10d", 0) * 100
        ret_10d = overall.get("avg_return_10d", 0)
        wr_20d = overall.get("win_rate_20d", 0) * 100
        ret_20d = overall.get("avg_return_20d", 0)

        safe = run.get("safe_income", {})
        risk = run.get("high_risk", {})
        safe_wr = safe.get("win_rate_10d", 0) * 100
        risk_wr = risk.get("win_rate_10d", 0) * 100

        if baseline_wr is None:
            baseline_wr = wr_10d

        delta = wr_10d - baseline_wr
        delta_str = f"  ({delta:+.1f})" if abs(delta) > 0.05 else ""

        print(
            f"{date:<20} {total:>8} {buys:>6} "
            f"{wr_10d:>7.1f}% {ret_10d:>+7.2f}% {wr_20d:>7.1f}% {ret_20d:>+7.2f}% "
            f"{safe_wr:>7.1f}% {risk_wr:>7.1f}%"
            f"{delta_str}"
        )

    print(f"\n{'=' * 100}")
    print("  Baseline = first run with data. Delta shown vs baseline 10d win rate.")
    print("  Target: no regression in win rate. Higher is better.")
    print(f"{'=' * 100}\n")


if __name__ == "__main__":
    print_comparison()
