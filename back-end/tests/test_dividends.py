"""services/dividends.py — pure computations and the brain's dividend rules,
plus their wiring into Check a stock (trade + hold) and compare.
No network: yfinance is never called (conftest patches _fetch_raw)."""

import asyncio
from datetime import date, timedelta

import pandas as pd
import pytest

from app.services import dividends as dv
from app.services import stock_compare as scmp

TODAY = date(2026, 9, 29)


def run(coro):
    return asyncio.run(coro)


def series(start: date, n: int, amounts, step_days: int = 91) -> list[tuple[date, float]]:
    """n payments every step_days; amounts: a constant, a list, or fn(i)."""
    out = []
    for i in range(n):
        a = amounts(i) if callable(amounts) else (amounts[i % len(amounts)] if isinstance(amounts, list) else amounts)
        out.append((start + timedelta(days=step_days * i), float(a)))
    return out


def quarterly_growing(years=8, start=date(2018, 10, 10), growth=0.06, base=0.50):
    n = years * 4 + 1
    return series(start, n, lambda i: round(base * (1 + growth) ** (i // 4), 4))


# ============================================================
# History cleaning + specials
# ============================================================

def test_clean_payments_from_pandas_series_with_tz():
    idx = pd.DatetimeIndex(["2026-02-19 09:30", "2026-05-21 09:30"]).tz_localize("America/New_York")
    s = pd.Series([0.91, 0.91], index=idx)
    assert dv.clean_payments(s) == [(date(2026, 2, 19), 0.91), (date(2026, 5, 21), 0.91)]


def test_clean_payments_drops_bad_and_sums_same_day():
    got = dv.clean_payments([("2026-01-01", 0.5), ("2026-01-01", 0.1), ("2026-02-01", 0), ("2026-03-01", "x")])
    assert got == [(date(2026, 1, 1), pytest.approx(0.6))]


def test_split_specials_large_one_off():
    pays = series(date(2023, 1, 10), 12, 0.25)
    pays.insert(6, (pays[5][0] + timedelta(days=30), 5.0))  # big special between two regulars
    regular, specials = dv.split_specials(pays)
    assert specials == [(pays[6][0], 5.0)]
    assert len(regular) == 12


def test_split_specials_small_off_cycle_extra():
    pays = series(date(2023, 1, 10), 12, 1.0)
    extra = (pays[4][0] + timedelta(days=10), 0.08)
    pays = sorted(pays + [extra])
    regular, specials = dv.split_specials(pays)
    assert specials == [extra] and len(regular) == 12


# ============================================================
# Frequency
# ============================================================

@pytest.mark.parametrize("step,label", [(30, "monthly"), (91, "quarterly"), (182, "semiannual"), (365, "annual")])
def test_infer_frequency_bands(step, label):
    freq, gap = dv.infer_frequency(series(date(2022, 1, 5), 10, 1.0, step))
    assert freq == label and gap == step


def test_infer_frequency_irregular_and_short():
    pays = [(date(2024, 1, 1), 1.0), (date(2024, 2, 20), 1.0), (date(2024, 9, 1), 1.0), (date(2025, 1, 1), 1.0)]
    assert dv.infer_frequency(pays)[0] == "irregular"
    assert dv.infer_frequency(pays[:1]) == (None, None)


def test_infer_frequency_tolerates_jitter():
    pays = [(date(2024, 1, 15) + timedelta(days=d), 0.5) for d in (0, 88, 184, 270, 365, 458, 546)]
    assert dv.infer_frequency(pays)[0] == "quarterly"


# ============================================================
# Cuts, growth, years without a cut
# ============================================================

def test_detect_cuts_flat_then_cut():
    pays = series(date(2021, 1, 10), 8, 0.52) + series(date(2023, 1, 5), 6, 0.2775)
    cuts = dv.detect_cuts(pays, "quarterly")
    assert cuts == [date(2023, 1, 5)]      # one cut, not one per slot


def test_detect_cuts_second_cut_is_reported():
    pays = series(date(2020, 1, 10), 8, 1.0) + series(date(2022, 1, 5), 4, 0.6) + series(date(2023, 1, 1), 4, 0.3)
    assert dv.detect_cuts(pays, "quarterly") == [date(2022, 1, 5), date(2023, 1, 1)]


def test_detect_cuts_ignores_small_wobble_and_raises():
    pays = series(date(2020, 1, 10), 12, lambda i: 1.0 if i % 3 else 0.9)  # 10% wobble < 15%
    assert dv.detect_cuts(pays, "quarterly") == []
    assert dv.detect_cuts(quarterly_growing(), "quarterly") == []


def test_detect_cuts_interim_final_pattern_is_not_a_cut():
    # Semiannual: interim 0.30, final 0.60 every year — same-slot comparison.
    pays = series(date(2019, 3, 1), 12, [0.30, 0.60], 182)
    assert dv.infer_frequency(pays)[0] == "semiannual"
    assert dv.detect_cuts(pays, "semiannual") == []


def test_detect_cuts_irregular_returns_empty():
    assert dv.detect_cuts(series(date(2020, 1, 1), 8, 1.0), "irregular") == []


def test_dividend_cagr_growing_and_flat():
    g = dv.dividend_cagr(quarterly_growing(growth=0.06), "quarterly")
    assert g == pytest.approx(0.06, abs=0.01)
    flat = series(date(2019, 1, 10), 26, 0.5)
    assert dv.dividend_cagr(flat, "quarterly") == pytest.approx(0.0, abs=1e-9)


def test_dividend_cagr_needs_history():
    assert dv.dividend_cagr(series(date(2023, 1, 10), 10, 0.5), "quarterly") is None
    assert dv.dividend_cagr(quarterly_growing(), "irregular") is None


def test_years_without_cut():
    pays = series(date(2010, 1, 1), 4, 1.0)
    assert dv.years_without_cut(pays, [], date(2020, 1, 1)) == pytest.approx(10.0, abs=0.1)
    assert dv.years_without_cut(pays, [date(2018, 1, 1)], date(2020, 1, 1)) == pytest.approx(2.0, abs=0.1)
    assert dv.years_without_cut([], [], TODAY) is None


def test_is_stale():
    assert dv.is_stale(TODAY - timedelta(days=200), 91, TODAY) is True
    assert dv.is_stale(TODAY - timedelta(days=100), 91, TODAY) is False
    assert dv.is_stale(None, 91, TODAY) is True


# ============================================================
# Projection
# ============================================================

def test_projected_amounts_flat_vs_seasonal():
    assert dv.projected_amounts(series(date(2025, 1, 1), 6, 0.5), "quarterly") == [0.5] * 4
    raised = series(date(2025, 1, 1), 5, 0.5) + [(date(2026, 4, 1), 0.53)]
    assert dv.projected_amounts(raised, "quarterly") == [0.53] * 4
    seasonal = series(date(2024, 3, 1), 4, [0.30, 0.60], 182)
    assert dv.projected_amounts(seasonal, "semiannual") == [0.30, 0.60]


def test_project_schedule_estimated_from_last_ex():
    sched = dv.project_schedule(date(2026, 8, 14), 91, [0.97] * 4, TODAY, pay_offset_days=18)
    assert [s["ex_date"] for s in sched] == ["2026-11-13", "2027-02-12", "2027-05-14", "2027-08-13"]
    assert all(s["estimated"] for s in sched)
    assert sched[0]["pay_date"] == "2026-12-01" and sched[0]["pay_estimated"] is True
    assert sched[0]["amount"] == 0.97


def test_project_schedule_uses_confirmed_future_dates():
    sched = dv.project_schedule(date(2026, 8, 20), 91, [0.91] * 4, TODAY, confirmed_ex=date(2026, 11, 18),
                                confirmed_pay=date(2026, 12, 9), pay_offset_days=21)
    assert sched[0] == {"ex_date": "2026-11-18", "pay_date": "2026-12-09", "amount": 0.91,
                        "estimated": False, "pay_estimated": False}
    assert sched[1]["ex_date"] == "2027-02-17" and sched[1]["estimated"] is True
    assert all(date.fromisoformat(s["ex_date"]) <= TODAY + timedelta(days=365) for s in sched)


def test_project_schedule_skips_overdue_cycles_and_handles_no_data():
    sched = dv.project_schedule(date(2026, 6, 1), 91, [1.0] * 4, TODAY)
    assert date.fromisoformat(sched[0]["ex_date"]) >= TODAY
    assert sched[0]["pay_date"] is None
    assert dv.project_schedule(None, None, [], TODAY) == []


# ============================================================
# build_profile
# ============================================================

MSFT_INFO = {"quoteType": "EQUITY", "currency": "USD", "dividendRate": 3.64, "regularMarketPrice": 400.0,
             "payoutRatio": 0.25, "fiveYearAvgDividendYield": 0.8, "exDividendDate": 1795046400,  # 2026-11-18
             "dividendDate": 1796860800, "sector": "Technology", "industry": "Software"}


def test_build_profile_payer_with_confirmed_next():
    prof = dv.build_profile("MSFT", MSFT_INFO, quarterly_growing(start=date(2018, 11, 20), base=0.50),
                            {"Ex-Dividend Date": date(2026, 11, 18), "Dividend Date": date(2026, 12, 9)}, TODAY)
    assert prof["pays_dividend"] is True and prof["frequency"] == "quarterly"
    assert prof["yield"] == pytest.approx(3.64 / 400, rel=1e-3)
    assert prof["annual_rate"] == 3.64 and prof["payout_ratio"] == 0.25
    assert prof["five_year_avg_yield"] == pytest.approx(0.008)
    assert prof["next_ex_date"] == "2026-11-18" and prof["next_estimated"] is False
    assert prof["next_pay_date"] and prof["next_pay_estimated"] is False
    assert prof["growth_5y_cagr"] > 0 and prof["recent_cut"] is False
    assert 1 <= len(prof["upcoming"]) <= 5 and len(prof["last_payments"]) == 8
    assert prof["last_payments"][0]["ex_date"] > prof["last_payments"][-1]["ex_date"]  # newest first


def test_build_profile_ignores_future_history_rows_and_calendar_in_past():
    pays = series(date(2024, 8, 14), 9, 0.97)  # last 2026-08-19; later rows are "future"
    pays = [p for p in pays if p[0] <= TODAY] + [(TODAY + timedelta(days=30), 0.97)]
    prof = dv.build_profile("ENB.TO", {"quoteType": "EQUITY", "currency": "CAD"}, pays,
                            {"Ex-Dividend Date": date(2026, 8, 13), "Dividend Date": date(2026, 8, 31)}, TODAY)
    assert prof["next_estimated"] is True
    assert prof["next_pay_date"] is not None and prof["next_pay_estimated"] is True  # 18-day offset reused


def test_build_profile_non_payer_crypto_and_suspended():
    assert dv.build_profile("BTC-USD", {}, [], {}, TODAY)["reason"] == "crypto"
    none = dv.build_profile("TSLA", {"quoteType": "EQUITY"}, None, {}, TODAY)
    assert none["pays_dividend"] is False and none["yield"] is None and none["upcoming"] == []
    old = series(TODAY - timedelta(days=91 * 8 + 300), 8, 0.4)
    sus = dv.build_profile("XYZ", {"quoteType": "EQUITY"}, old, {}, TODAY)
    assert sus["pays_dividend"] is False and sus["suspended"] is True and sus["recent_cut"] is True


def test_build_profile_recent_cut():
    pays = series(date(2022, 1, 10), 12, 0.52) + series(date(2025, 1, 10), 7, 0.30)
    prof = dv.build_profile("CUT", {"quoteType": "EQUITY", "payoutRatio": 1.3}, pays, {}, TODAY)
    assert prof["recent_cut"] is True and prof["last_cut_date"] == "2025-01-10"
    assert prof["years_without_cut"] == pytest.approx(1.7, abs=0.1)


def test_get_dividend_profile_crypto_skips_fetch_and_caches(monkeypatch):
    calls = []

    def fake(symbol, info=None):
        calls.append(symbol)
        return {"info": {"quoteType": "EQUITY", "dividendRate": 1.0, "regularMarketPrice": 50.0},
                "dividends": series(date(2024, 1, 10), 11, 0.25), "calendar": {}}

    monkeypatch.setattr(dv, "_fetch_raw", fake)
    monkeypatch.setattr(dv, "today_et", lambda: TODAY)
    assert run(dv.get_dividend_profile("ETH-USD"))["reason"] == "crypto"
    a = run(dv.get_dividend_profile("KO"))
    b = run(dv.get_dividend_profile("KO"))
    assert a["pays_dividend"] and a == b and calls == ["KO"]


def test_get_dividend_profile_never_raises(monkeypatch):
    def boom(symbol, info=None):
        raise RuntimeError("network")

    monkeypatch.setattr(dv, "_fetch_raw", boom)
    prof = run(dv.get_dividend_profile("ZZZ"))
    assert prof["pays_dividend"] is False and prof["reason"] == "unavailable"


# ============================================================
# Trade-mode rules
# ============================================================

def _payer(**kw):
    base = {"pays_dividend": True, "next_ex_date": "2026-10-08", "next_amount": 0.50, "next_estimated": False,
            "next_pay_date": "2026-11-01"}
    return {**base, **kw}


def test_trade_rule_ex_date_inside_window():
    rules, lv = dv.trade_dividend_rules(_payer(), 50.0, 50.0, 46.0, 54.0, "NYSE", today=TODAY)
    codes = [r["code"] for r in rules]
    assert codes == ["ex_dividend_in_window"]
    p = rules[0]["params"]
    assert p["pct"] == pytest.approx(1.0) and p["amount"] == 0.5 and 1 <= p["days"] <= 20
    assert lv["rr_with_dividend"] == pytest.approx((54 - 50 + 0.5) / 4, abs=0.01)
    assert rules[0]["effect"] == "positive"


def test_trade_rule_stop_risk_when_dividend_is_big_vs_stop():
    rules, _ = dv.trade_dividend_rules(_payer(next_amount=1.0), 50.0, 50.0, 48.0, 54.0, "NYSE", today=TODAY)
    stop = [r for r in rules if r["code"] == "ex_dividend_stop_risk"]
    assert stop and stop[0]["params"]["pct_of_risk"] == 50


def test_trade_rule_outside_window_non_payer_and_today():
    far = _payer(next_ex_date=(TODAY + timedelta(days=60)).isoformat())
    assert dv.trade_dividend_rules(far, 50, 50, 48, 54, "NYSE", today=TODAY) == ([], None)
    assert dv.trade_dividend_rules({"pays_dividend": False}, 50, 50, 48, 54, "NYSE", today=TODAY) == ([], None)
    rules, lv = dv.trade_dividend_rules(_payer(next_ex_date=TODAY.isoformat()), 50, 50, 48, 54, "NYSE", today=TODAY)
    assert [r["code"] for r in rules] == ["ex_dividend_just_passed"] and lv is None


# ============================================================
# Hold-mode rules
# ============================================================

def _stock(**kw):
    base = {"pays_dividend": True, "yield": 0.03, "payout_ratio": 0.5, "growth_5y_cagr": 0.06,
            "years_without_cut": 12.0, "five_year_avg_yield": 0.028, "recent_cut": False, "frequency": "quarterly"}
    return {**base, **kw}


def codes(a):
    return [r["code"] for r in a["rules"]]


def test_long_grower_with_sustainable_payout_is_good():
    a = dv.long_term_dividend_assessment(_stock(), "STOCK", "Industrials", "Machinery")
    assert a["item"]["key"] == "dividend" and a["item"]["rating"] == "good"
    assert codes(a) == ["consistent_grower", "sustainable_payout"] and a["cap"] is False


def test_long_recent_cut_plus_payout_over_one_caps_verdict():
    a = dv.long_term_dividend_assessment(_stock(recent_cut=True, payout_ratio=1.2, last_cut_date="2025-06-01",
                                                growth_5y_cagr=-0.1, years_without_cut=1.3), "STOCK")
    assert a["item"]["rating"] == "poor" and a["cap"] is True
    assert {"recent_cut", "payout_unsustainable", "cap_verdict"} <= set(codes(a))
    assert dv.apply_verdict_cap("SOLID", True) == ("REASONABLE_WITH_CAVEATS", {
        "code": "dividend_cut_unsustainable", "from": "SOLID", "to": "REASONABLE_WITH_CAVEATS"})
    assert dv.apply_verdict_cap("NOT_A_GOOD_FIT", True) == ("NOT_A_GOOD_FIT", None)
    assert dv.apply_verdict_cap("SOLID", False) == ("SOLID", None)


def test_long_payout_over_one_alone_is_poor_but_no_cap():
    a = dv.long_term_dividend_assessment(_stock(payout_ratio=1.4), "STOCK", "Consumer Defensive")
    assert a["item"]["rating"] == "poor" and a["cap"] is False and "payout_unsustainable" in codes(a)


def test_long_reit_utility_midstream_context_softens_payout():
    for sector, industry in (("Real Estate", "REIT - Retail"), ("Utilities", "Utilities - Regulated"),
                             ("Energy", "Oil & Gas Midstream")):
        a = dv.long_term_dividend_assessment(_stock(payout_ratio=1.4), "STOCK", sector, industry)
        assert a["item"]["rating"] == "fair", sector
    util = dv.long_term_dividend_assessment(_stock(payout_ratio=0.85), "STOCK", "Utilities", "Utilities")
    assert util["item"]["rating"] == "good" and "sustainable_payout" in codes(util)


def test_long_yield_trap_and_high_payout():
    trap = dv.long_term_dividend_assessment(_stock(**{"yield": 0.09, "five_year_avg_yield": 0.04}),
                                            "STOCK")
    assert "yield_trap" in codes(trap) and trap["item"]["rating"] == "fair"
    low = dv.long_term_dividend_assessment(_stock(**{"yield": 0.02, "five_year_avg_yield": 0.01}), "STOCK")
    assert "yield_trap" not in codes(low)  # below the 4% floor
    high = dv.long_term_dividend_assessment(_stock(payout_ratio=0.9), "STOCK", "Industrials")
    assert "payout_high" in codes(high) and high["item"]["rating"] == "fair"


def test_long_non_payer_etf_crypto_are_not_rated():
    assert dv.long_term_dividend_assessment({"pays_dividend": False}, "STOCK")["item"]["rating"] == "n/a"
    assert dv.long_term_dividend_assessment(_stock(), "ETF")["item"]["code"] == "etf_distribution"
    assert dv.long_term_dividend_assessment(_stock(), "CRYPTO")["item"]["rating"] == "n/a"
    sus = dv.long_term_dividend_assessment({"pays_dividend": False, "suspended": True}, "STOCK")
    assert sus["item"]["rating"] == "poor"


def test_ai_summary_is_short_and_factual():
    s = dv.ai_summary({**_stock(), "annual_rate": 2.0, "next_ex_date": "2026-11-18", "next_estimated": True})
    assert s.startswith("Dividend: yield 3.00%") and "(estimated)" in s and "recent cut: no" in s
    assert len(s) < 300
    assert dv.ai_summary({"pays_dividend": False}) == "No regular dividend."


# ============================================================
# Wiring: long check (verdict cap), prompts, compare
# ============================================================

def test_long_check_dividend_cap_overrides_ai_solid(monkeypatch):
    from tests.test_long_term_check import AI_OK, STOCK_PROFILE, Harness

    cut_hist = series(date(2021, 1, 10), 14, 0.52) + series(date(2024, 7, 10), 6, 0.25)
    info = {**STOCK_PROFILE["info"], "payoutRatio": 1.3, "dividendRate": 1.0, "regularMarketPrice": 45.0}
    monkeypatch.setattr(dv, "_fetch_raw", lambda symbol, info=None: {"info": info, "dividends": cut_hist,
                                                                      "calendar": {}})
    monkeypatch.setattr(dv, "today_et", lambda: date(2025, 12, 1))
    h = Harness(symbol="ACME", profile={**STOCK_PROFILE, "info": info}, ai_result=dict(AI_OK))
    h.sent.return_value = {"confidence": 0}
    r = h.run()
    item = next(s for s in r["scorecard"] if s["key"] == "dividend")
    assert item["rating"] == "poor"
    assert r["verdict"] == "REASONABLE_WITH_CAVEATS" and r["verdict_source"] == "ai"
    assert r["verdict_adjustments"][0]["code"] == "dividend_cut_unsustainable"
    assert any(n["code"] == "dividend_cap" for n in r["notes"])
    assert r["dividend"]["recent_cut"] is True and r["dividend_rules"]
    prompt = h.ai.call_args.args[1]
    assert "## Dividend" in prompt and "recent cut: yes" in prompt


def test_long_check_non_payer_unchanged():
    from tests.test_long_term_check import AI_OK, Harness

    r = Harness(ai_result=dict(AI_OK)).run()
    assert r["verdict"] == "SOLID" and r["verdict_adjustments"] == []
    assert r["dividend"]["pays_dividend"] is False


def test_format_fundamentals_includes_dividend_summary_only_when_given():
    from app.ai.prompts import format_fundamentals

    assert "Dividend:" not in format_fundamentals({"dividend_yield": 0.02})
    assert "- Dividend: yield" in format_fundamentals({"_dividend_summary": "Dividend: yield 2.00%."})


def test_compare_dividend_rows():
    res = [
        {"symbol": "MSFT", "verdict": "SOLID", "dividend": {"pays_dividend": True, "yield": 0.0077,
                                                           "next_ex_date": "2026-11-18", "next_estimated": False,
                                                           "growth_5y_cagr": 0.10}},
        {"symbol": "T", "verdict": "SOLID", "dividend": {"pays_dividend": True, "yield": 0.045,
                                                        "next_ex_date": "2026-10-08", "next_estimated": True,
                                                        "growth_5y_cagr": -0.11, "recent_cut": False}},
        {"symbol": "TSLA", "verdict": "SOLID", "dividend": {"pays_dividend": False}},
    ]
    for mode in ("long", "short"):
        cmp = scmp.build_comparison(mode, res)
        m = {x["key"]: x for x in cmp["metrics"] if x["group"] == "dividend"}
        assert set(m) == {"dividend_yield", "next_ex_date", "dividend_growth_5y"}
        assert m["dividend_yield"]["values"] == {"MSFT": 0.77, "T": 4.5, "TSLA": None}
        assert m["dividend_yield"]["best"] is None                 # informational
        assert m["dividend_growth_5y"]["best"] == ["MSFT"]
        assert m["next_ex_date"]["format"] == "date" and m["next_ex_date"]["detail"]["T"]["estimated"] is True


# ============================================================
# Wiring: trade-mode check
# ============================================================

def test_short_check_reports_ex_date_in_window_without_changing_verdict(monkeypatch):
    from tests.test_stock_check_service import Harness

    base = Harness().run()
    soon = dv.today_et() + timedelta(days=14)
    prof = {**dv.empty_profile("ACME"), "pays_dividend": True, "yield": 0.02, "frequency": "quarterly",
            "next_ex_date": soon.isoformat(), "next_amount": 0.5, "next_estimated": True}

    async def fake_profile(symbol, info=None, price=None):
        return prof

    monkeypatch.setattr(dv, "get_dividend_profile", fake_profile)
    h = Harness()
    r = h.run()
    assert r["verdict"] == base["verdict"]
    assert r["dividend"]["pays_dividend"] is True
    assert [x["code"] for x in r["dividend_rules"]][0] == "ex_dividend_in_window"
    assert any(n["code"] == "ex_dividend_in_window" for n in r["notes"])
    assert r["levels"]["dividend"]["amount"] == 0.5 and r["levels"]["dividend"]["pct"] == pytest.approx(0.5, abs=0.05)
    fund_arg = h.synth.call_args_list[0].args[2]
    assert fund_arg["_dividend_summary"].startswith("Dividend: yield 2.00%")


def test_short_check_non_payer_has_no_dividend_rules():
    from tests.test_stock_check_service import Harness

    r = Harness().run()
    assert r["dividend"]["pays_dividend"] is False and r["dividend_rules"] == [] and r["levels"]["dividend"] is None
