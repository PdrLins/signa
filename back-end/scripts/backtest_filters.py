"""Backtest candidate entry filters against historical closes.

The first-pass `backtest_patterns.py` identified single-dimension cohorts
with strong win/loss rates (e.g., SAFE_INCOME × LONG: 33% win, -14.9%
total). This script answers the next question: **if we had APPLIED a
filter at entry time, what would historical P&L have looked like?**

For each candidate filter, we replay all 52 closed brain trades and
ask: would this filter have admitted this trade? If admitted, count
its outcome. Compare admitted-trades win rate / total P&L against the
unfiltered baseline (40.4% win rate, -17.6% total).

INFORMATION ONLY — no DB writes, no code changes.

Run:
    python -m scripts.backtest_filters
"""

from __future__ import annotations

from collections import Counter
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


def _enrich(closed: list[dict]) -> list[dict]:
    """Attach _signal + computed fields (sector, sentiment, days_held)
    so each trade carries everything filters might want to test.
    """
    db = get_client()
    for t in closed:
        sym = t["symbol"]
        try:
            sig = (
                db.table("signals")
                .select(
                    "score, ai_status, sentiment_score, risk_reward, "
                    "fundamental_data, grok_data"
                )
                .eq("symbol", sym)
                .lte("created_at", t["entry_date"])
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            ).data or []
        except Exception:
            sig = []
        s = sig[0] if sig else {}
        t["_sig"] = s

        sent_a = s.get("sentiment_score") or 0
        grok = s.get("grok_data") or {}
        sent_b = grok.get("sentiment_score") or grok.get("score") or 0
        t["_sentiment"] = max(sent_a, sent_b)

        fund = s.get("fundamental_data") or {}
        t["_sector"] = (fund.get("sector") or "Unknown").strip()

        t["_rr"] = s.get("risk_reward") or 0
        t["_ai"] = s.get("ai_status") or "skipped"

        edt = _parse_dt(t.get("entry_date"))
        xdt = _parse_dt(t.get("exit_date"))
        t["_days"] = (xdt - edt).total_seconds() / 86400 if edt and xdt else 0
    return closed


def _stats(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0}
    n = len(trades)
    wins = sum(1 for t in trades if t.get("is_win"))
    pcts = [t.get("pnl_pct") or 0 for t in trades]
    return {
        "n": n,
        "wins": wins,
        "losses": n - wins,
        "win_rate": wins / n * 100,
        "avg_pct": mean(pcts),
        "total_pct": sum(pcts),
    }


def _fmt(s: dict, label: str) -> str:
    if s["n"] == 0:
        return f"  {label:<60} (no trades admitted)"
    return (
        f"  {label:<60} n={s['n']:>3}  W/L={s['wins']:>3}/{s['losses']:<3}  "
        f"rate={s['win_rate']:>5.1f}%  avg={s['avg_pct']:+6.2f}%  total={s['total_pct']:+7.1f}%"
    )


def _filter_eq(t: dict, **kwargs) -> bool:
    """Return True iff trade matches every key=value in kwargs.
    Special keys: _score_min, _score_max, _sentiment_min, _rr_min,
    _exclude_sectors (list), _exclude_buckets (list), _hz, _bucket.
    """
    score = t.get("entry_score") or 0
    if "_score_min" in kwargs and score < kwargs["_score_min"]:
        return False
    if "_score_max" in kwargs and score > kwargs["_score_max"]:
        return False
    if "_sentiment_min" in kwargs and t["_sentiment"] < kwargs["_sentiment_min"]:
        return False
    if "_rr_min" in kwargs and t["_rr"] < kwargs["_rr_min"]:
        return False
    if "_exclude_sectors" in kwargs and t["_sector"] in kwargs["_exclude_sectors"]:
        return False
    if "_exclude_buckets" in kwargs and (t.get("bucket") or "") in kwargs["_exclude_buckets"]:
        return False
    if "_hz" in kwargs and (t.get("trade_horizon") or "") != kwargs["_hz"]:
        return False
    if "_bucket" in kwargs and (t.get("bucket") or "") != kwargs["_bucket"]:
        return False
    if "_ai" in kwargs and t["_ai"] != kwargs["_ai"]:
        return False
    if "_exclude_hz" in kwargs and (t.get("trade_horizon") or "") in kwargs["_exclude_hz"]:
        return False
    return True


def main():
    db = get_client()

    closed = (
        db.table("virtual_trades")
        .select(
            "id, symbol, entry_price, exit_price, entry_date, exit_date, "
            "entry_score, pnl_pct, pnl_amount, is_win, exit_reason, "
            "bucket, trade_horizon, direction, market_regime, source, "
            "is_wallet_trade, position_size_usd"
        )
        .eq("source", "brain")
        .eq("status", "CLOSED")
        .order("exit_date", desc=False)
        .execute()
    ).data or []

    if not closed:
        print("No closed trades. Nothing to backtest.")
        return

    print(f"═══ Backtesting {len(closed)} closed brain trades ═══")
    closed = _enrich(closed)
    baseline = _stats(closed)
    print(_fmt(baseline, "BASELINE (no filter, all trades)"))
    print()

    # ── Filter recipes ──────────────────────────────────────────────
    # Each recipe is a hypothesis. The label describes the rule. The
    # filter func returns True iff the trade would have been admitted.

    filters: list[tuple[str, dict]] = [
        ("Score >= 75 (current Tier 1)",
         {"_score_min": 75}),
        ("Score >= 80 (today's Day-19 raise)",
         {"_score_min": 80}),
        ("Score >= 85",
         {"_score_min": 85}),

        ("Drop SAFE_INCOME × LONG (worst cohort -14.9%)",
         {"_exclude_buckets": [], "_exclude_hz": []}),  # placeholder, custom below

        ("SHORT horizon only",
         {"_hz": "SHORT"}),
        ("LONG horizon only",
         {"_hz": "LONG"}),

        ("Drop Financial Services + Industrials",
         {"_exclude_sectors": ["Financial Services", "Industrials"]}),

        ("Sentiment >= 60",
         {"_sentiment_min": 60}),
        ("Sentiment >= 70",
         {"_sentiment_min": 70}),

        ("R/R >= 1.5",
         {"_rr_min": 1.5}),
        ("R/R >= 2.0",
         {"_rr_min": 2.0}),

        ("ai_status = validated only",
         {"_ai": "validated"}),
    ]

    print("═══ SINGLE-RULE FILTERS ═══")
    for label, kwargs in filters:
        # Special handling for the cross-cohort filter
        if label.startswith("Drop SAFE_INCOME"):
            ts = [t for t in closed
                  if not (t.get("bucket") == "SAFE_INCOME"
                          and t.get("trade_horizon") == "LONG")]
        else:
            ts = [t for t in closed if _filter_eq(t, **kwargs)]
        print(_fmt(_stats(ts), label))
    print()

    # ── Combined recipes (the actual candidate strategies) ──────────
    print("═══ COMBINED FILTERS (candidate strategies) ═══")

    candidates: list[tuple[str, callable]] = [
        ("A. Score >= 75 + drop SAFE_INCOME×LONG",
         lambda t: (t.get("entry_score") or 0) >= 75
                   and not (t.get("bucket") == "SAFE_INCOME" and t.get("trade_horizon") == "LONG")),

        ("B. Score >= 75 + SHORT horizon only",
         lambda t: (t.get("entry_score") or 0) >= 75
                   and t.get("trade_horizon") == "SHORT"),

        ("C. Score >= 75 + drop Fin/Industrials sectors",
         lambda t: (t.get("entry_score") or 0) >= 75
                   and t["_sector"] not in ("Financial Services", "Industrials")),

        ("D. Score >= 75 + SHORT + drop Fin/Industrials",
         lambda t: (t.get("entry_score") or 0) >= 75
                   and t.get("trade_horizon") == "SHORT"
                   and t["_sector"] not in ("Financial Services", "Industrials")),

        ("E. Score >= 80 + SHORT only (today's actual rule)",
         lambda t: (t.get("entry_score") or 0) >= 80
                   and t.get("trade_horizon") == "SHORT"),

        ("F. Score >= 75 + sentiment >= 60",
         lambda t: (t.get("entry_score") or 0) >= 75
                   and t["_sentiment"] >= 60),

        ("G. Score >= 75 + drop SAFE_INCOME×LONG + drop Fin/Industrials",
         lambda t: (t.get("entry_score") or 0) >= 75
                   and not (t.get("bucket") == "SAFE_INCOME" and t.get("trade_horizon") == "LONG")
                   and t["_sector"] not in ("Financial Services", "Industrials")),

        ("H. Score >= 75 + R/R >= 1.5",
         lambda t: (t.get("entry_score") or 0) >= 75
                   and t["_rr"] >= 1.5),

        ("I. Score >= 80 + drop SAFE_INCOME×LONG (Day-19 raise PLUS LONG/SAFE filter)",
         lambda t: (t.get("entry_score") or 0) >= 80
                   and not (t.get("bucket") == "SAFE_INCOME" and t.get("trade_horizon") == "LONG")),

        ("J. The kitchen sink: 75+ AND SHORT AND not Fin AND not Industrials AND validated",
         lambda t: (t.get("entry_score") or 0) >= 75
                   and t.get("trade_horizon") == "SHORT"
                   and t["_sector"] not in ("Financial Services", "Industrials")
                   and t["_ai"] == "validated"),
    ]

    results = []
    for label, fn in candidates:
        ts = [t for t in closed if fn(t)]
        s = _stats(ts)
        results.append((label, s))
        print(_fmt(s, label))
    print()

    # Rank by total_pct
    print("═══ RANKED BY TOTAL P&L (filtered subset) ═══")
    ranked = sorted([r for r in results if r[1]["n"] > 0], key=lambda r: -r[1]["total_pct"])
    for label, s in ranked:
        delta_n = baseline["n"] - s["n"]
        delta_total = s["total_pct"] - baseline["total_pct"]
        print(f"  total {s['total_pct']:+7.1f}%  ({delta_total:+6.1f}pp vs baseline)  "
              f"win {s['win_rate']:>5.1f}%  n={s['n']:>3} (-{delta_n})  "
              f"{label}")
    print()

    print("═══ READING ═══")
    print("  • Baseline = no filter, all trades, total -17.6%.")
    print("  • Each filter shows what historical P&L would be if we'd applied it.")
    print("  • '★ best' filter is the strategy with the highest historical total_pct.")
    print("  • Beware small-N filters — even a great win rate is noise at n<10.")
    print("  • These are HISTORICAL signals — past performance doesn't guarantee future,")
    print("    but it's the strongest evidence we have for which patterns to act on.")


if __name__ == "__main__":
    main()
