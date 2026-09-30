"""My holdings — daily monitor (17:45 ET weekdays) + on-demand refresh.

For each of the owner's real holdings:

  price        last close, day / 1-month / YTD change (dividend-adjusted closes)
  trend        below the 200-day SMA = trend break; SMA50 < SMA200 = death cross
  drawdown     % below the 52-week (252-bar) high
  earnings     stocks only: next report date (app/signals/earnings.py) and
               trading days until it
  red flags    stocks only: material, CITED red flags from Grok sentiment.
               A cached Grok result from a scan / "Check a stock" is reused
               ($0); otherwise Grok is called at most once per stock per
               settings.holdings_grok_refresh_days (stored in
               holding_status.sentiment.grok_on), budget-checked. ETFs /
               crypto never call AI.
  position     when shares are known: value, weight, unrealized gain (own
               currency + CAD via CAD=X), overweight flag
               (> settings.holdings_max_weight_pct)

Telegram alerts (EN/PT, one digest message per run) fire ONLY on state
changes, de-duplicated with `holdings.alert_state`:
  * a new trend break (price falls below the 200-day SMA)
  * a new high/critical cited red flag
  * earnings within settings.holdings_earnings_alert_trading_days trading
    days (once per report date)
  * the position crossing above the concentration limit
A holding's first snapshot is a silent baseline (no trend / flag /
concentration alert for a state that already existed at import).
settings.holdings_alerts_enabled=False keeps updating state but never sends.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import math
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from loguru import logger

from app.core.config import settings
from app.services import holdings_service as hs

ET = ZoneInfo("America/New_York")
HISTORY_PERIOD = "2y"
FETCH_CONCURRENCY = 4
ALERT_SEVERITIES = ("high", "critical")
MAX_REMEMBERED_FLAGS = 30

# symbol|ET-date -> True: in-process guard on top of the stored
# sentiment.checked_on, so a failed DB write can't cause a second check.
_sentiment_calls: dict[str, bool] = {}
# symbol -> ET date of the last paid Grok call made by the monitor (guards
# the weekly refresh even if the stored snapshot is lost).
_grok_calls: dict[str, date] = {}
_run_lock = asyncio.Lock()


def _today_et() -> date:
    return datetime.now(ET).date()


def _num(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _r(v, nd=2):
    return round(v, nd) if v is not None and math.isfinite(v) else None


# ============================================================
# Price status (pure)
# ============================================================

def compute_price_status(closes: pd.Series | None) -> dict:
    """Trend / change / drawdown figures from daily closes (oldest first)."""
    if closes is None or len(closes) < 2:
        return {"error": "no_data"}
    s = closes.dropna()
    s = s[s > 0]
    if len(s) < 2:
        return {"error": "no_data"}
    idx = pd.DatetimeIndex(s.index)
    price = float(s.iloc[-1])
    prev = float(s.iloc[-2])
    last_day = idx[-1]

    def close_on_or_before(ts) -> float | None:
        m = s[idx <= ts]
        return float(m.iloc[-1]) if len(m) else None

    base_1m = close_on_or_before(last_day - pd.Timedelta(days=30))
    ytd_base = close_on_or_before(pd.Timestamp(year=last_day.year, month=1, day=1) - pd.Timedelta(days=1))
    sma50 = float(s.iloc[-50:].mean()) if len(s) >= 50 else None
    sma200 = float(s.iloc[-200:].mean()) if len(s) >= 200 else None
    window = s.iloc[-252:]
    high = float(window.max())
    trend_break = bool(sma200 is not None and price < sma200)
    death_cross = bool(sma50 is not None and sma200 is not None and sma50 < sma200)
    if sma200 is None:
        trend = "unknown"
    elif trend_break:
        trend = "break"
    elif death_cross:
        trend = "weak"
    else:
        trend = "ok"
    return {
        "price": _r(price, 4),
        "prev_close": _r(prev, 4),
        "day_change_pct": _r((price / prev - 1) * 100),
        "change_1m_pct": _r((price / base_1m - 1) * 100) if base_1m else None,
        "ytd_pct": _r((price / ytd_base - 1) * 100) if ytd_base else None,
        "sma50": _r(sma50, 4),
        "sma200": _r(sma200, 4),
        "pct_vs_sma200": _r((price / sma200 - 1) * 100) if sma200 else None,
        "trend": trend,
        "trend_break": trend_break,
        "death_cross": death_cross,
        "high_52w": _r(high, 4),
        "drawdown_pct": _r((price / high - 1) * 100) if high else None,
        "as_of": last_day.date().isoformat(),
    }


def fetch_closes(symbols: list[str]) -> dict[str, pd.Series]:
    """Fresh daily closes for every symbol (one batched yf.download).
    Blocking — call via asyncio.to_thread. Missing symbols are absent."""
    syms = list(dict.fromkeys(s for s in symbols if s))
    if not syms:
        return {}
    from app.services.price_cache import _close_series_from_download

    out: dict[str, pd.Series] = {}
    try:
        import yfinance as yf

        data = yf.download(syms, period=HISTORY_PERIOD, interval="1d", progress=False,
                           threads=False, auto_adjust=True)
        if data is None or data.empty:
            return {}
        multi = isinstance(data.columns, pd.MultiIndex) and len(syms) > 1
        for sym in syms:
            s = _close_series_from_download(data, sym, multi)
            if s is not None:
                out[sym] = s
    except Exception as e:
        logger.warning(f"holdings monitor: price download failed ({len(syms)} symbols): {e}")
    return out


# ============================================================
# Earnings + red flags (async, per holding)
# ============================================================

def asset_type_of(h: dict) -> str:
    at = str(h.get("asset_type") or "").upper()
    if at in ("STOCK", "ETF", "CRYPTO", "OTHER"):
        return at
    sym = str(h.get("symbol") or "")
    if sym.endswith("-USD"):
        return "CRYPTO"
    from app.scanners.universe import get_asset_class
    return get_asset_class(sym)


def _exchange_code(h: dict) -> str:
    sym = str(h.get("symbol") or "")
    if sym.endswith("-USD"):
        return "CRYPTO"
    if sym.endswith((".TO", ".V")):
        return "TSX"
    return "NYSE"


async def earnings_info(h: dict, today: date | None = None) -> dict | None:
    """{"date", "days", "trading_days"} for stocks; None otherwise / unknown."""
    if asset_type_of(h) != "STOCK":
        return None
    from app.core.market_calendar import trading_days_until
    from app.signals.earnings import get_earnings_context

    try:
        ctx = await get_earnings_context(h["symbol"])
    except Exception as e:
        logger.debug(f"holdings monitor: earnings({h['symbol']}) failed: {e}")
        return None
    d = (ctx or {}).get("next_earnings_date")
    if not d:
        return {"date": None, "days": None, "trading_days": None}
    today = today or _today_et()
    try:
        nd = date.fromisoformat(str(d)[:10])
    except ValueError:
        return {"date": None, "days": None, "trading_days": None}
    return {"date": nd.isoformat(), "days": (nd - today).days,
            "trading_days": trading_days_until(_exchange_code(h), nd, today)}


def _market_cap(symbol: str) -> float | None:
    try:
        import yfinance as yf
        fi = yf.Ticker(symbol).fast_info
        return _num(fi.get("marketCap") if hasattr(fi, "get") else getattr(fi, "market_cap", None))
    except Exception:
        return None


def flag_key(f: dict) -> str:
    raw = f"{f.get('url') or ''}|{str(f.get('text') or '')[:120]}"
    return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()[:16]


def _grok_due(last: str | date | None, today: date) -> bool:
    if not last:
        return True
    try:
        d = last if isinstance(last, date) else date.fromisoformat(str(last)[:10])
    except ValueError:
        return True
    return (today - d).days >= max(1, int(settings.holdings_grok_refresh_days))


async def red_flag_check(h: dict, prev_status: dict | None, today: date | None = None) -> tuple[list[dict], dict]:
    """(material cited red flags, sentiment meta). Stocks only.

    1. already checked today → reuse the stored flags;
    2. a cached Grok result (from a scan / check, 24h) → use it, $0;
    3. the last paid Grok call for this stock is < holdings_grok_refresh_days
       old → keep the stored flags;
    4. else one Grok call, budget-checked (a blocked budget is not counted
       as a call, so the next run tries again).
    """
    today_d = today or _today_et()
    today_s = today_d.isoformat()
    prev = prev_status or {}
    prev_flags = list(prev.get("red_flags") or [])
    prev_meta = prev.get("sentiment") or {}
    if asset_type_of(h) != "STOCK":
        return [], {"skipped": "not_a_stock"}
    if not (settings.ai_enabled and settings.holdings_ai_red_flags):
        return prev_flags, {"skipped": "disabled", "checked_on": prev_meta.get("checked_on")}
    sym = h["symbol"]
    guard = f"{sym}|{today_s}"
    if prev_meta.get("checked_on") == today_s or _sentiment_calls.get(guard):
        return prev_flags, {**prev_meta, "reused": True}

    from app.ai import provider as ai_provider
    from app.services.long_term_check import material_red_flags

    _sentiment_calls[guard] = True
    last_grok = _grok_calls.get(sym) or prev_meta.get("grok_on")
    if isinstance(last_grok, date):
        last_grok = last_grok.isoformat()
    meta: dict = {"checked_on": today_s, "grok_on": last_grok}

    res = ai_provider.get_cached_sentiment(sym)
    if res is None:
        if not _grok_due(last_grok, today_d):
            return prev_flags, {**prev_meta, "checked_on": today_s, "grok_on": last_grok, "reused": True}
        try:
            from app.services.budget_service import BudgetService
            budget = await BudgetService.get_instance()
            allowed, reason = await budget.can_call("grok", "sentiment")
        except Exception as e:
            allowed, reason = False, str(e)
        if not allowed or not settings.xai_api_key:
            logger.info(f"holdings monitor: Grok skipped for {sym} ({reason if not allowed else 'no XAI_API_KEY'})")
            return prev_flags, {**meta, "error": "budget" if not allowed else "unavailable"}
        mcap = await asyncio.to_thread(_market_cap, sym)
        _grok_calls[sym] = today_d
        meta["grok_on"] = today_s
        try:
            res = await ai_provider.analyze_sentiment(sym, market_cap=mcap)
        except Exception as e:
            logger.warning(f"holdings monitor: sentiment({sym}) failed: {e}")
            return prev_flags, {**meta, "error": "failed"}
    else:
        mcap = await asyncio.to_thread(_market_cap, sym)
    meta["provider"] = res.get("_provider")
    meta["cached"] = bool(res.get("_cached"))
    if res.get("error"):
        meta["error"] = "unavailable"
        return prev_flags, meta
    flags = material_red_flags(res, mcap)
    for f in flags:
        f["key"] = flag_key(f)
    return flags, meta


# ============================================================
# Alerts (pure state machine)
# ============================================================

def evaluate_alerts(h: dict, status: dict, position: dict | None, prev_state: dict | None,
                    earnings_days: int | None = None) -> tuple[list[dict], dict]:
    """(alerts to send, new alert_state). `prev_state` None = first
    snapshot: a silent baseline for trend / red flags / concentration
    (earnings still alert — they are keyed by report date)."""
    n_days = settings.holdings_earnings_alert_trading_days if earnings_days is None else earnings_days
    baseline = prev_state is None
    prev = prev_state or {}
    sym = h.get("symbol")
    alerts: list[dict] = []
    state = {
        "trend_break": prev.get("trend_break", False),
        "overweight": prev.get("overweight", False),
        "red_flags": list(prev.get("red_flags") or []),
        "earnings_alerted": prev.get("earnings_alerted"),
    }

    if status.get("trend") in ("ok", "weak", "break"):
        tb = bool(status.get("trend_break"))
        if tb and not prev.get("trend_break") and not baseline:
            alerts.append({"type": "trend_break", "symbol": sym, "price": status.get("price"),
                           "sma200": status.get("sma200"), "pct": status.get("pct_vs_sma200")})
        state["trend_break"] = tb

    known = set(state["red_flags"])
    for f in status.get("red_flags") or []:
        k = f.get("key") or flag_key(f)
        if k in known:
            continue
        known.add(k)
        state["red_flags"].append(k)
        if not baseline and str(f.get("severity") or "").lower() in ALERT_SEVERITIES:
            alerts.append({"type": "red_flag", "symbol": sym, "text": f.get("text"), "url": f.get("url"),
                           "severity": f.get("severity"), "category": f.get("category")})
    state["red_flags"] = state["red_flags"][-MAX_REMEMBERED_FLAGS:]

    e = status.get("earnings") or {}
    td = e.get("trading_days")
    if e.get("date") and td is not None and 0 <= int(td) <= n_days and e["date"] != prev.get("earnings_alerted"):
        alerts.append({"type": "earnings", "symbol": sym, "date": e["date"], "trading_days": td})
        state["earnings_alerted"] = e["date"]

    if position is not None and position.get("weight_pct") is not None:
        ow = bool(position.get("overweight"))
        if ow and not prev.get("overweight") and not baseline:
            alerts.append({"type": "overweight", "symbol": sym, "weight_pct": position.get("weight_pct"),
                           "max_pct": settings.holdings_max_weight_pct})
        state["overweight"] = ow
    return alerts, state


def format_alerts(alerts: list[dict]) -> str:
    from app.notifications.messages import msg

    lines = [msg("holdings_alert_header", count=len(alerts))]
    for a in alerts[:20]:
        sym = html.escape(str(a.get("symbol") or "?"))
        t = a["type"]
        if t == "trend_break":
            lines.append(msg("holdings_alert_trend_break", symbol=sym, price=_fmt(a.get("price")),
                             sma200=_fmt(a.get("sma200")), pct=_fmt(a.get("pct"), 1)))
        elif t == "red_flag":
            lines.append(msg("holdings_alert_red_flag", symbol=sym,
                             severity=html.escape(str(a.get("severity") or "")),
                             text=html.escape(str(a.get("text") or "")[:220]),
                             url=html.escape(str(a.get("url") or ""), quote=True)))
        elif t == "earnings":
            lines.append(msg("holdings_alert_earnings", symbol=sym, date=html.escape(str(a.get("date"))),
                             days=a.get("trading_days")))
        elif t == "overweight":
            lines.append(msg("holdings_alert_overweight", symbol=sym, weight=_fmt(a.get("weight_pct"), 1),
                             max=_fmt(a.get("max_pct"), 0)))
    lines.append(msg("holdings_alert_footer"))
    return "\n".join(lines)


def _fmt(v, nd=2) -> str:
    f = _num(v)
    return "?" if f is None else f"{f:,.{nd}f}"


def send_alerts(alerts: list[dict]) -> bool:
    if not alerts or not settings.holdings_alerts_enabled or not settings.telegram_chat_id:
        return False
    from app.notifications.telegram_bot import enqueue

    enqueue(settings.telegram_chat_id, format_alerts(alerts))
    return True


# ============================================================
# The run
# ============================================================

async def monitor_holdings(holdings: list[dict], usdcad: float | None = None,
                           today: date | None = None, ai_allowed: bool = True) -> tuple[list[dict], list[dict]]:
    """Compute a fresh snapshot for every holding (no DB, no Telegram).
    ai_allowed=False (users without system.ai) skips the Grok red-flag check.
    Returns (updates [{id, holding_status, alert_state}], alerts).

    One stock can sit in several accounts (migration 013): price status,
    earnings and the red-flag check run ONCE per symbol, every row of the
    symbol gets the same status, and alerts are evaluated once per symbol
    (position = the lots merged; prev state = the first row that has one)
    with the resulting alert_state written to every row of the symbol.
    Callers pass one user's holdings."""
    today = today or _today_et()
    groups: dict[str, list[dict]] = {}
    for h in holdings:
        groups.setdefault(str(h.get("symbol") or "").upper(), []).append(h)
    closes = await asyncio.to_thread(fetch_closes, [rows[0]["symbol"] for rows in groups.values()])
    sem = asyncio.Semaphore(FETCH_CONCURRENCY)
    now_iso = datetime.now(timezone.utc).isoformat()

    def _prev_status(rows: list[dict]) -> dict:
        return next((r.get("holding_status") for r in rows if r.get("holding_status")), None) or {}

    async def one(rows: list[dict]) -> dict:
        h = rows[0]
        async with sem:
            st = compute_price_status(closes.get(h["symbol"]))
            prev = _prev_status(rows)
            if st.get("error") and prev.get("price") is not None:
                # keep the last good figures, mark them stale
                st = {**{k: v for k, v in prev.items() if k not in ("error", "position")}, "stale": True}
            st["asset_type"] = asset_type_of(h)
            st["currency"] = hs.holding_currency(h)
            st["earnings"] = await earnings_info(h, today)
            if ai_allowed:
                flags, meta = await red_flag_check(h, prev, today)
            else:
                flags, meta = [], {"skipped": "plan"}
            st["red_flags"] = flags
            st["sentiment"] = meta
            st["updated_at"] = now_iso
            return st

    syms = list(groups)
    statuses = await asyncio.gather(*(one(groups[s]) for s in syms), return_exceptions=True)
    by_sym: dict[str, dict] = {}
    for sym, st in zip(syms, statuses):
        if isinstance(st, BaseException):
            logger.warning(f"holdings monitor: {sym} failed: {st}")
            st = {**_prev_status(groups[sym]), "stale": True, "updated_at": now_iso}
        by_sym[sym] = st

    # position figures: per row (its own lot) and per symbol (lots merged, for alerts)
    snap = [{**h, "holding_status": by_sym[str(h.get("symbol") or "").upper()]} for h in holdings]
    per_row, _t = hs.portfolio_math(snap, usdcad)
    merged = hs.merge_by_symbol(snap)
    per_sym, _t2 = hs.portfolio_math([{**m, "id": str(m.get("symbol") or "").upper()} for m in merged], usdcad)

    updates: list[dict] = []
    all_alerts: list[dict] = []
    for m in merged:
        sym = str(m.get("symbol") or "").upper()
        rows = groups[sym]
        base = by_sym[sym]
        sym_pos = per_sym.get(sym)
        prev_state = next((r.get("alert_state") for r in rows if r.get("alert_state") is not None), None)
        alerts, state = evaluate_alerts(m, dict(base), sym_pos if m.get("shares") else None, prev_state)
        all_alerts.extend(alerts)
        for r in rows:
            st = dict(base)
            pos = per_row.get(str(r.get("id") or r.get("symbol")))
            if pos:
                st["position"] = pos
            updates.append({"id": r.get("id"), "user_id": r.get("user_id"), "holding_status": st,
                            "alert_state": state})
    return updates, all_alerts


async def run_holdings_monitor(user_id: str | None = None) -> dict:
    """Scheduler / refresh entry point: load, monitor, persist, alert."""
    from app.db import queries

    if _run_lock.locked():
        return {"status": "busy"}
    async with _run_lock:
        try:
            rows = await asyncio.to_thread(queries.get_holdings, user_id) if user_id \
                else await asyncio.to_thread(queries.get_all_holdings)
        except Exception as e:
            logger.warning(f"holdings monitor: holdings table unavailable (apply migration 010?): {e}")
            return {"status": "unavailable"}
        if not rows:
            return {"status": "ok", "holdings": 0, "alerts": 0}
        from app.services.price_cache import get_usdcad_rate
        usdcad = await asyncio.to_thread(get_usdcad_rate)

        by_user: dict[str, list[dict]] = {}
        for r in rows:
            by_user.setdefault(str(r.get("user_id")), []).append(r)
        total_alerts = 0
        updated = 0
        now_iso = datetime.now(timezone.utc).isoformat()
        from app.core.access import can, get_user_access
        for uid, hs_rows in by_user.items():
            level = (await asyncio.to_thread(get_user_access, uid))["level"]
            updates, alerts = await monitor_holdings(hs_rows, usdcad, ai_allowed=can(level, "system.ai"))
            for u in updates:
                try:
                    await asyncio.to_thread(queries.update_holding, str(u["id"]), uid, {
                        "holding_status": u["holding_status"], "alert_state": u["alert_state"],
                        "status_updated_at": now_iso,
                    })
                    updated += 1
                except Exception as e:
                    logger.warning(f"holdings monitor: save {u['id']} failed: {e}")
            # Alerts go to the owner's Telegram chat; other users get none
            # until per-user notifications exist.
            if level == "owner" and send_alerts(alerts):
                total_alerts += len(alerts)
        logger.info(f"Holdings monitor: {updated}/{len(rows)} updated, {total_alerts} alert(s) sent")
        return {"status": "ok", "holdings": len(rows), "updated": updated, "alerts": total_alerts}


def is_running() -> bool:
    return _run_lock.locked()


def _reset_state() -> None:
    """Test helper."""
    _sentiment_calls.clear()
    _grok_calls.clear()

