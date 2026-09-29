"""Thin adapter over the LIVE Signa code — the backtest's only link to it.

Every scoring / blocker / prefilter / regime / exit / sizing decision in
the backtest goes through a function defined in `app/`. Nothing here
re-implements a rule; the wrappers only (a) call through the module
attribute at CALL time (so a monkeypatch of e.g.
`app.ai.signal_engine.compute_score` is honoured and the backtest follows
edits to the live code automatically) and (b) strip the parts of the live
call path that touch the database, the network or the wall clock.

Where the live path cannot be called as-is, the reason is stated next to
the wrapper:

  * `classify_bucket` — live `scan_service._classify_bucket` persists the
    bucket to Supabase. We call the same pure helpers it calls
    (`_known_bucket`, `is_leveraged_or_inverse`,
    `_has_classifying_fundamentals`, `_bucket_from_fundamentals`) in the
    same order, without the DB write.
  * entry gating — live `_evaluate_brain_entry` requires an AI BUY
    (`ai_status == "validated"`), reads the wall clock (market hours) and
    fetches the live USDCAD rate. The portfolio simulator calls the same
    building blocks in the same order (apply_slippage →
    compute_entry_levels → calc_risk_position_size → check_portfolio_limits
    → correlation gate) with point-in-time prices and FX.
"""

from __future__ import annotations

from loguru import logger

from app.ai import signal_engine
from app.core.config import settings
from app.scanners import indicators as live_indicators
from app.scanners import market_scanner, prefilter, universe
from app.scanners import macro_scanner
from app.services import scan_service
from app.services import virtual_portfolio as vp
from app.services import wallet
from app.signals import regime

__all__ = ["settings", "quiet_live_logs"]


def quiet_live_logs() -> None:
    """Silence the live modules' per-call logging (prefilter summary,
    blocker hits, regime) — pure noise across ~100k calls. Called by the
    CLI / workers only, never at import (it would leak into other tests)."""
    logger.disable("app")


# ── Signal layer ────────────────────────────────────────────

def compute_indicators(df):
    # exchange=None: never drop the "incomplete" last bar based on the
    # wall clock. In the backtest bar t is complete (post-close scan).
    return live_indicators.compute_indicators(df, exchange=None)


def screening_features(df) -> dict:
    return market_scanner._screening_features(df)


def prefilter_candidates(screening: dict, held: set[str] | None = None) -> list[str]:
    return prefilter.prefilter_candidates(screening, set(), held or set())


def compute_score(technical, fundamental, macro, grok, synthesis, bucket, regime_, asset_type):
    return signal_engine.compute_score(
        technical, fundamental, macro, grok, synthesis, bucket, regime_, asset_type,
    )


def tech_only_action(score, bucket, technical, fundamental, macro) -> tuple[str, list[str]]:
    """Live tech-only action: blockers → AVOID, score_to_action, blackout → HOLD."""
    return scan_service._tech_only_action(score, bucket, technical, fundamental, macro)


def check_blockers(technical, fundamental, macro) -> tuple[bool, list[str]]:
    return signal_engine.check_blockers({}, fundamental, macro, technical)


def check_entry_blackout(fundamental) -> str | None:
    return signal_engine.check_entry_blackout(fundamental)


def score_to_action(score, bucket) -> str:
    return signal_engine.score_to_action(score, bucket)


def classify_bucket(ticker: str, fundamentals: dict | None) -> str:
    """Live `_classify_bucket` minus its Supabase upsert (see module doc)."""
    known = scan_service._known_bucket(ticker)
    if known is not None:
        return known
    if universe.is_leveraged_or_inverse(ticker, fundamentals):
        return "HIGH_RISK"
    if not scan_service._has_classifying_fundamentals(fundamentals):
        return "HIGH_RISK"
    return scan_service._bucket_from_fundamentals(fundamentals)


def asset_class(ticker: str, fundamentals: dict | None) -> str:
    return scan_service._asset_class(ticker, fundamentals)


def market_regime(macro: dict) -> str:
    return regime.get_market_regime(macro)


def macro_environment(macro: dict) -> str:
    return macro_scanner.classify_macro_environment(macro)


def get_all_tickers() -> list[str]:
    return universe.get_all_tickers()


def get_exchange(ticker: str) -> str:
    return universe.get_exchange(ticker)


# ── Execution / risk layer ──────────────────────────────────

def apply_slippage(price: float, side: str, symbol: str) -> float:
    return vp.apply_slippage(price, side, symbol)


def compute_entry_levels(sig: dict, fill: float) -> dict:
    return vp.compute_entry_levels(sig, fill, "LONG")


def calc_risk_position_size(equity, cash, entry_usd, stop_usd) -> tuple[float, float]:
    return wallet.calc_risk_position_size(equity, cash, entry_usd, stop_usd, trust_multiplier=1.0)


def check_portfolio_limits(**kw) -> tuple[float, str | None]:
    return vp.check_portfolio_limits(**kw)


def correlation_gate(*, symbol, alloc_usd, equity_usd, open_book, closes_loader) -> str | None:
    """Live correlation gate with a point-in-time closes loader. None = allowed.

    Absent (older live code) or erroring → never blocks, like live.
    """
    if not getattr(settings, "brain_correlation_check_enabled", False):
        return None
    try:
        from app.services import portfolio_risk
    except Exception:
        return None
    try:
        check = portfolio_risk.check_correlation_limit(
            symbol=symbol, alloc_usd=alloc_usd, equity_usd=equity_usd,
            open_book=open_book, closes_loader=closes_loader,
        )
    except Exception:
        return None
    return check.reason


def evaluate_exit(pos: dict, price: float, now, latest_signal: dict | None = None):
    return vp.evaluate_exit(pos, price, now=now, latest_signal=latest_signal)


def compute_close_amounts(trade: dict, exit_ref_price: float, fx_exit: float) -> dict:
    return vp.compute_close_amounts(trade, exit_ref_price, fx_exit)


def drawdown_breaker_tripped(equity: float, peak: float) -> bool:
    return vp.drawdown_breaker_tripped(equity, peak)


def trading_days_between(a, b) -> int:
    return vp.trading_days_between(a, b)


def native_currency(symbol: str) -> str:
    from app.services.price_cache import native_currency as _nc
    return _nc(symbol)


def is_crypto(symbol: str) -> bool:
    return vp._is_crypto_symbol(symbol)


def brain_min_score() -> int:
    return vp.BRAIN_MIN_SCORE
