"""Compute aggregate metrics from evaluated backtest results."""

from loguru import logger


def compute_metrics(evaluated: list[dict]) -> dict:
    """Compute full metrics from evaluated signal results.

    Returns dict with overall stats, per-bucket stats, GEM stats,
    score distribution, signal counts, best/worst performers, and
    auto-detected issues.
    """
    all_signals = evaluated
    buy_signals = [r for r in evaluated if r["signal"] == "BUY"]
    hold_signals = [r for r in evaluated if r["signal"] == "HOLD"]
    avoid_signals = [r for r in evaluated if r["signal"] == "AVOID"]
    gem_signals = [r for r in buy_signals if r["is_gem"]]

    safe_buys = [r for r in buy_signals if r["bucket"] == "SAFE_INCOME"]
    risk_buys = [r for r in buy_signals if r["bucket"] == "HIGH_RISK"]

    # Per-group metrics
    overall = _compute_group_metrics(buy_signals, "overall")
    safe_income = _compute_group_metrics(safe_buys, "SAFE_INCOME")
    high_risk = _compute_group_metrics(risk_buys, "HIGH_RISK")
    gems = _compute_group_metrics(gem_signals, "GEM")

    # Score distribution (all signals, not just BUYs)
    score_dist = _compute_score_distribution(all_signals)

    # Signal counts
    signal_counts = {
        "total": len(all_signals),
        "buy_count": len(buy_signals),
        "hold_count": len(hold_signals),
        "avoid_count": len(avoid_signals),
        "gem_count": len(gem_signals),
    }

    # Best and worst performers (by 10d return)
    best_5 = _top_n(buy_signals, "return_10d", n=5, ascending=False)
    worst_5 = _top_n(buy_signals, "return_10d", n=5, ascending=True)

    # Auto-detected issues
    issues = _detect_issues(
        overall, safe_income, high_risk, gems,
        buy_signals, all_signals,
    )

    metrics = {
        "signal_counts": signal_counts,
        "overall": overall,
        "safe_income": safe_income,
        "high_risk": high_risk,
        "gems": gems,
        "score_distribution": score_dist,
        "best_5": best_5,
        "worst_5": worst_5,
        "issues": issues,
    }

    logger.info(
        f"Metrics: {signal_counts['buy_count']} BUYs, "
        f"{signal_counts['gem_count']} GEMs, "
        f"{len(issues)} issues detected"
    )

    return metrics


def _compute_group_metrics(signals: list[dict], label: str) -> dict:
    """Compute win rates and average returns for a group of BUY signals."""
    count = len(signals)
    if count == 0:
        return {
            "label": label,
            "count": 0,
            "win_rate_5d": None,
            "win_rate_10d": None,
            "win_rate_20d": None,
            "avg_return_5d": None,
            "avg_return_10d": None,
            "avg_return_20d": None,
        }

    result = {"label": label, "count": count}

    for window in [5, 10, 20]:
        return_key = f"return_{window}d"
        profitable_key = f"profitable_{window}d"

        returns = [r[return_key] for r in signals if r.get(return_key) is not None]
        wins = [r[profitable_key] for r in signals if r.get(profitable_key) is not None]

        result[f"win_rate_{window}d"] = (
            round(sum(wins) / len(wins), 4) if wins else None
        )
        result[f"avg_return_{window}d"] = (
            round(sum(returns) / len(returns), 4) if returns else None
        )

    return result


def _compute_score_distribution(signals: list[dict]) -> dict:
    """Count how many signals fall in each score range."""
    ranges = {
        "40-50": 0,
        "50-60": 0,
        "60-70": 0,
        "70-80": 0,
        "80-90": 0,
        "90-100": 0,
    }

    for s in signals:
        score = s.get("score", 0)
        if score < 50:
            ranges["40-50"] += 1
        elif score < 60:
            ranges["50-60"] += 1
        elif score < 70:
            ranges["60-70"] += 1
        elif score < 80:
            ranges["70-80"] += 1
        elif score < 90:
            ranges["80-90"] += 1
        else:
            ranges["90-100"] += 1

    return ranges


def _top_n(
    signals: list[dict],
    key: str,
    n: int = 5,
    ascending: bool = False,
) -> list[dict]:
    """Get top/bottom N signals by a return key."""
    with_values = [s for s in signals if s.get(key) is not None]
    sorted_signals = sorted(
        with_values,
        key=lambda s: s[key],
        reverse=not ascending,
    )

    return [
        {
            "ticker": s["ticker"],
            "date": s["date"],
            "score": s["score"],
            "bucket": s["bucket"],
            "is_gem": s["is_gem"],
            key: s[key],
        }
        for s in sorted_signals[:n]
    ]


def _detect_issues(
    overall: dict,
    safe_income: dict,
    high_risk: dict,
    gems: dict,
    buy_signals: list[dict],
    all_signals: list[dict],
) -> list[str]:
    """Auto-detect scoring patterns that suggest problems."""
    issues: list[str] = []

    # 1. Win rate below 50%
    wr10 = overall.get("win_rate_10d")
    if wr10 is not None and wr10 < 0.50:
        issues.append(
            f"Win rate below 50% at 10d ({wr10:.1%}) — "
            f"scorer may not be better than random"
        )

    # 2. High RSI on failed BUY signals
    failed_buys = [
        s for s in buy_signals
        if s.get("profitable_10d") is False
    ]
    if failed_buys:
        avg_rsi_failed = sum(
            s.get("indicators_snapshot", {}).get("rsi", 0) for s in failed_buys
        ) / len(failed_buys)
        if avg_rsi_failed > 65:
            issues.append(
                f"High RSI correlates with failures (avg RSI {avg_rsi_failed:.0f} "
                f"on failed BUYs) — add RSI cap"
            )

    # 3. Safe Income much better than High Risk
    safe_wr = safe_income.get("win_rate_10d")
    risk_wr = high_risk.get("win_rate_10d")
    if safe_wr is not None and risk_wr is not None:
        diff = safe_wr - risk_wr
        if diff > 0.20:
            issues.append(
                f"High Risk bucket needs tuning — Safe Income win rate "
                f"({safe_wr:.1%}) beats High Risk ({risk_wr:.1%}) by {diff:.1%}"
            )

    # 4. GEM win rate worse than overall BUY win rate
    gem_wr = gems.get("win_rate_10d")
    if gem_wr is not None and wr10 is not None:
        if gem_wr < wr10:
            issues.append(
                f"GEM conditions not adding value — GEM win rate ({gem_wr:.1%}) "
                f"is lower than overall BUY ({wr10:.1%}) — review thresholds"
            )

    # 5. Any ticker with 0 BUY signals
    all_tickers = set()
    buy_tickers = set()
    for s in all_signals:
        all_tickers.add(s["ticker"])
    for s in buy_signals:
        buy_tickers.add(s["ticker"])

    never_bought = all_tickers - buy_tickers
    if never_bought:
        for t in sorted(never_bought):
            issues.append(f"Possible data issue for {t} — 0 BUY signals in test period")

    return issues
