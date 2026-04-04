"""Rich terminal output for backtest results."""

from rich.console import Console
from rich.table import Table
from rich.text import Text

console = Console()


def print_summary(metrics: dict, config: dict | None = None):
    """Print a formatted backtest report to the terminal."""
    start = config.get("start_date", "?") if config else "?"
    end = config.get("end_date", "?") if config else "?"
    tickers_cfg = config.get("tickers", {}) if config else {}
    us_count = len(tickers_cfg.get("US", []))
    tsx_count = len(tickers_cfg.get("TSX", []))
    crypto_count = len(tickers_cfg.get("CRYPTO", []))
    total_tickers = us_count + tsx_count + crypto_count

    counts = metrics.get("signal_counts", {})
    overall = metrics.get("overall", {})
    gems = metrics.get("gems", {})
    safe = metrics.get("safe_income", {})
    risk = metrics.get("high_risk", {})

    # Header
    console.print()
    console.print("═" * 50, style="bold cyan")
    console.print(" 💎 SIGNA BACKTEST REPORT", style="bold white")
    console.print(f" Period: {start} → {end}", style="dim")
    parts = [f"{us_count} US", f"{tsx_count} TSX"]
    if crypto_count:
        parts.append(f"{crypto_count} Crypto")
    console.print(f" Universe: {total_tickers} tickers ({' + '.join(parts)})", style="dim")
    console.print("═" * 50, style="bold cyan")
    console.print()

    # Signal counts
    console.print("[bold]SIGNALS GENERATED[/bold]")
    console.print(f"  Total signals:    {counts.get('total', 0)}")
    console.print(
        f"  BUY: {counts.get('buy_count', 0)}  "
        f"HOLD: {counts.get('hold_count', 0)}  "
        f"AVOID: {counts.get('avoid_count', 0)}  "
        f"GEM: {counts.get('gem_count', 0)}"
    )
    console.print()

    # Buy accuracy
    console.print("[bold]BUY SIGNAL ACCURACY (scorer only — no Claude)[/bold]")
    _print_rate("  Win rate  5 days:", overall.get("win_rate_5d"))
    _print_rate("  Win rate 10 days:", overall.get("win_rate_10d"))
    _print_rate("  Win rate 20 days:", overall.get("win_rate_20d"))
    _print_return("  Avg return 10 days:", overall.get("avg_return_10d"))
    console.print()

    # GEM alerts
    gem_count = gems.get("count", 0)
    gem_wr = gems.get("win_rate_10d")
    gem_avg = gems.get("avg_return_10d")
    console.print("[bold]💎 GEM ALERTS[/bold]")
    parts = [f"  Total: {gem_count}"]
    if gem_wr is not None:
        parts.append(f"Win rate 10d: {gem_wr:.1%}")
    if gem_avg is not None:
        parts.append(f"Avg: {_fmt_return(gem_avg)}")
    console.print("  |  ".join(parts))
    console.print()

    # By bucket
    console.print("[bold]BY BUCKET[/bold]")
    _print_bucket_line("  Safe Income", safe)
    _print_bucket_line("  High Risk  ", risk)
    console.print()

    # Top 5
    best = metrics.get("best_5", [])
    if best:
        console.print("[bold]TOP 5 SIGNALS[/bold]")
        _print_signal_table(best, "return_10d")
        console.print()

    # Worst 5
    worst = metrics.get("worst_5", [])
    if worst:
        console.print("[bold]WORST 5 SIGNALS[/bold]")
        _print_signal_table(worst, "return_10d")
        console.print()

    # Score distribution
    dist = metrics.get("score_distribution", {})
    if dist:
        console.print("[bold]SCORE DISTRIBUTION[/bold]")
        for range_label, count in dist.items():
            bar = "█" * min(count // 5, 40) if count > 0 else ""
            console.print(f"  {range_label}: {count:>5}  {bar}")
        console.print()

    # Issues
    issues = metrics.get("issues", [])
    if issues:
        console.print("[bold yellow]⚠️  AUTO-DETECTED ISSUES[/bold yellow]")
        for issue in issues:
            console.print(f"  • {issue}", style="yellow")
        console.print()
    else:
        console.print("[bold green]✅ No issues detected[/bold green]")
        console.print()


def _print_rate(label: str, value: float | None):
    """Print a win rate line with color."""
    if value is None:
        console.print(f"{label}    N/A", style="dim")
        return
    color = "green" if value >= 0.5 else "red"
    console.print(f"{label}    [{color}]{value:.1%}[/{color}]")


def _print_return(label: str, value: float | None):
    """Print a return line with color."""
    if value is None:
        console.print(f"{label}  N/A", style="dim")
        return
    console.print(f"{label}  {_fmt_return(value)}")


def _fmt_return(value: float) -> str:
    """Format a return percentage with color markup."""
    sign = "+" if value >= 0 else ""
    color = "green" if value >= 0 else "red"
    return f"[{color}]{sign}{value:.1f}%[/{color}]"


def _print_bucket_line(label: str, bucket: dict):
    """Print a single bucket summary line."""
    wr = bucket.get("win_rate_10d")
    avg = bucket.get("avg_return_10d")
    count = bucket.get("count", 0)
    parts = [f"{label} ({count})"]
    if wr is not None:
        parts.append(f"win rate: {wr:.1%}")
    if avg is not None:
        parts.append(f"avg return: {_fmt_return(avg)}")
    console.print("  →  ".join(parts))


def _print_signal_table(signals: list[dict], return_key: str):
    """Print a table of top/bottom signals."""
    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Ticker", style="bold")
    table.add_column("Date")
    table.add_column("Score", justify="right")
    table.add_column("Return (10d)", justify="right")
    table.add_column("Bucket")
    table.add_column("GEM")

    for s in signals:
        ret = s.get(return_key)
        if ret is not None:
            sign = "+" if ret >= 0 else ""
            color = "green" if ret >= 0 else "red"
            ret_str = f"[{color}]{sign}{ret:.1f}%[/{color}]"
        else:
            ret_str = "N/A"

        gem_str = "💎" if s.get("is_gem") else ""

        table.add_row(
            s.get("ticker", "?"),
            s.get("date", "?"),
            str(round(s.get("score", 0))),
            ret_str,
            s.get("bucket", "?"),
            gem_str,
        )

    console.print(table)
