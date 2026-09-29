"""Read-only insight aggregations for the Today / Is-it-working / Signal pages.

Backs app/api/v1/insights.py. Shapes match front-end/src/types/insights.ts.

Principles:
  * Read only. Nothing here writes to the DB (the wallet row is selected
    directly, never through wallet.get_wallet, which lazy-creates).
  * Anything not stored (or not computable) is None — never invented.
  * Tolerant of missing migrations: brain_wallet.breaker_tripped_at (009),
    signals.routine_ai_signal / decision_overturned (008),
    candidate_outcomes (008), virtual_snapshots.brain_equity (006).
  * Outputs pass through `_clean` so NaN / inf never reach the JSON encoder.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from loguru import logger

from app.core.cache import TTLCache
from app.core.config import settings
from app.db import queries

ET = ZoneInfo("America/New_York")
BACKTEST_DIR = (Path(__file__).resolve().parents[2] / "docs" / "backtests").resolve()
MAX_REPORT_BYTES = 20 * 1024 * 1024
HORIZONS = (5, 10, 20)

# Benchmark closes (yfinance) — 1h cache on top of price_cache's own cache.
_bench_cache = TTLCache(max_size=20, default_ttl=3600)


# ============================================================
# Generic helpers
# ============================================================

def _clean(v: Any) -> Any:
    """Recursively replace NaN/inf with None; tuples/sets -> lists."""
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, Mapping):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_clean(x) for x in v]
    return v


def _num(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _int(v) -> int | None:
    f = _num(v)
    return int(f) if f is not None else None


def _parse_dt(v) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        dt = v
    else:
        try:
            dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = datetime.fromisoformat(str(v)[:10])
            except ValueError:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _et_date(v) -> date | None:
    dt = _parse_dt(v)
    return dt.astimezone(ET).date() if dt else None


def _fmt_num(v, nd: int = 2) -> str:
    f = _num(v)
    if f is None:
        return "?"
    s = f"{f:.{nd}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _fmt_money(v) -> str:
    f = _num(v)
    if f is None:
        return "?"
    if abs(f) >= 1e9:
        return f"${f / 1e9:.1f}B"
    if abs(f) >= 1e6:
        return f"${f / 1e6:.1f}M"
    return f"${f:,.0f}"


def _humanize(s: str) -> str:
    return s.replace("_", " ").strip()


def _is_crypto(symbol: str | None, sig: Mapping | None = None) -> bool:
    sig = sig or {}
    fd = sig.get("fundamental_data") or {}
    return (
        (sig.get("asset_type") or "").upper() == "CRYPTO"
        or (fd.get("quote_type") or "").upper() == "CRYPTOCURRENCY"
        or (symbol or "").upper().endswith("-USD")
    )


def _tech_price(t: Mapping) -> float | None:
    return _num(t.get("last_close")) or _num(t.get("current_price"))


# ============================================================
# Reason mapping (pure)
# ============================================================

_AI_STATUSES = ("low_confidence", "rejected", "skipped", "failed", "validated")


def _reason(code: str, params: dict, text: str, raw: str | None) -> dict:
    return {"code": code, "params": params, "text": text, "raw": raw}


def _tech_filter_reason(sub: str, sig: Mapping, raw: str | None) -> dict:
    t = (sig or {}).get("technical_data") or {}
    price = _tech_price(t)
    sma50, sma200, rsi = _num(t.get("sma_50")), _num(t.get("sma_200")), _num(t.get("rsi"))
    value = limit = None
    if sub == "overextended_vs_sma50":
        limit = settings.tech_filter_max_ext_sma50_pct
        if price and sma50:
            value = round((price / sma50 - 1) * 100, 1)
        text = (f"Filter: {_fmt_num(value, 1)}% above 50-day average (max {_fmt_num(limit, 0)}%)"
                if value is not None else f"Filter: too far above 50-day average (max {_fmt_num(limit, 0)}%)")
    elif sub == "rsi_overbought":
        limit = settings.tech_filter_max_rsi
        value = round(rsi, 1) if rsi is not None else None
        text = (f"Filter: RSI {_fmt_num(value, 0)} (max {_fmt_num(limit, 0)})"
                if value is not None else f"Filter: RSI above {_fmt_num(limit, 0)}")
    elif sub == "below_sma200":
        text = "Filter: price below 200-day average"
    elif sub == "sma50_below_sma200":
        text = "Filter: 50-day average below 200-day average"
    elif sub in ("low_liquidity", "no_liquidity_data"):
        crypto = _is_crypto((sig or {}).get("symbol"), sig)
        limit = (settings.tech_filter_min_dollar_volume_crypto if crypto
                 else settings.tech_filter_min_dollar_volume)
        dv = _num(t.get("dollar_volume_avg_20"))
        if dv is None and price:
            vol = _num(t.get("volume_avg_20")) or _num(t.get("volume_avg"))
            dv = (vol if crypto else vol * price) if vol is not None else None
        value = round(dv, 0) if dv is not None else None
        text = ("Filter: no volume data" if sub == "no_liquidity_data"
                else f"Filter: low liquidity ({_fmt_money(value)}/day, min {_fmt_money(limit)})"
                if value is not None else f"Filter: low liquidity (min {_fmt_money(limit)}/day)")
    elif sub == "insufficient_history":
        text = "Filter: not enough price history"
    elif sub == "active_blocker":
        text = "Filter: an active blocker (e.g. cited red flag)"
    else:
        text = f"Filter: {_humanize(sub) or 'failed'}"
    return _reason("technical_filter", {"check": sub or None, "value": value, "limit": limit}, text, raw)


def describe_reason(raw_reason: str | None, details: Mapping | None = None,
                    signal: Mapping | None = None, decision: str | None = None) -> dict:
    """Map a brain_decisions reason (+ details, + signal row) to
    {"code", "params", "text", "raw"}.

    `code` is stable and translated by the UI; `text` is an English fallback
    carrying the numbers. Unknown formats map to code "other".
    """
    d = dict(details or {})
    s = dict(signal or {})
    raw = (raw_reason or "").strip() or None
    r = raw or ""
    rl = r.lower()

    # ── entered ──
    if decision == "ENTER" or (decision is None and rl.startswith("ai_buy")):
        risk_pct = settings.brain_risk_per_trade_pct
        size, risk = _num(d.get("alloc_usd")), _num(d.get("risk_usd"))
        text = "Passed every check"
        if size is not None:
            text += f" · size {_fmt_money(size)} ({_fmt_num(risk_pct, 1)}% risk)"
        return _reason("entered", {"size_usd": size, "risk_usd": risk, "risk_pct": risk_pct}, text, raw)

    if rl.startswith("short:"):
        return _reason("other", {"raw": _humanize(r)}, f"Short entry skipped: {_humanize(r[6:])}", raw)

    # ── Codex veto (veto mode): the decision model said BUY, Codex overruled ──
    g = s.get("grok_data") if isinstance(s.get("grok_data"), Mapping) else {}
    cx = g.get("_codex") if isinstance(g, Mapping) else None
    if isinstance(cx, Mapping) and cx.get("vetoed") and (not rl or rl.startswith("not_ai_buy")):
        csig, cconf = cx.get("signal"), _num(cx.get("confidence"))
        return _reason("codex_veto", {"signal": csig, "confidence": cconf},
                       f"Codex review vetoed the BUY ({csig or '?'}, confidence {_fmt_num(cconf, 0)})", raw)

    # ── decision model veto takes precedence over "AI said no" ──
    if s.get("decision_overturned") is True and (not rl or rl.startswith("not_ai_buy") or rl == "ai_failed"):
        sig = s.get("ai_signal")
        return _reason("decision_veto", {"decision_signal": sig},
                       f"Decision model vetoed the BUY ({sig or 'no BUY'})", raw)

    if rl.startswith("not_ai_buy"):
        rest = r[len("not_ai_buy"):].lstrip("_")
        status, sig = None, None
        for st in _AI_STATUSES:
            if rest.lower().startswith(st):
                status = st
                sig = rest[len(st):].lstrip("_") or None
                break
        if sig in ("None", "none", "null"):
            sig = None
        if status == "skipped" or (status is None and not rest):
            return _reason("ai_not_called", {}, "AI not called (technical filter or not selected)", raw)
        if status == "failed":
            return _reason("ai_failed", {}, "AI analysis failed", raw)
        if status == "low_confidence":
            conf = _num(s.get("confidence")) if s.get("confidence") is not None else _num(d.get("confidence"))
            mn = settings.ai_validated_min_confidence
            txt = (f"AI BUY at confidence {_fmt_num(conf, 0)} (min {mn})" if conf is not None
                   else f"AI BUY below confidence {mn}")
            return _reason("ai_low_confidence", {"confidence": conf, "min": mn}, txt, raw)
        sig = sig or s.get("ai_signal")
        return _reason("ai_rejected", {"signal": sig}, f"AI said {sig or 'not BUY'}", raw)

    if rl == "ai_failed":
        return _reason("ai_failed", {}, "AI analysis failed", raw)

    # ── correlation / beta ──
    if rl.startswith("correlation"):
        c = d.get("correlation") or {}
        rule = c.get("rule")
        corr, sym = _num(c.get("max_corr")), c.get("max_corr_symbol")
        limit = _num(c.get("max_pairwise"))
        if limit is None:
            limit = settings.brain_corr_max_pairwise
        thr = _num(c.get("cluster_threshold"))
        if thr is None:
            thr = settings.brain_corr_cluster_threshold
        cluster = ", ".join(c.get("cluster_symbols") or []) or None
        if rule == "correlated_cluster":
            text = f"Correlated ≥ {_fmt_num(thr)} with {len(c.get('cluster_symbols') or [])} holdings ({cluster})"
        elif corr is not None and sym:
            text = f"Correlated {_fmt_num(corr)} with {sym} (limit {_fmt_num(limit)})"
        else:
            text = f"Too correlated with current holdings (limit {_fmt_num(limit)})"
        return _reason("correlation_limit", {"corr": corr, "symbol": sym, "limit": limit, "rule": rule,
                                             "cluster": cluster, "threshold": thr}, text, raw)
    if rl.startswith("portfolio_beta"):
        c = d.get("correlation") or {}
        beta = _num(c.get("post_trade_beta"))
        limit = _num(getattr(settings, "brain_max_portfolio_beta", None))
        return _reason("portfolio_beta_limit", {"beta": beta, "limit": limit},
                       f"Portfolio beta would be {_fmt_num(beta)} (limit {_fmt_num(limit)})", raw)

    # ── reward / risk ──
    if rl.startswith("rr_below_min"):
        m = re.search(r"(-?\d+(?:\.\d+)?)\s*$", r)
        rr = _num(m.group(1)) if m else _num(d.get("rr"))
        mn = settings.brain_min_rr
        return _reason("rr_below_min", {"rr": rr, "min": mn},
                       (f"Reward/risk {rr:.1f} below {mn:.1f}" if rr is not None else f"Reward/risk below {mn:.1f}"), raw)

    # ── earnings blackout ──
    if "earnings" in rl and "blackout" in rl:
        fd = s.get("fundamental_data") or {}
        text_src = f"{r} {s.get('reasoning') or ''}"
        m = re.search(r"(\d+)\s*trading day", text_src)
        days = _int(m.group(1)) if m else _int(fd.get("trading_days_to_next_earnings"))
        ml = re.search(r"limit\s*(\d+)", text_src)
        limit = _int(ml.group(1)) if ml else _int(getattr(settings, "earnings_blackout_trading_days", None))
        text = (f"Earnings in {days} trading days (blackout {limit})" if days is not None
                else f"Earnings blackout ({limit} trading days)")
        return _reason("earnings_blackout", {"days": days, "limit": limit}, text, raw)

    # ── technical filter ──
    if rl.startswith("technical_filter") or rl.startswith("tech_filter"):
        sub = r.split(":", 1)[1].strip() if ":" in r else ""
        if not sub:
            reasons = ((d.get("tech_filter") or {}).get("reasons")
                       or (((s.get("technical_data") or {}).get("_tech_filter") or {}).get("reasons")) or [])
            sub = reasons[0] if reasons else ""
        return _tech_filter_reason(sub, s, raw)

    # ── drawdown breaker ──
    if rl.startswith("drawdown_breaker") or rl.startswith("drawdown"):
        b = d.get("breaker") or {}
        days = _int(b.get("days_remaining"))
        text = ("Drawdown breaker pause" + (f" ({days} trading days left)" if days is not None else ""))
        return _reason("drawdown_breaker_pause", {"days_remaining": days}, text, raw)

    # ── portfolio limits ──
    if rl.startswith("max_open"):
        m = re.search(r"(\d+)\s*$", r)
        mx = _int(m.group(1)) if m else settings.brain_max_open_positions
        return _reason("max_open_positions", {"max": mx}, f"Already {mx} positions open (max {mx})", raw)
    if rl.startswith("sector_cap"):
        sector = r[len("sector_cap"):].lstrip("_") or d.get("sector") or ""
        sector_h = _humanize(sector).title() if sector else None
        mx = settings.brain_max_per_sector
        return _reason("sector_cap", {"sector": sector_h, "max": mx},
                       f"Sector limit reached: {sector_h or 'this sector'} (max {mx})", raw)
    if rl.startswith("crypto_cap"):
        mx = settings.brain_max_crypto_pct
        return _reason("crypto_cap", {"max": mx}, f"Crypto limit reached ({_fmt_num(mx, 0)}% of equity)", raw)
    if "cooldown" in rl:
        m = re.search(r"(\d+)\s*d\b", r)
        days = _int(m.group(1)) if m else settings.brain_reentry_cooldown_days
        return _reason("reentry_cooldown", {"days": days},
                       f"Re-entry cooldown ({days} trading days after the last exit)", raw)
    if rl == "already_held":
        return _reason("already_held", {}, "Already held", raw)
    if rl == "market_closed":
        return _reason("market_closed", {}, "Market closed", raw)
    if rl.startswith("action_sell"):
        return _reason("action_sell", {}, "Signal is SELL", raw)
    if rl.startswith("action_avoid"):
        return _reason("action_avoid", {}, "Signal is AVOID", raw)
    if rl == "size_below_minimum":
        return _reason("size_below_minimum", {}, "Position size below the minimum", raw)
    if rl.startswith("fx_unavailable"):
        cur = r[len("fx_unavailable"):].lstrip("_") or None
        return _reason("fx_unavailable", {"currency": cur}, f"No FX rate for {cur or 'currency'}", raw)
    if rl == "no_price":
        return _reason("no_price", {}, "No price at signal time", raw)

    if not raw:
        return _reason("other", {"raw": None}, "No decision recorded", raw)
    return _reason("other", {"raw": _humanize(r)}, _humanize(r).capitalize(), raw)


# ============================================================
# Wallet / equity (read only)
# ============================================================

def _wallet() -> dict | None:
    try:
        return queries.get_brain_wallet_readonly(queries.get_brain_user_id())
    except Exception as e:
        logger.debug(f"insights: wallet read failed ({e})")
        return None


def _latest_prices(symbols: list[str]) -> dict[str, float | None]:
    """Current prices via price_cache (cache first, one batched fetch for misses)."""
    out: dict[str, float | None] = {}
    if not symbols:
        return out
    try:
        from app.services import price_cache

        missing = []
        for sym in dict.fromkeys(symbols):
            hit, price, _ = price_cache._get_cached(sym)
            if hit:
                out[sym] = price
            else:
                missing.append(sym)
        if missing:
            for sym, (price, _chg) in price_cache._fetch_prices_batch(missing).items():
                out[sym] = price
    except Exception as e:
        logger.debug(f"insights: price fetch failed ({e})")
    return out


def _position_value_usd(trade: Mapping, price: float | None) -> float:
    """USD value: cost basis scaled by native price move (FX move ignored)."""
    cost = _num(trade.get("position_size_usd")) or 0.0
    entry = _num(trade.get("entry_price"))
    if price and entry and entry > 0 and cost:
        if (trade.get("direction") or "LONG") == "SHORT":
            return cost * (2 - price / entry)
        return cost * price / entry
    return cost


def _net_deposits(w: Mapping | None) -> float | None:
    if not w:
        return None
    dep = _num(w.get("total_deposited"))
    if dep is None:
        return None
    return dep - (_num(w.get("total_withdrawn")) or 0.0)


def _snapshot_equity(snaps: list[dict]) -> float | None:
    for s in reversed(snaps or []):
        v = _num(s.get("brain_equity"))
        if v is not None:
            return v
    return None


def _breaker(equity: float | None, peak: float | None, tripped_at) -> dict:
    limit = settings.brain_max_drawdown_pct
    pause = int(getattr(settings, "brain_drawdown_pause_trading_days", 10) or 10)
    state, days_remaining = ("paused" if tripped_at else "normal"), None
    if equity is not None and peak:
        try:
            from app.services import virtual_portfolio as vp

            fn = getattr(vp, "evaluate_drawdown_breaker", None)
            if fn is not None:
                st = fn(equity, peak, tripped_at, datetime.now(timezone.utc))
                state = "paused" if getattr(st, "blocked", False) else "normal"
                days_remaining = getattr(st, "days_remaining", None)
        except Exception as e:
            logger.debug(f"insights: breaker evaluation failed ({e})")
    if state == "normal":
        days_remaining = None
    return {"state": state, "days_remaining": days_remaining,
            "tripped_at": str(tripped_at) if tripped_at else None,
            "limit_pct": limit, "pause_days": pause}


def build_status(wallet: Mapping | None, open_trades: list[dict], prices: Mapping[str, float | None],
                 snapshots: list[dict], ai_spend: dict | None) -> dict:
    """Status strip. Pure given its inputs."""
    invested = sum(_num(t.get("position_size_usd")) or 0.0 for t in open_trades)
    equity = None
    if wallet:
        equity = ((_num(wallet.get("balance")) or 0.0) + (_num(wallet.get("collateral_reserved")) or 0.0)
                  + sum(_position_value_usd(t, prices.get(t.get("symbol"))) for t in open_trades))
    if equity is None:
        equity = _snapshot_equity(snapshots)
    baseline = _net_deposits(wallet)
    change_pct = ((equity / baseline - 1) * 100) if equity is not None and baseline else None

    reset_at = (wallet or {}).get("created_at")
    spy = [(_num(s.get("spy_price"))) for s in snapshots if _num(s.get("spy_price"))]
    spy_change = ((spy[-1] / spy[0] - 1) * 100) if len(spy) >= 2 else None

    peak = _num((wallet or {}).get("peak_equity")) or None
    peak_eff = max(peak or (baseline or 0.0), equity or 0.0) or None
    drawdown = ((equity / peak_eff - 1) * 100) if equity is not None and peak_eff else None

    return {
        "equity": round(equity, 2) if equity is not None else None,
        "reset_at": reset_at,
        "baseline": round(baseline, 2) if baseline is not None else None,
        "change_pct": round(change_pct, 3) if change_pct is not None else None,
        "spy_change_pct": round(spy_change, 3) if spy_change is not None else None,
        "open_positions": len(open_trades),
        "max_positions": settings.brain_max_open_positions,
        "invested_usd": round(invested, 2),
        "invested_pct": round(invested / equity * 100, 1) if equity else None,
        "peak_equity": round(peak_eff, 2) if peak_eff else None,
        "drawdown_pct": round(min(drawdown, 0.0), 2) if drawdown is not None else None,
        "breaker": _breaker(equity, peak_eff, (wallet or {}).get("breaker_tripped_at")),
        "ai_spend": ai_spend,
    }


def ai_spend_from_summary(summary: Mapping | None) -> dict | None:
    if not summary:
        return None
    providers = summary.get("providers") or {}
    budget = sum(_num(p.get("monthly_limit_usd")) or 0.0 for p in providers.values()
                 if not p.get("is_free_tier"))
    return {"month_usd": round(_num(summary.get("total_monthly_spend_usd")) or 0.0, 2),
            "budget_usd": round(budget, 2)}


# ============================================================
# Today: funnel + decisions + positions
# ============================================================

def _routine_signal(sig: Mapping) -> str | None:
    if "routine_ai_signal" in sig:
        return sig.get("routine_ai_signal")
    return sig.get("ai_signal")


def build_funnel(scan: Mapping | None, signals: list[dict], decisions: list[dict]) -> dict:
    """Scan funnel counts. `candidates` = signals persisted by the scan."""
    has_filter = any(isinstance((s.get("technical_data") or {}).get("_tech_filter"), dict) for s in signals)
    return {
        "universe": _int((scan or {}).get("tickers_scanned")),
        "candidates": len(signals),
        "passed_filter": (sum(1 for s in signals
                              if ((s.get("technical_data") or {}).get("_tech_filter") or {}).get("passed") is True)
                          if has_filter else None),
        "ai_checked": sum(1 for s in signals if s.get("ai_status") not in (None, "skipped")),
        "routine_buy": sum(1 for s in signals if str(_routine_signal(s) or "").upper() == "BUY"),
        "decision_confirmed": sum(1 for s in signals if s.get("decision_overturned") is False),
        "bought": len({d.get("symbol") for d in decisions if d.get("decision") == "ENTER"}),
    }


def _decision_by_symbol(decisions: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for d in decisions:
        sym = d.get("symbol")
        if not sym:
            continue
        if sym not in out or d.get("decision") == "ENTER":
            out[sym] = d
    return out


def _model_signals(sig: Mapping) -> tuple[str | None, str | None]:
    """(routine, decision) signals for the decisions list."""
    overturned = sig.get("decision_overturned")
    if overturned is not None:
        return _routine_signal(sig), sig.get("ai_signal")
    if sig.get("ai_status") in (None, "skipped"):
        return None, None
    return sig.get("ai_signal"), None


def build_decisions(signals: list[dict], decisions: list[dict]) -> list[dict]:
    by_sym = _decision_by_symbol(decisions)
    seen: set[str] = set()
    rows = []
    for sig in signals:
        sym = sig.get("symbol")
        if not sym or sym in seen:
            continue
        seen.add(sym)
        dec = by_sym.get(sym)
        det = (dec or {}).get("details") or {}
        routine, decision_sig = _model_signals(sig)
        rr = _num(det.get("rr"))
        if rr is None:
            rr = _num(sig.get("risk_reward"))
        rows.append({
            "symbol": sym,
            "bucket": sig.get("bucket"),
            "decision": (dec or {}).get("decision"),
            "reason": (describe_reason(dec.get("reason"), det, sig, dec.get("decision")) if dec else None),
            "action": sig.get("action"),
            "ai_status": sig.get("ai_status"),
            "routine_signal": routine,
            "decision_signal": decision_sig,
            "decision_overturned": sig.get("decision_overturned"),
            "p_win": _num(sig.get("p_win")),
            "rr": rr,
            "score": _int(sig.get("score")),
        })

    def key(r):
        entered = r["decision"] == "ENTER"
        checked = r["ai_status"] not in (None, "skipped")
        return (0 if entered else 1 if checked else 2, -(r["p_win"] or -1), -(r["score"] or 0))
    rows.sort(key=key)
    return rows


def build_positions(open_trades: list[dict], prices: Mapping[str, float | None],
                    now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    out = []
    for t in open_trades:
        sym = t.get("symbol")
        entry, stop, target = _num(t.get("entry_price")), _num(t.get("stop_loss")), _num(t.get("target_price"))
        price = _num(prices.get(sym))
        short = (t.get("direction") or "LONG") == "SHORT"
        pnl = None
        if price and entry:
            pnl = ((entry - price) if short else (price - entry)) / entry * 100
        progress = None
        if price is not None and stop is not None and target is not None and target != stop:
            progress = min(1.0, max(0.0, (price - stop) / (target - stop)))
        ed = _parse_dt(t.get("entry_date"))
        out.append({
            "id": str(t.get("id")),
            "symbol": sym,
            "entry_price": entry,
            "current_price": price,
            "pnl_pct": round(pnl, 2) if pnl is not None else None,
            "stop": stop,
            "target": target,
            "progress": round(progress, 3) if progress is not None else None,
            "days_held": (now - ed).days if ed else None,
            "entry_date": t.get("entry_date"),
            "currency": t.get("currency"),
        })
    return out


def map_risk(m: Mapping | None) -> dict | None:
    if not m:
        return None
    mp = m.get("max_pair")
    lc = m.get("largest_cluster") or None
    return {
        "n_positions": _int(m.get("n_positions")) or 0,
        "beta": _num(m.get("beta")),
        "vol_annual_pct": _num(m.get("vol_annual_pct")),
        "avg_pairwise_corr": _num(m.get("avg_pairwise_corr")),
        "max_pair": ({"a": mp.get("a"), "b": mp.get("b"), "corr": _num(mp.get("corr"))} if mp else None),
        "largest_cluster": ({"symbols": list(lc.get("symbols") or []), "weight": _num(lc.get("weight")) or 0.0}
                            if lc else None),
    }


def risk_limits() -> dict:
    return {
        "corr_max_pairwise": settings.brain_corr_max_pairwise,
        "corr_cluster_threshold": settings.brain_corr_cluster_threshold,
        "corr_cluster_max": settings.brain_corr_cluster_max,
        "max_drawdown_pct": settings.brain_max_drawdown_pct,
        "min_rr": settings.brain_min_rr,
        "risk_per_trade_pct": settings.brain_risk_per_trade_pct,
    }


def _safe(fn, default, what: str):
    try:
        return fn()
    except Exception as e:
        logger.warning(f"insights: {what} failed ({e})")
        return default


STALE_SCAN_MINUTES = 30


def newest_scan() -> dict | None:
    """The most recent scan of any status (None on failure)."""
    rows = _safe(lambda: queries.get_scans(limit=1), [], "newest scan")
    return rows[0] if rows else None


def running_scan_ref(scan: Mapping | None) -> dict | None:
    """Progress of a scan still in flight, else None."""
    if not scan or str(scan.get("status") or "").upper() not in ("RUNNING", "QUEUED", "PENDING"):
        return None
    started = _parse_dt(scan.get("started_at"))
    if started and (datetime.now(timezone.utc) - started) > timedelta(minutes=STALE_SCAN_MINUTES):
        return None  # a crashed scan left RUNNING; don't show a banner forever
    return {
        "id": str(scan.get("id")),
        "type": scan.get("scan_type"),
        "started_at": scan.get("started_at"),
        "progress_pct": _int(scan.get("progress_pct")),
        "phase": scan.get("phase"),
    }


def get_today(ai_spend: dict | None = None) -> dict:
    wallet = _wallet()
    reset_date = _et_date((wallet or {}).get("created_at"))
    open_trades = _safe(queries.get_open_brain_trades, [], "open trades")
    snapshots = _safe(lambda: queries.get_virtual_snapshots_since(reset_date.isoformat() if reset_date else None),
                      [], "snapshots")
    prices = _latest_prices([t.get("symbol") for t in open_trades if t.get("symbol")])

    scan = _safe(queries.get_latest_insight_scan, None, "latest scan")
    signals, decisions = [], []
    if scan and scan.get("id"):
        signals = _safe(lambda: queries.get_signals_for_scan(scan["id"]), [], "scan signals")
        decisions = _safe(lambda: queries.get_brain_decisions(scan_id=scan["id"], limit=1000), [], "decisions")

    def _risk():
        from app.services.portfolio_risk import get_portfolio_risk_metrics
        return map_risk(get_portfolio_risk_metrics())

    return _clean({
        "as_of": datetime.now(timezone.utc).isoformat(),
        "status": build_status(wallet, open_trades, prices, snapshots, ai_spend),
        "scan": ({"id": str(scan["id"]), "type": scan.get("scan_type"), "status": scan.get("status"),
                  "started_at": scan.get("started_at"), "completed_at": scan.get("completed_at")}
                 if scan and scan.get("id") else None),
        "funnel": build_funnel(scan, signals, decisions) if scan else None,
        "decisions": build_decisions(signals, decisions),
        # False = the scan predates the brain_decisions log (or the brain never
        # ran for it), so rows without a decision are "no log", not "skipped".
        "decisions_logged": bool(decisions),
        "positions": build_positions(open_trades, prices),
        "risk": _safe(_risk, None, "portfolio risk") if open_trades else None,
        "limits": risk_limits(),
    })


# ============================================================
# Performance ("Is it working?")
# ============================================================

def _summary(stat: Mapping) -> dict:
    ci = stat.get("ci")
    return {
        "n": int(stat.get("n") or 0),
        "mean": _num(stat.get("mean")),
        "ci": list(ci) if ci else None,
        "sufficient": bool(stat.get("sufficient")),
        "excludes_zero": stat.get("excludes_zero"),
    }


def verdict_from_summary(stat: Mapping, threshold: int) -> str:
    n = int(stat.get("n") or 0)
    if n < threshold:
        return "insufficient"
    ez = stat.get("excludes_zero")
    return "positive" if ez == "pos" else "negative" if ez == "neg" else "inconclusive"


def _normalize_gate_verdict(v: str | None) -> str:
    v = (v or "").lower()
    if v.startswith("insufficient"):
        return "insufficient"
    return v if v in ("costing", "protective", "inconclusive") else "insufficient"


def _pct_series(values: list[float | None]) -> list[float | None]:
    base = next((v for v in values if v), None)
    if not base:
        return [None for _ in values]
    return [round((v / base - 1) * 100, 3) if v is not None else None for v in values]


def _bench_closes(symbol: str):
    key = f"bench:{symbol}"
    cached = _bench_cache.get(key)
    if cached is not None:
        return cached if cached is not False else None
    try:
        from app.services.price_cache import fetch_daily_closes

        s = fetch_daily_closes([symbol], period="2y").get(symbol)
    except Exception as e:
        logger.debug(f"insights: benchmark {symbol} fetch failed ({e})")
        s = None
    _bench_cache.set(key, s if s is not None else False)
    return s


def _aligned(series, dates: list[str]) -> list[float | None]:
    if series is None:
        return [None] * len(dates)
    out = []
    try:
        import pandas as pd

        for d in dates:
            sub = series[series.index <= pd.Timestamp(d)]
            out.append(float(sub.iloc[-1]) if len(sub) else None)
    except Exception as e:
        logger.debug(f"insights: benchmark alignment failed ({e})")
        return [None] * len(dates)
    return out


def build_equity_curve(snapshots: list[dict], spy_series=None, xiu_series=None) -> dict:
    snaps = [s for s in snapshots if s.get("snapshot_date")]
    dates = [str(s["snapshot_date"])[:10] for s in snaps]
    signa = _pct_series([_num(s.get("brain_equity")) for s in snaps])
    spy_raw = [_num(s.get("spy_price")) for s in snaps]
    if sum(1 for v in spy_raw if v) < 2 and spy_series is not None:
        spy_raw = _aligned(spy_series, dates)
    spy = _pct_series(spy_raw)
    xiu = _pct_series(_aligned(xiu_series, dates)) if xiu_series is not None else [None] * len(dates)
    points = [{"date": d, "signa": a, "spy": b, "xiu": c} for d, a, b, c in zip(dates, signa, spy, xiu)]

    def last(vals):
        return next((v for v in reversed(vals) if v is not None), None)
    return {"points": points, "signa_pct": last(signa), "spy_pct": last(spy), "xiu_pct": last(xiu)}


def codex_agreement(rows: list[dict], codex_by_signal: Mapping[str, Mapping] | None,
                    horizon: int, min_n: int) -> dict:
    """Decision-model BUYs that Codex reviewed: Codex agreed (BUY) vs
    disagreed (HOLD/AVOID/SELL) -> forward excess returns. Errored reviews
    are left out. diff = agree − disagree, only when both n >= min_n."""
    from app.services.daily_learning.outcomes import _values, diff_ci, summarize

    field = f"excess_ret_{horizon}d"
    agree, disagree = [], []
    for r in rows:
        cx = (codex_by_signal or {}).get(str(r.get("signal_id")))
        if not isinstance(cx, Mapping) or cx.get("error") or not cx.get("signal"):
            continue
        (agree if str(cx.get("signal")).upper() == "BUY" else disagree).append(r)
    a_vals, d_vals = _values(agree, field), _values(disagree, field)
    a, d = summarize(a_vals, min_n=min_n), summarize(d_vals, min_n=min_n)
    out = {"reviewed": len(agree) + len(disagree), "agree": _summary(a), "disagree": _summary(d),
           "diff": None, "diff_ci": None, "direction": None}
    if a["n"] >= min_n and d["n"] >= min_n:
        out["diff"] = a["mean"] - d["mean"]
        lo, hi = diff_ci(a_vals, d_vals)
        out["diff_ci"] = [lo, hi]
        out["direction"] = "codex_helps" if lo > 0 else "codex_costs" if hi < 0 else None
    return out


def build_performance(rows: list[dict], snapshots: list[dict], closed_trades: int,
                      spy_series=None, xiu_series=None,
                      codex_by_signal: Mapping[str, Mapping] | None = None) -> dict:
    """Pure assembly of the /insights/performance payload."""
    from app.services.daily_learning.outcomes import (
        _values, calibration_table, overturn_stats, skip_reason_effectiveness, summarize,
    )
    from app.services.daily_learning.stats import MIN_OBSERVATIONS

    h = 10
    field = f"excess_ret_{h}d"
    entered = [r for r in rows if r.get("brain_decision") == "ENTER"]
    v_stat = summarize(_values(entered, field))
    cohorts_def = [
        ("entered", entered),
        ("vetoed", [r for r in rows if r.get("decision_overturned") is True]),
        ("rejected", [r for r in rows if r.get("ai_status") == "rejected" and r.get("decision_overturned") is not True]),
        ("ai_not_called", [r for r in rows if r.get("ai_status") == "skipped"]),
    ]
    cal = calibration_table(rows, 5)
    overall = cal.get("overall") or {}
    ov = ((overturn_stats(rows, h).get("metrics") or {}).get("excess_ret") or {})
    skips = skip_reason_effectiveness(rows, h)

    return _clean({
        "as_of": datetime.now(timezone.utc).isoformat(),
        "threshold": MIN_OBSERVATIONS,
        "horizon": h,
        "verdict": {
            "state": verdict_from_summary(v_stat, MIN_OBSERVATIONS),
            "n": int(v_stat.get("n") or 0),
            "needed": MIN_OBSERVATIONS,
            "mean": _num(v_stat.get("mean")),
            "ci": list(v_stat["ci"]) if v_stat.get("ci") else None,
        },
        "counts": {
            "tracked": len(rows),
            "filled": sum(1 for r in rows if _num(r.get(field)) is not None),
            "validated_buys": int(v_stat.get("n") or 0),
            "closed_trades": closed_trades,
        },
        "equity_curve": build_equity_curve(snapshots, spy_series, xiu_series),
        "cohorts": [{"key": k, **_summary(summarize(_values(g, field)))} for k, g in cohorts_def],
        "calibration": {
            "horizon": cal.get("horizon", 5),
            "n": cal.get("n", 0),
            "buckets": [{"bucket": b["bucket"], "n": b["n"], "mean_p_win": b["mean_p_win"],
                         "win_rate": b["win_rate"], "win_ci": list(b["win_ci"]) if b.get("win_ci") else None}
                        for b in cal.get("buckets") or []],
            "hidden_buckets": cal.get("hidden_buckets", 0),
            "brier": _num(overall.get("brier")),
            "brier_base_rate": _num(overall.get("brier_base_rate")),
        },
        "overturn": {
            "confirmed": _summary(ov.get("confirmed") or {}),
            "vetoed": _summary(ov.get("vetoed") or {}),
            "diff": _num(ov.get("diff")),
            "diff_ci": list(ov["diff_ci"]) if ov.get("diff_ci") else None,
            "direction": ov.get("direction"),
        },
        "skip_reasons": [{"reason": g["reason"], **_summary(g), "verdict": _normalize_gate_verdict(g.get("verdict"))}
                         for g in skips.get("gates") or []],
        "codex": codex_agreement(rows, codex_by_signal, h, MIN_OBSERVATIONS),
    })


def get_performance() -> dict:
    wallet = _wallet()
    reset_dt = _parse_dt((wallet or {}).get("created_at"))
    since = reset_dt or (datetime.now(timezone.utc) - timedelta(days=365))
    rows = _safe(lambda: queries.get_candidate_outcomes(since.isoformat()), [], "candidate outcomes")
    reset_date = _et_date(reset_dt) if reset_dt else None
    snapshots = _safe(lambda: queries.get_virtual_snapshots_since(reset_date.isoformat() if reset_date else None),
                      [], "snapshots")
    closed = _safe(lambda: queries.count_closed_brain_trades(reset_dt.isoformat() if reset_dt else None),
                   0, "closed trades")
    spy_series = None
    if sum(1 for s in snapshots if _num(s.get("spy_price"))) < 2 and snapshots:
        spy_series = _bench_closes("SPY")
    xiu_series = _bench_closes("XIU.TO") if snapshots else None
    # Codex only reviews decision-model BUYs (decision_overturned is False).
    reviewed_ids = [r.get("signal_id") for r in rows if r.get("decision_overturned") is False]
    codex = _safe(lambda: queries.get_signal_codex_verdicts(reviewed_ids), {}, "codex verdicts")
    return build_performance(rows, snapshots, closed, spy_series, xiu_series, codex)


# ============================================================
# Backtest reports (docs/backtests/*/report.json)
# ============================================================

def _band_row(name: str, m: Mapping) -> dict:
    return {
        "band": name,
        "trades": int(m.get("trades") or 0),
        "avg_excess_vs_spy_pct": _num(m.get("avg_excess_vs_spy_pct")),
        "win_rate_pct": _num(m.get("win_rate_pct")),
        "expectancy_pct": _num(m.get("expectancy_pct")),
    }


def _report_paths(base: Path | None = None) -> list[Path]:
    base = (base or BACKTEST_DIR).resolve()
    if not base.is_dir():
        return []
    out = []
    for p in sorted(base.glob("*/report.json")):
        try:
            rp = p.resolve()
            if not rp.is_relative_to(base) or not rp.is_file():
                continue
            if rp.stat().st_size > MAX_REPORT_BYTES:
                continue
            out.append(rp)
        except OSError:
            continue
    return out


def _load_report(p: Path) -> dict | None:
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError) as e:
        logger.debug(f"insights: backtest report {p.name} unreadable ({e})")
        return None


def parse_backtests(base: Path | None = None) -> dict:
    """Summaries of every report.json under BACKTEST_DIR (no user paths)."""
    base = (base or BACKTEST_DIR).resolve()
    reports = []
    for p in _report_paths(base):
        rep = _load_report(p)
        if rep is None:
            continue
        meta = rep.get("meta") or {}
        port = rep.get("portfolio") or {}
        eq = port.get("equity") or {}
        run = {
            "name": str(meta.get("name") or p.parent.name),
            "generated_at": meta.get("generated_at"),
            "start": meta.get("start"),
            "end": meta.get("end"),
            "entry_rule": meta.get("entry_rule"),
            "n_symbols": _int(meta.get("n_symbols")),
            "total_return_pct": _num(eq.get("total_return_pct")),
            "cagr_pct": _num(eq.get("cagr_pct")),
            "max_drawdown_pct": _num(eq.get("max_drawdown_pct")),
            "sharpe": _num(eq.get("sharpe")),
            "trades": int((port.get("trades") or {}).get("trades") or 0),
        }
        reports.append((run, rep))
    reports.sort(key=lambda x: str(x[0]["generated_at"] or ""), reverse=True)
    if not reports:
        return {"runs": [], "latest": None}

    run, rep = reports[0]
    study = rep.get("study") or {}
    benches = {}
    for k, v in (rep.get("benchmarks") or {}).items():
        benches[k] = ({"total_return_pct": _num(v.get("total_return_pct")), "cagr_pct": _num(v.get("cagr_pct")),
                       "max_drawdown_pct": _num(v.get("max_drawdown_pct"))}
                      if isinstance(v, Mapping) and v.get("available", True) else None)
    by_filter: list[dict] = []
    tf = study.get("by_tech_filter") or rep.get("by_tech_filter") or {}
    tfr = study.get("by_tech_filter_reason") or rep.get("by_tech_filter_reason") or {}
    for k, v in tf.items():
        if isinstance(v, Mapping):
            by_filter.append(_band_row(str(k), v))
    for k, v in tfr.items():
        if isinstance(v, Mapping):
            by_filter.append(_band_row(f"FAIL:{k}", v))
    latest = {
        "name": run["name"],
        "start": run["start"],
        "end": run["end"],
        "benchmarks": benches,
        "study_trades": _int(study.get("n_trades")),
        "by_band": [_band_row(str(k), v) for k, v in (study.get("by_band") or {}).items() if isinstance(v, Mapping)],
        "by_filter": by_filter or None,
        "caveats": [str(c).replace("**", "") for c in (rep.get("caveats") or [])],
    }
    return _clean({"runs": [r for r, _ in reports], "latest": latest})


# ============================================================
# Signal decision trail
# ============================================================

def tech_checks(technical_data: Mapping | None, signal: Mapping | None = None,
                filter_reasons: list[str] | None = None) -> list[dict]:
    t = technical_data or {}
    price = _tech_price(t)
    sma50, sma200, rsi = _num(t.get("sma_50")), _num(t.get("sma_200")), _num(t.get("rsi"))
    crypto = _is_crypto((signal or {}).get("symbol"), signal)
    floor = settings.tech_filter_min_dollar_volume_crypto if crypto else settings.tech_filter_min_dollar_volume
    dv = _num(t.get("dollar_volume_avg_20"))
    if dv is None and price:
        vol = _num(t.get("volume_avg_20")) or _num(t.get("volume_avg"))
        dv = (vol if crypto else vol * price) if vol is not None else None
    ext = (price / sma50 - 1) * 100 if price and sma50 else None
    checks = [
        {"key": "above_sma200", "ok": (price > sma200) if price and sma200 else None,
         "value": round((price / sma200 - 1) * 100, 1) if price and sma200 else None, "limit": 0.0},
        {"key": "sma50_above_sma200", "ok": (sma50 > sma200) if sma50 and sma200 else None,
         "value": round((sma50 / sma200 - 1) * 100, 1) if sma50 and sma200 else None, "limit": 0.0},
        {"key": "rsi", "ok": (rsi <= settings.tech_filter_max_rsi) if rsi is not None else None,
         "value": round(rsi, 1) if rsi is not None else None, "limit": settings.tech_filter_max_rsi},
        {"key": "extension_sma50", "ok": (ext <= settings.tech_filter_max_ext_sma50_pct) if ext is not None else None,
         "value": round(ext, 1) if ext is not None else None, "limit": settings.tech_filter_max_ext_sma50_pct},
        {"key": "liquidity", "ok": (dv >= floor) if dv is not None else None,
         "value": round(dv, 0) if dv is not None else None, "limit": floor},
        {"key": "blockers", "ok": ("active_blocker" not in filter_reasons) if filter_reasons is not None else None,
         "value": None, "limit": None},
    ]
    return checks


def _grok(g: Mapping | None) -> dict | None:
    if not g or not isinstance(g, Mapping):
        return None
    public = {k: v for k, v in g.items() if not str(k).startswith("_")}
    if not public:
        return None
    flags = []
    for f in g.get("red_flags") or []:
        if isinstance(f, Mapping):
            flags.append({"text": str(f.get("text") or f.get("flag") or ""), "url": f.get("url"),
                          "severity": f.get("severity"), "category": f.get("category")})
        elif f:
            flags.append({"text": str(f), "url": None, "severity": None, "category": None})
    cites = [c if isinstance(c, str) else (c or {}).get("url") for c in (g.get("citations") or [])]
    return {
        "summary": g.get("summary") or None,
        "score": _num(g.get("score")),
        "label": g.get("label"),
        "citations": [c for c in cites if isinstance(c, str) and c.startswith(("http://", "https://"))],
        "x_citation_count": _int(g.get("x_citation_count")),
        "red_flags": flags,
        "error": g.get("error"),
    }


def model_verdicts(sig: Mapping) -> tuple[dict | None, dict | None]:
    """(routine, decision_model) verdicts from what the signal row stores.

    When the decision model ran, the row's confidence/p_win/reasoning are the
    decision model's; the routine model only left its signal behind."""
    g = sig.get("grok_data") or {}
    dec_state = g.get("_decision") if isinstance(g, Mapping) else None
    overturned = sig.get("decision_overturned")
    own = {"signal": sig.get("ai_signal"), "confidence": _num(sig.get("confidence")),
           "p_win": _num(sig.get("p_win")), "reasoning": sig.get("reasoning") or None}
    cx = g.get("_codex") if isinstance(g, Mapping) else None
    if isinstance(cx, Mapping) and cx.get("vetoed"):
        own["signal"] = "BUY"  # the decision model said BUY; Codex vetoed it
    if dec_state == "unavailable":
        return own, {"signal": None, "confidence": None, "p_win": None, "reasoning": None, "status": "unavailable"}
    if dec_state == "confirmed" or overturned is not None:
        routine = {"signal": _routine_signal(sig) if "routine_ai_signal" in sig else None,
                   "confidence": None, "p_win": None, "reasoning": None}
        return routine, {**own, "status": "vetoed" if overturned else "confirmed"}
    if sig.get("ai_status") in (None, "skipped"):
        return None, None
    return own, None


def codex_verdict(g: Mapping | None) -> dict | None:
    """The stored Codex review (grok_data["_codex"]) for the trail, or None."""
    cx = g.get("_codex") if isinstance(g, Mapping) else None
    if not isinstance(cx, Mapping):
        return None
    return {
        "signal": cx.get("signal"),
        "confidence": _num(cx.get("confidence")),
        "p_win": _num(cx.get("p_win")),
        "reasoning": cx.get("reasoning") or None,
        "key_risks": [str(r) for r in (cx.get("key_risks") or []) if r][:5],
        "provider": cx.get("provider"),
        "mode": cx.get("mode"),
        "vetoed": bool(cx.get("vetoed")),
        "error": cx.get("error"),
    }


def _due_date(start: date, n: int, crypto: bool) -> date:
    if crypto:
        return start + timedelta(days=n)
    try:
        from app.core.market_calendar import is_us_trading_day

        d, k = start, 0
        while k < n:
            d += timedelta(days=1)
            if is_us_trading_day(d):
                k += 1
        return d
    except Exception:
        return start + timedelta(days=math.ceil(n * 7 / 5))


def build_outcomes(sig: Mapping, row: Mapping | None) -> dict:
    sd = _et_date((row or {}).get("signal_at") or sig.get("created_at"))
    crypto = _is_crypto(sig.get("symbol"), sig)
    r = row or {}
    return {
        "signal_at": r.get("signal_at") or sig.get("created_at"),
        "horizons": [{
            "days": h,
            "due_date": _due_date(sd, h, crypto).isoformat() if sd else None,
            "fwd_ret_frac": _num(r.get(f"fwd_ret_{h}d")),
            "spy_ret_frac": _num(r.get(f"spy_ret_{h}d")),
            "excess_ret_frac": _num(r.get(f"excess_ret_{h}d")),
            "filled_at": r.get(f"filled_{h}d_at"),
        } for h in HORIZONS],
    }


def _pick_decision(sig: Mapping, rows: list[dict]) -> dict | None:
    same = [d for d in rows if sig.get("scan_id") and d.get("scan_id") == sig.get("scan_id")]
    pool = same or []
    if not pool:
        return None
    for d in pool:
        if d.get("decision") == "ENTER":
            return d
    return pool[0]


def _equity_estimate(wallet: Mapping | None, open_trades: list[dict], snapshots: list[dict]) -> float | None:
    if wallet:
        eq = ((_num(wallet.get("balance")) or 0.0) + (_num(wallet.get("collateral_reserved")) or 0.0)
              + sum(_num(t.get("position_size_usd")) or 0.0 for t in open_trades))
        if eq > 0:
            return eq
    return _snapshot_equity(snapshots)


def build_trail(sig: Mapping, decision: Mapping | None, trade: Mapping | None, outcome: Mapping | None,
                open_trades: list[dict], equity: float | None) -> dict:
    t = sig.get("technical_data") or {}
    fd = sig.get("fundamental_data") or {}
    det = dict((decision or {}).get("details") or {})
    symbol = sig.get("symbol")

    tf_stored = t.get("_tech_filter") if isinstance(t.get("_tech_filter"), Mapping) else None
    tf = tf_stored or (det.get("tech_filter") if isinstance(det.get("tech_filter"), Mapping) else None)
    reasons = list((tf or {}).get("reasons") or []) if tf else None
    checks = tech_checks(t, sig, reasons)
    tech_filter = None
    if tf or any(c["value"] is not None for c in checks):
        tech_filter = {"passed": tf.get("passed") if tf else None, "reasons": reasons or [], "checks": checks}

    routine, dmodel = model_verdicts(sig)

    order = None
    if det or trade:
        crypto = _is_crypto(symbol, sig)
        tr = trade or {}
        fill = _num(tr.get("entry_price")) if tr else _num(det.get("fill"))
        stop = (_num(tr.get("initial_stop")) or _num(tr.get("stop_loss"))) if tr else _num(det.get("stop"))
        target = _num(tr.get("target_price")) if tr else _num(det.get("target"))
        alloc = _num(tr.get("position_size_usd")) if tr else _num(det.get("alloc_usd"))
        risk = _num(det.get("risk_usd"))
        order = {
            "ref_price": _num(tr.get("entry_ref_price")) if tr and tr.get("entry_ref_price") else _num(det.get("ref_price")),
            "fill": fill if fill is not None else _num(det.get("fill")),
            "stop": stop if stop is not None else _num(det.get("stop")),
            "target": target if target is not None else _num(det.get("target")),
            "rr": (_num(tr.get("entry_rr")) if tr and tr.get("entry_rr") is not None else _num(det.get("rr"))),
            "shares": (_num(tr.get("shares")) if tr and tr.get("shares") is not None else _num(det.get("shares"))),
            "alloc_usd": alloc if alloc is not None else _num(det.get("alloc_usd")),
            "risk_usd": risk,
            "risk_pct": round(risk / equity * 100, 2) if risk is not None and equity else None,
            "position_pct": round((alloc or 0) / equity * 100, 2) if alloc is not None and equity else None,
            "slippage_bps": settings.brain_slippage_bps_crypto if crypto else settings.brain_slippage_bps_stock,
            "levels_source": det.get("levels_source"),
            "trade_id": det.get("trade_id") or (str(tr.get("id")) if tr.get("id") else None),
        }

    corr = None
    c = det.get("correlation")
    if isinstance(c, Mapping) and c:
        corr = {
            "status": c.get("status"),
            "rule": c.get("rule"),
            "max_corr": _num(c.get("max_corr")),
            "max_corr_symbol": c.get("max_corr_symbol"),
            "corr": {str(k): _num(v) for k, v in (c.get("corr") or {}).items() if _num(v) is not None},
            "max_pairwise": _num(c.get("max_pairwise")),
            "cluster_threshold": _num(c.get("cluster_threshold")),
        }

    sector = det.get("sector") or fd.get("sector")
    sector_exp = None
    if sector:
        held = sum(1 for tr in open_trades
                   if (tr.get("sector") or "").strip().lower() == str(sector).strip().lower())
        sector_exp = {"sector": sector, "held": held, "max": settings.brain_max_per_sector}

    return _clean({
        "symbol": symbol,
        "signal_id": str(sig.get("id")),
        "scan_id": str(sig["scan_id"]) if sig.get("scan_id") else None,
        "created_at": sig.get("created_at"),
        "company_name": sig.get("company_name") or fd.get("company_name"),
        "sector": fd.get("sector"),
        "bucket": sig.get("bucket"),
        "action": sig.get("action"),
        "ai_status": sig.get("ai_status"),
        "score": _int(sig.get("score")),
        "price_at_signal": _num(sig.get("price_at_signal")),
        "decision": ({"decision": decision.get("decision"),
                      "reason": describe_reason(decision.get("reason"), det, sig, decision.get("decision")),
                      "decided_at": decision.get("decided_at")} if decision else None),
        "tech_filter": tech_filter,
        "grok": _grok(sig.get("grok_data")),
        "routine": routine,
        "decision_model": dmodel,
        "codex": codex_verdict(sig.get("grok_data")),
        "order": order,
        "correlation": corr,
        "sector_exposure": sector_exp,
        "outcomes": build_outcomes(sig, outcome),
    })


class SignalNotFound(Exception):
    pass


def get_signal_trail(symbol: str) -> dict:
    sig = queries.get_latest_signal_for_symbol(symbol)
    if not sig:
        raise SignalNotFound(symbol)
    decisions = _safe(lambda: queries.get_brain_decisions(scan_id=sig.get("scan_id"), symbol=symbol, limit=20)
                      if sig.get("scan_id") else [], [], "signal decisions")
    decision = _pick_decision(sig, decisions)
    trade = None
    tid = ((decision or {}).get("details") or {}).get("trade_id")
    if decision and decision.get("decision") == "ENTER" and tid:
        trade = _safe(lambda: queries.get_virtual_trade_by_id(tid), None, "trade")
    outcome = _safe(lambda: queries.get_candidate_outcome_for_signal(str(sig.get("id"))), None, "outcome")
    open_trades = _safe(queries.get_open_brain_trades, [], "open trades")
    wallet = _wallet()
    snaps = [] if wallet else _safe(lambda: queries.get_virtual_snapshots_since(None), [], "snapshots")
    equity = _equity_estimate(wallet, open_trades, snaps)
    return build_trail(sig, decision, trade, outcome, open_trades, equity)



def verdicts_from_rows(rows: list[dict]) -> dict:
    """signals rows (see queries.get_signal_verdicts) -> {id: verdict chip data}.
    Missing columns come back as None; tech_filter_passed is None when the
    signal has no stored `_tech_filter`."""
    out: dict = {}
    for r in rows or []:
        sid = r.get("id")
        if not sid:
            continue
        tf = r.get("tech_filter")
        passed = tf.get("passed") if isinstance(tf, dict) else None
        out[sid] = _clean({
            "ai_status": r.get("ai_status"),
            "ai_signal": r.get("ai_signal"),
            "p_win": r.get("p_win"),
            "routine_ai_signal": r.get("routine_ai_signal"),
            "decision_overturned": r.get("decision_overturned"),
            "tech_filter_passed": passed if isinstance(passed, bool) else None,
        })
    return out
