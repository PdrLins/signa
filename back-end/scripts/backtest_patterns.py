"""Backtest patterns on every closed brain trade.

For each closed brain virtual_trade we look up the SIGNAL that was
active at entry time (same symbol, latest signal at-or-before entry
date) and stitch that signal's features (score, bucket, horizon,
sentiment, R/R, sector, factor labels) onto the close outcome
(win/loss, pnl_pct, exit_reason, days held).

Then we slice the resulting dataset multiple ways and look for cohorts
where:
  • Win rate >= 55% with N >= 5 → "lean in" candidates (raise allocation,
    relax filters, add to seed list)
  • Win rate <= 30% with N >= 5 → "filter out" candidates (eliminate
    from entry pool, raise threshold for that subset)

Output is human-readable to stdout. INFORMATION ONLY — no DB writes,
no code changes, no config changes.

Run:
    python -m scripts.backtest_patterns

Iterate the slicing dimensions inline as we learn what matters.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean

from app.db.supabase import get_client


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _fmt_cohort(label: str, trades: list[dict]) -> str:
    if not trades:
        return f"  {label:<35} (no data)"
    n = len(trades)
    wins = sum(1 for t in trades if t.get("is_win"))
    win_rate = wins / n * 100
    pcts = [t.get("pnl_pct") or 0 for t in trades]
    avg = mean(pcts)
    total_pct = sum(pcts)
    # Tag cohorts by signal strength
    tag = ""
    if n >= 5 and win_rate >= 55:
        tag = "  ★ LEAN IN"
    elif n >= 5 and win_rate <= 30:
        tag = "  ⚠ FILTER OUT"
    return f"  {label:<35} n={n:>3}  wins={wins:>3}/{n-wins:<3}  rate={win_rate:>5.1f}%  avg={avg:+6.2f}%  sum_pct={total_pct:+7.1f}%{tag}"


def main():
    db = get_client()

    # Pull every closed brain virtual_trade with its full record. These
    # carry pnl_pct/is_win/exit_reason already, plus the entry context
    # we recorded at insert time (entry_score, bucket, trade_horizon,
    # direction, market_regime, tier_reason, entry_thesis_keywords).
    closed = (
        db.table("virtual_trades")
        .select(
            "id, symbol, entry_price, exit_price, entry_date, exit_date, "
            "entry_score, exit_score, pnl_pct, pnl_amount, is_win, exit_reason, "
            "bucket, signal_style, source, target_price, stop_loss, "
            "entry_tier, trust_multiplier, tier_reason, trade_horizon, "
            "direction, market_regime, is_wallet_trade, position_size_usd"
        )
        .eq("source", "brain")
        .eq("status", "CLOSED")
        .order("exit_date", desc=False)
        .execute()
    ).data or []

    if not closed:
        print("No closed brain trades. Nothing to analyze.")
        return

    # Enrich each trade with the signal that was active at entry. The
    # signal carries sentiment_score, risk_reward, ai_status, factor_labels,
    # technical_data — none of which are stamped on virtual_trades at insert.
    print(f"═══ Enriching {len(closed)} closed brain trades with entry signals ═══")
    for t in closed:
        sym = t["symbol"]
        edt = _parse_dt(t.get("entry_date"))
        if not edt:
            continue
        # Latest signal for this symbol AT OR BEFORE entry_date. We pick
        # the closest one in time (most recent before entry); that's what
        # the brain's tier evaluator actually saw at decision time.
        try:
            sig_rows = (
                db.table("signals")
                .select(
                    "score, action, ai_status, sentiment_score, risk_reward, "
                    "confidence, fundamental_data, technical_data, grok_data, "
                    "factor_labels, market_regime, signal_style"
                )
                .eq("symbol", sym)
                .lte("created_at", t["entry_date"])
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            ).data or []
        except Exception:
            sig_rows = []
        t["_signal"] = sig_rows[0] if sig_rows else {}

    print()
    print("═══ OVERALL ═══")
    n = len(closed)
    wins = sum(1 for t in closed if t.get("is_win"))
    pcts = [t.get("pnl_pct") or 0 for t in closed]
    print(f"  n={n}  wins={wins}/{n-wins}  win_rate={wins/n*100:.1f}%  avg_pnl={mean(pcts):+.2f}%  total={sum(pcts):+.1f}%")
    print()

    # ── Slice 1: by entry_score band ─────────────────────────────────
    print("═══ BY ENTRY SCORE BAND ═══")
    score_bands = [(0, 60, "<60"), (60, 65, "60-64"), (65, 70, "65-69"),
                   (70, 75, "70-74"), (75, 80, "75-79"), (80, 85, "80-84"),
                   (85, 90, "85-89"), (90, 100, "90+")]
    for lo, hi, label in score_bands:
        ts = [t for t in closed if lo <= (t.get("entry_score") or 0) < hi]
        print(_fmt_cohort(f"score {label}", ts))
    print()

    # ── Slice 2: by bucket ────────────────────────────────────────────
    print("═══ BY BUCKET ═══")
    for b in ["HIGH_RISK", "SAFE_INCOME"]:
        ts = [t for t in closed if (t.get("bucket") or "") == b]
        print(_fmt_cohort(f"bucket={b}", ts))
    print()

    # ── Slice 3: by trade_horizon ─────────────────────────────────────
    print("═══ BY HORIZON ═══")
    for h in ["SHORT", "LONG"]:
        ts = [t for t in closed if (t.get("trade_horizon") or "") == h]
        print(_fmt_cohort(f"horizon={h}", ts))
    print()

    # ── Slice 4: by direction ─────────────────────────────────────────
    print("═══ BY DIRECTION ═══")
    for d in ["LONG", "SHORT"]:
        ts = [t for t in closed if (t.get("direction") or "LONG") == d]
        print(_fmt_cohort(f"direction={d}", ts))
    print()

    # ── Slice 5: by exit_reason ───────────────────────────────────────
    print("═══ BY EXIT REASON ═══")
    reasons = Counter((t.get("exit_reason") or "?") for t in closed)
    for reason, _ in reasons.most_common():
        ts = [t for t in closed if (t.get("exit_reason") or "?") == reason]
        print(_fmt_cohort(f"exit={reason}", ts))
    print()

    # ── Slice 6: by tier_reason ───────────────────────────────────────
    print("═══ BY TIER REASON (entry quality) ═══")
    tier_reasons = Counter((t.get("tier_reason") or "?") for t in closed)
    for tr, _ in tier_reasons.most_common():
        ts = [t for t in closed if (t.get("tier_reason") or "?") == tr]
        print(_fmt_cohort(f"tier={tr}", ts))
    print()

    # ── Slice 7: by market_regime at entry ────────────────────────────
    print("═══ BY MARKET REGIME (at entry) ═══")
    regimes = Counter((t.get("market_regime") or "?") for t in closed)
    for r, _ in regimes.most_common():
        ts = [t for t in closed if (t.get("market_regime") or "?") == r]
        print(_fmt_cohort(f"regime={r}", ts))
    print()

    # ── Slice 8: by sentiment band (from joined signal) ──────────────
    print("═══ BY SENTIMENT SCORE (from joined signal) ═══")
    sent_bands = [(0, 50, "<50"), (50, 60, "50-59"), (60, 70, "60-69"),
                  (70, 80, "70-79"), (80, 100, "80+")]
    for lo, hi, label in sent_bands:
        ts = []
        for t in closed:
            sig = t.get("_signal") or {}
            sent_a = sig.get("sentiment_score") or 0
            grok = sig.get("grok_data") or {}
            sent_b = grok.get("sentiment_score") or grok.get("score") or 0
            sent = max(sent_a, sent_b)
            if lo <= sent < hi:
                ts.append(t)
        print(_fmt_cohort(f"sentiment {label}", ts))
    print()

    # ── Slice 9: by R/R band ──────────────────────────────────────────
    print("═══ BY RISK/REWARD AT ENTRY ═══")
    rr_bands = [(0, 1.0, "<1.0"), (1.0, 1.5, "1.0-1.5"), (1.5, 2.0, "1.5-2.0"),
                (2.0, 2.5, "2.0-2.5"), (2.5, 3.0, "2.5-3.0"), (3.0, 99, "3.0+")]
    for lo, hi, label in rr_bands:
        ts = []
        for t in closed:
            sig = t.get("_signal") or {}
            rr = sig.get("risk_reward") or 0
            if lo <= rr < hi:
                ts.append(t)
        print(_fmt_cohort(f"R/R {label}", ts))
    print()

    # ── Slice 10: by sector (from joined signal's fundamental_data) ──
    print("═══ BY SECTOR (top sectors only) ═══")
    sector_groups: dict[str, list[dict]] = defaultdict(list)
    for t in closed:
        sig = t.get("_signal") or {}
        fund = sig.get("fundamental_data") or {}
        sector = (fund.get("sector") or "?").strip()
        sector_groups[sector].append(t)
    # Sort by sample size, show top 8
    sorted_sectors = sorted(sector_groups.items(), key=lambda kv: -len(kv[1]))[:8]
    for sector, ts in sorted_sectors:
        print(_fmt_cohort(f"sector={sector}", ts))
    print()

    # ── Slice 11: by AI status ────────────────────────────────────────
    print("═══ BY AI STATUS AT ENTRY ═══")
    for ai in ["validated", "low_confidence", "skipped", "failed"]:
        ts = [t for t in closed if ((t.get("_signal") or {}).get("ai_status") or "") == ai]
        print(_fmt_cohort(f"ai_status={ai}", ts))
    print()

    # ── Slice 12: by days held band ───────────────────────────────────
    print("═══ BY DAYS HELD ═══")
    bands = [(0, 0.5, "<12h"), (0.5, 1, "12-24h"), (1, 2, "1-2d"),
             (2, 3, "2-3d"), (3, 5, "3-5d"), (5, 10, "5-10d"), (10, 99, "10d+")]
    for lo, hi, label in bands:
        ts = []
        for t in closed:
            edt = _parse_dt(t.get("entry_date"))
            xdt = _parse_dt(t.get("exit_date"))
            if not edt or not xdt:
                continue
            d = (xdt - edt).total_seconds() / 86400
            if lo <= d < hi:
                ts.append(t)
        print(_fmt_cohort(f"held {label}", ts))
    print()

    # ── Slice 13: SCORE × HORIZON cross-tab (the high-leverage one) ──
    print("═══ SCORE × HORIZON CROSS-TAB ═══")
    for hz in ["SHORT", "LONG"]:
        for lo, hi, label in [(75, 80, "75-79"), (80, 85, "80-84"), (85, 90, "85-89"), (90, 100, "90+")]:
            ts = [t for t in closed
                  if (t.get("trade_horizon") or "") == hz
                  and lo <= (t.get("entry_score") or 0) < hi]
            if ts:
                print(_fmt_cohort(f"hz={hz} score={label}", ts))
    print()

    # ── Slice 14: BUCKET × HORIZON cross-tab ──────────────────────────
    print("═══ BUCKET × HORIZON CROSS-TAB ═══")
    for b in ["HIGH_RISK", "SAFE_INCOME"]:
        for hz in ["SHORT", "LONG"]:
            ts = [t for t in closed
                  if (t.get("bucket") or "") == b
                  and (t.get("trade_horizon") or "") == hz]
            if ts:
                print(_fmt_cohort(f"{b} × {hz}", ts))
    print()

    # ── Best/worst individual trades ──────────────────────────────────
    print("═══ TOP 5 WINNERS / TOP 5 LOSERS (by pnl_pct) ═══")
    by_pct = sorted(closed, key=lambda t: t.get("pnl_pct") or 0, reverse=True)
    for t in by_pct[:5]:
        sig = t.get("_signal") or {}
        sent_a = sig.get("sentiment_score") or 0
        grok = sig.get("grok_data") or {}
        sent_b = grok.get("sentiment_score") or grok.get("score") or 0
        sent = max(sent_a, sent_b)
        print(f"  ✅ {t['symbol']:<10} {t.get('pnl_pct'):+.2f}%  score={t.get('entry_score')}  sent={sent}  bucket={t.get('bucket')}  hz={t.get('trade_horizon')}  exit={t.get('exit_reason')}")
    print("  ...")
    for t in by_pct[-5:]:
        sig = t.get("_signal") or {}
        sent_a = sig.get("sentiment_score") or 0
        grok = sig.get("grok_data") or {}
        sent_b = grok.get("sentiment_score") or grok.get("score") or 0
        sent = max(sent_a, sent_b)
        print(f"  ❌ {t['symbol']:<10} {t.get('pnl_pct'):+.2f}%  score={t.get('entry_score')}  sent={sent}  bucket={t.get('bucket')}  hz={t.get('trade_horizon')}  exit={t.get('exit_reason')}")
    print()

    print("═══ READING GUIDE ═══")
    print("  ★ LEAN IN     = cohort with n≥5 AND win rate ≥ 55%. Consider raising allocation,")
    print("                  relaxing filters, or adding to seed picks.")
    print("  ⚠ FILTER OUT  = cohort with n≥5 AND win rate ≤ 30%. Consider tightening filter")
    print("                  (raise score floor, exclude bucket/horizon/sector for these conditions).")


if __name__ == "__main__":
    main()
