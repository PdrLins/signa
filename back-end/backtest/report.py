"""Markdown + JSON report writer."""

from __future__ import annotations

import json
from pathlib import Path


def caveats(meta: dict) -> list[str]:
    c = [
        "**TECHNICAL / TREND LAYER ONLY.** Historical AI inputs (X/Twitter sentiment, "
        "Claude synthesis, catalysts, cited red flags) do not exist, so every signal is the "
        "live pipeline's *tech-only* signal (`compute_score` with empty grok/synthesis, "
        "`ai_status=\"skipped\"`). The live brain NEVER auto-buys tech-only signals (it "
        "requires a validated AI BUY that passes the technical filter — or, in legacy score "
        "mode, score >= %s). This is NOT the brain's track record."
        % meta.get("brain_min_score"),
        "AI veto: %s" % (
            "placeholder ENABLED — it is a no-op (no historical AI data); no signal was vetoed."
            if meta.get("ai_veto") else "not simulated (no historical AI data)."),
    ]
    if meta.get("filter_only_entries"):
        c.append("**NON-LIVE ENTRY RULE — `--filter-only-entries`.** Portfolio entries fire on a "
                 "technical-filter PASS alone. The live brain additionally requires a validated "
                 "AI BUY; this run studies the filter as an entry rule, not live behaviour.")
    elif meta.get("entry_mode") == "filter":
        c.append("Entry mode `filter` (live default): an entry needs a validated AI BUY + a "
                 "technical-filter PASS. No historical AI exists, so the portfolio makes no "
                 "entries — see the signal study's *By technical filter* tables, or re-run with "
                 "`--filter-only-entries` (NON-LIVE) / `--entry-mode score`.")
    if meta.get("include_fundamentals"):
        c.append("**LOOKAHEAD WARNING — `--include-fundamentals` is ON.** TODAY's yfinance "
                 "fundamentals (P/E, growth, margins, dividend yield, short interest, market cap) "
                 "were applied to every past date. Results are contaminated by lookahead and "
                 "must not be used as evidence of edge.")
    else:
        c.append("Fundamentals excluded (no point-in-time source). Only sector / industry / "
                 "quote type / name are used, for the bucket and the sector cap; the fundamental "
                 "score components sit at their neutral defaults.")
    if meta.get("universe_csv"):
        c.append("Universe from user CSV `%s` (membership windows honoured). Bias depends on "
                 "how that file was built." % meta["universe_csv"])
    else:
        c.append("**SURVIVORSHIP BIAS.** The universe is today's `app/scanners/universe.py` "
                 "list — names chosen with hindsight, delisted/failed names absent. This "
                 "inflates returns; pass `--universe <csv>` with a point-in-time list to fix.")
    c += [
        "Macro is point-in-time VIX + SPY trend only; FRED series, Fear & Greed, VIX term "
        "structure are absent (the hostile-macro blocker therefore never fires).",
        "Earnings calendar not modelled point-in-time: the earnings blackout and PEAD / "
        "PRE_EARNINGS catalyst never trigger (optimistic: no earnings-gap avoidance).",
        "Execution: signals at day-t close, fills at the symbol's next bar OPEN with live "
        "slippage (%s bps stocks / %s bps crypto) and $%s commission per fill; stop assumed "
        "hit before target when one bar touches both; gaps fill at the open."
        % (meta.get("slippage_bps_stock"), meta.get("slippage_bps_crypto"), meta.get("commission_usd")),
        "Prices are split/dividend-adjusted (yfinance auto_adjust) for strategy and "
        "benchmarks alike. %s" % (
            "TSX (.TO) names excluded." if meta.get("exclude_tsx") else
            "TSX (.TO) names are converted to USD with point-in-time CAD=X at entry, mark and exit."),
    ]
    return c


def _table(rows: dict[str, dict], cols: list[tuple[str, str]], first: str) -> list[str]:
    if not rows:
        return ["_none_", ""]
    out = ["| " + first + " | " + " | ".join(h for h, _ in cols) + " |",
           "|---" * (len(cols) + 1) + "|"]
    for k, m in rows.items():
        out.append("| " + k + " | " + " | ".join(
            "" if m.get(key) is None else str(m.get(key)) for _, key in cols) + " |")
    out.append("")
    return out


EQ_COLS = [("Total %", "total_return_pct"), ("CAGR %", "cagr_pct"), ("MaxDD %", "max_drawdown_pct"),
           ("Sharpe", "sharpe"), ("Vol %", "ann_vol_pct")]
TR_COLS = [("Trades", "trades"), ("Win %", "win_rate_pct"), ("Avg win %", "avg_win_pct"),
           ("Avg loss %", "avg_loss_pct"), ("Payoff", "payoff_ratio"),
           ("Expectancy %", "expectancy_pct"), ("Avg R", "avg_r"), ("Hold d", "avg_hold_days")]
ST_COLS = [("Trades", "trades"), ("Win %", "win_rate_pct"), ("Expectancy %", "expectancy_pct"),
           ("Median %", "median_pct"), ("Avg R", "avg_r"), ("Excess vs SPY %", "avg_excess_vs_spy_pct"),
           ("Beat SPY %", "beat_spy_pct")]


def render_markdown(res: dict) -> str:
    meta = res["meta"]
    L = [f"# Signa backtest — {meta['name']}", ""]
    if meta.get("smoke"):
        L += ["> **SMOKE TEST** — tiny universe / short window, for plumbing only. Not evidence.", ""]
    L += [f"Window {meta['start']} → {meta['end']} · {meta['n_symbols']} symbols loaded · "
          f"entry rule: {meta['entry_rule']} · generated {meta['generated_at']}", ""]
    L += ["## Read this first", ""] + [f"- {c}" for c in res["caveats"]] + [""]

    L += ["## Portfolio vs benchmarks", ""]
    rows = {"Strategy (USD)": res["portfolio"]["equity"]}
    for name, b in res["benchmarks"].items():
        if b.get("available"):
            rows[f"{name} buy & hold"] = b
            if b.get("usd"):
                rows[f"{name} buy & hold (USD)"] = b["usd"]
    L += _table(rows, EQ_COLS, "Series")
    ex = res["portfolio"].get("excess_return_pct", {})
    if ex:
        L += ["Excess total return (strategy − benchmark): " +
              ", ".join(f"{k} {v:+.2f} pp" for k, v in ex.items() if v is not None), ""]
    p = res["portfolio"]
    L += [f"Exposure: avg {p['equity'].get('exposure_avg_pct')}% of equity invested, "
          f"{p['equity'].get('days_invested_pct')}% of sessions with a position · turnover "
          f"{p.get('turnover_annual_x')}x/yr · fees ${p.get('fees_usd')} · drawdown breaker: "
          f"{p.get('breaker_trips', 0)} trips, {p.get('breaker_resumes', 0)} resumes, entries "
          f"paused on {p.get('breaker_days')} days (pause "
          f"{(meta.get('live_settings') or {}).get('brain_drawdown_pause_trading_days')} "
          f"trading days, then peak reset)", ""]

    L += ["## Portfolio trades", ""]
    if not p["trades"].get("trades") and meta.get("entry_mode") == "filter" \
            and not meta.get("filter_only_entries"):
        L += ["> **No entries (expected).** Filter mode needs a validated AI BUY, which does not "
              "exist historically. See *By technical filter* in the signal study, or use "
              "`--filter-only-entries` (NON-LIVE).", ""]
    elif not p["trades"].get("trades"):
        sd = res["score_distribution"]["by_bucket"]
        mx = ", ".join(f"{b} max {v['max']}" for b, v in sd.items()) or "no candidates"
        L += [f"> **No entries.** Under the live rules the tech-only score never produced a BUY "
              f"({mx}; live thresholds {meta.get('buy_thresholds')}). Without AI sentiment / "
              "catalyst the score is structurally capped below the BUY line. Use "
              "`--entry-score N` to study the technical layer at a NON-LIVE threshold, and see "
              "the signal study below.", ""]
    L += _table({"All": p["trades"]}, TR_COLS, "")
    if p["trades"].get("exit_reasons"):
        L += ["Exit reasons: " + ", ".join(f"{k} {v}" for k, v in p["trades"]["exit_reasons"].items()), ""]
    L += ["Entry decisions: " + ", ".join(f"{k} {v}" for k, v in p["entry_decisions"].items()), ""]
    L += ["### By entry score band", ""] + _table(p["by_band"], TR_COLS, "Band")
    L += ["### By bucket", ""] + _table(p["by_bucket"], TR_COLS, "Bucket")

    L += ["## Walk-forward (no parameters are fitted; the split is reporting only)", ""]
    for seg_name in ("in_sample", "out_of_sample"):
        seg = res["walk_forward"].get(seg_name)
        if not seg:
            continue
        L += [f"### {seg_name.replace('_', '-').title()} ({seg['start']} → {seg['end']})", ""]
        rows = {"Strategy": seg["equity"]}
        for name, b in seg["benchmarks"].items():
            if b.get("available"):
                rows[name] = b
        L += _table(rows, EQ_COLS, "Series")
        L += _table({"Trades": seg["trades"]}, TR_COLS, "")

    st = res["study"]
    L += ["## Signal study — per-symbol, non-overlapping (capacity-free)", "",
          "Every prefiltered candidate signal can open a one-share study trade when its symbol "
          "is free; same live levels and exits; slippage both sides, no commission. Shows "
          "whether score / action / blockers separate outcomes.", ""]
    L += _table({"All": st["all"]}, ST_COLS, "")
    L += ["### By score band", ""] + _table(st["by_band"], ST_COLS, "Band")
    L += ["### By bucket", ""] + _table(st["by_bucket"], ST_COLS, "Bucket")
    L += ["### By live tech-only action", ""] + _table(st["by_class"], ST_COLS, "Action")
    L += ["### By regime", ""] + _table(st["by_regime"], ST_COLS, "Regime")
    if st.get("by_tech_filter"):
        L += ["### By technical filter", "",
              "Live `technical_filter` (trend above SMA200 with SMA50 > SMA200, RSI <= 75, "
              "<= 15% above SMA50, 20d dollar-volume floor, no blocker). Does PASS beat FAIL?", ""]
        L += _table(st["by_tech_filter"], ST_COLS, "Filter")
        L += ["Failing trades by reason (a trade failing several conditions appears in each "
              "row, so rows overlap):", ""]
        L += _table(st.get("by_tech_filter_reason") or {}, ST_COLS, "Failing reason")

    sd = res["score_distribution"]
    L += ["## Score distribution (all candidate-days)", "",
          f"{sd['n']} candidate-days. " + " · ".join(
              f"{b}: n={v['n']}, max={v['max']}, p95={v['p95']}, >=BUY thr={v['ge_buy_threshold']}, "
              f">={meta.get('brain_min_score')}={v['ge_brain_min']}"
              for b, v in sd["by_bucket"].items()), "",
          "Live tech-only actions: " + ", ".join(f"{k} {v}" for k, v in sd["actions"].items()), ""]
    return "\n".join(L)


def write(res: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md = out_dir / "report.md"
    js = out_dir / "report.json"
    md.write_text(render_markdown(res))
    js.write_text(json.dumps(res, indent=2, default=str))
    return md, js
