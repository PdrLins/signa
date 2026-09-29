"""Portfolio-level risk for the brain: correlation gate, beta, volatility.

============================================================
THE CORRELATION RULE (entry gate, LONG candidates only)
============================================================

Sector / crypto caps are label-based; two "different sector" names can
still be the same trade (e.g. a semiconductor and a cloud name in a tech
sell-off, or BTC and a crypto miner). This gate looks at what the prices
actually do.

Inputs: ~`brain_corr_lookback_days` (120) trading days of daily returns
(USD-converted for CAD listings) for the candidate and every open LONG
brain position. Pearson correlation, pairwise, requiring at least
`brain_corr_min_obs` (40) overlapping returns per pair.

A candidate is BLOCKED (skip reason "correlation_limit") when EITHER

  (a) pairwise: its correlation to any single open position is
      >= brain_corr_max_pairwise (0.80) — it is effectively a duplicate
      of a position we already hold; or
  (b) cluster: >= brain_corr_cluster_max (2) open positions correlate
      >= brain_corr_cluster_threshold (0.70) — it would extend an
      existing correlated cluster to 3+ names.

Why this rule and not "correlation-weighted exposure > cap": daily stock
returns share a market factor, so ordinary pairwise correlations sit at
0.3-0.5. A Σ corr × weight rule therefore grows with the NUMBER of
positions rather than with concentration, and would block diversified
books. Thresholding at 0.70/0.80 isolates genuinely redundant exposure,
is easy to audit and is independent of position sizing. The weighted
exposure (Σ max(ρ,0)·w) is still computed and logged in the decision
details for reporting.

Missing data NEVER blocks: if the candidate has no usable history, the
check is skipped (details carry status="skipped" + why); open positions
without enough overlap are listed under "no_data" and ignored.

Optional (off by default): `brain_max_portfolio_beta` > 0 blocks when the
post-trade portfolio beta to SPY would exceed the cap
(reason "portfolio_beta_limit").

============================================================
REPORTING
============================================================

`get_portfolio_risk_metrics()` returns the correlation matrix summary,
largest correlated cluster, portfolio beta to SPY and an annualized
volatility estimate sqrt(wᵀΣw · 252) for the daily snapshot / API.
Weights are position cost basis / equity (cash has zero beta and vol).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from loguru import logger

from app.core.config import settings

BENCHMARK = "SPY"
TRADING_DAYS = 252

ClosesLoader = Callable[[list[str]], dict]


# ============================================================
# DATA
# ============================================================

def _load_closes(symbols: list[str]) -> dict:
    """Daily closes (USD) per symbol via price_cache (batched, cached 6h).

    CAD listings are converted with the USDCAD ("CAD=X") history when
    available so correlations/beta are measured in the wallet currency.
    """
    from app.services.price_cache import fetch_daily_closes, native_currency

    cad = [s for s in symbols if native_currency(s) == "CAD"]
    closes = fetch_daily_closes(list(symbols) + (["CAD=X"] if cad else []), period="1y")
    fx = closes.pop("CAD=X", None)
    if fx is not None and cad:
        for sym in cad:
            s = closes.get(sym)
            if s is None:
                continue
            rate = fx.reindex(s.index.union(fx.index)).sort_index().ffill().reindex(s.index)
            closes[sym] = (s / rate).dropna()
    return closes


def returns_frame(closes: dict, lookback: int | None = None):
    """Aligned daily simple returns (DataFrame, one column per symbol).

    Weekend rows (crypto) are dropped so every series lives on the equity
    calendar; a day missing for one exchange yields NaN (not 0), and
    correlations are computed pairwise over overlapping observations.
    """
    import pandas as pd

    series = {k: v for k, v in (closes or {}).items() if v is not None and len(v) > 1}
    if not series:
        return pd.DataFrame()
    frame = pd.concat(series, axis=1, sort=True)
    frame = frame[pd.DatetimeIndex(frame.index).dayofweek < 5]
    rets = frame.pct_change(fill_method=None)
    rets = rets.iloc[1:]
    lookback = lookback or settings.brain_corr_lookback_days
    return rets.tail(lookback)


def _finite(x) -> float | None:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def pair_correlation(rets, a: str, b: str, min_obs: int | None = None) -> float | None:
    """Pearson correlation of two return columns over overlapping obs."""
    min_obs = settings.brain_corr_min_obs if min_obs is None else min_obs
    if rets is None or a not in rets or b not in rets:
        return None
    pair = rets[[a, b]].dropna()
    if len(pair) < max(min_obs, 3):
        return None
    return _finite(pair[a].corr(pair[b]))


# ============================================================
# CORRELATION RULE
# ============================================================

def evaluate_correlation_rule(
    corrs: dict[str, float],
    weights: dict[str, float] | None = None,
    *,
    max_pairwise: float | None = None,
    cluster_threshold: float | None = None,
    cluster_max: int | None = None,
) -> tuple[bool, dict]:
    """Apply the correlation rule to candidate-vs-open correlations.

    `corrs` = {open_symbol: ρ(candidate, open_symbol)} (only usable pairs).
    `weights` = {open_symbol: position weight (fraction of equity)}.
    Returns (blocked, details).
    """
    max_pairwise = settings.brain_corr_max_pairwise if max_pairwise is None else max_pairwise
    cluster_threshold = (settings.brain_corr_cluster_threshold
                         if cluster_threshold is None else cluster_threshold)
    cluster_max = settings.brain_corr_cluster_max if cluster_max is None else cluster_max
    weights = weights or {}

    details: dict = {
        "max_pairwise": max_pairwise,
        "cluster_threshold": cluster_threshold,
        "cluster_max": cluster_max,
        "corr": {s: round(c, 3) for s, c in sorted(corrs.items(), key=lambda kv: -kv[1])},
    }
    if not corrs:
        details["rule"] = None
        return False, details

    top_sym, top = max(corrs.items(), key=lambda kv: kv[1])
    cluster = sorted((s for s, c in corrs.items() if c >= cluster_threshold),
                     key=lambda s: -corrs[s])
    details.update({
        "max_corr": round(top, 3),
        "max_corr_symbol": top_sym,
        "n_above_cluster_threshold": len(cluster),
        "cluster_symbols": cluster,
        "weighted_exposure": round(sum(max(c, 0.0) * float(weights.get(s) or 0.0)
                                       for s, c in corrs.items()), 4),
    })
    rule = None
    if top >= max_pairwise:
        rule = "pairwise"
    elif cluster_max > 0 and len(cluster) >= cluster_max:
        rule = "correlated_cluster"
    details["rule"] = rule
    return rule is not None, details


# ============================================================
# BETA / VOLATILITY / CLUSTERS
# ============================================================

def symbol_betas(rets, symbols: list[str], benchmark: str = BENCHMARK,
                 min_obs: int | None = None) -> dict[str, float]:
    """β_i = cov(r_i, r_bench) / var(r_bench) over overlapping obs."""
    min_obs = settings.brain_corr_min_obs if min_obs is None else min_obs
    out: dict[str, float] = {}
    if rets is None or benchmark not in rets:
        return out
    for sym in symbols:
        if sym == benchmark:
            out[sym] = 1.0
            continue
        if sym not in rets:
            continue
        pair = rets[[sym, benchmark]].dropna()
        if len(pair) < max(min_obs, 3):
            continue
        var_b = float(pair[benchmark].var())
        if var_b <= 0:
            continue
        beta = _finite(float(pair[sym].cov(pair[benchmark])) / var_b)
        if beta is not None:
            out[sym] = beta
    return out


def portfolio_beta(weights: dict[str, float], betas: dict[str, float]) -> float | None:
    """Σ w_i β_i over positions with a beta (cash contributes 0)."""
    used = [(w, betas[s]) for s, w in weights.items() if s in betas]
    if not used:
        return None
    return sum(w * b for w, b in used)


def portfolio_volatility(rets, weights: dict[str, float], min_obs: int | None = None,
                         annualize: bool = True) -> float | None:
    """sqrt(wᵀ Σ w) from the pairwise daily covariance matrix.

    Symbols without data are dropped (their risk is not estimated). Pairs
    with too little overlap contribute 0 covariance. Annualized × √252.
    """
    import numpy as np

    min_obs = settings.brain_corr_min_obs if min_obs is None else min_obs
    syms = [s for s in weights if rets is not None and s in rets
            and rets[s].count() >= max(min_obs, 3)]
    if not syms:
        return None
    cov = rets[syms].cov(min_periods=max(min_obs, 3)).fillna(0.0).to_numpy()
    w = np.array([float(weights[s]) for s in syms])
    var = float(w @ cov @ w)
    vol = math.sqrt(max(var, 0.0))
    return vol * math.sqrt(TRADING_DAYS) if annualize else vol


def largest_cluster(corr_matrix, threshold: float | None = None) -> list[str]:
    """Largest connected group of symbols linked by ρ >= threshold."""
    threshold = settings.brain_corr_cluster_threshold if threshold is None else threshold
    if corr_matrix is None or corr_matrix.empty:
        return []
    syms = list(corr_matrix.columns)
    seen: set[str] = set()
    best: list[str] = []
    for start in syms:
        if start in seen:
            continue
        comp, stack = [], [start]
        seen.add(start)
        while stack:
            s = stack.pop()
            comp.append(s)
            for t in syms:
                if t in seen:
                    continue
                c = _finite(corr_matrix.at[s, t])
                if c is not None and c >= threshold:
                    seen.add(t)
                    stack.append(t)
        if len(comp) > len(best):
            best = comp
    return sorted(best) if len(best) > 1 else []


# ============================================================
# ENTRY GATE
# ============================================================

@dataclass
class CorrelationCheck:
    reason: str | None                      # None = allowed
    details: dict = field(default_factory=dict)


def _book_weights(open_book: list[dict], equity: float) -> dict[str, float]:
    """Signed weights (fraction of equity) of open brain positions by symbol."""
    out: dict[str, float] = {}
    if equity <= 0:
        return out
    for p in open_book or []:
        sym = p.get("symbol")
        if not sym:
            continue
        sign = -1.0 if (p.get("direction") or "LONG") == "SHORT" else 1.0
        out[sym] = out.get(sym, 0.0) + sign * float(p.get("cost_usd") or 0) / equity
    return out


def check_correlation_limit(
    *,
    symbol: str,
    alloc_usd: float,
    equity_usd: float,
    open_book: list[dict],
    closes_loader: ClosesLoader | None = None,
) -> CorrelationCheck:
    """Correlation (and optional beta) gate for one LONG candidate.

    Never raises and never blocks on missing data.
    """
    if not settings.brain_correlation_check_enabled:
        return CorrelationCheck(None, {"status": "disabled"})

    weights = _book_weights(open_book, equity_usd)
    longs = [s for s, w in weights.items() if w > 0 and s != symbol]
    beta_cap = float(settings.brain_max_portfolio_beta or 0)
    if not longs and beta_cap <= 0:
        return CorrelationCheck(None, {"status": "skipped", "why": "no_open_positions"})

    loader = closes_loader or _load_closes
    wanted = [symbol] + sorted(weights) + ([BENCHMARK] if beta_cap > 0 else [])
    try:
        closes = loader(list(dict.fromkeys(wanted)))
        rets = returns_frame(closes)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"Correlation check for {symbol} skipped: history load failed ({e})")
        return CorrelationCheck(None, {"status": "skipped", "why": "history_error"})

    min_obs = settings.brain_corr_min_obs
    if symbol not in rets or rets[symbol].count() < min_obs:
        logger.info(f"Correlation check for {symbol} skipped: insufficient candidate history")
        return CorrelationCheck(None, {"status": "skipped", "why": "no_candidate_history"})

    corrs: dict[str, float] = {}
    no_data: list[str] = []
    for s in longs:
        c = pair_correlation(rets, symbol, s, min_obs)
        if c is None:
            no_data.append(s)
        else:
            corrs[s] = c

    blocked, details = evaluate_correlation_rule(corrs, {s: weights[s] for s in corrs})
    details.update({"status": "checked", "n_open_checked": len(corrs),
                    "lookback_days": settings.brain_corr_lookback_days})
    if no_data:
        details["no_data"] = sorted(no_data)
    if blocked:
        return CorrelationCheck("correlation_limit", details)

    if beta_cap > 0 and equity_usd > 0:
        post = dict(weights)
        post[symbol] = post.get(symbol, 0.0) + alloc_usd / equity_usd
        betas = symbol_betas(rets, list(post), BENCHMARK, min_obs)
        beta = portfolio_beta(post, betas)
        if beta is not None:
            details["post_trade_beta"] = round(beta, 3)
            details["beta_cap"] = beta_cap
            if beta > beta_cap:
                return CorrelationCheck("portfolio_beta_limit", details)
        else:
            details["post_trade_beta"] = None
    return CorrelationCheck(None, details)


# ============================================================
# REPORTING
# ============================================================

def _load_open_book() -> tuple[list[dict], float]:
    """Open brain positions + equity estimate (cash + collateral + cost)."""
    from app.db.supabase import get_client

    db = get_client()
    rows = (
        db.table("virtual_trades")
        .select("id, symbol, sector, direction, position_size_usd, is_wallet_trade, source")
        .eq("status", "OPEN").eq("source", "brain")
        .execute()
    ).data or []
    book = [{
        "symbol": r.get("symbol"), "sector": r.get("sector"),
        "direction": r.get("direction") or "LONG",
        "cost_usd": float(r.get("position_size_usd") or 0),
    } for r in rows if r.get("symbol")]
    equity = sum(p["cost_usd"] for p in book if p["direction"] != "SHORT")
    try:
        from app.services import wallet as wallet_svc

        w = wallet_svc.get_wallet(None) or {}
        equity += float(w.get("balance") or 0) + float(w.get("collateral_reserved") or 0)
    except Exception as e:
        logger.debug(f"portfolio risk: wallet read failed ({e})")
    return book, equity


def get_portfolio_risk_metrics(
    open_book: list[dict] | None = None,
    equity_usd: float | None = None,
    closes_loader: ClosesLoader | None = None,
) -> dict:
    """Current portfolio risk summary for the daily snapshot / API.

    `open_book` items: {"symbol", "cost_usd", "direction"?}. When omitted,
    open brain positions and equity are read from the DB/wallet.
    """
    if open_book is None:
        open_book, eq = _load_open_book()
        equity_usd = equity_usd if equity_usd is not None else eq
    if not equity_usd or equity_usd <= 0:
        equity_usd = sum(float(p.get("cost_usd") or 0) for p in open_book) or 0.0

    weights = _book_weights(open_book, equity_usd) if equity_usd > 0 else {}
    out: dict = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "n_positions": len(weights),
        "equity_usd": round(equity_usd, 2),
        "gross_exposure": round(sum(abs(w) for w in weights.values()), 4),
        "lookback_days": settings.brain_corr_lookback_days,
        "beta": None, "vol_annual_pct": None,
        "avg_pairwise_corr": None, "max_pair": None, "n_pairs_above_threshold": 0,
        "largest_cluster": {"symbols": [], "weight": 0.0},
        "betas": {}, "missing": [],
    }
    if not weights:
        return out

    loader = closes_loader or _load_closes
    try:
        rets = returns_frame(loader(sorted(weights) + [BENCHMARK]))
    except Exception as e:
        logger.warning(f"portfolio risk metrics: history load failed ({e})")
        out["missing"] = sorted(weights)
        return out

    min_obs = settings.brain_corr_min_obs
    have = [s for s in weights if s in rets and rets[s].count() >= min_obs]
    out["missing"] = sorted(s for s in weights if s not in have)
    if not have:
        return out

    corr = rets[have].corr(min_periods=max(min_obs, 3))
    pairs = []
    for i, a in enumerate(have):
        for b in have[i + 1:]:
            c = _finite(corr.at[a, b])
            if c is not None:
                pairs.append((a, b, c))
    thr = settings.brain_corr_cluster_threshold
    if pairs:
        out["avg_pairwise_corr"] = round(sum(c for *_, c in pairs) / len(pairs), 3)
        a, b, c = max(pairs, key=lambda t: t[2])
        out["max_pair"] = {"a": a, "b": b, "corr": round(c, 3)}
        out["n_pairs_above_threshold"] = sum(1 for *_, c in pairs if c >= thr)
    cluster = largest_cluster(corr, thr)
    out["largest_cluster"] = {"symbols": cluster,
                              "weight": round(sum(weights[s] for s in cluster), 4)}

    hw = {s: weights[s] for s in have}
    betas = symbol_betas(rets, have, BENCHMARK, min_obs)
    out["betas"] = {s: round(b, 3) for s, b in betas.items()}
    beta = portfolio_beta(hw, betas)
    out["beta"] = round(beta, 3) if beta is not None else None
    vol = portfolio_volatility(rets, hw, min_obs)
    out["vol_annual_pct"] = round(vol * 100, 2) if vol is not None else None
    return out
