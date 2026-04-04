"""Save backtest results to CSV, JSON, Markdown, and improvement files."""

import json
import random
from datetime import datetime
from pathlib import Path

import pandas as pd
from loguru import logger


def save_results(evaluated: list[dict], metrics: dict, config: dict) -> list[str]:
    """Save all output files and return list of paths created."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path("backtest/reports/output")
    output_dir.mkdir(parents=True, exist_ok=True)

    saved_files: list[str] = []

    # 1. CSV — full results
    csv_path = output_dir / f"backtest_results_{timestamp}.csv"
    _save_csv(evaluated, csv_path)
    saved_files.append(str(csv_path))

    # 2. JSON — metrics summary
    json_path = output_dir / f"backtest_summary_{timestamp}.json"
    _save_json(metrics, json_path)
    saved_files.append(str(json_path))

    # 3. Claude Code analysis file
    analysis_path = output_dir / f"claude_code_analysis_{timestamp}.md"
    _save_claude_analysis(evaluated, metrics, config, analysis_path)
    saved_files.append(str(analysis_path))

    # 4. Improvements file
    improvements_path = output_dir / f"IMPROVEMENTS_{timestamp}.md"
    _save_improvements(metrics, improvements_path)
    saved_files.append(str(improvements_path))

    logger.info("Output files saved:")
    for f in saved_files:
        logger.info(f"  → {f}")

    return saved_files


def _save_csv(evaluated: list[dict], path: Path):
    """Save evaluated results as CSV."""
    # Flatten nested dicts for CSV compatibility
    rows = []
    for r in evaluated:
        row = {}
        for k, v in r.items():
            if isinstance(v, dict):
                for nested_k, nested_v in v.items():
                    row[f"{k}_{nested_k}"] = nested_v
            else:
                row[k] = v
        rows.append(row)

    df = pd.DataFrame(rows)
    df.to_csv(path, index=False)
    logger.debug(f"CSV saved: {len(rows)} rows → {path}")


def _save_json(metrics: dict, path: Path):
    """Save metrics dict as JSON."""
    # Convert any non-serializable types
    def _clean(obj):
        if isinstance(obj, float):
            if obj != obj:  # NaN check
                return None
            return round(obj, 4)
        if isinstance(obj, dict):
            return {k: _clean(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_clean(v) for v in obj]
        return obj

    with open(path, "w") as f:
        json.dump(_clean(metrics), f, indent=2, default=str)
    logger.debug(f"JSON saved → {path}")


def _save_claude_analysis(
    evaluated: list[dict],
    metrics: dict,
    config: dict,
    path: Path,
):
    """Generate a markdown file formatted for Claude Code AI analysis."""
    counts = metrics.get("signal_counts", {})
    overall = metrics.get("overall", {})
    gems_m = metrics.get("gems", {})
    safe_m = metrics.get("safe_income", {})
    risk_m = metrics.get("high_risk", {})
    issues = metrics.get("issues", [])

    buy_signals = [r for r in evaluated if r.get("signal") == "BUY"]

    lines: list[str] = []
    _w = lines.append

    # Header
    _w("# Signa Backtest Analysis")
    _w("")
    _w("## Overview")
    _w(f"- Period: {config.get('start_date')} → {config.get('end_date')}")
    _w(f"- Total signals: {counts.get('total', 0)}")
    _w(f"- BUY: {counts.get('buy_count', 0)} | HOLD: {counts.get('hold_count', 0)} | AVOID: {counts.get('avoid_count', 0)} | GEM: {counts.get('gem_count', 0)}")
    _w(f"- Overall win rate (10d): {_fmt_pct(overall.get('win_rate_10d'))}")
    _w(f"- Overall avg return (10d): {_fmt_ret(overall.get('avg_return_10d'))}")
    _w(f"- Safe Income win rate: {_fmt_pct(safe_m.get('win_rate_10d'))} | High Risk: {_fmt_pct(risk_m.get('win_rate_10d'))}")
    _w(f"- GEM win rate: {_fmt_pct(gems_m.get('win_rate_10d'))} ({gems_m.get('count', 0)} alerts)")
    _w("")

    # Section 1 — Failed BUYs
    _w("## Section 1 — Failed BUY Signals (Score High, Return Negative)")
    _w("")
    failed = [r for r in buy_signals if r.get("return_10d") is not None and r["return_10d"] < 0]
    failed.sort(key=lambda r: r["return_10d"])
    _w(_signal_table(failed[:20]))
    _w("")

    # Section 2 — Missed Opportunities
    _w("## Section 2 — Missed Opportunities (Score Low, Price Surged)")
    _w("")
    non_buys = [r for r in evaluated if r.get("signal") in ("HOLD", "AVOID") and r.get("return_10d") is not None and r["return_10d"] > 10]
    non_buys.sort(key=lambda r: r["return_10d"], reverse=True)
    _w(_signal_table(non_buys[:20]))
    _w("")

    # Section 3 — GEM Analysis
    _w("## Section 3 — GEM Alert Analysis")
    _w("")
    gem_signals = [r for r in buy_signals if r.get("is_gem")]
    if gem_signals:
        _w(_signal_table(gem_signals))
    else:
        _w("No GEM alerts generated in this period.")
    _w("")

    # Section 4 — Score Distribution
    _w("## Section 4 — Score Distribution")
    _w("")
    dist = metrics.get("score_distribution", {})
    _w("| Range | Count |")
    _w("|-------|-------|")
    for range_label, count in dist.items():
        _w(f"| {range_label} | {count} |")
    _w("")

    # Section 5 — Random Sample
    _w("## Section 5 — Raw Sample (50 random rows)")
    _w("")
    sample_size = min(50, len(evaluated))
    sample = random.Random(42).sample(evaluated, sample_size) if evaluated else []
    _w(_signal_table(sample))
    _w("")

    # Section 6 — Questions for AI
    _w("## Section 6 — Questions for AI Review")
    _w("")
    _w("Based on this backtest data, please analyze:")
    _w("")
    _w("1. Why are high RSI BUY signals underperforming?")
    _w("2. What indicator combinations predict the best 10-day returns?")
    _w("3. Should the GEM threshold be raised or lowered?")
    _w("4. What changes to scorer.py weights would improve win rate?")
    _w("5. Are there any data quality issues to investigate?")
    _w("")

    if issues:
        _w("### Auto-Detected Issues to Investigate")
        _w("")
        for issue in issues:
            _w(f"- {issue}")
        _w("")

    with open(path, "w") as f:
        f.write("\n".join(lines))
    logger.debug(f"Claude analysis saved → {path}")


def _save_improvements(metrics: dict, path: Path):
    """Generate an improvements markdown file based on detected issues."""
    issues = metrics.get("issues", [])
    overall = metrics.get("overall", {})
    gems_m = metrics.get("gems", {})
    safe_m = metrics.get("safe_income", {})
    risk_m = metrics.get("high_risk", {})

    lines: list[str] = []
    _w = lines.append

    _w("# Auto-Detected Improvements")
    _w("")

    # Critical issues
    critical = [i for i in issues if "below 50%" in i or "not adding value" in i]
    warnings = [i for i in issues if i not in critical]

    _w("## 🔴 Critical Issues")
    _w("")
    if critical:
        for issue in critical:
            _w(f"- {issue}")
    else:
        _w("- None detected")
    _w("")

    _w("## 🟡 Investigate")
    _w("")
    if warnings:
        for issue in warnings:
            _w(f"- {issue}")
    else:
        _w("- None detected")
    _w("")

    # Working well
    _w("## 🟢 Working Well")
    _w("")
    wr10 = overall.get("win_rate_10d")
    if wr10 is not None and wr10 >= 0.6:
        _w(f"- Overall 10-day win rate is strong at {wr10:.1%}")
    gem_wr = gems_m.get("win_rate_10d")
    buy_wr = overall.get("win_rate_10d")
    if gem_wr is not None and buy_wr is not None and gem_wr > buy_wr:
        _w(f"- GEM alerts outperform regular BUYs ({gem_wr:.1%} vs {buy_wr:.1%})")
    safe_wr = safe_m.get("win_rate_10d")
    if safe_wr is not None and safe_wr >= 0.65:
        _w(f"- Safe Income bucket performing well at {safe_wr:.1%} win rate")
    risk_wr = risk_m.get("win_rate_10d")
    if risk_wr is not None and risk_wr >= 0.55:
        _w(f"- High Risk bucket above threshold at {risk_wr:.1%} win rate")
    if not any(line.startswith("- ") for line in lines[lines.index("## 🟢 Working Well") + 2:]):
        _w("- Insufficient data to determine positive patterns")
    _w("")

    # Recommended config changes
    _w("## Recommended Config Changes")
    _w("")
    if wr10 is not None and wr10 < 0.5:
        _w("- **Raise BUY threshold**: Change `signal_thresholds.buy` from 75 to 80")
        _w("  Rationale: Current threshold admits too many false positives")
    rsi_issue = any("RSI" in i for i in issues)
    if rsi_issue:
        _w("- **Add RSI cap**: Skip BUY signals when RSI > 65")
        _w("  Rationale: Overbought stocks are failing after BUY signal")
    bucket_issue = any("High Risk bucket needs tuning" in i for i in issues)
    if bucket_issue:
        _w("- **Adjust High Risk weights**: Increase `technical_momentum` from 0.40 to 0.50, reduce `catalyst_detection` to 0.20")
        _w("  Rationale: Momentum proxy for catalyst is unreliable")
    gem_issue = any("GEM conditions not adding value" in i for i in issues)
    if gem_issue:
        _w("- **Raise GEM score threshold**: Change `gem_conditions.min_score` from 85 to 90")
        _w("  Rationale: Current GEM filter is not selective enough")
    if not any(line.startswith("- ") for line in lines[lines.index("## Recommended Config Changes") + 2:]):
        _w("- No changes recommended — current config is performing well")
    _w("")

    with open(path, "w") as f:
        f.write("\n".join(lines))
    logger.debug(f"Improvements saved → {path}")


def _signal_table(signals: list[dict]) -> str:
    """Format a list of signal dicts as a markdown table."""
    if not signals:
        return "No signals in this category."

    header = "| Ticker | Date | Score | Return (10d) | RSI | MACD | vs SMA200 | Vol Ratio | Bucket | GEM |"
    sep = "|--------|------|-------|-------------|-----|------|-----------|-----------|--------|-----|"
    rows = [header, sep]

    for s in signals:
        ind = s.get("indicators_snapshot", {})
        ret = s.get("return_10d")
        ret_str = f"{ret:+.1f}%" if ret is not None else "N/A"
        macd_l = ind.get("macd_line", 0) or 0
        macd_s = ind.get("macd_signal", 0) or 0
        macd_str = "bullish" if macd_l > macd_s else "bearish"
        vs200 = ind.get("vs_sma200")
        vs200_str = f"{vs200:+.1%}" if vs200 is not None else "N/A"
        vol = ind.get("volume_ratio")
        vol_str = f"{vol:.1f}x" if vol is not None else "N/A"
        gem_str = "💎" if s.get("is_gem") else ""

        rows.append(
            f"| {s.get('ticker', '?')} | {s.get('date', '?')} | "
            f"{s.get('score', 0):.0f} | {ret_str} | "
            f"{ind.get('rsi', 0):.0f} | {macd_str} | "
            f"{vs200_str} | {vol_str} | "
            f"{s.get('bucket', '?')} | {gem_str} |"
        )

    return "\n".join(rows)


def _fmt_pct(val: float | None) -> str:
    """Format a percentage value."""
    if val is None:
        return "N/A"
    return f"{val:.1%}"


def _fmt_ret(val: float | None) -> str:
    """Format a return value."""
    if val is None:
        return "N/A"
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.1f}%"
