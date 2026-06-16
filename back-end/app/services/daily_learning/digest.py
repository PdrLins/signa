"""Digest formatters — render MD report + Telegram digest strings.

============================================================
WHAT THIS MODULE PRODUCES
============================================================

  render_md_report(...) -> str
      The full markdown report written to docs/daily-reports/{date}.md.
      Mirrors the hand-written journal-entry shape so it reads naturally
      next to the existing learning-journal.md content.

  render_telegram_digest(metrics, top_findings, ...) -> str
      Short plaintext message (~6 lines, ~250 chars) for the daily
      Telegram heartbeat. Fires every market day including zero-finding
      days (per Pedro's call — heartbeat proves loop ran).

============================================================
DESIGN NOTES
============================================================

  - Pure functions: input dicts/objects in, string out. No DB calls,
    no IO. Orchestrator handles file writing + Telegram enqueueing.
  - parse_mode for Telegram: plain text (not HTML). Saves the escape
    dance, no formatting features needed for the digest shape.
  - Markdown for the file: standard CommonMark, renders cleanly on
    GitHub and any editor that supports MD tables.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Sequence


def _safe(d: dict | None, key: str, default=""):
    if d is None:
        return default
    return d.get(key, default)


def _fmt_money(v: float | None) -> str:
    if v is None:
        return "$0.00"
    return f"${v:+,.2f}"


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "0.00%"
    return f"{v:+.2f}%"


def _fmt_closes_list(closes_list: list[dict]) -> str:
    if not closes_list:
        return "_(no closes)_"
    lines = ["| Symbol | Reason | P&L | Style | Tier |", "|---|---|---|---|---|"]
    for c in closes_list:
        lines.append(
            f"| {c.get('symbol','')} | {c.get('exit_reason','')} "
            f"| {_fmt_money(c.get('pnl_amount'))} ({_fmt_pct(c.get('pnl_pct'))}) "
            f"| {c.get('signal_style') or '-'} | {c.get('entry_tier') or '-'} |"
        )
    return "\n".join(lines)


def _fmt_entries_list(entries_list: list[dict]) -> str:
    if not entries_list:
        return "_(no entries)_"
    lines = [
        "| Symbol | Score | Style | Tier | Sizing |",
        "|---|---|---|---|---|",
    ]
    for e in entries_list:
        lines.append(
            f"| {e.get('symbol','')} | {e.get('entry_score','')} "
            f"| {e.get('signal_style') or '-'} | {e.get('entry_tier') or '-'} "
            f"| ${e.get('position_size_usd', 0):,.0f} |"
        )
    return "\n".join(lines)


def _fmt_cohort_table(cohorts: Sequence[Any]) -> str:
    if not cohorts:
        return "_No cohort drift flagged._"
    lines = [
        "| Cohort | n_30d | wr_30d | wr_90d | drift | severity |",
        "|---|---|---|---|---|---|",
    ]
    for c in cohorts:
        lines.append(
            f"| {c.dimension}={c.value} | {c.n_30d} | "
            f"{c.wr_30d:.0%} | {c.wr_90d:.0%} | "
            f"{c.drift*100:+.0f}pp | {c.severity} |"
        )
    return "\n".join(lines)


def _fmt_patterns(patterns: Sequence[Any]) -> str:
    if not patterns:
        return "_No explicit patterns detected._"
    return "\n\n".join(p.body for p in patterns)


def _fmt_hypothesis_actions(actions: dict[str, list]) -> str:
    grad = actions.get("graduated") or []
    rej = actions.get("rejected") or []
    incon = actions.get("inconclusive") or []
    lines = []
    if grad:
        lines.append(f"- **Graduated:** {len(grad)}")
        for g in grad:
            lines.append(f"  - `{g.get('key_concept')}` (sup={g.get('supporting')}/con={g.get('contradicting')})")
    else:
        lines.append("- Graduated: 0")
    if rej:
        lines.append(f"- **Rejected:** {len(rej)}")
        for r in rej:
            lines.append(f"  - id={r.get('id','')[:8]} (sup={r.get('supporting')}/con={r.get('contradicting')})")
    else:
        lines.append("- Rejected: 0")
    if incon:
        lines.append(f"- Inconclusive (threshold met, ratio undecided): {len(incon)}")
    return "\n".join(lines)


def _fmt_new_hypotheses(creation_summary: dict) -> str:
    created = creation_summary.get("created") or []
    skipped = creation_summary.get("skipped_existing_active") or []
    resurfaced = creation_summary.get("resurfaced_rejected") or []
    lines = []
    if created:
        lines.append(f"- **Created:** {len(created)}")
        for c in created:
            lines.append(f"  - id={c.get('id','')[:8]} pattern={c.get('pattern_match')}")
    else:
        lines.append("- Created: 0")
    if resurfaced:
        lines.append(f"- **Resurfaced (previously rejected):** {len(resurfaced)}")
        for r in resurfaced:
            lines.append(f"  - id={r.get('id','')[:8]} pattern={r.get('pattern_match')}")
    if skipped:
        lines.append(f"- Skipped (active hypothesis already exists): {len(skipped)}")
    return "\n".join(lines)


def _fmt_suggestions(suggestions: list[dict]) -> str:
    if not suggestions:
        return "_No new INVESTIGATE rows._"
    lines = []
    for i, s in enumerate(suggestions, 1):
        lines.append(
            f"{i}. [INVESTIGATE] **{s.get('rule_name','?')}** — "
            f"{s.get('reasoning','')}"
        )
    return "\n".join(lines)


def render_md_report(
    *,
    metrics: dict,
    cohorts: Sequence[Any],
    patterns: Sequence[Any],
    new_hypothesis_summary: dict,
    hypothesis_actions: dict,
    suggestions: list[dict],
    run_id: str,
    started_at: datetime,
    completed_at: datetime,
) -> str:
    """Build the daily MD report body."""
    target_date = metrics["target_date"]
    closes = metrics["closes"]
    entries = metrics["entries"]
    wallet = metrics["wallet"]
    open_ = metrics["open"]
    regime = metrics.get("regime") or "?"
    warn = metrics.get("warning")

    sections: list[str] = []
    sections.append(f"# Daily Learning Report — {target_date}\n")
    runtime_s = (completed_at - started_at).total_seconds()
    sections.append(
        f"_Auto-generated by daily_learning_loop at "
        f"{completed_at.astimezone().strftime('%H:%M:%S %Z')}. "
        f"Run ID: `{run_id}`. Runtime: {runtime_s:.1f}s._\n"
    )

    sections.append("## Day at a glance\n")
    sections.append(
        f"- **Closes:** {closes['count']} ({closes['wins']}W / {closes['losses']}L, "
        f"net {_fmt_money(closes['net_pnl'])})\n"
        f"- **Entries:** {entries['count']} "
        f"(by tier: {entries['by_tier']}, by style: {entries['by_style']})\n"
        f"- **Wallet realized:** {_fmt_money(wallet['cumulative_realized'])} "
        f"(today {_fmt_pct(wallet['daily_pct'])}, "
        f"trailing 7d {_fmt_pct(wallet['rolling_7d_pct'])}, "
        f"trailing 30d {_fmt_pct(wallet['rolling_30d_pct'])})\n"
        f"- **Open:** {open_['count']} positions, "
        f"${open_['deployed_usd']:,.0f} deployed, "
        f"unrealized {_fmt_money(open_['unrealized_pnl'])}\n"
        f"- **Regime:** {regime}"
        + (f"\n- **Warning:** `{warn}` (cohort analysis skipped)" if warn else "")
    )

    sections.append("\n## Today's closes\n")
    sections.append(_fmt_closes_list(closes["list"]))

    sections.append("\n## Today's entries\n")
    sections.append(_fmt_entries_list(entries["list"]))

    sections.append("\n## Cohort drift (30d vs 90d)\n")
    sections.append(_fmt_cohort_table(cohorts))

    sections.append("\n## Explicit patterns detected\n")
    sections.append(_fmt_patterns(patterns))

    sections.append("\n## Hypothesis ledger\n")
    sections.append("### New (this run)\n")
    sections.append(_fmt_new_hypotheses(new_hypothesis_summary))
    sections.append("\n### Lifecycle actions\n")
    sections.append(_fmt_hypothesis_actions(hypothesis_actions))

    sections.append("\n## Suggested investigations\n")
    sections.append(_fmt_suggestions(suggestions))

    sections.append("\n## Run metadata\n")
    sections.append(
        f"- Started: {started_at.isoformat()}\n"
        f"- Completed: {completed_at.isoformat()}\n"
        f"- Runtime: {runtime_s:.2f}s\n"
        f"- Cohort findings: {len(cohorts)}\n"
        f"- Explicit-pattern findings: {len(patterns)}\n"
        f"- Hypotheses created: {len(new_hypothesis_summary.get('created') or [])}\n"
        f"- Hypotheses graduated: {len(hypothesis_actions.get('graduated') or [])}\n"
        f"- Hypotheses rejected: {len(hypothesis_actions.get('rejected') or [])}\n"
        f"- Suggestions emitted: {len(suggestions)}\n"
    )

    return "\n".join(sections) + "\n"


def render_telegram_digest(
    *,
    metrics: dict,
    findings: list[Any],
    top_findings_count: int = 2,
    md_relative_path: str | None = None,
) -> str:
    """Short plaintext digest for Telegram. Fires every day (heartbeat).

    findings is the combined list of CohortFindings + Findings, already
    sorted by severity. We take the top_findings_count for the digest.
    """
    target_date = metrics["target_date"]
    closes = metrics["closes"]
    wallet = metrics["wallet"]

    lines = [f"Daily Learning — {target_date}"]
    lines.append(
        f"Wallet: {wallet['daily_pct']:+.2f}% ({_fmt_money(wallet['cumulative_realized'])})"
    )
    lines.append(
        f"Closes: {closes['count']} ({closes['wins']}W/{closes['losses']}L, "
        f"net {_fmt_money(closes['net_pnl'])})"
    )

    if not findings:
        lines.append("0 findings — all clear")
    else:
        lines.append(f"{len(findings)} findings detected:")
        for f in findings[:top_findings_count]:
            # CohortFinding.headline is a method; Finding.headline is an attr.
            head = f.headline() if callable(getattr(f, "headline", None)) else getattr(f, "headline", "?")
            lines.append(f"• {head}")
        if len(findings) > top_findings_count:
            lines.append(f"…+{len(findings) - top_findings_count} more in report")

    if md_relative_path:
        lines.append(f"Report: {md_relative_path}")
    return "\n".join(lines)
