"""Virtual Portfolio — the brain (Signa's autonomous paper-trading engine).

============================================================
WHAT THIS MODULE IS
============================================================

The "brain" opens and closes virtual positions from the signals produced
by `scan_service`, with no human input, and records every trade in
`virtual_trades` backed by a USD cash wallet (`wallet.py`). No real money
is at stake; the point is to MEASURE whether the signal model has an edge,
so every rule below is chosen to make the measurement honest:

  * realistic fills (slippage + commission on both sides, CAD→USD FX),
  * hard stops that nothing can suppress,
  * fixed-fractional risk per trade so outcomes are comparable,
  * one exit policy shared by the scan and the watchdog,
  * a `brain_decisions` row for every candidate so we can audit WHY the
    brain did or didn't trade.

============================================================
2026-09 DECISION-QUALITY RESET — THE RULES
============================================================

ENTRY (all must pass, see `_evaluate_brain_entry`)
  1. AI BUY: ai_status == "validated" AND ai_signal == "BUY" AND the
     technical gate passes. Tech-only / low_confidence / failed signals
     NEVER auto-buy (`_eval_brain_trust_tier`). The technical gate is
     `signal_engine.technical_filter` (price > SMA200, SMA50 > SMA200,
     RSI <= 75, <= 15% above SMA50, 20d $ volume floor, no blocker) when
     brain_entry_mode == "filter" (default), or the legacy
     score >= BRAIN_MIN_SCORE when "score". Several qualifying
     candidates in one scan are taken in AI p_win order, then AI
     confidence (`brain_entry_sort_key`) — never by score in filter mode.
  2. Not already held (either track), not in the same-symbol re-entry
     cooldown (`brain_reentry_cooldown_days` trading days after any exit).
  3. Drawdown breaker (`evaluate_drawdown_breaker`): when equity falls to
     peak × (1 − brain_max_drawdown_pct) the breaker trips
     (brain_wallet.breaker_tripped_at) and new entries pause for
     brain_drawdown_pause_trading_days US trading days; then the peak is
     reset to current equity and entries resume (no permanent latch).
  4. Exchange open today (holiday filter) and market hours for equities.
  5. Levels: Claude's stop/target when valid, otherwise ATR fallback
     (stop = entry − brain_stop_atr_mult × ATR, target = entry +
     brain_target_r_mult × risk). R:R is computed IN CODE from the fill
     price and must be >= brain_min_rr (`compute_entry_levels`).
  6. Size = risk-based (`wallet.calc_risk_position_size`): lose
     brain_risk_per_trade_pct of equity at the stop, capped at
     brain_max_position_pct of equity.
  7. Portfolio limits (`check_portfolio_limits`): brain_max_open_positions,
     brain_max_per_sector, brain_max_crypto_pct. No rotation — when full,
     new candidates simply wait.
  8. CAD listings need a USDCAD rate; without one the entry is skipped.
  9. Correlation gate (`_correlation_gate` → portfolio_risk, LONG only,
     `brain_correlation_check_enabled`): skip "correlation_limit" when the
     candidate's 120d daily-return correlation to any open position is
     >= brain_corr_max_pairwise, or >= brain_corr_cluster_max open
     positions correlate >= brain_corr_cluster_threshold. Missing price
     history never blocks. Optional post-trade beta cap (off by default).

EXIT (`evaluate_exit`, used by check_virtual_exits AND the watchdog)
  STOP_HIT       price through stop — always hard, never thesis-gated.
  TRAILING_STOP  after +brain_trail_activate_r R, stop ratchets to
                 peak − brain_trail_atr_mult × ATR (never loosens).
  TARGET_HIT     price through target.
  TIME_EXPIRED   held >= brain_max_hold_days.
  SIGNAL         (scan only) the fresh AI call is SELL/AVOID
                 (`signal_exit_reason`) or the user forced a sell.
  THESIS_INVALIDATED is executed by thesis_tracker; it can only close a
  position early — a "valid" thesis never keeps a losing position open
  (`_exit_is_thesis_protected`, off by default).

SHORTS are disabled by default (`brain_short_entries_enabled`). The code
path remains direction-aware (P&L, learning outcomes, stops).

Legacy gates fit on tiny samples (Filter D sectors, LONG-horizon
suspension, portfolio heat / VIX floor, MOMENTUM & NEUTRAL tier caps,
post-win / post-loss / watchdog cooldowns, per-day caps, quality and
stagnation prunes) are still in the code but OFF via config flags.

============================================================
MARKET HOURS DISCIPLINE
============================================================

Equities are only bought/sold during the US regular session (Mon-Fri
9:30-16:00 ET) on days their exchange is open. Crypto trades 24/7.
Pre-market SELL signals on held equities are FLAGGED FOR REVIEW and
re-checked by `process_pending_reviews` at the first in-hours scan; the
user can force a sell from Telegram (/forcesell → FORCE_SELL sentinel).

============================================================
CONCURRENCY / STATE
============================================================

Brain Telegram notifications are queued in a scan-local list
(`new_notification_queue`) and drained once by
`flush_brain_notifications`. The DB (virtual_trades, brain_wallet,
wallet_transactions) is the only source of truth; every close is guarded
by `.eq("status", "OPEN")` so scan / watchdog / thesis tracker can race
safely (see close_virtual_trade for the wallet ordering).
"""

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from loguru import logger

from app.core.cache import TTLCache
from app.core.config import settings
from app.core.dates import days_since, parse_iso_utc
from app.db import queries
from app.db.supabase import get_client, with_retry
from app.services.knowledge_events import (
    EVENT_THINKING_OBSERVATION_ADDED,
    OUTCOME_CONTRADICTING,
    OUTCOME_NEUTRAL,
    OUTCOME_SUPPORTING,
    log_event,
)
from app.services.price_cache import _fetch_prices_batch, fx_to_usd, native_currency


# ============================================================
# CONSTANTS
# ============================================================

BRAIN_MIN_SCORE = 75
"""LEGACY (brain_entry_mode == "score") score floor for an AI-BUY entry.
In the default "filter" mode the gate is `signal_engine.technical_filter`
and the score is display-only: the 2021-2026 signal study showed higher
scores did not predict better returns."""

FILTER_D_BLOCKED_SECTORS: frozenset[str] = frozenset({
    "Financial Services",
    "Industrials",
})
"""Day-20 sector exclusion (n=9 trades). Only applied when
`settings.brain_filter_d_sectors_enabled` is True (default False since
the 2026-09 reset — the evidence was far too small to keep as a veto)."""


# ============================================================
# TYPES
# ============================================================

BrainNotificationQueue = list[tuple[str, dict]]
"""A scan-local queue of brain Telegram notifications: (template_key, kwargs)."""


def new_notification_queue() -> BrainNotificationQueue:
    """Create a fresh brain notification queue for a single scan run."""
    return []


def _is_us_market_open() -> bool:
    """True during the US regular session (Mon-Fri 9:30-16:00 ET).

    Exchange holidays are handled separately via
    `app.core.market_calendar.is_market_open` (see `_is_tradable_now`).
    """
    now_et = datetime.now(ZoneInfo("America/New_York"))
    if now_et.weekday() >= 5:
        return False
    minutes = now_et.hour * 60 + now_et.minute
    return 570 <= minutes < 960


def _is_crypto_symbol(symbol: str | None, sig: dict | None = None) -> bool:
    return (sig or {}).get("asset_type") == "CRYPTO" or (symbol or "").endswith("-USD")


def _is_tradable_now(symbol: str, market_open: bool | None = None) -> bool:
    """Can an order on `symbol` fill right now? Crypto: always. Equities:
    US regular session AND the listing exchange is open today."""
    if _is_crypto_symbol(symbol):
        return True
    if market_open is None:
        market_open = _is_us_market_open()
    if not market_open:
        return False
    try:
        from app.core.market_calendar import is_market_open
        from app.scanners.universe import get_exchange
        today_et = datetime.now(ZoneInfo("America/New_York")).date()
        return bool(is_market_open(get_exchange(symbol), today_et))
    except Exception as e:  # calendar failure must not block risk exits
        logger.debug(f"market calendar check failed for {symbol}: {e}")
        return True


# ============================================================
# EXECUTION COSTS
# ============================================================

def slippage_bps(symbol: str | None) -> float:
    return (
        settings.brain_slippage_bps_crypto if _is_crypto_symbol(symbol)
        else settings.brain_slippage_bps_stock
    )


def apply_slippage(price: float, side: str, symbol: str | None) -> float:
    """Fill price for a market order. side='BUY' pays up, 'SELL' receives less.

    Applied to every brain fill on BOTH sides: LONG entry = BUY, LONG exit =
    SELL, SHORT entry = SELL, SHORT cover = BUY.
    """
    bps = slippage_bps(symbol) / 10_000.0
    if side == "BUY":
        return float(price) * (1.0 + bps)
    return float(price) * (1.0 - bps)


# ============================================================
# ENTRY GATE
# ============================================================

def is_ai_buy(sig: dict) -> bool:
    """Claude actually called BUY (and the scan validated it)."""
    if sig.get("ai_status") != "validated":
        return False
    if not settings.brain_require_ai_buy:
        return True
    return (sig.get("ai_signal") or "").upper() == "BUY"


def _entry_mode() -> str:
    return "score" if (settings.brain_entry_mode or "").lower() == "score" else "filter"


def brain_technical_filter(sig: dict) -> tuple[bool, list[str]]:
    """`signal_engine.technical_filter` on a signal dict, with the live
    tech-level blockers (RSI / volume / SMA200 / hostile macro / cited red
    flags) as the blocker input."""
    from app.ai.signal_engine import check_blockers, technical_filter
    tech = sig.get("technical_data") or {}
    fund = sig.get("fundamental_data") or {}
    try:
        _, blockers = check_blockers(sig.get("grok_data") or {}, fund, sig.get("macro_data") or {}, tech)
    except Exception:
        blockers = []
    asset_class = sig.get("asset_type") or ("CRYPTO" if _is_crypto_symbol(sig.get("symbol"), sig) else None)
    return technical_filter(tech, fund, asset_class, blockers)


def brain_entry_sort_key(sig: dict, mode: str | None = None) -> tuple:
    """Order in which one scan's candidates claim entry slots.

    filter mode (default): AI p_win desc, then AI confidence desc (missing
    values last). score mode (legacy): score desc. Python's sort is stable,
    so ties keep the incoming (prefilter) order.
    """
    if (mode or _entry_mode()) == "score":
        return (-(sig.get("score") or 0),)
    p_win = sig.get("p_win")
    conf = sig.get("confidence")
    return (
        -(float(p_win) if p_win is not None else -1.0),
        -(float(conf) if conf is not None else -1.0),
    )


def _eval_brain_trust_tier(sig: dict, portfolio_heat: int = 0) -> tuple[int, float, str]:
    """Decide whether a signal may be auto-bought.

    Returns (tier, trust_multiplier, reason). tier 0 = do not buy. After the
    2026-09 reset there is ONE admissible tier: an AI BUY (see `is_ai_buy`)
    that passes `technical_filter` (brain_entry_mode "filter", default) or
    has score >= BRAIN_MIN_SCORE (legacy "score" mode; skip reason
    "technical_filter:<first failing reason>" / "score_below_min_<n>").
    Low-confidence, tech-only ("skipped") and
    failed-AI signals never auto-buy. trust_multiplier scales the per-trade
    RISK budget; it is 1.0 unless one of the legacy downsizing flags is on.
    """
    score = sig.get("score", 0) or 0
    ai_status = sig.get("ai_status", "skipped")
    technical_data = sig.get("technical_data") or {}

    if ai_status == "failed":
        return 0, 0.0, "ai_failed"
    if not is_ai_buy(sig):
        ai_sig = (sig.get("ai_signal") or "none").lower()
        return 0, 0.0, f"not_ai_buy_{ai_status}_{ai_sig}"

    if settings.brain_filter_d_sectors_enabled:
        sector = ((sig.get("fundamental_data") or {}).get("sector") or "").strip()
        if sector in FILTER_D_BLOCKED_SECTORS:
            return 0, 0.0, f"filter_d_sector_excluded_{sector.lower().replace(' ', '_')}"

    if settings.brain_portfolio_heat_enabled:
        if portfolio_heat >= 3:
            return 0, 0.0, "portfolio_locked"
        if portfolio_heat >= 2 and score < 80:
            return 0, 0.0, f"portfolio_defensive_score{score}"
        if portfolio_heat >= 1 and score < 76:
            return 0, 0.0, f"portfolio_cautious_score{score}"

    if _entry_mode() == "score":
        if score < BRAIN_MIN_SCORE:
            return 0, 0.0, f"score_below_min_{score}"
    else:
        passed, reasons = brain_technical_filter(sig)
        if not passed:
            return 0, 0.0, f"technical_filter:{reasons[0]}"

    if settings.brain_trend_downsize_enabled:
        vs_sma50 = technical_data.get("vs_sma50")
        if vs_sma50 is not None and vs_sma50 < 0:
            return 2, 0.5, "ai_buy_below_sma50"
        bb, macd = technical_data.get("bb_position"), technical_data.get("macd_histogram")
        if bb is not None and bb > 0.95 and macd is not None and macd < 0:
            return 2, 0.5, "ai_buy_overextended_bb"
    if settings.brain_portfolio_heat_enabled and portfolio_heat >= 2:
        return 2, 0.5, "ai_buy_heat_defensive"
    if settings.brain_momentum_force_tier2 and sig.get("signal_style") == "MOMENTUM":
        return 2, 0.5, "ai_buy_momentum_capped"
    if (settings.brain_neutral_high_score_force_tier2
            and sig.get("signal_style") == "NEUTRAL"
            and score >= settings.brain_neutral_high_score_threshold):
        return 2, 0.5, "ai_buy_neutral_high_score_capped"
    return 1, 1.0, "ai_buy"


def _eval_brain_short_tier(sig: dict) -> tuple[int, float, str]:
    """Decide whether a signal qualifies as a SHORT entry.

    Shorts are OFF unless `brain_short_entries_enabled`. When on, only an
    explicit AI SELL/AVOID call (not a tech-only or blocker AVOID) with
    score <= brain_short_max_score and correctly ordered levels qualifies.
    """
    if not settings.brain_short_entries_enabled:
        return 0, 0.0, "shorts_disabled"
    score = sig.get("score", 100) or 100
    ai_status = sig.get("ai_status", "skipped")
    if ai_status in ("failed", "skipped") or (sig.get("ai_signal") or "").upper() not in ("SELL", "AVOID"):
        return 0, 0.0, "short_requires_ai_sell"
    if sig.get("action") != "AVOID":
        return 0, 0.0, "short_requires_avoid_action"
    if score > settings.brain_short_max_score:
        return 0, 0.0, f"short_score_too_high_{score}"
    if settings.brain_filter_d_sectors_enabled:
        sector = ((sig.get("fundamental_data") or {}).get("sector") or "").strip()
        if sector in FILTER_D_BLOCKED_SECTORS:
            return 0, 0.0, f"short_filter_d_sector_excluded_{sector.lower().replace(' ', '_')}"
    gd = sig.get("grok_data") or {}
    if isinstance(gd, dict) and gd.get("score") is not None and gd["score"] > 40:
        return 0, 0.0, f"short_sentiment_not_bearish_{gd['score']}"
    return 1, 1.0, "short_ai_bearish"


def compute_entry_levels(sig: dict, entry_price: float, direction: str = "LONG") -> dict:
    """Final stop / target / R:R for a new position, computed in code.

    Claude's stop/target are used when present and on the right side of the
    FILL price. A Claude stop tighter than brain_min_stop_atr_mult × ATR is
    replaced by the ATR stop (noise stops are not risk control). Missing
    levels fall back to ATR: stop = entry ∓ brain_stop_atr_mult × ATR and
    target = entry ± brain_target_r_mult × risk. R:R = reward / risk from
    the fill price; the caller rejects when rr < brain_min_rr.

    Returns {"stop", "target", "rr", "atr", "source", "reason"}; a non-None
    "reason" means the entry must be skipped.
    """
    short = direction == "SHORT"
    entry = float(entry_price)
    td = sig.get("technical_data") or {}
    try:
        atr = float(td.get("atr")) if td.get("atr") else None
    except (TypeError, ValueError):
        atr = None
    if atr is not None and atr <= 0:
        atr = None

    def _num(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    stop, target = _num(sig.get("stop_loss")), _num(sig.get("target_price"))
    if (sig.get("grok_data") or {}).get("_levels_source") == "atr_fallback":
        # The scan filled a 2R target from the QUOTED price; measured from the
        # slipped fill it lands just under brain_min_rr and every such entry
        # was rejected. Rebuild the fallback target from the fill instead.
        target = None
    source = "ai"
    stop_ok = stop is not None and ((stop > entry) if short else (0 < stop < entry))
    if stop_ok and atr and abs(entry - stop) < settings.brain_min_stop_atr_mult * atr:
        stop_ok = False
        source = "ai_stop_too_tight"
    if not stop_ok:
        if not atr:
            return {"stop": None, "target": None, "rr": None, "atr": None,
                    "source": source, "reason": "no_valid_stop_and_no_atr"}
        k = settings.brain_stop_atr_mult * atr
        stop = entry + k if short else entry - k
        source = "atr" if source == "ai" else f"{source}->atr"
    risk = abs(entry - stop)
    target_ok = target is not None and ((0 < target < entry) if short else (target > entry))
    if not target_ok:
        reward = settings.brain_target_r_mult * risk
        target = entry - reward if short else entry + reward
        source += "+r_target"
    if target <= 0 or risk <= 0:
        return {"stop": stop, "target": target, "rr": None, "atr": atr,
                "source": source, "reason": "invalid_levels"}
    rr = abs(target - entry) / risk
    reason = None
    if rr + 1e-9 < settings.brain_min_rr:
        reason = f"rr_below_min_{rr:.2f}"
    return {"stop": round(stop, 6), "target": round(target, 6), "rr": round(rr, 3),
            "atr": atr, "source": source, "reason": reason}


def check_portfolio_limits(
    *,
    symbol: str,
    sector: str | None,
    is_crypto: bool,
    alloc_usd: float,
    equity_usd: float,
    open_book: list[dict],
) -> tuple[float, str | None]:
    """Apply portfolio-level limits to a proposed allocation.

    `open_book` = current brain positions, each {"symbol", "sector",
    "is_crypto", "cost_usd"}. Returns (allowed_alloc_usd, reject_reason);
    the crypto cap may SHRINK the allocation instead of rejecting.
    """
    if len(open_book) >= settings.brain_max_open_positions:
        return 0.0, f"max_open_positions_{settings.brain_max_open_positions}"
    if any(p.get("symbol") == symbol for p in open_book):
        return 0.0, "already_held"
    if sector and settings.brain_max_per_sector > 0:
        same = sum(1 for p in open_book if (p.get("sector") or "") == sector)
        if same >= settings.brain_max_per_sector:
            return 0.0, f"sector_cap_{sector.lower().replace(' ', '_')}"
    if is_crypto:
        crypto_cost = sum(float(p.get("cost_usd") or 0) for p in open_book if p.get("is_crypto"))
        room = equity_usd * settings.brain_max_crypto_pct / 100.0 - crypto_cost
        if room < settings.wallet_min_balance_for_trade:
            return 0.0, "crypto_cap"
        alloc_usd = min(alloc_usd, room)
    return alloc_usd, None


def drawdown_breaker_tripped(equity_usd: float, peak_equity_usd: float,
                             max_drawdown_pct: float | None = None) -> bool:
    """Peak-to-trough breaker: True when equity is >= max_drawdown_pct below peak."""
    pct = settings.brain_max_drawdown_pct if max_drawdown_pct is None else max_drawdown_pct
    if pct is None or pct <= 0 or peak_equity_usd <= 0:
        return False
    return equity_usd <= peak_equity_usd * (1.0 - pct / 100.0)


@dataclass
class BreakerState:
    """Result of one `evaluate_drawdown_breaker` call."""
    blocked: bool
    peak: float
    tripped_at: object | None     # same type the caller passed/received (ISO str, datetime or date)
    reason: str | None            # "drawdown_breaker_pause" when blocked
    event: str | None             # "tripped" | "resumed" | None
    days_elapsed: int | None = None
    days_remaining: int | None = None

    def details(self) -> dict:
        return {"days_elapsed": self.days_elapsed, "days_remaining": self.days_remaining,
                "peak": round(self.peak, 2), "tripped_at": str(self.tripped_at) if self.tripped_at else None}


_ET = ZoneInfo("America/New_York")


def _et_date(x) -> date | None:
    """ISO string / datetime (naive = UTC) / date → US-Eastern calendar date."""
    if x is None:
        return None
    if isinstance(x, str):
        x = parse_iso_utc(x)
        if x is None:
            return None
    if isinstance(x, datetime):
        if x.tzinfo is None:
            x = x.replace(tzinfo=timezone.utc)
        return x.astimezone(_ET).date()
    if isinstance(x, date):
        return x
    return None


def evaluate_drawdown_breaker(
    equity: float,
    peak: float,
    tripped_at,
    now,
    *,
    max_drawdown_pct: float | None = None,
    pause_trading_days: int | None = None,
) -> BreakerState:
    """Drawdown breaker with a timed pause instead of a permanent latch.

    Pure. `tripped_at` / `now` may be ISO strings, datetimes or dates; the
    elapsed count is US trading days (market_calendar, NYSE holidays)
    strictly after the trip day up to and including today.

      not tripped, drawdown <  max → not blocked; peak ratchets to new highs
      not tripped, drawdown >= max → TRIP: tripped_at = now, blocked
      tripped, elapsed <  N       → blocked (pause)
      tripped, elapsed >= N       → RESUME: peak = current equity,
                                    tripped_at cleared, not blocked

    Why the reset: once the book is flat in cash, equity cannot climb back
    to the old peak, so a peak-referenced breaker would block forever.
    """
    n = settings.brain_drawdown_pause_trading_days if pause_trading_days is None else pause_trading_days
    n = max(0, int(n or 0))
    peak = max(float(peak or 0.0), float(equity))
    trip_day = _et_date(tripped_at)
    today = _et_date(now)
    if trip_day is not None and today is not None:
        from app.core.market_calendar import us_trading_days_between
        elapsed = us_trading_days_between(trip_day, today)
        if elapsed < n:
            return BreakerState(True, peak, tripped_at, "drawdown_breaker_pause", None,
                                elapsed, n - elapsed)
        return BreakerState(False, float(equity), None, None, "resumed", elapsed, 0)
    if drawdown_breaker_tripped(equity, peak, max_drawdown_pct):
        return BreakerState(True, peak, now, "drawdown_breaker_pause", "tripped", 0, n)
    return BreakerState(False, peak, None, None, None)


def trading_days_between(start: date, end: date) -> int:
    """Weekdays strictly after `start` up to and including `end` (holidays ignored)."""
    if end <= start:
        return 0
    n, d = 0, start
    while d < end:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def signal_exit_reason(sig: dict) -> str | None:
    """Should a fresh signal close an open LONG? One rule for every path.

    Exit only on an explicit AI SELL/AVOID call or a user /forcesell. A
    tech-only or blocker-driven AVOID (no AI SELL) is NOT an exit — the
    hard stop manages that risk. (Replaces the old score-drop guard.)
    """
    if sig.get("_review_forced"):
        return "user_forced"
    if sig.get("action") not in ("SELL", "AVOID"):
        return None
    ai_sig = (sig.get("ai_signal") or "").upper()
    if ai_sig in ("SELL", "AVOID"):
        return f"ai_{ai_sig.lower()}"
    return None


def _extract_thesis_keywords(sig: dict) -> dict:
    """Snapshot the machine-checkable entry conditions for the thesis re-eval."""
    td = sig.get("technical_data") or {}
    md = sig.get("macro_data") or {}
    gd = sig.get("grok_data") or {}
    return {
        "regime": md.get("regime") or sig.get("market_regime"),
        "score_at_entry": sig.get("score"),
        "macd_histogram": td.get("macd_histogram"),
        "rsi": td.get("rsi"),
        "vs_sma200": td.get("vs_sma200"),
        "sentiment_score": gd.get("score") if isinstance(gd, dict) else None,
        "sentiment_label": gd.get("label") if isinstance(gd, dict) else None,
        "catalyst": sig.get("catalyst"),
        "catalyst_type": sig.get("catalyst_type"),
        "fear_greed": md.get("fear_greed"),
        "ai_signal": sig.get("ai_signal"),
        "p_win": sig.get("p_win"),
    }


# ============================================================
# EXIT POLICY (shared by check_virtual_exits and the watchdog)
# ============================================================

HARD_EXIT_REASONS = frozenset({"STOP_HIT", "TRAILING_STOP", "THESIS_INVALIDATED",
                               "WATCHDOG_FORCE_SELL", "WATCHDOG_EXIT"})


def _exit_is_thesis_protected(pos: dict, exit_reason: str, pnl_pct: float | None) -> bool:
    """May a 'valid' thesis suppress this exit? Almost never.

    Only when `brain_thesis_suppresses_exits` is on, only for soft exits
    (TARGET_HIT / TIME_EXPIRED / SIGNAL), and only for a position that is
    currently WINNING. Stops are always hard and a losing position is never
    held open because of a thesis opinion.
    """
    if not settings.brain_thesis_suppresses_exits:
        return False
    if exit_reason in HARD_EXIT_REASONS:
        return False
    if pnl_pct is None or pnl_pct <= 0:
        return False
    return (pos.get("thesis_last_status") or "").lower() == "valid"


@dataclass
class ExitDecision:
    reason: str | None          # None = hold
    stop: float | None          # effective stop after any trailing ratchet
    peak: float | None
    trough: float | None
    changed: bool               # stop/peak/trough moved → persist
    detail: str = ""


def evaluate_exit(
    pos: dict,
    price: float,
    *,
    now: datetime | None = None,
    latest_signal: dict | None = None,
) -> ExitDecision:
    """THE exit policy. Pure: no DB, no network.

    Priority: STOP_HIT / TRAILING_STOP > TARGET_HIT > TIME_EXPIRED > SIGNAL.
    The trailing ratchet is applied BEFORE the stop test so a gap through a
    freshly-raised trail exits the same tick.
    """
    now = now or datetime.now(timezone.utc)
    direction = pos.get("direction") or "LONG"
    short = direction == "SHORT"
    entry = float(pos.get("entry_price") or 0)
    price = float(price)
    if entry <= 0:
        return ExitDecision(None, None, None, None, False, "no_entry_price")

    def _f(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    cat = settings.brain_catastrophic_stop_pct / 100.0
    stop = _f(pos.get("stop_loss"))
    if stop is None:
        stop = entry * (1 + cat) if short else entry * (1 - cat)
    initial = _f(pos.get("initial_stop")) or stop
    target = _f(pos.get("target_price"))
    atr = _f(pos.get("entry_atr"))
    risk = (initial - entry) if short else (entry - initial)

    old_stop = stop
    old_peak, old_trough = _f(pos.get("peak_price")), _f(pos.get("trough_price"))
    peak = max(old_peak or entry, price)
    trough = min(old_trough or entry, price)

    if atr and risk > 0:
        act = settings.brain_trail_activate_r * risk
        trail_dist = settings.brain_trail_atr_mult * atr
        if short and trough <= entry - act:
            stop = min(stop, trough + trail_dist)
        elif not short and peak >= entry + act:
            stop = max(stop, peak - trail_dist)

    changed = (
        abs(stop - old_stop) > 1e-9
        or (not short and (old_peak is None or peak > old_peak))
        or (short and (old_trough is None or trough < old_trough))
    )
    pnl_pct = ((entry - price) if short else (price - entry)) / entry * 100
    trailed = (stop < initial - 1e-9) if short else (stop > initial + 1e-9)

    reason, detail = None, ""
    stop_hit = price >= stop if short else price <= stop
    if stop_hit:
        reason = "TRAILING_STOP" if trailed else "STOP_HIT"
        detail = f"price {price:.4f} through stop {stop:.4f}"
    elif target is not None and (price <= target if short else price >= target):
        reason, detail = "TARGET_HIT", f"price {price:.4f} through target {target:.4f}"
    else:
        max_days = (settings.brain_max_hold_days if pos.get("source") == "brain"
                    else settings.virtual_trade_max_days)
        held = days_since(pos.get("entry_date"), now=now)
        if max_days and held >= max_days:
            reason, detail = "TIME_EXPIRED", f"held {held}d >= {max_days}d"
        elif latest_signal is not None and not short:
            why = signal_exit_reason(latest_signal)
            if why:
                reason, detail = "SIGNAL", why

    if reason and _exit_is_thesis_protected(pos, reason, pnl_pct):
        detail = f"{reason} suppressed by valid thesis (winner {pnl_pct:+.1f}%)"
        reason = None
    return ExitDecision(reason, stop, peak if not short else old_peak,
                        trough if short else old_trough, changed, detail)


# ============================================================
# LEARNING LOOP — record outcomes + update hypothesis evidence
# ============================================================

def _record_brain_outcome(
    closed_trade: dict,
    exit_price: float,
    exit_score: int | None,
    exit_reason: str,
    pnl_pct: float,
) -> None:
    """Forward a closed BRAIN trade to learning_service.record_outcome() and
    update matching hypotheses. Direction-aware (shorts record action
    'SHORT' with short-side P&L). Best-effort: never raises."""
    if closed_trade.get("source") != "brain":
        return
    entry_date_raw = closed_trade.get("entry_date")
    if not entry_date_raw:
        logger.warning(f"Skipping brain outcome for {closed_trade.get('symbol')}: entry_date is null")
        return
    direction = closed_trade.get("direction") or "LONG"
    try:
        from app.services import learning_service
        entry_dt = parse_iso_utc(entry_date_raw)
        if entry_dt is None:
            logger.warning(f"Skipping brain outcome for {closed_trade.get('symbol')}: bad entry_date")
            return
        days_held = max(0, (datetime.now(timezone.utc) - entry_dt).days)
        learning_service.record_outcome(
            signal_id=None,
            symbol=closed_trade["symbol"],
            action="SHORT" if direction == "SHORT" else "BUY",
            score=int(closed_trade.get("entry_score") or 0),
            bucket=closed_trade.get("bucket") or "UNKNOWN",
            signal_date=entry_date_raw,
            entry_price=float(closed_trade["entry_price"]),
            exit_price=float(exit_price),
            days_held=days_held,
            target_price=closed_trade.get("target_price"),
            stop_loss=closed_trade.get("stop_loss"),
            market_regime=closed_trade.get("market_regime"),
            catalyst_type=None,
            notes=exit_reason,
            pnl_pct_override=pnl_pct,
        )
    except Exception as e:
        logger.warning(f"Failed to record brain outcome for {closed_trade.get('symbol')}: {e}")

    try:
        _match_thinking_observations(closed_trade, exit_reason, pnl_pct)
    except Exception as e:
        logger.warning(f"Failed to update hypothesis observations for {closed_trade.get('symbol')}: {e}")

    try:
        from app.services.signal_service import invalidate_track_record_cache
        invalidate_track_record_cache()
    except Exception as e:
        logger.debug(f"Track record cache invalidation skipped: {e}")


def _num_or_none(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _match_score(bound: str):
    def _m(trade: dict, expected, _exit_reason) -> bool:
        exp = _num_or_none(expected)
        score = _num_or_none(trade.get("entry_score"))
        if exp is None or score is None:
            return False
        if bound == "min":
            return score >= exp
        if bound == "max":
            return score <= exp
        return score == exp
    return _m


def _match_exit_reason(trade: dict, expected, exit_reason) -> bool:
    actual = exit_reason or trade.get("exit_reason")
    return bool(actual) and actual == expected


def _match_exit_family(trade: dict, expected, exit_reason) -> bool:
    actual = exit_reason or trade.get("exit_reason") or ""
    return bool(expected) and isinstance(expected, str) and actual.startswith(expected)


def _match_entry_tier(trade: dict, expected, _exit_reason) -> bool:
    try:
        return trade.get("entry_tier") is not None and int(trade["entry_tier"]) == int(expected)
    except (TypeError, ValueError):
        return False


# Every key a hypothesis pattern_match may use. A key NOT in this map makes
# the pattern non-matching (strict): an uncheckable condition must never
# silently widen the cohort to "every trade".
PATTERN_MATCHERS = {
    "bucket": lambda t, v, _r: t.get("bucket") == v,
    "regime": lambda t, v, _r: t.get("market_regime") == v,
    "market_regime": lambda t, v, _r: t.get("market_regime") == v,
    "signal_style": lambda t, v, _r: (t.get("signal_style") or "UNCLASSIFIED") == v,
    "entry_tier": _match_entry_tier,
    "direction": lambda t, v, _r: (t.get("direction") or "LONG") == v,
    "sector": lambda t, v, _r: bool(t.get("sector")) and t.get("sector") == v,
    "symbol": lambda t, v, _r: t.get("symbol") == v,
    "symbols": lambda t, v, _r: isinstance(v, (list, tuple)) and t.get("symbol") in v,
    "score_min": _match_score("min"),
    "score_max": _match_score("max"),
    "score_eq": _match_score("eq"),
    "entry_score_min": _match_score("min"),
    "entry_score_max": _match_score("max"),
    "exit_reason": _match_exit_reason,
    "exit_reason_family": _match_exit_family,
}

# Keys describing the OUTCOME of a trade. Hypotheses keyed on them are
# circular ("stopped-out trades lose"), so the daily loop doesn't create
# them — but they still match strictly if a human writes one.
OUTCOME_PATTERN_KEYS = frozenset({"exit_reason", "exit_reason_family"})


def _trade_matches_pattern(trade: dict, pattern_match: dict, exit_reason: str | None = None) -> bool:
    """Strict match of a closed trade against a hypothesis pattern_match.

    EVERY key must be a known key (see PATTERN_MATCHERS) AND match. Unknown
    keys (e.g. window_days, count_threshold, new_cohorts) → no match. An
    empty or non-dict pattern → no match.
    """
    if not pattern_match or not isinstance(pattern_match, dict):
        return False
    for key, expected in pattern_match.items():
        matcher = PATTERN_MATCHERS.get(key)
        if matcher is None:
            return False
        try:
            if not matcher(trade, expected, exit_reason):
                return False
        except Exception:
            return False
    return True


_WIN_WORDS = ("over-perform", "overperform", "outperform", "will win", "will gain", "favorable", "favors")


def _infer_expected_direction(prediction: str) -> str:
    text = (prediction or "").lower()
    if any(w in text for w in _WIN_WORDS) and "under" not in text:
        return "win"
    return "loss"


def _classify_observation(prediction: str, pnl_pct: float, expected_direction: str | None = None) -> str:
    """Does a closed trade SUPPORT or CONTRADICT a hypothesis?

    `expected_direction` ('win' | 'loss', stored on signal_thinking since
    migration 006) says what the hypothesis predicts. When missing it is
    inferred from the prediction text (over-/out-perform → 'win', else
    'loss'). Trades within ±1% are NEUTRAL.
    """
    if -1.0 < pnl_pct < 1.0:
        return OUTCOME_NEUTRAL
    expected = (expected_direction or "").lower() or _infer_expected_direction(prediction)
    won = pnl_pct > 0
    if expected == "win":
        return OUTCOME_SUPPORTING if won else OUTCOME_CONTRADICTING
    return OUTCOME_CONTRADICTING if won else OUTCOME_SUPPORTING


def _match_thinking_observations(closed_trade: dict, exit_reason: str, pnl_pct: float) -> None:
    """For every active hypothesis whose pattern strictly matches this closed
    trade, increment the evidence counter and log a knowledge_event carrying
    pnl_pct (the graduation step computes expectancy from those events)."""
    db = get_client()
    active = (
        db.table("signal_thinking")
        .select("*")
        .eq("status", "active")
        .execute()
    ).data or []
    for hypothesis in active:
        pattern = hypothesis.get("pattern_match") or {}
        if not _trade_matches_pattern(closed_trade, pattern, exit_reason):
            continue
        outcome = _classify_observation(
            hypothesis.get("prediction") or "", pnl_pct, hypothesis.get("expected_direction"),
        )
        field = {
            OUTCOME_SUPPORTING: "observations_supporting",
            OUTCOME_CONTRADICTING: "observations_contradicting",
        }.get(outcome, "observations_neutral")
        before = hypothesis.get(field) or 0
        after = before + 1
        try:
            db.table("signal_thinking").update({
                field: after,
                "last_evaluated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", hypothesis["id"]).execute()
        except Exception as e:
            logger.warning(f"Failed to bump {field} on hypothesis {hypothesis['id']}: {e}")
            continue
        log_event(
            EVENT_THINKING_OBSERVATION_ADDED,
            triggered_by="brain_close_hook",
            thinking_id=hypothesis["id"],
            trade_id=closed_trade.get("id"),
            observation_outcome=outcome,
            payload={
                "symbol": closed_trade.get("symbol"),
                "bucket": closed_trade.get("bucket"),
                "market_regime": closed_trade.get("market_regime"),
                "entry_score": closed_trade.get("entry_score"),
                "direction": closed_trade.get("direction") or "LONG",
                "pnl_pct": round(pnl_pct, 4),
                "exit_reason": exit_reason,
                "counter_field": field,
                "counter_before": before,
                "counter_after": after,
            },
            reason=(
                f"Trade {closed_trade.get('symbol')} closed {pnl_pct:+.2f}% ({exit_reason}) — "
                f"matches hypothesis \"{(hypothesis.get('hypothesis') or '')[:60]}\" — "
                f"{field}: {before} → {after}"
            ),
        )


def _flag_positions_for_review(
    db, all_open: list, symbol: str, action: str, score: int,
    reason: str, now_iso: str, notifications: BrainNotificationQueue,
) -> None:
    """Tag held positions of `symbol` as pending review at next market open.

    Called from the SELL/AVOID branch of `process_virtual_trades` when the
    market is closed and the held position is an equity (so the trade
    cannot actually fill). The flag tells `process_pending_reviews` to
    re-evaluate this position the next time the market is open.

    Args:
        db: Supabase client (passed in to avoid re-fetching).
        all_open: All currently-open virtual_trades, loaded once at the
            start of `process_virtual_trades` for in-memory iteration.
        symbol: Ticker symbol of the position to flag.
        action: The deteriorated action that triggered the flag — usually
            "SELL" or "AVOID".
        score: The fresh signal score that triggered the flag.
        reason: Human-readable reason (the signal's `reasoning` field).
            Truncated to 500 chars when stored, 200 when sent over Telegram.
        now_iso: Current UTC timestamp as ISO-8601 string. Stored in
            `pending_review_at`.
        notifications: Scan-local notification queue. A "brain_pending_review"
            entry is appended for each newly-flagged BRAIN position
            (watchlist positions are tracked silently — they're data
            collection only, not actionable).

    Idempotency: positions that ALREADY have a pending_review_at flag are
    skipped. This prevents alert spam if the user has multiple pre-market
    scans flag the same position twice in a row (e.g. 6am and 7am scans).
    """
    for pos in all_open:
        if pos["symbol"] != symbol:
            continue
        if pos.get("pending_review_at"):
            continue  # Already flagged, don't spam alerts
        entry_score = pos.get("entry_score", 0) or 0
        try:
            db.table("virtual_trades").update({
                "pending_review_at": now_iso,
                "pending_review_action": action,
                "pending_review_score": score,
                "pending_review_reason": (reason or "")[:500],
            }).eq("id", pos["id"]).execute()
        except Exception as e:
            logger.warning(f"Failed to flag {symbol} for review: {e}")
            continue
        logger.warning(
            f"Virtual REVIEW FLAGGED: {symbol} signal turned {action} "
            f"({entry_score}->{score}) — will re-check at market open"
        )
        # Only notify for brain positions (watchlist track is just data collection)
        if pos.get("source") == "brain":
            notifications.append(("brain_pending_review", {
                "symbol": symbol,
                "action": action,
                "entry_score": str(entry_score),
                "exit_score": str(score),
                "reason": reason[:200] if reason else "Signal deteriorated overnight",
            }))


def process_pending_reviews(
    signals: list[dict],
    notifications: BrainNotificationQueue,
) -> dict:
    """Re-evaluate positions flagged for review at a previous pre-market scan.

    This function implements step 3 of the pre-market review system (see
    file header). It runs at the START of every in-hours scan, BEFORE
    `process_virtual_trades`, on the same `signals` list reference.

    For each position with `pending_review_at` set:

      • The fresh signal for that ticker is looked up in `signals`.
      • If no fresh signal exists, the flag is left in place (retry next scan).
      • If `pending_review_action == "FORCE_SELL"` (user override via
        /forcesell), the fresh signal's `action` is mutated to "SELL"
        and a `_review_forced` marker is set so the score-drop guard
        in `process_virtual_trades` knows to bypass itself.
      • If the fresh signal is still SELL/AVOID → CONFIRMED. The flag is
        cleared. Because we operate on the SAME `signals` list reference
        that `process_virtual_trades` will iterate next, the SELL action
        propagates naturally and the sell executes in the same scan run.
      • If the fresh signal recovered to BUY/HOLD → CLEARED. The flag is
        cleared and a "brain_review_cleared" notification is queued.

    Args:
        signals: Fresh signals from the current scan. THIS FUNCTION MUTATES
            the signal dicts for forced-sell cases (sets `action` and
            `_review_forced`). The mutation is intentional — the same list
            reference is then iterated by `process_virtual_trades` which
            sees the mutated values.
        notifications: Scan-local queue. Appends `brain_review_cleared`
            entries for recovered brain positions (deduped by symbol so
            multiple positions for the same ticker only generate one alert).

    Returns:
        Dict with two counters:
            cleared: positions whose flag was cleared due to recovery.
            confirmed: positions whose flag was cleared due to confirmed
                deterioration (these will be sold by `process_virtual_trades`
                later in the same scan).

    Returns immediately with zero counts if the market is closed —
    pending reviews can only be processed during market hours.
    """
    if not _is_us_market_open():
        return {"cleared": 0, "confirmed": 0}

    db = get_client()
    flagged_result = (
        db.table("virtual_trades")
        .select("id, symbol, entry_score, source, pending_review_action, "
                "pending_review_score, pending_review_reason, target_price, stop_loss, "
                "bucket, signal_style")
        .eq("status", "OPEN")
        .not_.is_("pending_review_at", "null")
        .execute()
    )
    flagged = flagged_result.data or []
    if not flagged:
        return {"cleared": 0, "confirmed": 0}

    # Index fresh signals by symbol for O(1) lookup
    by_symbol: dict[str, dict] = {}
    for sig in signals:
        sym = sig.get("symbol")
        if sym:
            by_symbol[sym] = sig

    cleared = 0
    confirmed = 0
    notified_recovered: set[str] = set()  # Dedupe per-symbol "review cleared" notifications
    for pos in flagged:
        symbol = pos["symbol"]
        fresh = by_symbol.get(symbol)
        if not fresh:
            # No fresh signal for this ticker — leave the flag, retry next scan
            continue

        fresh_action = fresh.get("action")
        fresh_score = fresh.get("score", 0)
        entry_score = pos.get("entry_score", 0) or 0
        # Detect a user-forced sell via the sentinel value set by /forcesell.
        # This is more robust than parsing the reason text.
        forced = pos.get("pending_review_action") == "FORCE_SELL"

        # User-forced sell from /forcesell command: override the fresh signal
        # so process_virtual_trades sees a SELL action this scan and executes.
        # Also flag _review_forced so the SELL flow's score-drop guard
        # (which protects against AI methodology change false-AVOIDs)
        # doesn't accidentally block the user's explicit override.
        if forced:
            fresh["action"] = "SELL"
            fresh["_review_forced"] = True
            fresh_action = "SELL"
            logger.warning(
                f"Virtual REVIEW FORCED SELL: {symbol} (user override via /forcesell) "
                f"— executing this scan"
            )

        if fresh_action in ("SELL", "AVOID"):
            # Confirmed: clear the review flag. The regular SELL flow in
            # process_virtual_trades (which runs right after this on the same
            # scan, on the SAME `signals` list reference) will see the SELL
            # action and execute the sell since market is now open. We clear
            # the flag here so a future scan doesn't see a stale flag and
            # skip the SELL flow with another flagging operation.
            try:
                db.table("virtual_trades").update({
                    "pending_review_at": None,
                    "pending_review_action": None,
                    "pending_review_score": None,
                    "pending_review_reason": None,
                }).eq("id", pos["id"]).execute()
            except Exception as e:
                logger.warning(f"Failed to clear review flag for {symbol}: {e}")
            confirmed += 1
            logger.warning(
                f"Virtual REVIEW CONFIRMED: {symbol} still {fresh_action} "
                f"at open ({entry_score}->{fresh_score}) — will sell this scan"
            )
        else:
            # Recovered: clear the flag and notify
            try:
                db.table("virtual_trades").update({
                    "pending_review_at": None,
                    "pending_review_action": None,
                    "pending_review_score": None,
                    "pending_review_reason": None,
                }).eq("id", pos["id"]).execute()
            except Exception as e:
                logger.warning(f"Failed to clear review flag for {symbol}: {e}")
                continue
            cleared += 1
            logger.info(
                f"Virtual REVIEW CLEARED: {symbol} recovered to {fresh_action} "
                f"({entry_score}->{fresh_score}) — keeping position"
            )
            if pos.get("source") == "brain" and symbol not in notified_recovered:
                notified_recovered.add(symbol)
                notifications.append(("brain_review_cleared", {
                    "symbol": symbol,
                    "action": fresh_action,
                    "entry_score": str(entry_score),
                    "exit_score": str(fresh_score),
                }))

    return {"cleared": cleared, "confirmed": confirmed}


@dataclass
class BrainEntryContext:
    """Live book state threaded through one scan's entry decisions.

    Slots are always recounted from `open_book` (which is mutated as this
    scan closes and opens positions) — never from a stale counter.
    """
    uid: str | None
    equity: float
    cash: float
    peak_equity: float
    breaker_tripped: bool
    open_book: list[dict]                 # brain positions: symbol, sector, is_crypto, cost_usd, direction, id
    cooldown: dict[str, str]              # symbol -> reason
    open_watchlist: set[str]
    market_open: bool
    portfolio_heat: int = 0
    breaker_details: dict | None = None   # days elapsed / remaining while paused


def _book_entry(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "symbol": row.get("symbol"),
        "sector": row.get("sector"),
        "is_crypto": _is_crypto_symbol(row.get("symbol")),
        "cost_usd": float(row.get("position_size_usd") or 0),
        "direction": row.get("direction") or "LONG",
    }


def _estimate_equity(wallet_row: dict | None, open_rows: list[dict], price_by_symbol: dict[str, float]) -> float:
    """Wallet equity in USD without a network call.

    cash + collateral + Σ open LONG value (+ Σ SHORT unrealized). Open rows
    are marked at this scan's signal price when available, else at cost.
    """
    if not wallet_row:
        return 0.0
    equity = float(wallet_row.get("balance") or 0) + float(wallet_row.get("collateral_reserved") or 0)
    for r in open_rows:
        if r.get("source") != "brain" or not r.get("is_wallet_trade"):
            continue
        shares = float(r.get("shares") or 0)
        fx = float(r.get("fx_to_usd_entry") or 1.0)
        px = price_by_symbol.get(r.get("symbol"))
        if (r.get("direction") or "LONG") == "SHORT":
            if px:
                equity += (float(r.get("entry_price") or 0) - px) * shares * fx
        else:
            equity += (px * shares * fx) if px else float(r.get("position_size_usd") or 0)
    return equity


def _reentry_cooldown_symbols(db) -> dict[str, str]:
    """Symbols blocked from brain entry: same-symbol re-entry cooldown
    (brain_reentry_cooldown_days trading days after ANY exit) plus any legacy
    cooldowns whose config is still > 0 (all 0 by default)."""
    out: dict[str, str] = {}
    now = datetime.now(timezone.utc)
    n_days = settings.brain_reentry_cooldown_days
    if n_days > 0:
        cutoff = (now - timedelta(days=n_days * 2 + 4)).isoformat()
        try:
            rows = (
                db.table("virtual_trades")
                .select("symbol, exit_date")
                .eq("source", "brain")
                .eq("status", "CLOSED")
                .gte("exit_date", cutoff)
                .execute()
            ).data or []
        except Exception as e:
            logger.warning(f"re-entry cooldown query failed: {e}")
            rows = []
        today = now.date()
        for r in rows:
            ex = parse_iso_utc(r.get("exit_date"))
            if r.get("symbol") and ex and trading_days_between(ex.date(), today) < n_days:
                out[r["symbol"]] = f"reentry_cooldown_{n_days}d"

    legacy = [
        ("thesis_rebuy", settings.brain_thesis_rebuy_cooldown_minutes / 60.0,
         {"in_": ("exit_reason", ["THESIS_INVALIDATED", "TARGET_HIT"])}),
        ("watchdog_exit", settings.brain_watchdog_exit_cooldown_hours,
         {"in_": ("exit_reason", ["WATCHDOG_EXIT", "WATCHDOG_FORCE_SELL"])}),
        ("post_winner", settings.brain_post_winner_cooldown_hours, {"gt": ("pnl_amount", 0)}),
        ("post_loss", settings.brain_post_loss_cooldown_hours, {"lt": ("pnl_amount", 0)}),
    ]
    for name, hours, flt in legacy:
        if not hours or hours <= 0:
            continue
        try:
            q = (
                db.table("virtual_trades").select("symbol")
                .eq("source", "brain").eq("status", "CLOSED")
                .gte("exit_date", (now - timedelta(hours=hours)).isoformat())
            )
            for op, (col, val) in flt.items():
                q = getattr(q, op)(col, val)
            for r in (q.execute().data or []):
                if r.get("symbol"):
                    out.setdefault(r["symbol"], f"{name}_cooldown")
        except Exception as e:
            logger.warning(f"{name} cooldown query failed: {e}")
    return out


def _portfolio_heat(n_open: int, signals: list[dict]) -> int:
    """Legacy heat score (Day 8). Only computed when brain_portfolio_heat_enabled."""
    if not settings.brain_portfolio_heat_enabled:
        return 0
    heat = int(n_open >= 8) + int(n_open > 12)
    macro = next((s["macro_data"] for s in signals if s.get("macro_data")), None)
    if macro and macro.get("vix") is not None and macro["vix"] < 16:
        heat += 1
    return heat


def _classify_horizon(sig: dict, symbol: str) -> str:
    catalyst_days = sig.get("catalyst_days") or 999
    if _is_crypto_symbol(symbol, sig) or (sig.get("bucket") or "") == "HIGH_RISK" or catalyst_days <= 7:
        return "SHORT"
    return "LONG"


def _evaluate_brain_entry(sig: dict, ctx: BrainEntryContext, direction: str = "LONG") -> tuple[str | None, dict]:
    """Run every entry gate for one candidate. Returns (skip_reason, plan).

    skip_reason None → `plan` holds everything needed to open the trade.
    Otherwise `plan` carries whatever was computed (for brain_decisions).
    """
    symbol = sig.get("symbol")
    plan: dict = {"direction": direction}
    ref_price = float(sig.get("price_at_signal") or 0)
    if ref_price <= 0:
        return "no_price", plan

    if direction == "SHORT":
        tier, trust, tier_reason = _eval_brain_short_tier(sig)
    else:
        tier, trust, tier_reason = _eval_brain_trust_tier(sig, ctx.portfolio_heat)
    plan.update({"tier": tier, "trust": trust, "tier_reason": tier_reason})
    if direction == "LONG" and _entry_mode() == "filter" and is_ai_buy(sig):
        passed, reasons = brain_technical_filter(sig)
        plan["tech_filter"] = {"passed": passed, "reasons": reasons}
    if tier <= 0:
        return tier_reason, plan
    if not settings.wallet_enabled:
        return "wallet_disabled", plan

    if any(p["symbol"] == symbol for p in ctx.open_book) or symbol in ctx.open_watchlist:
        return "already_held", plan
    if direction == "LONG" and (sig.get("grok_data") or {}).get("_earnings_blackout"):
        return "earnings_blackout", plan
    if symbol in ctx.cooldown:
        return ctx.cooldown[symbol], plan
    if ctx.breaker_tripped:
        plan["breaker"] = {**(ctx.breaker_details or {}),
                           "equity": round(ctx.equity, 2), "peak": round(ctx.peak_equity, 2)}
        return "drawdown_breaker_pause", plan
    if not _is_tradable_now(symbol, ctx.market_open):
        return "market_closed", plan

    horizon = _classify_horizon(sig, symbol)
    plan["horizon"] = horizon
    if settings.brain_long_horizon_suspended and horizon == "LONG" and direction == "LONG":
        return "filter_d_long_horizon_suspended", plan

    fx = fx_to_usd(symbol)
    if not fx:
        return f"fx_unavailable_{native_currency(symbol)}", plan
    plan["fx"] = fx
    plan["currency"] = native_currency(symbol)

    fill = apply_slippage(ref_price, "SELL" if direction == "SHORT" else "BUY", symbol)
    levels = compute_entry_levels(sig, fill, direction)
    plan.update({"ref_price": ref_price, "fill": fill, "levels": levels})
    if levels["reason"]:
        return levels["reason"], plan

    risk_per_share_usd = abs(fill - levels["stop"]) * fx
    from app.services import wallet as wallet_svc
    shares, alloc = wallet_svc.calc_risk_position_size(
        ctx.equity, ctx.cash, fill * fx, fill * fx - risk_per_share_usd,
        trust_multiplier=trust,
    )
    if shares <= 0:
        return "size_below_minimum", plan

    sector = ((sig.get("fundamental_data") or {}).get("sector") or "").strip() or None
    is_crypto = _is_crypto_symbol(symbol, sig)
    alloc2, limit_reason = check_portfolio_limits(
        symbol=symbol, sector=sector, is_crypto=is_crypto,
        alloc_usd=alloc, equity_usd=ctx.equity, open_book=ctx.open_book,
    )
    if limit_reason:
        return limit_reason, plan
    if alloc2 < alloc:
        alloc = round(alloc2, 2)
        shares = round(alloc / (fill * fx), 6)
    plan.update({
        "shares": shares, "alloc_usd": alloc, "sector": sector, "is_crypto": is_crypto,
        "risk_usd": round(shares * risk_per_share_usd, 2),
    })
    return None, plan


def _correlation_gate(sig: dict, plan: dict, ctx: BrainEntryContext) -> str | None:
    """Portfolio correlation / beta gate, run AFTER `_evaluate_brain_entry`
    passed (so history is only fetched for real candidates). Kept out of
    `_evaluate_brain_entry` so offline callers (backtest) never hit the
    network. Returns a skip reason or None; details go to plan["correlation"].
    No-op (plan untouched) when brain_correlation_check_enabled is False.
    """
    if not settings.brain_correlation_check_enabled or plan.get("direction") != "LONG":
        return None
    from app.services import portfolio_risk

    try:
        check = portfolio_risk.check_correlation_limit(
            symbol=sig.get("symbol"), alloc_usd=float(plan.get("alloc_usd") or 0),
            equity_usd=ctx.equity, open_book=ctx.open_book,
        )
    except Exception as e:  # never block an entry on a risk-model bug
        logger.warning(f"Correlation gate error for {sig.get('symbol')}: {e}")
        plan["correlation"] = {"status": "skipped", "why": "error"}
        return None
    plan["correlation"] = check.details
    if check.reason:
        d = check.details
        logger.info(
            f"Brain SKIP {sig.get('symbol')}: {check.reason} (rule={d.get('rule')}, "
            f"max_corr={d.get('max_corr')} vs {d.get('max_corr_symbol')}, "
            f"cluster={d.get('cluster_symbols')}, beta={d.get('post_trade_beta')})"
        )
    return check.reason


def _open_brain_position(db, sig: dict, plan: dict, ctx: BrainEntryContext, now_iso: str) -> str | None:
    """Open a planned brain position with wallet-safe ordering.

    1. debit the wallet (raises → abort, nothing written)
    2. INSERT the trade row with a pre-generated id (fails → refund)
    3. append the ledger row (best-effort, references the trade id)
    """
    from app.services import wallet as wallet_svc

    symbol = sig["symbol"]
    short = plan["direction"] == "SHORT"
    commission = settings.brain_commission_usd
    alloc = float(plan["alloc_usd"])
    levels = plan["levels"]
    trade_id = str(uuid4())
    # LONG: cash out = alloc + entry commission (the whole debit is cost basis).
    # SHORT: alloc moves balance → collateral; both commissions settle at cover.
    cost_basis = round(alloc + (0.0 if short else commission), 4)
    try:
        if short:
            bal, coll = wallet_svc.adjust_balance(ctx.uid, -alloc, +alloc, symbol=symbol)
        else:
            bal, coll = wallet_svc.adjust_balance(ctx.uid, -cost_basis, 0.0, symbol=symbol)
    except wallet_svc.WalletError as e:
        logger.warning(f"Brain entry {symbol} aborted — wallet debit failed: {e}")
        return None

    row = {
        "id": trade_id,
        "user_id": ctx.uid,
        "symbol": symbol,
        "action": "SHORT_SELL" if short else "BUY",
        "direction": plan["direction"],
        "entry_price": round(plan["fill"], 6),
        "entry_ref_price": plan["ref_price"],
        "entry_date": now_iso,
        "entry_score": sig.get("score"),
        "status": "OPEN",
        "bucket": sig.get("bucket"),
        "signal_style": sig.get("signal_style"),
        "sector": plan.get("sector"),
        "source": "brain",
        "target_price": levels["target"],
        "stop_loss": levels["stop"],
        "initial_stop": levels["stop"],
        "entry_atr": levels["atr"],
        "entry_rr": levels["rr"],
        "entry_p_win": sig.get("p_win"),
        "entry_ai_signal": sig.get("ai_signal"),
        "entry_tier": plan["tier"],
        "trust_multiplier": plan["trust"],
        "tier_reason": f"{plan['tier_reason']}|levels={levels['source']}",
        "trade_horizon": plan.get("horizon") or "SHORT",
        "peak_price": None if short else round(plan["fill"], 6),
        "trough_price": round(plan["fill"], 6) if short else None,
        "market_regime": sig.get("market_regime"),
        "entry_thesis": (sig.get("reasoning") or "")[:500],
        "entry_thesis_keywords": _extract_thesis_keywords(sig),
        "shares": plan["shares"],
        "position_size_usd": round(alloc if short else cost_basis, 2),
        "is_wallet_trade": True,
        "currency": plan.get("currency") or "USD",
        "fx_to_usd_entry": plan["fx"],
        "fees_usd": 0.0 if short else commission,
    }
    try:
        db.table("virtual_trades").insert(row).execute()
    except Exception as e:
        logger.error(f"Brain entry {symbol}: trade INSERT failed ({e}) — refunding wallet")
        try:
            if short:
                wallet_svc.adjust_balance(ctx.uid, +alloc, -alloc, symbol=symbol, allow_overdraft=True)
            else:
                wallet_svc.adjust_balance(ctx.uid, +cost_basis, 0.0, symbol=symbol, allow_overdraft=True)
        except Exception as e2:
            logger.error(f"Brain entry {symbol}: REFUND FAILED ({e2}) — run reconcile_wallet")
        return None

    wallet_svc.record_transaction(
        ctx.uid,
        wallet_svc.TxnType.SHORT_OPEN if short else wallet_svc.TxnType.BUY,
        -alloc if short else -cost_basis,
        bal, coll,
        trade_id=trade_id, symbol=symbol, shares=plan["shares"], price=plan["fill"],
        description=(
            f"{'SHORT_OPEN' if short else 'BUY'} {plan['shares']:.4f} {symbol} @ {plan['fill']:.4f} "
            f"{plan.get('currency', 'USD')} (ref {plan['ref_price']:.4f}, fx {plan['fx']:.4f}, "
            f"stop {levels['stop']:.4f}, target {levels['target']:.4f}, R:R {levels['rr']})"
        ),
    )
    ctx.cash = bal
    ctx.open_book.append({
        "id": trade_id, "symbol": symbol, "sector": plan.get("sector"),
        "is_crypto": plan.get("is_crypto", False), "cost_usd": alloc, "direction": plan["direction"],
    })
    return trade_id


def _decision_row(scan_id, sig: dict, decision: str, reason: str, plan: dict | None, now_iso: str) -> dict:
    plan = plan or {}
    levels = plan.get("levels") or {}
    details = {
        "direction": plan.get("direction"),
        "tier": plan.get("tier"),
        "tier_reason": plan.get("tier_reason"),
        "action": sig.get("action"),
        "p_win": sig.get("p_win"),
        "ai_provider": sig.get("ai_provider"),
        "ref_price": plan.get("ref_price"),
        "fill": plan.get("fill"),
        "stop": levels.get("stop"),
        "target": levels.get("target"),
        "rr": levels.get("rr"),
        "levels_source": levels.get("source"),
        "shares": plan.get("shares"),
        "alloc_usd": plan.get("alloc_usd"),
        "risk_usd": plan.get("risk_usd"),
        "sector": plan.get("sector"),
        "trade_id": plan.get("trade_id"),
        "correlation": plan.get("correlation"),
        "confidence": sig.get("confidence"),
        "tech_filter": plan.get("tech_filter"),
        "breaker": plan.get("breaker"),
        "entry_mode": _entry_mode(),
    }
    return {
        "scan_id": scan_id or sig.get("scan_id"),
        "symbol": sig.get("symbol"),
        "decided_at": now_iso,
        "decision": decision,
        "reason": (reason or "")[:200],
        "score": sig.get("score"),
        "ai_status": sig.get("ai_status"),
        "ai_signal": sig.get("ai_signal"),
        "details": {k: v for k, v in details.items() if v is not None},
    }


def _apply_drawdown_breaker(wallet_row: dict | None, uid: str | None, equity: float,
                            peak: float, notifications: BrainNotificationQueue) -> BreakerState:
    """Evaluate the breaker for this scan, persist trip / resume, notify once.

    Tolerates a DB without migration 009 (no `breaker_tripped_at` column):
    the trip can't be persisted, so every scan re-evaluates as "not yet
    tripped" (blocked while in drawdown, no timed resume) and no Telegram
    notification is sent (it would repeat every scan).
    """
    now = datetime.now(timezone.utc)
    has_col = bool(wallet_row) and "breaker_tripped_at" in wallet_row
    if wallet_row and not has_col:
        logger.warning("brain_wallet.breaker_tripped_at missing — apply migration "
                       "009_breaker_reset.sql; drawdown pause/reset is not persisted")
    tripped_at = (wallet_row or {}).get("breaker_tripped_at") if has_col else None
    st = evaluate_drawdown_breaker(equity, peak, tripped_at, now)
    pct = settings.brain_max_drawdown_pct
    n = settings.brain_drawdown_pause_trading_days

    if st.event == "tripped":
        st.tripped_at = now.isoformat()
        logger.warning(
            f"Drawdown breaker TRIPPED: equity ${equity:,.2f} is "
            f"{(1 - equity / st.peak) * 100:.1f}% below peak ${st.peak:,.2f} "
            f"(limit {pct}%) — pausing new entries for {n} trading days"
        )
        if has_col and _persist_breaker_state(uid, tripped_at=st.tripped_at):
            notifications.append(("brain_breaker_tripped", {
                "equity": f"{equity:,.2f}", "peak": f"{st.peak:,.2f}",
                "dd": f"{(1 - equity / st.peak) * 100:.1f}", "limit": f"{pct:g}", "days": str(n),
            }))
    elif st.event == "resumed":
        logger.warning(
            f"Drawdown breaker RESUMED after {st.days_elapsed} trading days — "
            f"peak reset to equity ${equity:,.2f}"
        )
        if _persist_breaker_state(uid, tripped_at=None, peak_equity=equity):
            notifications.append(("brain_breaker_resumed", {
                "equity": f"{equity:,.2f}", "days": str(st.days_elapsed),
            }))
    elif st.blocked:
        logger.info(f"Drawdown breaker pause: {st.days_elapsed} trading days elapsed, "
                    f"{st.days_remaining} remaining — no new entries this scan")
    return st


def _persist_breaker_state(uid, **kw) -> bool:
    from app.services import wallet as wallet_svc
    return wallet_svc.set_breaker_state(uid, **kw)


def process_virtual_trades(
    signals: list[dict],
    watchlist_symbols: set[str],
    notifications: BrainNotificationQueue,
    scan_id: str | None = None,
) -> dict:
    """Run the brain's buy/sell decision loop over a scan's fresh signals.

    Per signal (in `brain_entry_sort_key` order — AI p_win, then AI
    confidence; score only in legacy brain_entry_mode="score"):
      1. SELL/AVOID → close held LONGs when `signal_exit_reason` says so
         (AI SELL/AVOID or user-forced); equities outside hours are flagged
         for review instead.
      2. AI BUY on a held SHORT → cover.
      3. Watchlist track (unchanged exploratory ledger, no wallet).
      4. Brain entry via `_evaluate_brain_entry` → `_open_brain_position`.
    Then (only if enabled) brain SHORT entries. Every signal produces one
    `brain_decisions` row (ENTER or SKIP + reason).

    Returns {"buys", "sells", "shorts", "skipped"}.
    """
    db = get_client()
    buys = sells = shorts_opened = 0
    now = datetime.now(timezone.utc).isoformat()
    market_open = _is_us_market_open()

    all_open = (
        db.table("virtual_trades")
        .select(VIRTUAL_TRADES_CLOSE_FIELDS + ", pending_review_at, consecutive_avoid_count")
        .eq("status", "OPEN")
        .execute()
    ).data or []

    open_watchlist = {r["symbol"] for r in all_open if r.get("source") != "brain"}
    brain_rows = [r for r in all_open if r.get("source") == "brain"]
    open_brain_short = {r["symbol"] for r in brain_rows if r.get("direction") == "SHORT"}

    brain_user_id = queries.get_brain_user_id()
    from app.services import wallet as wallet_svc
    wallet_row = wallet_svc.get_wallet(brain_user_id) if settings.wallet_enabled else None

    price_by_symbol = {
        s["symbol"]: float(s["price_at_signal"])
        for s in signals if s.get("symbol") and s.get("price_at_signal")
    }
    equity = _estimate_equity(wallet_row, brain_rows, price_by_symbol)
    net_deposits = (
        float((wallet_row or {}).get("total_deposited") or 0)
        - float((wallet_row or {}).get("total_withdrawn") or 0)
    )
    stored_peak = wallet_svc.update_peak_equity(brain_user_id, equity) if wallet_row else None
    # Net deposits are only the FALLBACK peak (no stored peak yet): after a
    # breaker reset the stored peak is legitimately below net deposits.
    peak = max(stored_peak if stored_peak else net_deposits, equity)
    breaker_state = _apply_drawdown_breaker(wallet_row, brain_user_id, equity, peak, notifications)
    peak = breaker_state.peak
    breaker = breaker_state.blocked

    ctx = BrainEntryContext(
        uid=brain_user_id,
        equity=equity,
        cash=float((wallet_row or {}).get("balance") or 0),
        peak_equity=peak,
        breaker_tripped=breaker,
        open_book=[_book_entry(r) for r in brain_rows],
        cooldown=_reentry_cooldown_symbols(db),
        open_watchlist=open_watchlist,
        market_open=market_open,
        portfolio_heat=_portfolio_heat(len(brain_rows), signals),
        breaker_details=breaker_state.details() if breaker else None,
    )

    decisions: dict[str, dict] = {}

    def _decide(sig: dict, decision: str, reason: str, plan: dict | None = None) -> None:
        sym = sig.get("symbol")
        if sym and (sym not in decisions or decision == "ENTER"):
            decisions[sym] = _decision_row(scan_id, sig, decision, reason, plan, now)

    def _drop_from_book(trade_id) -> None:
        ctx.open_book[:] = [p for p in ctx.open_book if p.get("id") != trade_id]

    # Entry order: AI p_win, then AI confidence (filter mode) — score only
    # in legacy "score" mode. Exits in the same loop are order-independent.
    signals = sorted(signals, key=brain_entry_sort_key)

    for sig in signals:
        symbol = sig.get("symbol")
        action = sig.get("action")
        price = sig.get("price_at_signal")
        score = sig.get("score", 0)
        if not symbol or not price:
            continue
        price = float(price)
        is_crypto = _is_crypto_symbol(symbol, sig)

        if action not in ("SELL", "AVOID"):
            for pos in all_open:
                if (pos["symbol"] == symbol and pos.get("source") == "brain"
                        and int(pos.get("consecutive_avoid_count") or 0) > 0):
                    db.table("virtual_trades").update({"consecutive_avoid_count": 0}) \
                        .eq("id", pos["id"]).eq("status", "OPEN").execute()
                    pos["consecutive_avoid_count"] = 0

        # ── 1. SELL / AVOID: close held LONG positions ──
        if action in ("SELL", "AVOID"):
            held = [p for p in all_open if p["symbol"] == symbol and (p.get("direction") or "LONG") != "SHORT"]
            if held and not is_crypto and not market_open:
                if signal_exit_reason(sig):
                    _flag_positions_for_review(
                        db, held, symbol, action, score,
                        sig.get("reasoning") or f"Pre-market signal turned {action}",
                        now, notifications,
                    )
                _decide(sig, "SKIP", f"action_{action.lower()}_market_closed")
                continue
            why = signal_exit_reason(sig)
            for pos in held:
                source = pos.get("source", "watchlist")
                if source == "brain" and not why:
                    logger.info(
                        f"Virtual SIGNAL exit NOT taken for {symbol}: action={action} but no AI "
                        f"SELL call (ai_signal={sig.get('ai_signal')}); stop manages risk"
                    )
                    continue
                entry_price = float(pos["entry_price"])
                pnl_now = _calc_pnl_pct(entry_price, price, "LONG")
                if source == "brain" and _exit_is_thesis_protected(pos, "SIGNAL", pnl_now):
                    logger.info(f"Virtual SIGNAL exit suppressed for {symbol} — valid thesis on a winner")
                    continue
                if (source == "brain" and (pos.get("trade_horizon") or "SHORT") == "LONG"
                        and not sig.get("_review_forced")):
                    new_count = int(pos.get("consecutive_avoid_count") or 0) + 1
                    threshold = settings.brain_long_signal_exit_threshold
                    if new_count < threshold:
                        db.table("virtual_trades").update({"consecutive_avoid_count": new_count}) \
                            .eq("id", pos["id"]).eq("status", "OPEN").execute()
                        continue
                close_res = close_virtual_trade(pos, price, "SIGNAL", score, exit_action=action, exit_date_iso=now)
                if close_res.get("skipped"):
                    continue
                sells += 1
                pos["_closed"] = True
                if source == "brain":
                    _drop_from_book(pos.get("id"))
                    if settings.brain_reentry_cooldown_days > 0:
                        ctx.cooldown[symbol] = f"reentry_cooldown_{settings.brain_reentry_cooldown_days}d"
                    is_win = close_res["pnl_pct"] > 0
                    notifications.append(("brain_sell", {
                        "symbol": symbol, "price": f"{price:.2f}",
                        "pnl": f"{close_res['pnl_pct']:+.1f}",
                        "reason": f"AI call turned {action} ({why})",
                        "entry_score": str(pos.get("entry_score", 0)), "exit_score": str(score),
                        "verdict": f"{'✅ Win' if is_win else '❌ Loss'} — logged for learning.",
                    }))
                else:
                    open_watchlist.discard(symbol)
            all_open = [p for p in all_open if not (p["symbol"] == symbol and p.get("_closed"))]
            if action == "AVOID" and settings.brain_short_entries_enabled:
                continue  # evaluated by the SHORT pass below
            _decide(sig, "SKIP", f"action_{action.lower()}")
            continue

        # ── 2. Cover a SHORT when Claude now calls BUY ──
        if symbol in open_brain_short and is_ai_buy(sig) and (is_crypto or market_open):
            for pos in [p for p in all_open if p["symbol"] == symbol and p.get("direction") == "SHORT"]:
                close_res = close_virtual_trade(pos, price, "SIGNAL", score, exit_action=action, exit_date_iso=now)
                if close_res.get("skipped"):
                    continue
                sells += 1
                open_brain_short.discard(symbol)
                _drop_from_book(pos.get("id"))
                ctx.cooldown[symbol] = "reentry_cooldown_after_cover"

        if not is_crypto and not market_open:
            _decide(sig, "SKIP", "market_closed")
            continue

        # ── 3. Watchlist track (exploratory, no wallet) ──
        if (action == "BUY" and symbol in watchlist_symbols and score >= 62
                and symbol not in open_watchlist
                and not any(p["symbol"] == symbol for p in ctx.open_book)):
            db.table("virtual_trades").insert({
                "user_id": brain_user_id, "symbol": symbol, "action": "BUY",
                "entry_price": price, "entry_date": now, "entry_score": score, "status": "OPEN",
                "bucket": sig.get("bucket"), "signal_style": sig.get("signal_style"),
                "source": "watchlist", "target_price": sig.get("target_price"),
                "stop_loss": sig.get("stop_loss"), "market_regime": sig.get("market_regime"),
                "is_wallet_trade": False,
            }).execute()
            buys += 1
            open_watchlist.add(symbol)

        # ── 4. Brain entry ──
        reason, plan = _evaluate_brain_entry(sig, ctx, "LONG")
        if not reason:
            reason = _correlation_gate(sig, plan, ctx)
        if reason:
            _decide(sig, "SKIP", reason, plan)
            logger.debug(f"Brain SKIP {symbol} (score {score}): {reason}")
            continue
        trade_id = _open_brain_position(db, sig, plan, ctx, now)
        if not trade_id:
            _decide(sig, "SKIP", "open_failed", plan)
            continue
        plan["trade_id"] = trade_id
        _decide(sig, "ENTER", plan["tier_reason"], plan)
        buys += 1
        levels = plan["levels"]
        logger.info(
            f"Virtual BUY [brain]: {symbol} {plan['shares']:.4f} @ {plan['fill']:.4f} "
            f"(ref {plan['ref_price']:.4f}, score {score}, stop {levels['stop']:.4f}, "
            f"target {levels['target']:.4f}, R:R {levels['rr']}, ${plan['alloc_usd']:.2f}, "
            f"risk ${plan['risk_usd']:.2f})"
        )
        notifications.append(("brain_buy", {
            "symbol": symbol, "score": str(score), "bucket": sig.get("bucket", ""),
            "price": f"{plan['fill']:.2f}", "target": f"{levels['target']:.2f}",
            "stop": f"{levels['stop']:.2f}", "rr": f"{levels['rr']:.1f}",
            "tier": str(plan["tier"]), "trust": f"{int(plan['trust'] * 100)}",
        }))
        try:
            from app.scanners.universe import get_exchange
            queries.upsert_ticker(symbol, name=sig.get("company_name", ""),
                                  exchange=get_exchange(symbol), bucket=sig.get("bucket"))
        except Exception:
            pass

    # ── 5. Brain SHORT entries (off by default) ──
    if settings.brain_short_entries_enabled:
        for sig in signals:
            symbol = sig.get("symbol")
            if not symbol or sig.get("action") != "AVOID" or not sig.get("price_at_signal"):
                continue
            reason, plan = _evaluate_brain_entry(sig, ctx, "SHORT")
            if reason:
                _decide(sig, "SKIP", f"short:{reason}", plan)
                continue
            trade_id = _open_brain_position(db, sig, plan, ctx, now)
            if not trade_id:
                _decide(sig, "SKIP", "short:open_failed", plan)
                continue
            plan["trade_id"] = trade_id
            _decide(sig, "ENTER", f"short:{plan['tier_reason']}", plan)
            shorts_opened += 1
            open_brain_short.add(symbol)

    # ── 6. Decision funnel log ──
    if decisions:
        try:
            queries.insert_brain_decisions(list(decisions.values()))
        except Exception as e:
            logger.warning(f"brain_decisions insert failed ({len(decisions)} rows): {e}")
        funnel = Counter(
            (d["decision"] if d["decision"] == "ENTER" else d["reason"].split("_")[0])
            for d in decisions.values()
        )
        logger.info(f"Brain funnel: {dict(funnel)}")

    return {
        "buys": buys, "sells": sells, "shorts": shorts_opened,
        "skipped": sum(1 for d in decisions.values() if d["decision"] == "SKIP"),
    }


async def flush_brain_notifications(notifications: BrainNotificationQueue) -> int:
    """Drain the scan-local brain notification queue into the Telegram background worker.

    This is the ONLY function in this module that emits Telegram messages.
    Every other function APPENDS to the queue; this one drains it into the
    background `enqueue()` path so the scan NEVER blocks on Telegram HTTP.

    Before 2026-04-10: this function awaited `send_message()` per item —
    up to 150s of Telegram HTTP blocking inside the scan coroutine. That
    starved Claude Local subprocesses and caused AI synthesis failures
    when Telegram was slow or a login OTP collided with the scan.

    Now: each notification is enqueued instantly. The background worker in
    `telegram_bot._telegram_worker()` handles delivery + retry. The scan
    continues immediately after enqueue.

    Args:
        notifications: The scan-local queue threaded through every brain
            function this scan run. Will be cleared after enqueuing.

    Returns:
        Count of notifications enqueued. The queue is always cleared at
        the end regardless — the same notification should never be sent
        twice.
    """
    if not notifications:
        return 0
    from app.notifications.messages import msg
    from app.notifications.telegram_bot import enqueue
    sent = 0
    for key, kwargs in list(notifications):
        try:
            enqueue(settings.telegram_chat_id, msg(key, **kwargs))
            sent += 1
        except Exception as e:
            logger.debug(f"Brain notification enqueue failed ({key}): {e}")
    notifications.clear()
    return sent


# ── Direction-aware helpers (LONG vs SHORT) ──────────────────────

def _calc_pnl_pct(entry_price: float, current_price: float, direction: str) -> float:
    """P&L percentage respecting trade direction.

    LONG:  profit when price rises   → (current - entry) / entry
    SHORT: profit when price drops   → (entry - current) / entry
    """
    if direction == "SHORT":
        return (entry_price - current_price) / entry_price * 100
    return (current_price - entry_price) / entry_price * 100


def _calc_pnl_amount(entry_price: float, current_price: float, direction: str) -> float:
    """Dollar P&L per share respecting trade direction."""
    if direction == "SHORT":
        return entry_price - current_price
    return current_price - entry_price


# Column list for any SELECT that feeds `close_virtual_trade` / `evaluate_exit`.
# Requires migration 006 (initial_stop, entry_atr, sector, currency, fx_to_usd_entry, fees_usd).
VIRTUAL_TRADES_CLOSE_FIELDS = (
    "id, user_id, symbol, entry_price, entry_date, entry_score, source, "
    "bucket, signal_style, entry_tier, sector, market_regime, target_price, stop_loss, "
    "initial_stop, entry_atr, direction, trade_horizon, "
    "thesis_last_status, peak_price, trough_price, "
    "shares, position_size_usd, is_wallet_trade, currency, fx_to_usd_entry, fees_usd"
)


def _mark_to_market_one(
    *,
    entry_price: float,
    current_price: float,
    direction: str,
    is_wallet_trade: bool,
    shares: float,
    fx: float = 1.0,
) -> float:
    """USD value one open brain position contributes to wallet equity.

      • Wallet LONG : shares × current_price × fx
      • Wallet SHORT: (entry − current) × shares × fx (collateral lives in the wallet)
      • Non-wallet  : 0 (watchlist / legacy rows are not wallet money)
    """
    if not is_wallet_trade:
        return 0.0
    if (direction or "LONG").upper() == "SHORT":
        return (entry_price - current_price) * shares * fx
    return current_price * shares * fx


def _row_fx(row: dict) -> float:
    """Current native→USD rate for a row (falls back to the entry rate)."""
    fx = fx_to_usd(row.get("symbol")) if native_currency(row.get("symbol")) != "USD" else 1.0
    return float(fx or row.get("fx_to_usd_entry") or 1.0)


def calculate_brain_holdings_value(
    user_id: str | None = None,
    *,
    legacy_only: bool = False,
    strict: bool = False,
) -> float:
    """Sum the USD mark-to-market value of open brain WALLET positions.

    `legacy_only` / `strict` are kept for wallet.deposit's first-deposit
    snapshot; after the 2026-09 reset there are no legacy rows, so a
    legacy_only call returns 0.
    """
    from app.services.wallet import _resolve_user_id, LegacySnapshotFailed

    if legacy_only:
        return 0.0
    uid = _resolve_user_id(user_id)
    if not uid:
        return 0.0
    try:
        rows = (
            get_client().table("virtual_trades")
            .select("symbol, shares, entry_price, direction, is_wallet_trade, position_size_usd, fx_to_usd_entry")
            .eq("user_id", uid).eq("status", "OPEN").eq("source", "brain")
            .execute()
        ).data or []
        if not rows:
            return 0.0
        price_map = _fetch_prices_batch(list({r["symbol"] for r in rows if r.get("symbol")}))
        total = 0.0
        missing: list[str] = []
        for r in rows:
            px = (price_map.get(r["symbol"]) or (None, None))[0]
            if not px:
                missing.append(r["symbol"])
                if (r.get("direction") or "LONG") != "SHORT" and r.get("is_wallet_trade"):
                    total += float(r.get("position_size_usd") or 0)  # mark at cost
                continue
            total += _mark_to_market_one(
                entry_price=float(r.get("entry_price") or 0), current_price=float(px),
                direction=r.get("direction") or "LONG", is_wallet_trade=bool(r.get("is_wallet_trade")),
                shares=float(r.get("shares") or 0), fx=_row_fx(r),
            )
        if missing and strict:
            raise LegacySnapshotFailed(f"Could not price: {', '.join(missing)}")
        return total
    except LegacySnapshotFailed:
        raise
    except Exception as e:
        if strict:
            raise LegacySnapshotFailed(f"Holdings snapshot failed: {e}") from e
        logger.warning(f"calculate_brain_holdings_value failed: {e}")
        return 0.0


def _sum_holdings_from_enriched(enriched_open: list[dict]) -> float:
    """Sum USD holdings from rows already enriched by get_virtual_summary."""
    total = 0.0
    for t in enriched_open:
        if t.get("source") != "brain" or not t.get("is_wallet_trade"):
            continue
        if t.get("current_price") is None:
            if (t.get("direction") or "LONG") != "SHORT":
                total += float(t.get("position_size_usd") or 0)
            continue
        total += _mark_to_market_one(
            entry_price=float(t.get("entry_price") or 0),
            current_price=float(t["current_price"]),
            direction=t.get("direction") or "LONG",
            is_wallet_trade=True,
            shares=float(t.get("shares") or 0),
            fx=float(t.get("fx_to_usd") or 1.0),
        )
    return total


def compute_close_amounts(trade: dict, exit_ref_price: float, fx_exit: float | None = None) -> dict:
    """Pure P&L math for closing `trade` at quoted price `exit_ref_price`.

    Applies exit slippage (+ commission for wallet trades) and FX. Returns
    {"fill", "pnl_pct", "pnl_usd", "balance_delta", "collateral_delta",
     "fees_usd", "fx"}. For non-wallet rows pnl_usd is per-share and the
    wallet deltas are 0.
    """
    symbol = trade.get("symbol")
    direction = trade.get("direction") or "LONG"
    short = direction == "SHORT"
    entry = float(trade["entry_price"])
    fill = apply_slippage(exit_ref_price, "BUY" if short else "SELL", symbol)
    is_wallet = bool(trade.get("is_wallet_trade"))
    shares = float(trade.get("shares") or 0)
    fx = float(fx_exit or trade.get("fx_to_usd_entry") or 1.0)
    if not (is_wallet and shares > 0):
        return {
            "fill": fill, "pnl_pct": _calc_pnl_pct(entry, fill, direction),
            "pnl_usd": _calc_pnl_amount(entry, fill, direction),
            "balance_delta": 0.0, "collateral_delta": 0.0, "fees_usd": 0.0, "fx": fx,
        }
    commission = settings.brain_commission_usd
    cost = float(trade.get("position_size_usd") or 0)
    if short:
        fees = 2 * commission
        pnl_usd = (entry - fill) * shares * fx - fees
        balance_delta, collateral_delta = cost + pnl_usd, -cost
    else:
        fees = commission
        proceeds = shares * fill * fx - commission
        pnl_usd = proceeds - cost
        balance_delta, collateral_delta = proceeds, 0.0
    pnl_pct = (pnl_usd / cost * 100) if cost > 0 else _calc_pnl_pct(entry, fill, direction)
    return {
        "fill": fill, "pnl_pct": pnl_pct, "pnl_usd": pnl_usd,
        "balance_delta": balance_delta, "collateral_delta": collateral_delta,
        "fees_usd": fees + float(trade.get("fees_usd") or 0), "fx": fx,
    }


def close_virtual_trade(
    trade: dict,
    exit_price: float,
    exit_reason: str,
    exit_score: int | None,
    exit_action: str | None = None,
    exit_date_iso: str | None = None,
) -> dict:
    """The one close path: costs + FX, wallet settlement, DB update, learning.

    Wallet-safe ordering (see wallet.py ATOMICITY):
      1. credit the wallet (fails → abort; the row stays OPEN and the next
         pass retries),
      2. UPDATE the row to CLOSED guarded by status='OPEN' (0 rows → another
         path already closed it → reverse the credit; error → reverse),
      3. ledger row, 4. learning loop.

    `exit_price` is the QUOTED price; the stored exit_price is the fill after
    slippage. pnl_amount = USD P&L net of slippage/fees/FX for wallet trades.
    Returns {"pnl_pct", "pnl_amount_stored", "is_win"} (+ "skipped": True
    when nothing was closed).
    """
    grace_hours = settings.new_position_grace_hours
    if exit_reason in ("THESIS_INVALIDATED", "QUALITY_PRUNE") and grace_hours > 0:
        entry_dt = parse_iso_utc(trade.get("entry_date"))
        if entry_dt is not None:
            age_h = (datetime.now(timezone.utc) - entry_dt).total_seconds() / 3600
            if age_h < grace_hours:
                logger.info(f"Day-0 grace: {exit_reason} suppressed for {trade.get('symbol')} ({age_h:.1f}h)")
                return {"pnl_pct": 0, "pnl_amount_stored": 0, "is_win": False, "skipped": True}

    from app.services import wallet as wallet_svc

    db = get_client()
    sym = trade["symbol"]
    direction = trade.get("direction") or "LONG"
    is_wallet = bool(trade.get("is_wallet_trade")) and float(trade.get("shares") or 0) > 0
    fx_exit = _row_fx(trade) if is_wallet else None
    amounts = compute_close_amounts(trade, float(exit_price), fx_exit)
    pnl_pct, pnl_usd = amounts["pnl_pct"], amounts["pnl_usd"]
    is_win = pnl_usd > 0
    user_id = trade.get("user_id")

    # 1. credit first
    new_bal = new_coll = None
    if is_wallet:
        try:
            new_bal, new_coll = wallet_svc.adjust_balance(
                user_id, amounts["balance_delta"], amounts["collateral_delta"],
                symbol=sym, allow_overdraft=True,
            )
        except wallet_svc.WalletError as e:
            logger.error(f"close_virtual_trade {sym} ({exit_reason}) aborted — wallet credit failed: {e}")
            return {"pnl_pct": pnl_pct, "pnl_amount_stored": pnl_usd, "is_win": is_win,
                    "skipped": True, "error": str(e)}

    def _reverse() -> None:
        if not is_wallet:
            return
        try:
            wallet_svc.adjust_balance(user_id, -amounts["balance_delta"], -amounts["collateral_delta"],
                                      symbol=sym, allow_overdraft=True)
        except Exception as e:
            logger.error(f"close_virtual_trade {sym}: credit REVERSAL failed ({e}) — run reconcile_wallet")

    now_iso = exit_date_iso or datetime.now(timezone.utc).isoformat()
    patch: dict = {
        "status": "CLOSED",
        "exit_price": round(amounts["fill"], 6),
        "exit_ref_price": float(exit_price),
        "exit_date": now_iso,
        "exit_score": exit_score,
        "pnl_pct": round(pnl_pct, 4),
        "pnl_amount": round(pnl_usd, 4),
        "is_win": is_win,
        "exit_reason": exit_reason,
        "fees_usd": round(amounts["fees_usd"], 4),
    }
    if is_wallet:
        patch["fx_to_usd_exit"] = amounts["fx"]
    if exit_action is not None:
        patch["exit_action"] = exit_action

    # 2. guarded close
    try:
        update_result = (
            db.table("virtual_trades").update(patch)
            .eq("id", trade["id"]).eq("status", "OPEN").execute()
        )
    except Exception as e:
        logger.error(f"close_virtual_trade {sym}: UPDATE failed ({e}) — reversing wallet credit")
        _reverse()
        return {"pnl_pct": pnl_pct, "pnl_amount_stored": pnl_usd, "is_win": is_win,
                "skipped": True, "error": str(e)}
    if not (update_result.data or []):
        logger.info(f"close_virtual_trade: {sym} already closed by another path ({exit_reason})")
        _reverse()
        return {"pnl_pct": pnl_pct, "pnl_amount_stored": pnl_usd, "is_win": is_win, "skipped": True}

    # 3. ledger
    if is_wallet:
        short = direction == "SHORT"
        wallet_svc.record_transaction(
            user_id,
            wallet_svc.TxnType.SHORT_COVER if short else wallet_svc.TxnType.SELL,
            amounts["balance_delta"], new_bal, new_coll,
            trade_id=trade["id"], symbol=sym, shares=float(trade.get("shares") or 0),
            price=amounts["fill"],
            description=(
                f"{'SHORT_COVER' if short else 'SELL'} {float(trade.get('shares') or 0):.4f} {sym} "
                f"@ {amounts['fill']:.4f} (ref {float(exit_price):.4f}, fx {amounts['fx']:.4f}) "
                f"P&L ${pnl_usd:+.2f}, {exit_reason}"
            ),
        )

    # 4. learning
    try:
        _record_brain_outcome({**trade, "exit_reason": exit_reason}, amounts["fill"],
                              exit_score, exit_reason, pnl_pct)
    except Exception as e:
        logger.warning(f"Failed to record outcome for {sym}: {e}")

    return {"pnl_pct": pnl_pct, "pnl_amount_stored": pnl_usd, "is_win": is_win}


def _is_stop_hit(current_price: float, stop_loss: float, direction: str) -> bool:
    if direction == "SHORT":
        return current_price >= stop_loss
    return current_price <= stop_loss


def _is_target_hit(current_price: float, target_price: float, direction: str) -> bool:
    if direction == "SHORT":
        return current_price <= target_price
    return current_price >= target_price


def persist_exit_state(db, trade: dict, decision: ExitDecision) -> None:
    """Write a ratcheted stop / new peak / new trough back to the OPEN row."""
    if not decision.changed:
        return
    patch: dict = {"stop_loss": round(decision.stop, 6)} if decision.stop is not None else {}
    if decision.peak is not None:
        patch["peak_price"] = round(decision.peak, 6)
    if decision.trough is not None:
        patch["trough_price"] = round(decision.trough, 6)
    if not patch:
        return
    try:
        db.table("virtual_trades").update(patch).eq("id", trade["id"]).eq("status", "OPEN").execute()
        trade.update(patch)
    except Exception as e:
        logger.warning(f"persist_exit_state failed for {trade.get('symbol')}: {e}")


def check_virtual_exits(notifications: BrainNotificationQueue) -> dict:
    """Apply the shared exit policy (`evaluate_exit`) to every open trade.

    Price-driven: STOP_HIT / TRAILING_STOP / TARGET_HIT / TIME_EXPIRED.
    Equities are only processed when they can fill (session + exchange
    open); crypto always. Runs every scan (even with no new signals) and
    uses the same function as the watchdog, so the two never disagree.
    """
    db = get_client()
    open_trades = (
        db.table("virtual_trades").select(VIRTUAL_TRADES_CLOSE_FIELDS).eq("status", "OPEN").execute()
    ).data or []
    counters = {"stops_hit": 0, "targets_hit": 0, "profit_takes": 0, "expired": 0}
    if not open_trades:
        return counters

    market_open = _is_us_market_open()
    tradable = [t for t in open_trades if _is_tradable_now(t["symbol"], market_open)]
    if not tradable:
        return counters
    prices = _fetch_prices_batch(list({t["symbol"] for t in tradable}))
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    bucket = {"STOP_HIT": "stops_hit", "TARGET_HIT": "targets_hit",
              "TRAILING_STOP": "profit_takes", "TIME_EXPIRED": "expired"}

    for trade in tradable:
        symbol = trade["symbol"]
        current_price, _ = prices.get(symbol, (None, None))
        if not current_price:
            continue
        decision = evaluate_exit(trade, current_price, now=now)
        persist_exit_state(db, trade, decision)
        if not decision.reason:
            continue
        close_res = close_virtual_trade(trade, float(current_price), decision.reason, None, exit_date_iso=now_iso)
        if close_res.get("skipped"):
            continue
        counters[bucket.get(decision.reason, "expired")] += 1
        logger.info(
            f"Virtual EXIT [{trade.get('source')}]: {symbol} {decision.reason} @ {current_price:.4f} "
            f"(P&L {close_res['pnl_pct']:+.2f}%, ${close_res['pnl_amount_stored']:+.2f}; {decision.detail})"
        )
        if trade.get("source") == "brain":
            notifications.append(("brain_sell", {
                "symbol": symbol, "price": f"{current_price:.2f}",
                "pnl": f"{close_res['pnl_pct']:+.1f}",
                "reason": f"{decision.reason}: {decision.detail}",
                "entry_score": str(trade.get("entry_score", 0)), "exit_score": "-",
                "verdict": f"{'✅ Win' if close_res['is_win'] else '❌ Loss'} — logged for learning.",
            }))

    if any(counters.values()):
        logger.info(f"Virtual exits: {counters}")
    return counters


_vp_cache = TTLCache(max_size=2, default_ttl=300)


@with_retry
def get_brain_tier_breakdown() -> dict:
    """Get brain trade performance broken down by entry tier.

    Returns counts, win rate, and avg P&L for each tier (1=validated,
    2=low_confidence, 3=tech_only). Includes both open and closed trades.
    Cached for 5 minutes.

    Returns:
        {
            "tiers": [
                {
                    "tier": 1,
                    "label": "Validated",
                    "trust_pct": 100,
                    "open_count": int,
                    "closed_count": int,
                    "win_rate": float (0-1),
                    "avg_pnl_pct": float,
                    "best_pnl_pct": float | None,
                    "worst_pnl_pct": float | None,
                },
                ...
            ],
            "total_brain_trades": int,
            "trades_with_tier": int,
        }
    """
    cached = _vp_cache.get("tier_breakdown")
    if cached is not None:
        return cached

    db = get_client()
    try:
        result = (
            db.table("virtual_trades")
            .select("entry_tier, status, is_win, pnl_pct")
            .eq("source", "brain")
            .execute()
        )
        rows = result.data or []
    except Exception as e:
        logger.warning(f"Failed to fetch tier breakdown: {e}")
        return {"tiers": [], "total_brain_trades": 0, "trades_with_tier": 0}

    tier_meta = {
        1: {"label": "Validated AI", "trust_pct": 100},
        2: {"label": "Low Confidence", "trust_pct": 50},
        3: {"label": "Tech-Only Confirmed", "trust_pct": 50},
    }

    # Bucket rows by tier
    by_tier: dict[int, dict] = {
        1: {"open": 0, "closed": [], "wins": 0},
        2: {"open": 0, "closed": [], "wins": 0},
        3: {"open": 0, "closed": [], "wins": 0},
    }
    trades_with_tier = 0
    for row in rows:
        tier = row.get("entry_tier")
        if tier not in (1, 2, 3):
            continue
        trades_with_tier += 1
        if row.get("status") == "OPEN":
            by_tier[tier]["open"] += 1
        else:
            pnl = row.get("pnl_pct")
            if pnl is not None:
                by_tier[tier]["closed"].append(float(pnl))
            if row.get("is_win"):
                by_tier[tier]["wins"] += 1

    tiers_out = []
    for tier_num in (1, 2, 3):
        bucket = by_tier[tier_num]
        closed_count = len(bucket["closed"])
        win_rate = (bucket["wins"] / closed_count) if closed_count > 0 else 0.0
        avg_pnl = (sum(bucket["closed"]) / closed_count) if closed_count > 0 else 0.0
        best = max(bucket["closed"]) if bucket["closed"] else None
        worst = min(bucket["closed"]) if bucket["closed"] else None
        tiers_out.append({
            "tier": tier_num,
            "label": tier_meta[tier_num]["label"],
            "trust_pct": tier_meta[tier_num]["trust_pct"],
            "open_count": bucket["open"],
            "closed_count": closed_count,
            "win_rate": round(win_rate, 4),
            "avg_pnl_pct": round(avg_pnl, 2),
            "best_pnl_pct": round(best, 2) if best is not None else None,
            "worst_pnl_pct": round(worst, 2) if worst is not None else None,
        })

    summary = {
        "tiers": tiers_out,
        "total_brain_trades": len(rows),
        "trades_with_tier": trades_with_tier,
    }
    _vp_cache.set("tier_breakdown", summary, ttl=300)
    return summary


def get_virtual_summary() -> dict:
    """Get virtual portfolio performance summary for the dashboard.

    Includes live P&L for open positions via current price fetch.
    Cached for 5 minutes to avoid repeated DB + price queries on every page load.
    """
    cached = _vp_cache.get("summary")
    if cached is not None:
        return cached

    db = get_client()

    # All trades. Wallet fields (shares, position_size_usd, is_wallet_trade)
    # are pulled so the frontend can render "6.06 shares @ $164.96 ($1,000
    # invested)" and distinguish wallet trades from legacy 1-share rows.
    open_result = (
        db.table("virtual_trades")
        .select("symbol, entry_price, entry_date, entry_score, bucket, signal_style, source, "
                "target_price, stop_loss, thesis_last_status, tier_reason, trade_horizon, "
                "direction, consecutive_avoid_count, initial_stop, entry_rr, sector, "
                "shares, position_size_usd, is_wallet_trade, currency, fx_to_usd_entry")
        .eq("status", "OPEN")
        .order("entry_date", desc=True)
        .execute()
    )
    open_trades = open_result.data or []

    closed_result = (
        db.table("virtual_trades")
        .select("symbol, entry_price, exit_price, pnl_pct, pnl_amount, is_win, "
                "entry_date, exit_date, entry_score, exit_score, bucket, source, exit_reason, "
                "peak_price, entry_thesis, thesis_last_reason, tier_reason, trade_horizon, direction, "
                "shares, position_size_usd, is_wallet_trade")
        .eq("status", "CLOSED")
        .order("exit_date", desc=True)
        .limit(50)
        .execute()
    )
    closed_trades = closed_result.data or []

    # Fetch current prices for open positions
    now = datetime.now(timezone.utc)
    current_prices = {}
    signal_context = {}
    if open_trades:
        symbols = list({t["symbol"] for t in open_trades})
        price_data = _fetch_prices_batch(symbols)
        current_prices = {sym: p for sym, (p, _) in price_data.items() if p is not None}

        # Batch fetch latest signal context for all open symbols (1 query instead of N)
        sig_result = (
            db.table("signals")
            .select("symbol, score, reasoning, risk_reward, signal_style, contrarian_score, market_regime")
            .in_("symbol", symbols)
            .order("created_at", desc=True)
            .execute()
        )
        for row in (sig_result.data or []):
            sym = row.get("symbol")
            if sym and sym not in signal_context:
                signal_context[sym] = row

    def _build_exit_context(t: dict) -> str:
        """Build a one-line human-readable explanation of why a trade was closed."""
        reason = t.get("exit_reason", "")
        peak = t.get("peak_price")
        entry = float(t.get("entry_price") or 0)
        exit_px = float(t.get("exit_price") or 0)
        thesis_reason = t.get("thesis_last_reason") or ""

        if reason == "TRAILING_STOP" and peak:
            peak_pnl = ((float(peak) - entry) / entry * 100) if entry else 0
            drop_pct = ((float(peak) - exit_px) / float(peak) * 100) if float(peak) else 0
            thesis = t.get("thesis_last_status") or "unknown"
            return (
                f"Peak ${float(peak):.2f} (+{peak_pnl:.1f}%), dropped {drop_pct:.1f}% from peak. "
                f"Thesis was {thesis} — {'price drop confirmed weakness' if thesis != 'valid' else 'hard safety net triggered'}"
            )
        if reason == "TARGET_HIT":
            target = t.get("target_price")
            return f"Hit target ${float(target):.2f}" if target else "Hit AI-generated target"
        if reason == "STOP_HIT":
            stop = t.get("stop_loss")
            return f"Hit stop loss ${float(stop):.2f}" if stop else "Hit stop loss"
        if reason == "THESIS_INVALIDATED":
            snippet = thesis_reason[:120].strip()
            return f"Thesis invalidated: {snippet}" if snippet else "Thesis invalidated by Stage 6 re-eval"
        if reason == "WATCHDOG_EXIT":
            snippet = thesis_reason[:120].strip()
            return f"Watchdog: bearish sentiment + price drop" + (f". {snippet}" if snippet else "")
        if reason == "TIME_EXPIRED":
            return f"Held the maximum {settings.brain_max_hold_days} days without hitting target or stop"
        if reason == "QUALITY_PRUNE":
            thesis = t.get("thesis_last_status") or "none"
            return f"Pruned: losing position with {thesis} thesis — slot freed for a stronger pick"
        if reason == "STAGNATION_PRUNE":
            thesis = t.get("thesis_last_status") or "none"
            return f"Stagnation prune: held a week+ with no meaningful movement and {thesis} thesis — dead capital, slot freed"
        if reason == "ROTATION":
            return "Rotated out for a stronger candidate"
        return reason or "Unknown"

    def _calc_stats(trades: list[dict]) -> dict:
        # pnl_amount semantics depend on is_wallet_trade: wallet trades
        # store TOTAL dollars, legacy trades store per-share. Summing
        # across the mix is apples-and-oranges, so the two totals are
        # reported separately. The frontend picks whichever is non-zero
        # or renders both when migration populations coexist.
        #
        # ⚠ Day-21 deprecation: `total_return_pct` below sums per-trade
        # pnl_pct values, which is mathematically meaningless because each
        # trade has a different cost basis. Example: -10% on $1k + +5% on
        # $500 = sum of -5% but actual dollar net is $-75 vs $25k portfolio
        # = -0.3%. The field is kept for backwards compat but the frontend
        # no longer surfaces it as "Total Return" — that role has moved to
        # `wallet.roi_pct` (mark-to-market portfolio vs initial capital)
        # and `avg_return_pct` (per-trade arithmetic mean) as fallback.
        # DO NOT add new consumers of `total_return_pct`. Use one of:
        #   - wallet.roi_pct          (true return on capital, includes unrealized)
        #   - avg_return_pct          (mean of per-trade pnl_pct, defined here)
        #   - total_pnl_amount_wallet (raw realized $ for wallet trades)
        total = len(trades)
        wins = sum(1 for t in trades if t.get("is_win"))
        win_rate = (wins / total * 100) if total > 0 else 0
        avg_ret = sum(t.get("pnl_pct", 0) for t in trades) / total if total else 0
        total_ret = sum(t.get("pnl_pct", 0) for t in trades)
        wallet_trades = [t for t in trades if t.get("is_wallet_trade")]
        legacy_trades = [t for t in trades if not t.get("is_wallet_trade")]
        total_pnl_amount_wallet = sum(t.get("pnl_amount") or 0 for t in wallet_trades)
        total_pnl_amount_legacy = sum(t.get("pnl_amount") or 0 for t in legacy_trades)
        best = max(trades, key=lambda t: t.get("pnl_pct", 0)) if trades else None
        worst = min(trades, key=lambda t: t.get("pnl_pct", 0)) if trades else None
        return {
            "closed_count": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": round(win_rate, 1),
            "avg_return_pct": round(avg_ret, 2),
            "total_return_pct": round(total_ret, 2),
            "wallet_closed_count": len(wallet_trades),
            "legacy_closed_count": len(legacy_trades),
            "total_pnl_amount_wallet": round(total_pnl_amount_wallet, 2),
            "total_pnl_amount_legacy": round(total_pnl_amount_legacy, 2),
            "best_trade": {"symbol": best["symbol"], "pnl_pct": best["pnl_pct"], "pnl_amount": best.get("pnl_amount")} if best else None,
            "worst_trade": {"symbol": worst["symbol"], "pnl_pct": worst["pnl_pct"], "pnl_amount": worst.get("pnl_amount")} if worst else None,
        }

    def _enrich_open_trade(t: dict) -> dict:
        symbol = t["symbol"]
        entry_price = float(t["entry_price"])
        current = current_prices.get(symbol)

        # Calculate days held
        days_held = days_since(t.get("entry_date"), now=now)

        # Get signal reasoning (why the brain picked this)
        sig = signal_context.get(symbol, {})

        is_wallet = bool(t.get("is_wallet_trade"))
        shares_open = float(t.get("shares") or 0)
        position_size_usd = float(t.get("position_size_usd") or 0)

        enriched = {
            "symbol": symbol,
            "entry_price": entry_price,
            "entry_score": t.get("entry_score"),
            "bucket": t.get("bucket"),
            "source": t.get("source", "watchlist"),
            "signal_style": t.get("signal_style") or sig.get("signal_style"),
            "target_price": t.get("target_price"),
            "stop_loss": t.get("stop_loss"),
            "days_held": days_held,
            "current_score": sig.get("score"),
            "reasoning": sig.get("reasoning"),
            "risk_reward": sig.get("risk_reward"),
            "contrarian_score": sig.get("contrarian_score"),
            "market_regime": sig.get("market_regime"),
            "thesis_status": t.get("thesis_last_status"),  # valid/weakening/invalid/None
            "tier_reason": t.get("tier_reason"),
            "trade_horizon": t.get("trade_horizon") or "SHORT",
            "direction": t.get("direction") or "LONG",
            "consecutive_avoid_count": t.get("consecutive_avoid_count") or 0,
            # Wallet metadata — frontend uses these to render "6.06 shares
            # @ $164.96 ($1,000 invested)" rows and to distinguish wallet
            # trades from legacy 1-share holdings with a subtle badge.
            "is_wallet_trade": is_wallet,
            "shares": round(shares_open, 6) if shares_open else None,
            "position_size_usd": round(position_size_usd, 2) if position_size_usd else None,
            "initial_stop": t.get("initial_stop"),
            "entry_rr": t.get("entry_rr"),
            "sector": t.get("sector"),
            "currency": t.get("currency") or native_currency(symbol),
            "fx_to_usd": _row_fx(t) if is_wallet else 1.0,
        }

        if current:
            _d = t.get("direction") or "LONG"
            pnl_pct = _calc_pnl_pct(entry_price, current, _d)
            per_share_pnl = _calc_pnl_amount(entry_price, current, _d)
            enriched["current_price"] = round(current, 2)
            enriched["unrealized_pnl_pct"] = round(pnl_pct, 2)
            # For wallet trades, unrealized_pnl_amount is TOTAL dollars so
            # the UI can show "+$42.15" without re-deriving shares. For
            # legacy trades it stays per-share (1 implicit share).
            if is_wallet and shares_open > 0:
                fx_now = enriched["fx_to_usd"]
                value_usd = _mark_to_market_one(
                    entry_price=entry_price, current_price=current, direction=_d,
                    is_wallet_trade=True, shares=shares_open, fx=fx_now,
                )
                if _d == "SHORT":
                    enriched["unrealized_pnl_amount"] = round(value_usd, 2)
                else:
                    enriched["unrealized_pnl_amount"] = round(value_usd - position_size_usd, 2)
                    enriched["current_position_value"] = round(value_usd, 2)
            else:
                enriched["unrealized_pnl_amount"] = round(per_share_pnl, 2)

        return enriched

    # Enrich open trades with live P&L
    enriched_open = [_enrich_open_trade(t) for t in open_trades]

    # Calculate aggregate unrealized P&L per source
    def _unrealized_agg(trades: list[dict]) -> float:
        pnls = [t.get("unrealized_pnl_pct", 0) for t in trades if "unrealized_pnl_pct" in t]
        return round(sum(pnls) / len(pnls), 2) if pnls else 0

    # Split by source
    watchlist_open_enriched = [t for t in enriched_open if t.get("source") == "watchlist"]
    brain_open_enriched = [t for t in enriched_open if t.get("source") == "brain"]
    watchlist_closed = [t for t in closed_trades if t.get("source") == "watchlist"]
    brain_closed = [t for t in closed_trades if t.get("source") == "brain"]

    # Wallet summary (Day 15). Sum Holdings from the rows we already
    # enriched — reuses the price batch + per-trade math that
    # `_enrich_open_trade` just did, instead of kicking off a second
    # virtual_trades SELECT + price fetch through the wallet service.
    try:
        from app.services import wallet as wallet_svc
        open_positions_value = _sum_holdings_from_enriched(enriched_open)
        wallet_summary_dict = wallet_svc.wallet_summary(
            user_id=None,  # default to brain user
            open_positions_value=open_positions_value,
        )
    except Exception as e:
        logger.warning(f"Wallet summary failed: {e}")
        wallet_summary_dict = None

    result = {
        "open_count": len(open_trades),
        "open_trades": enriched_open,
        # Combined stats
        **_calc_stats(closed_trades),
        "recent_closed": [
            {
                "symbol": t["symbol"],
                "pnl_pct": t["pnl_pct"],
                "pnl_amount": t.get("pnl_amount"),
                "is_win": t["is_win"],
                "source": t.get("source", "watchlist"),
                "exit_reason": t.get("exit_reason"),
                "entry_score": t.get("entry_score"),
                "exit_score": t.get("exit_score"),
                # Frontend (brain/performance page) renders
                # "entry_date entry_price → exit_date exit_price"
                # under each closed-trade row. These fields are already
                # loaded by the SELECT above; omitting them here is what
                # made the UI render dashes instead of actual values.
                "entry_date": t.get("entry_date"),
                "exit_date": t.get("exit_date"),
                "entry_price": t.get("entry_price"),
                "exit_price": t.get("exit_price"),
                "peak_price": t.get("peak_price"),
                "exit_context": _build_exit_context(t),
                # Day 26: full entry/exit reasoning for the inline detail
                # panel on the closed-trade row. entry_thesis was the
                # synthesis Claude wrote at insert time; thesis_last_reason
                # is the most recent thesis re-eval explanation. Together
                # they answer "why bought" and "why sold". Truncate at
                # 800 chars each to keep payload bounded — full text is
                # available in DB if needed.
                "entry_thesis": (t.get("entry_thesis") or "")[:800],
                "thesis_last_reason": (t.get("thesis_last_reason") or "")[:800],
                "trade_horizon": t.get("trade_horizon") or "SHORT",
                "direction": t.get("direction") or "LONG",
                # Wallet metadata so the UI can render "$1,000 invested,
                # +$42 realized" for wallet closes vs legacy per-share rows.
                "is_wallet_trade": bool(t.get("is_wallet_trade")),
                "shares": t.get("shares"),
                "position_size_usd": t.get("position_size_usd"),
            }
            # Send all closed trades fetched (DB query above is `.limit(50)`).
            # The performance page paginates client-side in batches of 5 via
            # a "Load more" button; the dashboard widget slices its own view.
            for t in closed_trades
        ],
        # Per-source breakdown
        "watchlist": {
            "open_count": len(watchlist_open_enriched),
            "avg_unrealized_pnl_pct": _unrealized_agg(watchlist_open_enriched),
            **_calc_stats(watchlist_closed),
        },
        "brain": {
            "open_count": len(brain_open_enriched),
            "avg_unrealized_pnl_pct": _unrealized_agg(brain_open_enriched),
            **_calc_stats(brain_closed),
        },
        # Watchdog summary
        "watchdog": _get_watchdog_summary(db, len(brain_open_enriched)),
        # Wallet state (Day 15) — balance, collateral, total_value, ROI.
        # None when the wallet module failed or no users exist. UI should
        # hide the wallet card gracefully in that case.
        "wallet": wallet_summary_dict,
    }

    _vp_cache.set("summary", result)
    return result


def _get_watchdog_summary(db, positions_monitored: int) -> dict:
    """Get watchdog status for the dashboard."""
    try:
        recent = (
            db.table("watchdog_events")
            .select("symbol, event_type, created_at")
            .order("created_at", desc=True)
            .limit(5)
            .execute()
        )
        return {
            "active": settings.watchdog_enabled,
            "positions_monitored": positions_monitored,
            "recent_events": recent.data or [],
        }
    except Exception as e:
        logger.warning(f"Watchdog summary query failed: {e}")
        return {"active": settings.watchdog_enabled, "positions_monitored": positions_monitored, "recent_events": []}


@with_retry
def get_virtual_charts() -> dict:
    """Get chart data for the brain performance page.

    Returns pre-computed data structures the frontend can render directly.
    Cached for 5 minutes to avoid repeated DB queries on every page load.
    """
    cached = _vp_cache.get("charts")
    if cached is not None:
        return cached

    db = get_client()

    # All closed trades for charts
    result = (
        db.table("virtual_trades")
        .select("symbol, entry_price, exit_price, pnl_pct, is_win, entry_date, exit_date, "
                "entry_score, bucket, source, exit_reason, signal_style")
        .eq("status", "CLOSED")
        .order("exit_date", desc=True)
        .limit(200)
        .execute()
    )
    closed = result.data or []

    if not closed:
        return {
            "pnl_by_bucket": [],
            "monthly_returns": [],
            "exit_reasons": [],
            "score_vs_pnl": [],
            "win_rate_over_time": [],
        }

    # 1. P&L by bucket (brain vs watchlist, SAFE_INCOME vs HIGH_RISK)
    bucket_groups: dict[str, dict] = {}
    for t in closed:
        key = f"{t.get('source', 'watchlist')}_{t.get('bucket', 'UNKNOWN')}"
        if key not in bucket_groups:
            bucket_groups[key] = {"source": t.get("source"), "bucket": t.get("bucket"), "trades": 0, "total_pnl": 0, "wins": 0}
        bucket_groups[key]["trades"] += 1
        bucket_groups[key]["total_pnl"] += t.get("pnl_pct", 0)
        if t.get("is_win"):
            bucket_groups[key]["wins"] += 1

    pnl_by_bucket = [
        {
            "source": v["source"],
            "bucket": v["bucket"],
            "trades": v["trades"],
            "total_pnl_pct": round(v["total_pnl"], 2),
            "avg_pnl_pct": round(v["total_pnl"] / v["trades"], 2) if v["trades"] else 0,
            "win_rate": round(v["wins"] / v["trades"] * 100, 1) if v["trades"] else 0,
        }
        for v in bucket_groups.values()
    ]

    # 2. Monthly returns (brain track)
    brain_closed = [t for t in closed if t.get("source") == "brain"]
    monthly: dict[str, dict] = {}
    for t in brain_closed:
        exit_date = t.get("exit_date", "")
        if not exit_date:
            continue
        month_key = exit_date[:7]  # "2026-04"
        if month_key not in monthly:
            monthly[month_key] = {"month": month_key, "trades": 0, "total_pnl": 0, "wins": 0}
        monthly[month_key]["trades"] += 1
        monthly[month_key]["total_pnl"] += t.get("pnl_pct", 0)
        if t.get("is_win"):
            monthly[month_key]["wins"] += 1

    monthly_returns = sorted([
        {
            "month": v["month"],
            "trades": v["trades"],
            "total_pnl_pct": round(v["total_pnl"], 2),
            "avg_pnl_pct": round(v["total_pnl"] / v["trades"], 2) if v["trades"] else 0,
            "win_rate": round(v["wins"] / v["trades"] * 100, 1) if v["trades"] else 0,
        }
        for v in monthly.values()
    ], key=lambda x: x["month"])

    # 3. Exit reasons distribution
    reason_counts: dict[str, int] = {}
    for t in closed:
        reason = t.get("exit_reason", "SIGNAL") or "SIGNAL"
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    exit_reasons = [
        {"reason": reason, "count": count, "pct": round(count / len(closed) * 100, 1)}
        for reason, count in sorted(reason_counts.items())
    ]

    # 4. Score vs P&L scatter (for all closed trades)
    score_vs_pnl = [
        {
            "symbol": t["symbol"],
            "entry_score": t.get("entry_score"),
            "pnl_pct": t.get("pnl_pct"),
            "source": t.get("source"),
            "bucket": t.get("bucket"),
        }
        for t in closed
        if t.get("entry_score") is not None and t.get("pnl_pct") is not None
    ]

    # 5. Rolling win rate (last N trades, window of 10)
    win_rate_over_time = []
    # Reverse to chronological order
    chronological = list(reversed(closed))
    window = 10
    for i in range(window - 1, len(chronological)):
        batch = chronological[i - window + 1: i + 1]
        wins = sum(1 for t in batch if t.get("is_win"))
        trade = chronological[i]
        win_rate_over_time.append({
            "trade_num": i + 1,
            "symbol": trade.get("symbol"),
            "exit_date": trade.get("exit_date", "")[:10],
            "win_rate": round(wins / window * 100, 1),
        })

    result = {
        "pnl_by_bucket": pnl_by_bucket,
        "monthly_returns": monthly_returns,
        "exit_reasons": exit_reasons,
        "score_vs_pnl": score_vs_pnl,
        "win_rate_over_time": win_rate_over_time,
    }

    _vp_cache.set("charts", result)
    return result


def snapshot_virtual_portfolio() -> dict:
    """Take a daily snapshot of portfolio state for the equity curve.

    Call once per day (after the last scan). Upserts by snapshot_date.
    """
    db = get_client()
    summary = get_virtual_summary()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Get cumulative closed P&L (all time)
    all_closed = (
        db.table("virtual_trades")
        .select("pnl_pct, source")
        .eq("status", "CLOSED")
        .execute()
    )
    all_closed_data = all_closed.data or []
    brain_cum = sum(t.get("pnl_pct", 0) for t in all_closed_data if t.get("source") == "brain")
    watchlist_cum = sum(t.get("pnl_pct", 0) for t in all_closed_data if t.get("source") == "watchlist")

    # Fetch SPY price for benchmark
    spy_data = _fetch_prices_batch(["SPY"])
    spy_price, _ = spy_data.get("SPY", (None, None))

    # Wallet equity (USD, mark-to-market), peak ratchet and the daily
    # reconciliation (cash + open cost basis == deposits + realized P&L).
    brain_equity = None
    try:
        from app.services import wallet as wallet_svc
        wallet_info = summary.get("wallet") or {}
        if wallet_info.get("total_value") is not None:
            brain_equity = float(wallet_info["total_value"])
            wallet_svc.update_peak_equity(None, brain_equity)
        wallet_svc.reconcile_wallet()
    except Exception as e:
        logger.warning(f"Snapshot equity/reconcile step failed: {e}")

    snapshot = {
        "snapshot_date": today,
        "brain_open": summary.get("brain", {}).get("open_count", 0),
        "brain_unrealized_pnl": summary.get("brain", {}).get("avg_unrealized_pnl_pct", 0),
        "brain_cumulative_pnl": round(brain_cum, 2),
        "watchlist_open": summary.get("watchlist", {}).get("open_count", 0),
        "watchlist_unrealized_pnl": summary.get("watchlist", {}).get("avg_unrealized_pnl_pct", 0),
        "watchlist_cumulative_pnl": round(watchlist_cum, 2),
        "spy_price": spy_price,
    }

    # Upsert by snapshot_date (brain_equity column added in migration 006)
    if brain_equity is not None:
        snapshot["brain_equity"] = round(brain_equity, 2)
    try:
        db.table("virtual_snapshots").upsert(snapshot, on_conflict="snapshot_date").execute()
    except Exception as e:
        if "brain_equity" not in snapshot:
            raise
        logger.warning(f"Snapshot upsert with brain_equity failed ({e}); retrying without it")
        snapshot.pop("brain_equity", None)
        db.table("virtual_snapshots").upsert(snapshot, on_conflict="snapshot_date").execute()
    logger.info(f"Virtual snapshot saved for {today}: brain_cum={brain_cum:+.1f}%, watchlist_cum={watchlist_cum:+.1f}%")

    # Portfolio risk (correlation / beta / vol) — reported, not persisted:
    # virtual_snapshots has no column for it yet.
    try:
        from app.services.portfolio_risk import get_portfolio_risk_metrics
        risk = get_portfolio_risk_metrics()
        snapshot["portfolio_risk"] = risk
        logger.info(
            f"Portfolio risk: n={risk['n_positions']} beta={risk['beta']} "
            f"vol={risk['vol_annual_pct']}% avg_corr={risk['avg_pairwise_corr']} "
            f"largest_cluster={risk['largest_cluster']['symbols']}"
        )
    except Exception as e:
        logger.warning(f"Portfolio risk metrics failed: {e}")

    return snapshot
