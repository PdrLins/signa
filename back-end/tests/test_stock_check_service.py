"""services/stock_check — symbol resolution, verdict matrix, and the
guarantee that a check never writes live statistics. Network / AI / DB are
all mocked."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.ai import provider as ai_provider
from app.services import portfolio_risk
from app.services import stock_check as sc
from app.services import virtual_portfolio as vp
from app.services.portfolio_risk import CorrelationCheck


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clear_caches():
    sc._resolve_cache.clear()
    sc._macro_cache.clear()
    yield
    sc._resolve_cache.clear()
    sc._macro_cache.clear()


# ============================================================
# Symbol resolution
# ============================================================

def _prices(mapping):
    return lambda sym: mapping.get(sym)


def test_normalize_input():
    assert sc.normalize_input("  xeqt ") == "XEQT"
    assert sc.normalize_input("$aapl") == "AAPL"
    for bad in ("", "   ", "BAD$$", "A" * 25, "AB CD"):
        with pytest.raises(sc.StockCheckError) as e:
            sc.normalize_input(bad)
        assert e.value.code == "invalid_ticker"


def test_xeqt_resolves_to_tsx():
    tried = []

    def price(sym):
        tried.append(sym)
        return {"XEQT.TO": 31.2}.get(sym)

    with patch.object(sc, "_recent_price", side_effect=price):
        res = run(sc.resolve_symbol("xeqt"))
    assert res["symbol"] == "XEQT.TO"
    assert res["exchange"] == "TSX"
    assert res["input"] == "XEQT"
    assert tried[0] == "XEQT.TO"  # universe member is tried first


def test_raw_symbol_wins_when_it_has_data():
    with patch.object(sc, "_recent_price", side_effect=_prices({"AAPL": 190.0, "AAPL.TO": 30.0})):
        res = run(sc.resolve_symbol("AAPL"))
    assert res["symbol"] == "AAPL"


def test_unknown_suffix_order_raw_then_tsx_then_crypto():
    tried = []

    def price(sym):
        tried.append(sym)
        return {"ZZQX-USD": 0.01}.get(sym)

    with patch.object(sc, "_recent_price", side_effect=price):
        res = run(sc.resolve_symbol("zzqx"))
    assert tried == ["ZZQX", "ZZQX.TO", "ZZQX-USD"]
    assert res["symbol"] == "ZZQX-USD"
    assert res["exchange"] == "CRYPTO"


def test_btc_prefers_crypto_over_us_listing():
    with patch.object(sc, "_recent_price", side_effect=_prices({"BTC": 40.0, "BTC-USD": 65000.0})):
        res = run(sc.resolve_symbol("btc"))
    assert res["symbol"] == "BTC-USD"
    assert res["exchange"] == "CRYPTO"


def test_suffixed_input_is_tried_as_is():
    tried = []

    def price(sym):
        tried.append(sym)
        return 50.0

    with patch.object(sc, "_recent_price", side_effect=price):
        res = run(sc.resolve_symbol("shop.to"))
    assert tried == ["SHOP.TO"] and res["symbol"] == "SHOP.TO"


def test_unknown_symbol_is_not_found():
    with patch.object(sc, "_recent_price", return_value=None):
        with pytest.raises(sc.StockCheckError) as e:
            run(sc.resolve_symbol("QQQQZ"))
    assert e.value.code == "not_found" and e.value.status == 404
    assert "QQQQZ.TO" in e.value.message


def test_resolution_is_cached():
    m = MagicMock(side_effect=_prices({"XEQT.TO": 31.0}))
    with patch.object(sc, "_recent_price", m):
        run(sc.resolve_symbol("XEQT"))
        run(sc.resolve_symbol("xeqt"))
    assert m.call_count == 1


# ============================================================
# Pipeline harness
# ============================================================

GOOD_TECH = {
    "current_price": 100.0, "last_close": 100.0, "sma_50": 95.0, "sma_200": 85.0,
    "rsi": 55.0, "atr": 2.0, "dollar_volume_avg_20": 50_000_000.0, "volume_avg": 1_000_000.0,
    "volume_avg_20": 1_000_000.0, "volume_zscore": 0.1, "vs_sma50": 5.3, "vs_sma200": 17.6,
    "macd_histogram": 0.2, "bb_position": 0.6,
}
GOOD_FUND = {"company_name": "Acme Corp", "sector": "Technology", "market_cap": 1e12,
             "quote_type": "EQUITY", "dividend_yield": 0.0}
BUY = {"signal": "BUY", "confidence": 78, "p_win": 0.62, "reasoning": "Clean uptrend.",
       "target_price": 115.0, "stop_loss": 95.0, "_provider": "claude"}
SENTIMENT = {"score": 62, "label": "bullish", "confidence": 70, "summary": "Upbeat chatter.",
             "citations": ["https://example.com/a", "https://x.com/b"], "red_flags": []}


def book(equity=10_000.0, open_book=None, breaker_blocked=False, cooldown=None):
    open_book = open_book or []
    rows = [{"id": p.get("id", f"t{i}"), "symbol": p["symbol"], "sector": p.get("sector"),
             "position_size_usd": p.get("cost_usd", 1000.0)} for i, p in enumerate(open_book)]
    br = (vp.BreakerState(True, equity * 1.2, "2026-09-20", "drawdown_breaker_pause", None, 3, 7)
          if breaker_blocked else vp.BreakerState(False, equity, None, None, None))
    return {"open_rows": rows, "open_book": open_book, "wallet": {"balance": equity},
            "equity": equity, "cash": equity, "peak": br.peak, "breaker": br,
            "cooldown": cooldown or {}}


class Harness:
    def __init__(self, symbol="ACME", exchange="NYSE", tech=None, fund=None, routine=None,
                 decision=None, sentiment=None, earnings=None, book_state=None, market_open=True,
                 corr=None, fx=1.0, score=70):
        self.resolved = {"input": symbol, "symbol": symbol, "exchange": exchange, "price": 100.0}
        self.tech = dict(tech or GOOD_TECH)
        self.fund = dict(fund or GOOD_FUND)
        self.routine = routine if routine is not None else dict(BUY)
        self.decision = decision if decision is not None else {**BUY, "confidence": 82, "reasoning": "Confirmed."}
        self.sentiment = sentiment if sentiment is not None else dict(SENTIMENT)
        self.earnings = earnings or {}
        self.book = book_state or book()
        self.market_open = market_open
        self.corr = corr
        self.fx = fx
        self.score = score
        self.synth = AsyncMock(side_effect=self._synth)
        self.sent = AsyncMock(side_effect=lambda *a, **k: dict(self.sentiment))
        self.earn = AsyncMock(side_effect=lambda *a, **k: dict(self.earnings))
        self.phases: list[str] = []

    async def _synth(self, ticker, tech, fund, macro, grok, tier="routine"):
        return dict(self.decision if tier == "decision" else self.routine)

    def tiers(self):
        return [c.kwargs.get("tier", "routine") for c in self.synth.call_args_list]

    def run(self):
        corr = self.corr or CorrelationCheck(None, {"status": "checked", "corr": {}, "rule": None})
        with patch("app.scanners.market_scanner.get_price_history", AsyncMock(return_value=object())), \
             patch("app.scanners.market_scanner.get_fundamentals", AsyncMock(return_value=dict(self.fund))), \
             patch("app.scanners.indicators.compute_indicators", return_value=dict(self.tech)), \
             patch.object(sc, "_macro_snapshot", AsyncMock(return_value={"vix": 15})), \
             patch.object(sc, "_knowledge_block", AsyncMock(return_value="")), \
             patch.object(sc, "get_earnings_context", self.earn), \
             patch("app.scanners.barchart_scanner.get_options_flow", AsyncMock(return_value=None)), \
             patch("app.services.pattern_stats.get_pattern_warning", return_value=None), \
             patch.object(ai_provider, "analyze_sentiment", self.sent), \
             patch.object(ai_provider, "synthesize_signal", self.synth), \
             patch.object(sc, "compute_score", return_value=(self.score, {})), \
             patch.object(sc, "load_book_state", return_value=self.book), \
             patch.object(sc, "_market_open", return_value=self.market_open), \
             patch.object(vp, "fx_to_usd", return_value=self.fx), \
             patch.object(portfolio_risk, "check_correlation_limit", return_value=corr), \
             patch("app.signals.regime.get_market_regime", return_value="TRENDING"):
            return run(sc.run_check(self.resolved, progress=lambda ph, pct: self.phases.append(ph)))


def codes(result):
    return [r["code"] for r in result["reasons"]]


def hint_codes(result):
    return [h["code"] for h in result["what_would_change"]]


# ============================================================
# Verdict matrix
# ============================================================

def test_buy_now_when_every_gate_passes():
    h = Harness()
    r = h.run()
    assert r["verdict"] == "BUY_NOW", r["reasons"]
    assert r["headline"]["code"] == "buy_now"
    assert r["reasons"] == [] and r["what_would_change"] == []
    assert h.tiers() == ["routine", "decision"]  # Opus escalation ran
    # levels from the slipped fill; R:R >= brain_min_rr
    lv = r["levels"]
    assert lv["stop"] == 95.0 and lv["target"] == 115.0 and lv["rr"] >= 2.0
    # 1% risk sizing on $10k equity (capped at 10% of equity)
    assert r["size"]["shares"] > 0
    assert r["size"]["alloc_usd"] <= 1000.0 + 1e-6
    assert r["size"]["risk_pct"] <= 1.0 + 1e-6
    t = r["trail"]
    assert t["decision"]["decision"] == "ENTER"
    assert t["routine"]["signal"] == "BUY" and t["routine"]["reasoning"] == "Clean uptrend."
    assert t["decision_model"]["status"] == "confirmed"
    assert t["grok"]["citations"] == SENTIMENT["citations"]
    assert t["tech_filter"]["passed"] is True
    assert t["outcomes"] is None and t["signal_id"] is None
    assert r["cached"] is False
    import json
    json.dumps(r)  # plain JSON (no numpy / NaN)
    assert {c["code"] for c in r["caveats"]} >= {"not_advice", "edge_unproven"}
    assert h.phases[-1] == "done"
    assert h.phases.index("filter") < h.phases.index("sentiment") < h.phases.index("synthesis") \
        < h.phases.index("decision") < h.phases.index("risk")


def test_market_closed_does_not_block_but_adds_note():
    r = Harness(market_open=False).run()
    assert r["verdict"] == "BUY_NOW"
    assert "market_closed" in [n["code"] for n in r["notes"]]
    assert r["market_open"] is False


def test_wait_when_overextended_vs_sma50():
    tech = {**GOOD_TECH, "current_price": 120.0, "last_close": 120.0, "sma_50": 100.0}
    r = Harness(tech=tech, routine={**BUY, "target_price": 140.0, "stop_loss": 112.0},
                decision={**BUY, "target_price": 140.0, "stop_loss": 112.0}).run()
    assert r["verdict"] == "WAIT"
    assert r["reasons"][0]["params"]["check"] == "overextended_vs_sma50"
    hint = next(x for x in r["what_would_change"] if x["code"] == "pullback_sma50")
    assert hint["params"]["price"] == pytest.approx(115.0)
    assert "~$115.00" in hint["text"]


def test_wait_when_rsi_overbought():
    r = Harness(tech={**GOOD_TECH, "rsi": 78.0}).run()
    assert r["verdict"] == "WAIT"
    assert "rsi_cool" in hint_codes(r)
    assert "technical_filter" in codes(r)


def test_wait_in_earnings_blackout():
    soon = (datetime.now(ZoneInfo("America/New_York")).date() + timedelta(days=1)).isoformat()
    r = Harness(earnings={"next_earnings_date": soon}).run()
    assert r["verdict"] == "WAIT"
    assert "earnings_blackout" in codes(r)
    hint = next(x for x in r["what_would_change"] if x["code"] == "after_earnings")
    assert hint["params"]["date"] == soon
    assert r["earnings"]["date"] == soon and r["earnings"]["blackout"] is True


def test_wait_when_rr_below_min():
    low = {**BUY, "target_price": 104.0, "stop_loss": 95.0}
    r = Harness(routine=low, decision=low).run()
    assert r["verdict"] == "WAIT"
    assert "rr_below_min" in codes(r)
    hint = next(x for x in r["what_would_change"] if x["code"] == "rr_min")
    assert hint["params"]["price"] < 100.0


def test_wait_when_ai_says_hold_and_no_escalation():
    h = Harness(routine={**BUY, "signal": "HOLD", "confidence": 65})
    r = h.run()
    assert r["verdict"] == "WAIT"
    assert "ai_rejected" in codes(r)
    assert h.tiers() == ["routine"]  # a routine HOLD is never escalated
    assert r["trail"]["decision_model"] is None


def test_wait_when_decision_model_vetoes():
    h = Harness(decision={**BUY, "signal": "HOLD", "confidence": 70, "reasoning": "Too extended."})
    r = h.run()
    assert r["verdict"] == "WAIT"
    assert "decision_veto" in codes(r)
    assert r["trail"]["decision_model"]["status"] == "vetoed"
    assert r["trail"]["routine"]["signal"] == "BUY"


def test_wait_when_too_correlated_with_holdings():
    held = [{"symbol": "MSFT", "sector": "Technology", "is_crypto": False, "cost_usd": 1000.0,
             "direction": "LONG", "id": "t1"}]
    corr = CorrelationCheck("correlation_limit", {"status": "checked", "rule": "pairwise",
                                                  "max_corr": 0.91, "max_corr_symbol": "MSFT",
                                                  "corr": {"MSFT": 0.91}, "max_pairwise": 0.8})
    r = Harness(book_state=book(open_book=held), corr=corr).run()
    assert r["verdict"] == "WAIT"
    assert "correlation_limit" in codes(r)
    assert r["trail"]["correlation"]["max_corr_symbol"] == "MSFT"
    assert "diversify" in hint_codes(r)


def test_wait_when_portfolio_is_full():
    full = [{"symbol": f"S{i}", "sector": f"Sec{i}", "is_crypto": False, "cost_usd": 500.0,
             "direction": "LONG", "id": f"t{i}"} for i in range(8)]
    r = Harness(book_state=book(open_book=full)).run()
    assert r["verdict"] == "WAIT"
    assert "max_open_positions" in codes(r)


def test_wait_when_drawdown_breaker_paused():
    r = Harness(book_state=book(breaker_blocked=True)).run()
    assert r["verdict"] == "WAIT"
    assert "drawdown_breaker_pause" in codes(r)
    assert next(x for x in r["what_would_change"] if x["code"] == "breaker")["params"]["days"] == 7


def test_avoid_when_ai_says_avoid():
    r = Harness(routine={**BUY, "signal": "AVOID", "confidence": 70}).run()
    assert r["verdict"] == "AVOID"
    assert codes(r)[0] == "ai_rejected"
    assert r["headline"]["code"] == "avoid"


def test_avoid_when_trend_filter_fails_and_ai_is_not_called():
    tech = {**GOOD_TECH, "current_price": 80.0, "last_close": 80.0, "sma_50": 82.0, "sma_200": 85.0}
    h = Harness(tech=tech)
    r = h.run()
    assert r["verdict"] == "AVOID"
    assert r["reasons"][0]["params"]["check"] == "below_sma200"
    assert {"reclaim_sma200", "golden_cross"} <= set(hint_codes(r))
    h.synth.assert_not_called()
    h.sent.assert_not_called()
    assert r["ai"]["called"] is False
    assert "ai_skipped" in [n["code"] for n in r["notes"]]


def test_avoid_on_material_red_flag():
    flag = {"text": "SEC opens fraud investigation", "url": "https://example.com/sec",
            "severity": "high", "category": "fraud"}
    r = Harness(sentiment={**SENTIMENT, "red_flags": [flag]}).run()
    assert r["verdict"] == "AVOID"
    assert "red_flag" in codes(r)
    assert r["trail"]["grok"]["red_flags"][0]["url"] == "https://example.com/sec"


def test_etf_xeqt_is_safe_income_without_sentiment_or_earnings():
    fund = {"company_name": "iShares Core Equity ETF Portfolio", "quote_type": "ETF",
            "market_cap": None, "sector": None}
    h = Harness(symbol="XEQT.TO", exchange="TSX", fund=fund, fx=0.73)
    r = h.run()
    assert r["asset_class"] == "ETF"
    assert r["bucket"] == "SAFE_INCOME"
    assert r["currency"] == "CAD"
    assert r["earnings"] is None
    h.sent.assert_not_called()      # SAFE_INCOME skips Grok, as in the scan
    h.earn.assert_not_called()      # ETFs have no earnings
    assert r["verdict"] == "BUY_NOW"
    assert r["size"]["fx_to_usd"] == 0.73


def test_crypto_asset_class():
    fund = {"company_name": "Bitcoin USD", "quote_type": "CRYPTOCURRENCY"}
    tech = {**GOOD_TECH, "dollar_volume_avg_20": None, "volume_avg_20": 60_000_000_000.0}
    h = Harness(symbol="BTC-USD", exchange="CRYPTO", fund=fund, tech=tech)
    r = h.run()
    assert r["asset_class"] == "CRYPTO"
    assert r["bucket"] == "HIGH_RISK"
    assert r["earnings"] is None
    h.earn.assert_not_called()
    assert r["verdict"] == "BUY_NOW"


def test_decide_verdict_pure():
    ok = sc._gate("a", True, "wait")
    w = sc._gate("b", False, "wait", {"code": "x"})
    a = sc._gate("c", False, "avoid", {"code": "y"})
    assert sc.decide_verdict([ok]) == ("BUY_NOW", [])
    assert sc.decide_verdict([ok, w])[0] == "WAIT"
    v, failing = sc.decide_verdict([w, a])
    assert v == "AVOID" and failing[0]["key"] == "c"


def test_rr_fix_price():
    # target 115, stop 95, min 2 -> E = (115 + 190) / 3 = 101.67
    assert sc.rr_fix_price(115.0, 95.0, 2.0) == pytest.approx(101.6667, abs=1e-3)


def test_bucket_classifier_never_persists():
    with patch("app.db.queries.upsert_ticker") as up:
        b = sc.classify_bucket_readonly("NEWCO", {"sector": "Utilities", "market_cap": 2e11,
                                                  "dividend_yield": 0.03})
    assert b == "SAFE_INCOME"
    up.assert_not_called()
    from app.services import scan_service
    assert "NEWCO" not in scan_service._bucket_cache


# ============================================================
# No live-statistics writes
# ============================================================

def test_check_never_writes_signals_decisions_outcomes_trades_or_tickers():
    from tests.brain_fakes import FakeDB, patch_db, wallet_row

    db = FakeDB({
        "brain_wallet": [wallet_row()],
        "virtual_trades": [{"id": "t1", "symbol": "MSFT", "status": "OPEN", "source": "brain",
                            "direction": "LONG", "sector": "Technology", "shares": 5.0,
                            "position_size_usd": 1000.0, "is_wallet_trade": True,
                            "entry_price": 200.0, "fx_to_usd_entry": 1.0}],
    })
    from contextlib import ExitStack

    from app.db import queries

    names = ("insert_signals_batch", "insert_brain_decisions", "insert_candidate_outcomes",
             "update_candidate_outcome", "upsert_ticker", "insert_scan", "update_scan")
    forbidden = {n: MagicMock(side_effect=AssertionError(f"{n} must not be called"))
                 for n in names if hasattr(queries, n)}
    assert {"insert_signals_batch", "insert_brain_decisions", "insert_candidate_outcomes",
            "upsert_ticker"} <= set(forbidden)
    h = Harness()
    with ExitStack() as stack:
        stack.enter_context(patch_db(db))
        for n, m in forbidden.items():
            stack.enter_context(patch.object(queries, n, m))
        for target in ("app.services.ai_retry_queue.record_failure",
                       "app.services.ai_retry_queue.clear_success",
                       "app.services.wallet.update_peak_equity",
                       "app.services.wallet.set_breaker_state",
                       "app.services.wallet.get_wallet"):
            stack.enter_context(patch(target, side_effect=AssertionError(target)))
        r = _run_with_real_book(h)
    assert r["verdict"] in ("BUY_NOW", "WAIT", "AVOID")
    writes = [c for c in db.calls if c[1] in ("insert", "update", "upsert", "delete")]
    assert writes == [], writes
    for m in forbidden.values():
        m.assert_not_called()
    # it did read the book
    assert any(c[0] == "virtual_trades" and c[1] == "select" for c in db.calls)
    assert r["trail"]["sector_exposure"]["held"] == 1


def _run_with_real_book(h: Harness):
    """Harness.run() but without patching load_book_state."""
    corr = CorrelationCheck(None, {"status": "checked", "corr": {"MSFT": 0.4}, "rule": None})
    with patch("app.scanners.market_scanner.get_price_history", AsyncMock(return_value=object())), \
         patch("app.scanners.market_scanner.get_fundamentals", AsyncMock(return_value=dict(h.fund))), \
         patch("app.scanners.indicators.compute_indicators", return_value=dict(h.tech)), \
         patch.object(sc, "_macro_snapshot", AsyncMock(return_value={"vix": 15})), \
         patch.object(sc, "_knowledge_block", AsyncMock(return_value="")), \
         patch.object(sc, "get_earnings_context", h.earn), \
         patch("app.scanners.barchart_scanner.get_options_flow", AsyncMock(return_value=None)), \
         patch("app.services.pattern_stats.get_pattern_warning", return_value=None), \
         patch.object(ai_provider, "analyze_sentiment", h.sent), \
         patch.object(ai_provider, "synthesize_signal", h.synth), \
         patch.object(sc, "compute_score", return_value=(h.score, {})), \
         patch.object(sc, "_market_open", return_value=True), \
         patch.object(portfolio_risk, "check_correlation_limit", return_value=corr), \
         patch("app.signals.regime.get_market_regime", return_value="TRENDING"):
        return run(sc.run_check(h.resolved))
