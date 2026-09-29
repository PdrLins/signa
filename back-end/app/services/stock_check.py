"""On-demand "Check a stock" — the live scan + brain pipeline for ONE symbol.

The owner types a ticker ("XEQT") and asks "is this a good moment to buy?".
This module answers with the same code the scheduled scan and the brain
use, but WITHOUT buying anything and WITHOUT touching live statistics:

  * never inserts/updates signals, brain_decisions, candidate_outcomes,
    virtual_trades, tickers, or the AI retry queue;
  * reads the brain's book (open positions, wallet, cooldowns) read-only;
  * AI calls go through `app.ai.provider` exactly as the scan does, so the
    provider caches are shared and budget recording still happens.

Pipeline (mirrors scan_service._process_candidate + the brain entry gate):

  resolving    normalize + validate; try SYMBOL, SYMBOL.TO, SYMBOL-USD
  market_data  1y history, fundamentals, earnings, macro, knowledge block
  filter       check_blockers (tech-level) + technical_filter
  sentiment    Grok (HIGH_RISK only, as in the scan) + options flow
  synthesis    routine model  (provider.synthesize_signal)
  decision     decision model (scan_service._confirm_buy_with_decision_model),
               then the independent Codex review when the decision model
               confirmed a BUY (verdict in grok_data["_codex"] → trail.codex)
  risk         score, blockers, earnings blackout, levels, R:R, sizing,
               portfolio limits, correlation, drawdown breaker

AI is skipped (as the scan skips it) when the verdict is already AVOID on
structure: trend filter failed, illiquid, a material blocker, or a
HIGH_RISK name in a CRISIS regime.

Verdict:
  BUY_NOW  every live brain gate passes (market closed only adds a note)
  WAIT     the setup is sound but a timing gate fails
  AVOID    the AI says AVOID/SELL, a material red flag / blocker hits, or
           the trend filter fails
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from loguru import logger

from app.ai import provider as ai_provider
from app.ai.signal_engine import (
    check_blockers,
    check_entry_blackout,
    compute_score,
    score_to_action,
    technical_filter,
)
from app.core.cache import TTLCache
from app.core.config import settings
from app.core.utils import validate_ticker
from app.scanners import barchart_scanner, indicators, macro_scanner, market_scanner
from app.scanners.universe import get_all_tickers, get_asset_class, get_exchange
from app.services import insights_service
from app.services import scan_service as sv
from app.services import virtual_portfolio as vp
from app.signals.earnings import get_earnings_context

ET = ZoneInfo("America/New_York")
ProgressFn = Callable[[str, int], None]

PHASES = ("resolving", "market_data", "filter", "sentiment", "synthesis", "decision", "risk", "done")


# Technical-filter reasons that make the setup structurally unbuyable
# (AVOID) vs. the ones that are only about timing (WAIT).
STRUCTURAL_FILTER_REASONS = ("below_sma200", "sma50_below_sma200", "insufficient_history",
                             "low_liquidity", "no_liquidity_data")
TIMING_FILTER_REASONS = ("rsi_overbought", "overextended_vs_sma50")

CAVEATS = [
    {"code": "not_advice", "text": "Not financial advice. Signa is an experiment run on a virtual wallet."},
    {"code": "edge_unproven", "text": "The strategy's edge is unproven — see Is it working? before trusting any verdict."},
    {"code": "no_order", "text": "Checking a stock never places a trade and is not recorded in the brain's statistics."},
]

_resolve_cache = TTLCache(max_size=500, default_ttl=24 * 3600)
_macro_cache = TTLCache(max_size=2, default_ttl=15 * 60)


class StockCheckError(Exception):
    """A user-facing failure: `code` is stable (translated by the UI)."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "status": self.status}


def _noop(_phase: str, _pct: int) -> None:
    return None


def _plain(v: Any) -> Any:
    """numpy scalars -> Python (FastAPI can't encode numpy.bool_)."""
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if type(v).__module__ == "numpy" and hasattr(v, "item"):
        return v.item()
    return v


def _num(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# ============================================================
# Symbol resolution
# ============================================================

def normalize_input(raw: str | None) -> str:
    """Uppercase / trim / strip a leading '$'; raises invalid_ticker."""
    s = (raw or "").strip().upper().lstrip("$").strip()
    if not s or len(s) > 20 or not validate_ticker(s):
        raise StockCheckError("invalid_ticker", "Enter a ticker symbol like AAPL, XEQT or BTC.", 400)
    return s


def candidate_symbols(symbol: str, prefer_tsx: bool = False) -> list[str]:
    """Symbols to try, in order: raw, .TO (TSX), -USD (crypto).

    An input that already carries a suffix (SHOP.TO, BRK-B, BTC-USD) is
    tried as-is only. A candidate that is part of Signa's universe is tried
    first, so "BTC" means BTC-USD (not the US-listed BTC trust) and "XEQT"
    means XEQT.TO. prefer_tsx=True (My holdings: a Canadian owner) tries
    .TO before the bare US symbol.
    """
    if "." in symbol or "-" in symbol:
        return [symbol]
    cands = ([f"{symbol}.TO", symbol, f"{symbol}-USD"] if prefer_tsx
             else [symbol, f"{symbol}.TO", f"{symbol}-USD"])
    try:
        known = set(get_all_tickers())
    except Exception:
        known = set()
    preferred = [c for c in cands if c in known]
    return preferred + [c for c in cands if c not in preferred]


def exchange_for(symbol: str) -> str:
    if symbol.endswith("-USD"):
        return "CRYPTO"
    return get_exchange(symbol)


def _recent_price(symbol: str) -> float | None:
    """Last close from yfinance if the symbol traded in the last ~10 days."""
    import yfinance as yf

    try:
        df = yf.Ticker(symbol).history(period="10d")
    except Exception as e:
        logger.debug(f"stock_check: history({symbol}) failed: {e}")
        return None
    if df is None or df.empty or "Close" not in df:
        return None
    closes = df["Close"].dropna()
    if closes.empty:
        return None
    price = _num(closes.iloc[-1])
    return price if price and price > 0 else None


async def resolve_symbol(raw: str) -> dict:
    """{"input", "symbol", "exchange", "price"} or StockCheckError(not_found)."""
    sym = normalize_input(raw)
    cached = _resolve_cache.get(sym)
    if cached is not None:
        return dict(cached)
    tried = candidate_symbols(sym)
    for cand in tried:
        if not validate_ticker(cand):
            continue
        price = await asyncio.to_thread(_recent_price, cand)
        if price:
            res = {"input": sym, "symbol": cand, "exchange": exchange_for(cand), "price": price}
            _resolve_cache.set(sym, res)
            return dict(res)
    raise StockCheckError(
        "not_found",
        f"No recent price data for {sym} (tried {', '.join(tried)}).",
        404,
    )


# ============================================================
# Side-effect-free helpers
# ============================================================

def classify_bucket_readonly(symbol: str, fundamentals: dict | None) -> str:
    """scan_service._classify_bucket without the tickers-table upsert or the
    module bucket-cache write (same priority and heuristics)."""
    from app.scanners.universe import is_leveraged_or_inverse

    known = sv._known_bucket(symbol)
    if known is not None:
        return known
    if is_leveraged_or_inverse(symbol, fundamentals):
        return "HIGH_RISK"
    if not sv._has_classifying_fundamentals(fundamentals):
        return "HIGH_RISK"
    return sv._bucket_from_fundamentals(fundamentals or {})


async def _macro_snapshot() -> dict:
    cached = _macro_cache.get("macro")
    if cached is not None:
        return cached
    data = await macro_scanner.get_macro_snapshot()
    if data:
        _macro_cache.set("macro", data)
    return data or {}


async def _knowledge_block() -> str:
    from app.services.knowledge_service import KnowledgeService

    return await KnowledgeService().get_prompt_knowledge_block()  # same set the scan uses


def _inject_prompt_context(grok_data: dict, regime: str, knowledge: str, options_flow, bucket: str) -> None:
    """Same underscore meta-fields the scan adds before synthesis."""
    grok_data["_market_regime"] = regime
    grok_data["_catalyst_context"] = "No specific catalyst detected"
    grok_data["_regime_note"] = (
        f"Market is in {regime} mode — adjust signal accordingly" if regime != "TRENDING" else ""
    )
    if knowledge:
        grok_data["_knowledge_block"] = knowledge
    if options_flow:
        grok_data["_options_flow"] = options_flow
    try:
        from app.services.pattern_stats import get_pattern_warning

        warning = get_pattern_warning({"bucket": bucket, "market_regime": regime})
        if warning:
            grok_data["_knowledge_block"] = (grok_data.get("_knowledge_block") or "") + "\n\n" + warning
    except Exception as e:
        logger.debug(f"stock_check: pattern stats unavailable ({e})")


def load_book_state(symbol: str, price: float | None) -> dict:
    """The brain's live book, READ ONLY (no peak ratchet, no breaker persist,
    no wallet lazy-create). Each read degrades to empty on failure."""
    from app.db import queries

    try:
        open_rows = queries.get_open_brain_trades()
    except Exception as e:
        logger.debug(f"stock_check: open trades unavailable ({e})")
        open_rows = []
    try:
        wallet = queries.get_brain_wallet_readonly(queries.get_brain_user_id())
    except Exception as e:
        logger.debug(f"stock_check: wallet unavailable ({e})")
        wallet = None
    try:
        cooldown = vp._reentry_cooldown_symbols(vp.get_client())
    except Exception as e:
        logger.debug(f"stock_check: cooldowns unavailable ({e})")
        cooldown = {}

    prices = {symbol: float(price)} if price else {}
    equity = vp._estimate_equity(wallet, open_rows, prices) if wallet else 0.0
    net_dep = (_num((wallet or {}).get("total_deposited")) or 0.0) - (_num((wallet or {}).get("total_withdrawn")) or 0.0)
    stored_peak = _num((wallet or {}).get("peak_equity"))
    peak = max(stored_peak if stored_peak else net_dep, equity)
    tripped_at = (wallet or {}).get("breaker_tripped_at")
    breaker = vp.evaluate_drawdown_breaker(equity, peak, tripped_at, datetime.now(timezone.utc))
    return {
        "open_rows": open_rows,
        "open_book": [vp._book_entry(r) for r in open_rows],
        "wallet": wallet,
        "equity": equity,
        "cash": _num((wallet or {}).get("balance")) or 0.0,
        "peak": breaker.peak,
        "breaker": breaker,
        "cooldown": cooldown,
    }


def _market_open(symbol: str) -> bool:
    return vp._is_tradable_now(symbol, vp._is_us_market_open())


# ============================================================
# Gate + verdict helpers (pure)
# ============================================================

def _blocker_is_timing(text: str) -> bool:
    """RSI / SMA200-overextension blockers are timing (WAIT); red flags,
    hostile macro and dead volume are material (AVOID)."""
    t = (text or "").lower()
    return t.startswith("rsi overbought") or t.startswith("extreme overextension")


def _gate(key: str, ok: bool | None, severity: str, reason: dict | None = None, hint: dict | None = None) -> dict:
    return {"key": key, "ok": ok, "severity": severity, "reason": reason, "hint": hint}


def _reason(code: str, params: dict, text: str, raw: str | None = None) -> dict:
    return {"code": code, "params": params, "text": text, "raw": raw}


def _hint(code: str, params: dict, text: str) -> dict:
    return {"code": code, "params": params, "text": text}


def _money(v) -> str:
    f = _num(v)
    return f"${f:,.2f}" if f is not None else "?"


def filter_hint(reason: str, tech: dict, crypto: bool = False) -> dict | None:
    """What would have to change for one failing technical-filter check."""
    sma50, sma200 = _num(tech.get("sma_50")), _num(tech.get("sma_200"))
    if reason == "overextended_vs_sma50":
        mx = settings.tech_filter_max_ext_sma50_pct
        level = round(sma50 * (1 + mx / 100.0), 2) if sma50 else None
        return _hint("pullback_sma50", {"pct": mx, "price": level},
                     f"Wait for price to pull back to within {mx:g}% of the 50-day average"
                     + (f" (~{_money(level)})" if level else ""))
    if reason == "rsi_overbought":
        mx = settings.tech_filter_max_rsi
        return _hint("rsi_cool", {"limit": mx}, f"Wait for RSI(14) to cool to {mx:g} or below")
    if reason == "below_sma200":
        return _hint("reclaim_sma200", {"price": round(sma200, 2) if sma200 else None},
                     "Price must reclaim its 200-day average" + (f" (~{_money(sma200)})" if sma200 else ""))
    if reason == "sma50_below_sma200":
        return _hint("golden_cross", {"sma50": round(sma50, 2) if sma50 else None,
                                      "sma200": round(sma200, 2) if sma200 else None},
                     "The 50-day average must climb back above the 200-day average (uptrend confirmed)")
    if reason == "insufficient_history":
        return _hint("more_history", {}, "Needs about a year of daily prices before the trend check can run")
    if reason in ("low_liquidity", "no_liquidity_data"):
        floor = settings.tech_filter_min_dollar_volume_crypto if crypto else settings.tech_filter_min_dollar_volume
        return _hint("liquidity", {"min": floor}, "Trading volume is too thin for the brain to buy it")
    return None


def rr_fix_price(target: float | None, stop: float | None, min_rr: float) -> float | None:
    """Entry price at which (target - E) / (E - stop) == min_rr."""
    if target is None or stop is None or min_rr <= -1:
        return None
    e = (target + min_rr * stop) / (1.0 + min_rr)
    return round(e, 4) if e > stop else None


def decide_verdict(gates: list[dict]) -> tuple[str, list[dict]]:
    """(verdict, failing gates ordered by severity then list order)."""
    failing = [g for g in gates if g["ok"] is False]
    avoid = [g for g in failing if g["severity"] == "avoid"]
    wait = [g for g in failing if g["severity"] == "wait"]
    if avoid:
        return "AVOID", avoid + wait
    if wait:
        return "WAIT", wait
    return "BUY_NOW", []


def _headline(verdict: str, symbol: str, primary: dict | None) -> dict:
    ptext = (primary or {}).get("text") or ""
    if verdict == "BUY_NOW":
        return _hint("buy_now", {"symbol": symbol},
                     f"{symbol} passes every check the brain uses — it would buy it now.")
    if verdict == "WAIT":
        return _hint("wait", {"symbol": symbol, "reason": ptext},
                     f"{symbol} is a reasonable setup, but not right now: {ptext}.")
    return _hint("avoid", {"symbol": symbol, "reason": ptext},
                 f"The brain would not buy {symbol}: {ptext}.")


def _model_verdict(s: dict | None) -> dict | None:
    if not s:
        return None
    return {
        "signal": (str(s.get("signal")).upper() if s.get("signal") else None),
        "confidence": _num(s.get("confidence")),
        "p_win": sv._clean_p_win(s.get("p_win")),
        "reasoning": s.get("reasoning") or None,
    }


def _earnings_info(fund: dict, asset_class: str, blackout: str | None) -> dict | None:
    if asset_class != "STOCK":
        return None
    d = fund.get("next_earnings_date") or fund.get("earnings_date")
    if not d:
        return {"date": None, "days": None, "trading_days": None, "blackout": False}
    return {
        "date": str(d)[:10],
        "days": fund.get("days_to_next_earnings"),
        "trading_days": fund.get("trading_days_to_next_earnings"),
        "blackout": bool(blackout),
    }


# ============================================================
# The check
# ============================================================

async def run_check(resolved: dict, progress: ProgressFn | None = None) -> dict:
    """Run the full live analysis for one resolved symbol. Never persists."""
    p = progress or _noop
    symbol = resolved["symbol"]
    exchange = resolved.get("exchange") or exchange_for(symbol)
    now = datetime.now(timezone.utc)

    # ── market data ──
    p("market_data", 10)
    fetch_earnings = get_asset_class(symbol) == "STOCK"
    coros = [
        market_scanner.get_price_history(symbol, "1y"),
        market_scanner.get_fundamentals(symbol),
        _macro_snapshot(),
        _knowledge_block(),
    ]
    if fetch_earnings:
        coros.append(get_earnings_context(symbol))
    fetched = await asyncio.gather(*coros, return_exceptions=True)
    price_df = fetched[0] if not isinstance(fetched[0], BaseException) else None
    fund = dict(fetched[1]) if isinstance(fetched[1], dict) else {}
    macro = fetched[2] if isinstance(fetched[2], dict) else {}
    knowledge = fetched[3] if isinstance(fetched[3], str) else ""
    earnings_ctx = fetched[4] if fetch_earnings and isinstance(fetched[4], dict) else None

    asset_class = sv._asset_class(symbol, fund)
    if symbol.endswith("-USD"):
        asset_class = "CRYPTO"
    if asset_class == "STOCK":
        sv._merge_earnings(fund, earnings_ctx, exchange)
    bucket = classify_bucket_readonly(symbol, fund)
    tech = indicators.compute_indicators(price_df, exchange=exchange) if price_df is not None else {}
    if not tech or _num(tech.get("current_price")) is None:
        raise StockCheckError("insufficient_data", f"Not enough price history to analyse {symbol}.", 422)
    from app.signals.regime import get_market_regime
    regime = get_market_regime(macro)
    price = _num(tech.get("current_price"))

    # ── technical filter (same inputs as scan_service._stamp_tech_filter) ──
    p("filter", 25)
    try:
        _, tech_blockers = check_blockers({}, fund, macro, tech)
    except Exception:
        tech_blockers = []
    passed, filter_reasons = technical_filter(tech, fund, asset_class, tech_blockers)
    tech["_tech_filter"] = {"passed": passed, "reasons": filter_reasons}
    structural = [r for r in filter_reasons if r in STRUCTURAL_FILTER_REASONS]
    material_tech_blockers = [b for b in tech_blockers if not _blocker_is_timing(b)]
    crisis_skip = regime == "CRISIS" and bucket == "HIGH_RISK"
    run_ai = bool(settings.ai_enabled) and not structural and not material_tech_blockers and not crisis_skip

    # ── sentiment + AI ──
    grok_data: dict = {}
    routine: dict | None = None
    synthesis: dict = {}
    if run_ai:
        p("sentiment", 40)
        if bucket == "SAFE_INCOME":
            try:
                options_flow = await barchart_scanner.get_options_flow(symbol)
            except Exception:
                options_flow = None
            grok_data = {"score": 50, "label": "neutral", "confidence": 0, "top_themes": [],
                         "summary": "Sentiment skipped for Safe Income (10% weight)", "_skipped": True}
        else:
            got = await asyncio.gather(
                ai_provider.analyze_sentiment(symbol, market_cap=fund.get("market_cap")),
                barchart_scanner.get_options_flow(symbol),
                return_exceptions=True,
            )
            grok_data = dict(got[0]) if isinstance(got[0], dict) else {
                "score": 50, "label": "neutral", "confidence": 0, "error": "sentiment failed"}
            options_flow = got[1] if isinstance(got[1], dict) else None
        _inject_prompt_context(grok_data, regime, knowledge, options_flow, bucket)

        p("synthesis", 55)
        routine = await ai_provider.synthesize_signal(symbol, tech, fund, macro, grok_data)
        p("decision", 72)
        synthesis = await sv._confirm_buy_with_decision_model(symbol, routine, tech, fund, macro, grok_data)

    # ── risk ──
    p("risk", 88)
    ai_status = sv._classify_ai_status(synthesis) if run_ai else "skipped"
    score, breakdown = compute_score(tech, fund, macro, grok_data, synthesis, bucket, regime, asset_class)
    is_blocked, block_reasons = check_blockers(grok_data, fund, macro, tech)
    action = "AVOID" if is_blocked else score_to_action(score, bucket)
    blackout = check_entry_blackout(fund)
    target, stop, rr, levels_source = sv._resolve_trade_levels(
        price, tech.get("atr"), synthesis.get("target_price"), synthesis.get("stop_loss"),
        synthesis.get("risk_reward_ratio"),
    )
    if grok_data:
        grok_data["_levels_source"] = levels_source
        if synthesis.get("signal"):
            grok_data["_ai_signal"] = synthesis.get("signal")
        if synthesis.get("_decision"):
            grok_data["_decision"] = synthesis["_decision"]

    sig = {
        "symbol": symbol,
        "asset_type": asset_class,
        "exchange": exchange,
        "action": action,
        "score": score,
        "confidence": synthesis.get("confidence", 0) if run_ai else 0,
        "ai_status": ai_status,
        "ai_signal": (synthesis.get("signal") or None) if run_ai else None,
        "ai_provider": synthesis.get("_provider"),
        "p_win": sv._clean_p_win(synthesis.get("p_win")),
        **(sv._decision_audit_fields(synthesis) if run_ai else {"routine_ai_signal": None, "decision_overturned": None}),
        "bucket": bucket,
        "price_at_signal": price,
        "target_price": target,
        "stop_loss": stop,
        "risk_reward": rr,
        "reasoning": synthesis.get("reasoning") or "",
        "technical_data": tech,
        "fundamental_data": fund,
        "macro_data": macro,
        "grok_data": grok_data,
        "market_regime": regime,
        "company_name": fund.get("company_name"),
        "catalyst_type": breakdown.get("catalyst_type") if isinstance(breakdown, dict) else None,
    }

    book = await asyncio.to_thread(load_book_state, symbol, price)
    market_open = _market_open(symbol)
    gates, plan = await _brain_gates(sig, book, tech, fund, structural, filter_reasons, tech_blockers,
                                     block_reasons, crisis_skip, run_ai, blackout, action, is_blocked)

    verdict, failing = decide_verdict(gates)
    primary = failing[0]["reason"] if failing else None
    hints: list[dict] = []
    seen: set[str] = set()
    for g in failing:
        h = g.get("hint")
        if h and h["code"] not in seen:
            seen.add(h["code"])
            hints.append(h)

    notes: list[dict] = []
    if not market_open:
        notes.append(_hint("market_closed", {}, "The market is closed — an order now would fill at the next open."))
    if book["equity"] <= 0:
        notes.append(_hint("no_equity", {}, "The brain wallet has no equity, so no position size could be suggested."))
    if (synthesis or {}).get("_cached") or (routine or {}).get("_cached"):
        notes.append(_hint("ai_cached", {}, "The AI verdict was reused from a check or scan in the last few hours."))
    if not run_ai:
        why = ("ai_disabled" if not settings.ai_enabled else "structural")
        notes.append(_hint("ai_skipped", {"why": why},
                           "AI was not asked: the setup already fails a structural check (saves cost)."
                           if why == "structural" else "AI analysis is disabled in settings."))

    # ── decision trail (same shape as /insights/signal/{ticker}) ──
    decision_row = {
        "decision": "ENTER" if verdict == "BUY_NOW" else "SKIP",
        "reason": (primary or {}).get("raw") or ("ai_buy" if verdict == "BUY_NOW" else None),
        "details": plan["details"],
        "decided_at": now.isoformat(),
    }
    trail_sig = {**sig, "id": "check", "scan_id": None, "created_at": now.isoformat()}
    trail = insights_service.build_trail(trail_sig, decision_row, None, None, book["open_rows"], book["equity"] or None)
    trail["signal_id"] = None
    trail["outcomes"] = None
    if trail.get("decision") and primary is not None:
        trail["decision"]["reason"] = primary
    # The check has the routine model's full answer in memory — show it.
    if run_ai:
        trail["routine"] = _model_verdict(routine)
        dec_state = synthesis.get("_decision")
        if dec_state == "unavailable":
            trail["decision_model"] = {"signal": None, "confidence": None, "p_win": None,
                                       "reasoning": None, "status": "unavailable"}
        elif dec_state == "confirmed":
            dm = _model_verdict(synthesis) or {}
            if synthesis.get("_decision_signal"):  # Codex vetoed: keep what the decision model said
                dm["signal"] = str(synthesis["_decision_signal"]).upper()
            trail["decision_model"] = {**dm, "status": "confirmed" if dm.get("signal") == "BUY" else "vetoed"}
        else:
            trail["decision_model"] = None
    else:
        trail["routine"] = None
        trail["decision_model"] = None

    fx = plan.get("fx")
    size = None
    if plan.get("shares"):
        eq = book["equity"] or None
        size = {
            "shares": plan["shares"],
            "alloc_usd": plan.get("alloc_usd"),
            "risk_usd": plan.get("risk_usd"),
            "risk_pct": round(plan["risk_usd"] / eq * 100, 2) if eq and plan.get("risk_usd") is not None else None,
            "position_pct": round(plan["alloc_usd"] / eq * 100, 2) if eq and plan.get("alloc_usd") is not None else None,
            "equity_usd": round(eq, 2) if eq else None,
            "risk_per_trade_pct": settings.brain_risk_per_trade_pct,
            "currency": plan.get("currency"),
            "fx_to_usd": fx,
        }

    result = {
        "input": resolved.get("input") or symbol,
        "symbol": symbol,
        "exchange": exchange,
        "name": fund.get("company_name"),
        "asset_class": asset_class,
        "bucket": bucket,
        "sector": fund.get("sector"),
        "currency": plan.get("currency") or ("CAD" if symbol.endswith((".TO", ".V")) else "USD"),
        "price": price,
        "market_open": market_open,
        "market_regime": regime,
        "verdict": verdict,
        "headline": _headline(verdict, symbol, primary),
        "reasons": [g["reason"] for g in failing if g.get("reason")],
        "what_would_change": hints,
        "notes": notes,
        "gates": [{"key": g["key"], "ok": g["ok"], "severity": g["severity"]} for g in gates],
        "levels": {
            "entry": plan.get("fill") or price,
            "ref_price": price,
            "stop": (plan.get("levels") or {}).get("stop"),
            "target": (plan.get("levels") or {}).get("target"),
            "rr": (plan.get("levels") or {}).get("rr"),
            "min_rr": settings.brain_min_rr,
            "source": (plan.get("levels") or {}).get("source"),
            "atr": _num(tech.get("atr")),
        },
        "size": size,
        "earnings": _earnings_info(fund, asset_class, blackout),
        "ai": {"status": ai_status, "provider": sig.get("ai_provider"), "called": run_ai},
        "score": score,
        "trail": trail,
        "caveats": CAVEATS,
        "checked_at": now.isoformat(),
        "cached": False,
    }
    p("done", 100)
    return insights_service._clean(_plain(result))


async def _brain_gates(sig: dict, book: dict, tech: dict, fund: dict, structural: list[str],
                       filter_reasons: list[str], tech_blockers: list[str], block_reasons: list[str],
                       crisis_skip: bool, run_ai: bool, blackout: str | None, action: str,
                       is_blocked: bool) -> tuple[list[dict], dict]:
    """Every live brain gate for a LONG entry, evaluated (not short-circuited)
    so the answer can list everything that would have to change."""
    symbol = sig["symbol"]
    describe = insights_service.describe_reason
    gates: list[dict] = []
    details: dict = {"direction": "LONG", "entry_mode": vp._entry_mode(),
                     "tech_filter": tech.get("_tech_filter")}
    plan: dict = {"details": details}

    # 1. Regime: the scan never analyses HIGH_RISK names in a CRISIS regime.
    gates.append(_gate("regime", not crisis_skip, "avoid",
                       _reason("crisis_high_risk", {}, "Market regime is CRISIS — high-risk names are skipped",
                               "crisis_high_risk") if crisis_skip else None,
                       _hint("regime", {}, "Re-check once the market regime leaves CRISIS") if crisis_skip else None))

    # 2. Trend / liquidity (structural technical filter)
    for r in STRUCTURAL_FILTER_REASONS:
        if r in filter_reasons:
            gates.append(_gate(f"filter:{r}", False, "avoid",
                               describe(f"technical_filter:{r}", details, sig),
                               filter_hint(r, tech, vp._is_crypto_symbol(symbol, sig))))
    if not structural:
        gates.append(_gate("filter:trend", True, "avoid"))

    # 3. Material blockers (cited red flag, fraud news, hostile macro, dead volume)
    material = [b for b in block_reasons if not _blocker_is_timing(b)]
    for b in material:
        low = b.lower()
        code = "red_flag" if ("red flag" in low or "fraud" in low) else "blocker"
        hint = (_hint("red_flag_clear", {}, "The cited red flag would have to be resolved or proven immaterial")
                if code == "red_flag" else _hint("blocker_clear", {"text": b}, f"This blocker would have to clear: {b}"))
        gates.append(_gate("blocker", False, "avoid", _reason(code, {"text": b}, b, code), hint))
    if not material:
        gates.append(_gate("blocker", True, "avoid"))

    # 4. AI verdict
    ai_sig = (sig.get("ai_signal") or "").upper()
    ai_status = sig.get("ai_status")
    if run_ai:
        if ai_sig in ("SELL", "AVOID"):
            reason = describe(f"not_ai_buy_rejected_{ai_sig}", details, sig)
            gates.append(_gate("ai", False, "avoid", reason,
                               _hint("ai_bearish", {"signal": ai_sig},
                                     f"The AI calls it {ai_sig}; its thesis would have to change")))
        elif not vp.is_ai_buy(sig):
            if ai_status == "failed":
                raw = "ai_failed"
                hint = _hint("ai_retry", {}, "The AI analysis failed — try the check again later")
            elif ai_status == "low_confidence":
                raw = "not_ai_buy_low_confidence_BUY"
                hint = _hint("ai_conviction", {"min": settings.ai_validated_min_confidence},
                             f"The AI leans BUY but needs confidence ≥ {settings.ai_validated_min_confidence}")
            else:
                raw = f"not_ai_buy_rejected_{ai_sig or 'HOLD'}"
                hint = _hint("ai_hold", {"signal": ai_sig or "HOLD"},
                             "The AI says wait — re-check after the next catalyst or pullback")
            gates.append(_gate("ai", False, "wait", describe(raw, details, sig), hint))
        else:
            gates.append(_gate("ai", True, "wait"))
    elif not settings.ai_enabled:
        gates.append(_gate("ai", False, "wait", _reason("ai_disabled", {}, "AI analysis is disabled", "ai_disabled"),
                           _hint("ai_enable", {}, "Enable AI analysis in settings")))

    # Legacy admission flags (all off by default): sector exclusion, portfolio
    # heat, score-mode floor — whatever _eval_brain_trust_tier rejects beyond
    # "not an AI BUY" / the technical filter, which are reported above/below.
    if run_ai and vp.is_ai_buy(sig):
        heat = vp._portfolio_heat(len(book["open_book"]), [sig])
        tier, _trust, tier_reason = vp._eval_brain_trust_tier(sig, heat)
        if tier <= 0 and not tier_reason.startswith(("technical_filter", "not_ai_buy", "ai_failed")):
            gates.append(_gate("tier", False, "wait", describe(tier_reason, details, sig),
                               _hint("tier", {"reason": tier_reason}, "A brain admission rule rejects it right now")))

    # 5. Timing: extension / RSI (filter) and RSI / SMA200 blockers
    for r in TIMING_FILTER_REASONS:
        if r in filter_reasons:
            gates.append(_gate(f"filter:{r}", False, "wait",
                               describe(f"technical_filter:{r}", details, sig), filter_hint(r, tech)))
    for b in block_reasons:
        if _blocker_is_timing(b):
            low = b.lower()
            if low.startswith("rsi overbought") and "rsi_overbought" in filter_reasons:
                continue  # already reported by the filter check
            sma200 = _num(tech.get("sma_200"))
            hint = (_hint("pullback_sma200", {"price": round(sma200 * 1.5, 2) if sma200 else None},
                          "Wait for price to come back within 50% of the 200-day average")
                    if low.startswith("extreme") else
                    _hint("rsi_cool", {"limit": settings.tech_filter_max_rsi},
                          f"Wait for RSI(14) to cool to {settings.tech_filter_max_rsi:g} or below"))
            gates.append(_gate("blocker_timing", False, "wait",
                               _reason("blocker_timing", {"text": b}, b, "blocker_timing"), hint))

    # 6. Earnings blackout
    if blackout:
        d = fund.get("next_earnings_date") or fund.get("earnings_date")
        gates.append(_gate("earnings", False, "wait", describe(blackout, details, sig),
                           _hint("after_earnings", {"date": str(d)[:10] if d else None},
                                 f"Earnings on {str(d)[:10] if d else 'the upcoming date'}; re-check after the report")))
    else:
        gates.append(_gate("earnings", True, "wait"))

    # 7. Score-derived action (the brain skips SELL/AVOID actions)
    if not is_blocked and action in ("SELL", "AVOID"):
        gates.append(_gate("action", False, "wait", describe(f"action_{action.lower()}", details, sig),
                           _hint("score", {"score": sig.get("score")},
                                 "The composite score is below the HOLD line; re-check after the data improves")))

    # 8. Levels + R:R (from the slipped fill price, as the brain computes them)
    price = _num(sig.get("price_at_signal"))
    levels = None
    if price:
        fill = vp.apply_slippage(price, "BUY", symbol)
        levels = vp.compute_entry_levels(sig, fill, "LONG")
        plan.update({"ref_price": price, "fill": round(fill, 6), "levels": levels})
        details.update({"ref_price": price, "fill": round(fill, 6), "stop": levels.get("stop"),
                        "target": levels.get("target"), "rr": levels.get("rr"),
                        "levels_source": levels.get("source")})
        lr = levels.get("reason")
        if lr and lr.startswith("rr_below_min"):
            fix = rr_fix_price(levels.get("target"), levels.get("stop"), settings.brain_min_rr)
            gates.append(_gate("rr", False, "wait", describe(lr, details, sig),
                               _hint("rr_min", {"rr": levels.get("rr"), "min": settings.brain_min_rr, "price": fix},
                                     f"Reward/risk must reach {settings.brain_min_rr:g}"
                                     + (f" — roughly an entry at or below {_money(fix)}" if fix else ""))))
        elif lr:
            gates.append(_gate("rr", False, "wait", describe(lr, details, sig),
                               _hint("levels", {}, "No valid stop could be set (missing ATR)")))
        else:
            gates.append(_gate("rr", True, "wait"))

    # 9. Book state: already held / cooldown / breaker / horizon
    open_book = book["open_book"]
    if any(pb.get("symbol") == symbol for pb in open_book):
        gates.append(_gate("held", False, "wait", describe("already_held", details, sig),
                           _hint("already_held", {}, "The brain already holds it")))
    cd = book["cooldown"].get(symbol)
    if cd:
        gates.append(_gate("cooldown", False, "wait", describe(cd, details, sig),
                           _hint("cooldown", {"days": settings.brain_reentry_cooldown_days},
                                 f"Re-entry cooldown: wait {settings.brain_reentry_cooldown_days} trading days after the last exit")))
    br = book["breaker"]
    if br.blocked:
        details["breaker"] = {**br.details(), "equity": round(book["equity"], 2), "peak": round(book["peak"], 2)}
        gates.append(_gate("breaker", False, "wait", describe("drawdown_breaker_pause", details, sig),
                           _hint("breaker", {"days": br.days_remaining},
                                 "New entries are paused by the drawdown breaker"
                                 + (f" for {br.days_remaining} more trading days" if br.days_remaining is not None else ""))))
    else:
        gates.append(_gate("breaker", True, "wait"))
    if settings.brain_long_horizon_suspended and vp._classify_horizon(sig, symbol) == "LONG":
        gates.append(_gate("horizon", False, "wait",
                           describe("filter_d_long_horizon_suspended", details, sig),
                           _hint("horizon", {}, "Long-horizon entries are suspended in settings")))

    # 10. Sizing at 1% risk + portfolio limits
    fx = await asyncio.to_thread(vp.fx_to_usd, symbol)
    plan["fx"] = fx
    plan["currency"] = vp.native_currency(symbol)
    equity, cash = float(book["equity"] or 0), float(book["cash"] or 0)
    alloc = 0.0
    if levels and levels.get("stop") is not None and not (levels.get("reason") or "").startswith("no_valid") and fx and equity > 0:
        fill = plan["fill"]
        risk_per_share_usd = abs(fill - levels["stop"]) * fx
        from app.services import wallet as wallet_svc
        shares, alloc = wallet_svc.calc_risk_position_size(
            equity, cash, fill * fx, fill * fx - risk_per_share_usd, trust_multiplier=1.0,
        )
        if shares <= 0:
            gates.append(_gate("size", False, "wait", describe("size_below_minimum", details, sig),
                               _hint("size", {}, "Not enough free cash for a minimum-size position")))
        else:
            sector = (fund.get("sector") or "").strip() or None
            is_crypto = vp._is_crypto_symbol(symbol, sig)
            alloc2, limit_reason = vp.check_portfolio_limits(
                symbol=symbol, sector=sector, is_crypto=is_crypto,
                alloc_usd=alloc, equity_usd=equity, open_book=open_book,
            )
            if limit_reason and limit_reason != "already_held":
                gates.append(_gate("limits", False, "wait", describe(limit_reason, details, sig),
                                   _hint("slots", {"reason": limit_reason},
                                         "Wait until the brain frees a slot (position, sector or crypto limit)")))
            elif not limit_reason:
                gates.append(_gate("limits", True, "wait"))
            if alloc2 and alloc2 < alloc:
                alloc = round(alloc2, 2)
                shares = round(alloc / (fill * fx), 6)
            plan.update({"shares": shares, "alloc_usd": alloc, "sector": sector, "is_crypto": is_crypto,
                         "risk_usd": round(shares * risk_per_share_usd, 2)})
            details.update({"shares": shares, "alloc_usd": alloc, "risk_usd": plan["risk_usd"], "sector": sector})
    elif not fx:
        details["fx_unavailable"] = vp.native_currency(symbol)

    # 11. Correlation with holdings (runs even when an earlier gate failed,
    #     so the answer can show how it would fit the book).
    if open_book:
        try:
            from app.services import portfolio_risk
            check = await asyncio.to_thread(
                portfolio_risk.check_correlation_limit,
                symbol=symbol, alloc_usd=float(alloc or 0), equity_usd=equity, open_book=open_book,
            )
            details["correlation"] = check.details
            if check.reason:
                gates.append(_gate("correlation", False, "wait", describe(check.reason, details, sig),
                                   _hint("diversify", {"symbol": check.details.get("max_corr_symbol"),
                                                       "corr": check.details.get("max_corr")},
                                         "Too correlated with what the brain already holds"
                                         + (f" ({check.details.get('max_corr_symbol')})"
                                            if check.details.get("max_corr_symbol") else ""))))
            else:
                gates.append(_gate("correlation", True, "wait"))
        except Exception as e:
            logger.warning(f"stock_check: correlation check failed for {symbol}: {e}")
            details["correlation"] = {"status": "skipped", "why": "error"}
    else:
        details["correlation"] = {"status": "skipped", "why": "no_open_positions"}

    return gates, plan
