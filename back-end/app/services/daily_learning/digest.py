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


def _pct(v: float | None, digits: int = 2) -> str:
    return "-" if v is None else f"{v * 100:+.{digits}f}%"


def _ci(ci) -> str:
    if not ci or any(x is None or x != x for x in ci):
        return "-"
    return f"{ci[0] * 100:+.2f}..{ci[1] * 100:+.2f}%"


def _summary_cells(s: dict) -> str:
    return f"{s.get('n', 0)} | {_pct(s.get('mean'))} | {_ci(s.get('ci'))}"


def render_outcomes_section(outcomes: dict | None) -> str:
    """Markdown for the counterfactual candidate-outcome analysis.

    Groups below n=30 are shown for context but never flagged; a verdict
    needs n >= 30 AND a 95% CI that excludes zero.
    """
    if not outcomes:
        return "_Candidate outcomes unavailable (migration 008 not applied or no data yet)._"
    if outcomes.get("error"):
        return f"_Candidate outcomes failed: {outcomes['error']}_"
    h = outcomes.get("horizon", 10)
    lines = [
        f"_{outcomes.get('rows', 0)} tracked candidates, {outcomes.get('filled', 0)} with "
        f"{h}d returns. Returns are forward, vs SPY; one observation per symbol per day. "
        f"Claims need n>=30 and a 95% CI excluding zero._",
        "",
        f"### Skip-reason effectiveness ({h}d excess return of SKIPPED candidates)",
        "",
    ]
    sk = outcomes.get("skip_reasons") or {}
    gates = sk.get("gates") or []
    if not gates:
        lines.append("_No SKIP decisions with filled returns yet._")
    else:
        lines += ["| Gate | n | mean excess | 95% CI | verdict |", "|---|---|---|---|---|"]
        for g in gates:
            lines.append(f"| {g['reason']} | {_summary_cells(g)} | {g['verdict']} |")
        ent = sk.get("entered") or {}
        lines.append(f"| _(ENTER baseline)_ | {_summary_cells(ent)} | - |")
        lines.append("")
        lines.append("_costing = skipped names went on to beat SPY (the gate costs money); "
                     "protective = they lagged._")

    cal = outcomes.get("calibration") or {}
    lines += ["", f"### p_win calibration ({cal.get('horizon', 5)}d, win = fwd return > 0)", ""]
    if not cal.get("buckets"):
        lines.append(f"_No p_win bucket has n>=10 yet (n={cal.get('n', 0)})._")
    else:
        lines += ["| p_win | n | mean p_win | win rate | 95% CI | beat-SPY rate | 95% CI |",
                  "|---|---|---|---|---|---|---|"]
        for b in cal["buckets"]:
            ew = b.get("excess_win_rate")
            eci = b.get("excess_win_ci")
            lines.append(
                f"| {b['bucket']} | {b['n']} | {b['mean_p_win']:.2f} | {b['win_rate']:.0%} "
                f"| {b['win_ci'][0]:.0%}..{b['win_ci'][1]:.0%} "
                f"| {'-' if ew is None else f'{ew:.0%}'} "
                f"| {'-' if not eci else f'{eci[0]:.0%}..{eci[1]:.0%}'} |"
            )
        if cal.get("hidden_buckets"):
            lines.append(f"\n_{cal['hidden_buckets']} bucket(s) hidden (n<10)._")
    ov = cal.get("overall")
    if ov:
        lines.append(
            f"\nOverall (n={ov['n']}): Brier {ov['brier']:.3f} "
            f"(base-rate forecast {ov['brier_base_rate']:.3f}; lower is better), "
            f"mean p_win {ov['mean_p_win']:.2f} vs realised win rate {ov['win_rate']:.0%}."
        )
    else:
        lines.append(f"\n_Overall Brier withheld: n={cal.get('n', 0)} < 30._")

    ot = outcomes.get("overturn") or {}
    lines += ["", f"### Routine (Sonnet) vs decision (Opus) model ({ot.get('horizon', h)}d)", ""]
    metrics = ot.get("metrics") or {}
    if metrics:
        lines += ["| Metric | Group | n | mean | 95% CI |", "|---|---|---|---|---|"]
        for m, e in metrics.items():
            lines.append(f"| {m} | Opus-vetoed routine BUYs | {_summary_cells(e['vetoed'])} |")
            lines.append(f"| {m} | Opus-confirmed BUYs | {_summary_cells(e['confirmed'])} |")
        for m, e in metrics.items():
            lines.append(f"\n- **{m}:** {e['verdict']}")

    ai = (outcomes.get("ai_status") or {}).get("cohorts") or []
    lines += ["", "### AI-status cohorts (forward excess return vs SPY)", ""]
    if not ai:
        lines.append("_No cohorts yet._")
    else:
        lines += ["| ai_status | n 5d | 5d | n 10d | 10d (95% CI) | n 20d | 20d |",
                  "|---|---|---|---|---|---|---|"]
        for c in ai:
            s5, s10, s20 = c["excess_5d"], c["excess_10d"], c["excess_20d"]
            lines.append(
                f"| {c['ai_status']} | {s5['n']} | {_pct(s5['mean'])} | {s10['n']} "
                f"| {_pct(s10['mean'])} ({_ci(s10['ci'])}) | {s20['n']} | {_pct(s20['mean'])} |"
            )
    return "\n".join(lines)


def outcomes_digest_line(outcomes: dict | None) -> str | None:
    """One Telegram line: how many candidates are tracked + flagged gates."""
    if not outcomes or outcomes.get("error"):
        return None
    costing = [g["reason"] for g in (outcomes.get("skip_reasons") or {}).get("gates", [])
               if g.get("verdict") == "costing"]
    line = f"Outcomes: {outcomes.get('filled', 0)} candidates with {outcomes.get('horizon', 10)}d returns"
    if costing:
        line += f"; costly gates: {', '.join(costing[:3])}"
    return line


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
    outcomes: dict | None = None,
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

    sections.append("\n## Candidate outcomes (counterfactual)\n")
    sections.append(render_outcomes_section(outcomes))

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
    outcomes: dict | None = None,
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

    outcome_line = outcomes_digest_line(outcomes)
    if outcome_line:
        lines.append(outcome_line)

    if md_relative_path:
        lines.append(f"Report: {md_relative_path}")
    return "\n".join(lines)
