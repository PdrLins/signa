"""Curate the brain's knowledge tables per the 2026-09 rules audit.

Usage (from back-end/):
    venv/bin/python scripts/curate_brain_knowledge.py            # dry run (default): prints the plan, writes nothing
    venv/bin/python scripts/curate_brain_knowledge.py --apply    # archive, verify, then apply

WHAT --apply DOES, in order
  1. Exports investment_rules, signal_knowledge and signal_thinking to
     back-end/docs/archive/<YYYY-MM-DD>-knowledge/<table>.json (+ manifest.json;
     docs/archive/ is gitignored), then READS THE FILES BACK and checks the
     row ids match the DB. Nothing is changed unless that check passes.
  2. Deactivates (is_active=false, never deletes) every row the audit marked
     REMOVE, appending the reason to `notes`.
  3. Applies the audit's REVISE corrections that have a concrete corrected
     value (text / threshold). REVISE rows without one are left as they are
     and listed.
  4. Inserts the PROMPT_CORE rows (knowledge_service.build_prompt_core_rows)
     — skipped when the key_concept already exists (idempotent).
  5. Retires the hypotheses the audit says to retire (status='retired');
     bc1aa8c3 (HIGH_RISK score>=88) is kept.

Every step is idempotent: re-running --apply skips rows already in the
target state. Rows are matched by id AND name; a mismatch is skipped with a
warning. The API server caches knowledge for 5 minutes; changes show up in
prompts after that (or after a restart).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.db.supabase import get_client  # noqa: E402
from app.services.knowledge_service import build_prompt_core_rows  # noqa: E402

PAGE = 1000
TABLES = ("investment_rules", "signal_knowledge", "signal_thinking")
NAME_COL = {"investment_rules": "name", "signal_knowledge": "key_concept", "signal_thinking": "hypothesis"}
AUDIT_TAG = "[2026-09 audit]"

# ── REMOVE: deactivate (id, name, reason) ────────────────────────────────
REMOVE_RULES = [
    ("5920f54b-ee5e-454d-8b96-147bf52d94de", "momentum_trap", "Contradicts momentum evidence and the RSI>75 finding; small 2024-25 sample."),
    ("c48a0cef-a6c8-44b2-9e81-5fc02afdf3bf", "high_volume_momentum_continuation_boost", "Not implemented; short-horizon continuation in large caps is not robust."),
    ("31d3b27b-9003-4bfa-a3f2-f3119444aedb", "superficial_loss_warning_canada", "Never computed (dead row)."),
    ("6d071df5-cedf-40ef-b2d2-3c321e5de85a", "supply_deficit_commodity_boost", "Not implemented; duplicate of supply_deficit_asymmetry; anecdotal claim."),
    ("6a3b6146-65d3-46dd-b97d-27ddc5945c63", "minimum_market_cap", "Not enforced anywhere; universe is curated."),
    ("43756a25-0672-4f25-bd4c-ea263dc784a3", "kelly_position_sizing", "Conflicts with live 1%-risk sizing; score->win-rate map invalid (score has no edge)."),
    ("5ab12dc8-bdfb-4065-902d-a1c8727b3b95", "volume_spike_confirmation", "Not implemented; auto-generated from a small sample."),
    ("a119cc7e-cf83-4c17-8213-86102567a46d", "score_drop_guard", "Guards a code path removed in the 2026-09 reset."),
    ("99b26f6f-9669-4db9-827a-2a1c370a37d8", "contrarian_sentiment_override", "Conflicts with live code (contrarian BUY override removed)."),
    ("0bece124-2860-4058-83cc-8ef4632c24d5", "ai_sector_bubble_caution", "Not implemented; duplicate of bubble_detection_framework; dated opinion."),
    ("16b2d0e1-1af7-4a91-ae3d-9eda7143d96f", "replacement_cost_floor", "Not computable; long-horizon value idea."),
]
REMOVE_KNOWLEDGE = [
    ("ff97bf64-e512-4896-b50a-904d68d0e63c", "score_ranges_and_actions", "Wrong thresholds (BUY 75-90, inverted >72); score no longer gates entries."),
    ("1220f7ca-929d-4061-ba77-64f26ae843c2", "gem_conditions", "Post-hoc Telegram label, irrelevant to the BUY/HOLD decision."),
    ("34b24cbd-c05d-434a-8539-042294e67baa", "kelly_position_sizing", "Conflicts with live 1%-risk sizing; score->win-rate map invalid."),
    ("0ecc9e77-81b9-4391-8b86-a22fac9c3bdb", "backtest_key_findings", "Old 30-ticker findings contradicted by the 2021-2026 study."),
    ("70bbd8df-5698-4111-a70c-f66de7a765ac", "dispersion_as_opportunity", "Vague; not computed."),
    ("f0a45b10-f4a6-4639-81b1-e60c02f867d2", "cra_day_trading_five_factors", "Covered by canada_account_type_strategy."),
    ("69852bdb-c896-4d66-b462-926757d9bbc5", "capital_gains_vs_business_income_canada", "Covered by canada_account_type_strategy."),
    ("bd50f629-5175-4138-82ea-edac2c9c46f9", "blackrock_systematic_five_principles", "Marketing text; Kelly and invented Grok rules."),
    ("8f7d7ff1-4e89-4f2b-993d-d0256c783e65", "event_driven_is_highest_conviction", "Conflicts with the earnings blackout; tiers not in code."),
    ("ab854a3f-f04e-45e3-bf84-adea3f9fe2d4", "factor_rotation_by_regime", "Factor timing weakly supported; not implemented."),
    ("d8ceaa55-7cb8-411f-be53-6bd0e1c7393d", "optimal_lookback_windows", "Backwards vs evidence (1-month reverses; 12-1 momentum is the documented effect)."),
    ("cccc86d4-ec10-4a33-9f94-e9e1e11913b4", "contrarian_sentiment_in_commodities", "Tells Claude to flip negative sentiment; contrarian override removed; anecdotal."),
    ("1004019e-abd1-48a4-8776-145cd0441ace", "replacement_cost_valuation", "Duplicate; not computable."),
    ("b05e7acb-0dc0-4997-82e1-ea6838901786", "cycle_position_detection", "Long-horizon narrative, no data."),
    ("67bf2919-cefb-4837-bf17-c43324a603a9", "operating_leverage_detection", "Boost never implemented; no data."),
    ("ad60fc7b-1dd6-417c-ac4a-0908d39a4aa2", "esg_divestment_opportunity", "Narrative, not a signal."),
    ("d748ec26-a481-4458-a2a7-352306493ae1", "passive_flow_concentration_opportunity", "Not supported by evidence; not computed."),
    ("0c192219-2ccf-48ec-aec9-79c240cf302d", "geopolitical_second_order_effects", "Narrative."),
    ("490989e6-9dac-452d-adf1-4b8db50f0955", "score_consistency_guard", "Obsolete: score-based auto-close removed."),
    ("132bcb45-c742-4060-9ccd-3a5767d2fadf", "volatility_vs_permanent_loss", "Conflicts with ATR/risk sizing and hard stops."),
    ("50aae893-5657-4f95-a25d-b1b146ef61ff", "vix_term_structure_signal", "Says backwardation is a BUY signal; contradicts code (ratio>1.15 is hostile)."),
    ("4e72aefd-2f05-43e4-9012-fb84f689b838", "intermarket_copper_gold_ratio", "'Leads stocks by 2-4 weeks' unsupported."),
    ("78f0e55c-3c5d-4484-902b-626ed0cd5272", "post_earnings_drift_pead", "Third PEAD row; claims a bonus that does not exist."),
    ("1f3ccaac-82f2-4437-8118-e7fdb771ffff", "crypto_volatility_asymmetry", "Halved Kelly / 8% crypto stop not live."),
    ("68fb1f6a-4f66-4f44-89f4-75f108ef7e9e", "watchdog_slow_bleed_detection", "Slow-bleed exits removed in the 2026-09 reset."),
    ("15eafd5e-2d7f-4d8a-b89e-b4ba1bddee9d", "profit_target_strategy", "Old numbers contradicted by 2021-2026 study; -3% cut conflicts with ATR stops."),
    ("bb1d047d-aa0c-4f29-8c67-346a0f85629d", "cut_losers_fast_strategy", "-3/-5/-8% ladder conflicts with the 2xATR hard stop."),
    ("2749de5b-ef39-4282-97db-f632d15bc346", "portfolio_rotation_strategy", "No rotation logic; max 8 positions, not 20."),
    ("4aa80e24-6899-47ee-98d8-22d9b57e7e33", "composite_concern_rule", "Removed in reset; single-trade anecdote."),
    ("2b7addb1-8009-4d60-891e-85af1ca10312", "tighter_loss_threshold_day2", "n=1 anecdote; removed rule."),
    ("12264757-613c-4315-b663-f95d59cf8c15", "profit_taking_3pct", "Conflicts with 2R target + 2.5xATR trailing; anti-momentum."),
    ("3c8f2621-0fdc-40fc-9eaf-e740281296c4", "short_term_momentum_in_large_caps", "Overstated/contested claim."),
    ("cd7443a7-7b3f-4537-9dee-ca489fba5043", "bubble_detection_framework", "Sector-biased 2026 opinion; inputs not computable; penalty not implemented."),
    ("fd59e9e3-8107-480c-91f3-5d86a2e92750", "pead_decay_curve_and_optimal_hold", "Misstates Bernard-Thomas timing; covered by post_earnings_announcement_drift."),
    ("91e1490d-d8de-457e-9e2b-7f36266ef049", "put_call_ratio_contrarian", "Overstated; weak single-stock evidence."),
]

# ── REVISE: concrete corrections (id, name, {field: new value}) ──────────
REVISE_RULES = [
    ("58c575c3-ac9f-41a0-9b5d-09be0c757ee4", "rsi_overbought_blocker", {
        "description": "RSI(14) above 75 blocks a BUY (hardcoded in signal_engine.check_blockers; also settings.tech_filter_max_rsi). UNVALIDATED guard: in the 2021-2026 study, names failing the filter on RSI > 75 did best (n=104, +2.4pp vs SPY). Re-test at 80 or without it before relying on it.",
        "notes": "2026-09 audit: removed the '60%+ fail rate' claim from the old 30-ticker, 6-month test.",
    }),
    ("c9cf0b8c-ca42-45e9-8608-33d86f208a22", "fraud_red_flag_blocker", {
        "description": "Blocks a BUY only for red flags that are cited (have a URL) AND material: fraud / accounting / going-concern flags from medium severity up; other flags at high/critical severity unless the stated impact is < 1% of market cap. Flags without a severity block only on the keywords fraud, SEC investigation, scam, ponzi, insider trading. Routine litigation never blocks.",
        "formula": "signal_engine.red_flag_block_reason(flag, market_cap) is not None",
    }),
    ("d53095b2-2e9e-4e71-979e-93c48c9d0b6e", "rsi_sweet_spot", {
        "description": "RSI 50-65 adds +15 to the HIGH_RISK technical momentum score. UNVALIDATED scoring prior: the 2021-2026 study found the technical score has no edge vs SPY.",
        "notes": "2026-09 audit: removed the 'backtest validated / highest win rate' claim.",
    }),
    ("a9c609e5-982a-40a8-a2ce-8c168e12cf7c", "macd_surger", {
        "description": "A strongly positive MACD histogram, measured in ATR units (macd_histogram / ATR14 > settings.macd_hist_strong_atr = 0.25) so it is price-invariant, adds to the technical score. Unvalidated scoring prior.",
        "formula": "macd_histogram / atr14 > 0.25",
        "threshold_min": 0.25,
        "threshold_unit": "atr",
        "notes": "2026-09 audit: raw > 2.0 was price-dependent; removed the '3.3x return' claim from an old small test.",
    }),
    ("e35fd225-9ac5-47ec-9ace-0fa5085791be", "earnings_catalyst", {
        "description": "Upcoming earnings are labelled PRE_EARNINGS but not scored. No new BUY within 3 trading days of earnings (earnings blackout, BUY downgraded to HOLD): pre-earnings run-ups are not a reliable edge and the report is a binary gap risk.",
        "formula": "trading_days_to_next_earnings <= earnings_blackout_trading_days (3) → BUY becomes HOLD",
        "threshold_max": 3,
        "threshold_unit": "trading_days",
    }),
    ("50c93d76-a07d-4d59-98fe-0ac775391ffb", "score_below_hold", {
        "description": "Score below 55 (settings.score_hold) → AVOID label. It is a label, not the sell trigger: brain exits are stop / target / trailing stop / time limit (evaluate_exit).",
        "formula": "score < 55 → action = AVOID",
        "threshold_max": 55,
    }),
    ("25d4bd61-7198-4764-8172-25a75ef04c1c", "hostile_macro_blocker", {
        "description": "Blocks new BUYs when macro_scanner.classify_macro_environment returns 'hostile': 3 or more of VIX > 30, Fed funds > 5%, unemployment > 6%, 10y yield below Fed funds, VIX/VIX3M > 1.15, 10y-2y curve < 0, BBB OAS > 3%. The 2021-2026 tech-only study did not show worse expectancy on VOLATILE/CRISIS days; do not over-trust macro gating.",
        "formula": "classify_macro_environment(macro) != 'hostile'  (hostile = >= 3 stress conditions)",
    }),
    ("23a8ea4e-5067-45fb-8bbc-bc165fefbf9e", "minimum_daily_dollar_volume", {
        "description": "20-day average dollar volume must be >= $10M for stocks/ETFs (native currency) and >= $50M for crypto (settings.tech_filter_min_dollar_volume / _crypto), enforced by the technical filter.",
        "formula": "avg_dollar_volume_20d >= 10,000,000 (crypto 50,000,000)",
        "threshold_min": 10_000_000,
    }),
    ("32b09718-4c8d-4afa-9db1-31ecbc90f544", "tfsa_preferred_for_safe_income", {
        "description": "For SAFE_INCOME signals, a TFSA suits Canadian dividend payers and longer holds. Caveat: US dividends in a TFSA lose the 15% US withholding tax (an RRSP is treaty-exempt), so US dividend payers usually fit an RRSP better. General information, not tax advice.",
    }),
    ("2982b436-b8db-40f8-b2ab-ecad88ef9e75", "target_reached", {
        "description": "Target = entry + 2R (settings.brain_target_r_mult). Brain positions auto-close at the target (TARGET_HIT); for user positions a Telegram alert suggests taking profits.",
        "formula": "current_price >= target_price → brain: close TARGET_HIT; user position: alert",
    }),
    ("a511b746-bbe1-4a68-841b-2a45f7686737", "rrsp_preferred_for_high_risk", {
        "description": "For HIGH_RISK signals, an RRSP is suggested: active trading inside an RRSP is generally not taxed as business income, unlike frequent trading in a TFSA. General information, not tax advice.",
    }),
]

REVISE_KNOWLEDGE = [
    ("5305c34e-2aee-430b-9fa7-91ca60288017", "signal_blockers", {
        "explanation": "Code blocks a BUY for: RSI(14) > 75; price > 50% above SMA200; red flags that are cited AND material; hostile macro; avg volume < 50K or volume z-score < -2. A BUY within 3 trading days of earnings is downgraded to HOLD. The technical filter also requires price > SMA200, SMA50 > SMA200, <= 15% above SMA50 and 20-day dollar volume >= $10M ($50M crypto).",
    }),
    ("a4e53460-10b0-4e1b-8bfd-5cee00102678", "macro_environment_classification", {
        "explanation": "macro_scanner.classify_macro_environment counts stress conditions: VIX > 30, Fed funds > 5%, unemployment > 6%, 10y yield below Fed funds, VIX/VIX3M > 1.15, 10y-2y curve < 0, BBB OAS > 3%. 3+ = HOSTILE (blocks new BUYs), 1-2 = NEUTRAL, 0 = FAVORABLE. The SAFE_INCOME macro score uses VIX bands: <15 calm, 15-20 normal, 20-25 elevated, 25-35 high fear, 35+ crisis.",
    }),
    ("33fcc285-0286-48d0-a8b3-41e6774e5d9d", "crypto_handling", {
        "explanation": "Crypto tickers end in -USD and are always HIGH_RISK. They trade 24/7 (the watchdog runs on weekends). No fundamentals, so scoring leans on sentiment and momentum. The technical filter requires >= $50M 20-day dollar volume, and crypto is capped at 25% of equity (cost basis).",
    }),
    ("9570012e-20fb-47a6-8889-1f6e7a841f05", "momentum_crash_avoidance", {
        "explanation": "Momentum strategies crash in panic states after market declines when volatility is high (Daniel-Moskowitz). Enforced: the CRISIS regime (VIX > 30 or SPY more than 2% below its SMA200) sets HIGH_RISK scores to 0, so no HIGH_RISK entries; SAFE_INCOME scores are cut 40% unless the catalyst is a dividend or PEAD.",
        "formula": "regime == CRISIS: HIGH_RISK score = 0; SAFE_INCOME x0.60 unless catalyst in (DIVIDEND, PEAD, DIV_EXDATE)",
    }),
    ("5272d63a-f6f1-4b5f-9e37-5cc43dd4ebff", "market_regime_detection", {
        "explanation": "Four regimes (signals/regime.py), checked per scan: CRISIS (VIX > 30 or SPY > 2% below SMA200): HIGH_RISK paused, SAFE_INCOME x0.60 unless a dividend/PEAD catalyst. RECOVERY (VIX 20-30, SPY above SMA50, VIX > 30 within 30 days): no score adjustment. VOLATILE (VIX > 20 or SPY > 1% below SMA50): HIGH_RISK scores x0.85. TRENDING otherwise.",
        "formula": "if vix > 30 or spy_vs_sma200 < -2: CRISIS. elif 20 < vix <= 30 and spy_vs_sma50 > 0 and recent crisis: RECOVERY. elif vix > 20 or spy_vs_sma50 < -1: VOLATILE. else: TRENDING",
    }),
    ("cee1bd15-aed8-4262-979b-93cc8cede387", "grok_sentiment_calibration", {
        "explanation": "X/web sentiment counts only when cited; uncited results get zero weight. With fewer than 100 mentions the sentiment weight drops to 5%; extreme scores (> 85 or < 15) get a small contrarian adjustment in compute_score.",
    }),
    ("befff2a9-c813-4640-b593-1db08c48663c", "data_quality_validation", {
        "explanation": "Yahoo Finance data can contain errors, especially dividend_yield (sometimes 199% instead of 1.99%) and payout_ratio. The brain normalizes these: any percentage above 1.0 is divided by 100. An AI BUY only counts as validated with confidence >= 60 (settings.ai_validated_min_confidence); lower-confidence BUYs are never auto-bought.",
    }),
    ("fe38a2cb-ba37-41d9-8ae6-75d48b6fbd07", "short_squeeze_mechanics", {
        "explanation": "High short interest (> 10% of float) predicts LOWER average future returns: short sellers tend to be informed. A squeeze can happen when momentum builds, but it is not a reliable edge. Signa adds no squeeze bonus (removed 2026-09); the only short-interest score input is the enrichment short-trend adjustment (rising short interest = -1). Treat high short interest as a risk, not a catalyst.",
        "formula": None,
        "example": None,
    }),
    ("3a01d1fa-a974-465e-b03f-04b496bdbe0f", "asset_class_classification", {
        "explanation": "Signa classifies tickers as STOCK, ETF, or CRYPTO, automatically from the symbol. ETFs use ETF weights (reduced dividend weight). Crypto uses the same 2xATR stop and 1% risk sizing as stocks, with a 25% portfolio cap and a $50M dollar-volume floor.",
    }),
    ("ce1a95aa-d5d4-4029-a893-96cc31539a4b", "yield_curve_recession_predictor", {
        "explanation": "An inverted 10Y-2Y Treasury spread has preceded most US recessions since 1970, with long and variable lags, but it is not infallible: the 2022-2024 inversion was not followed by a recession by 2026. Stocks often rally during an inversion; the re-steepening afterwards has historically been the riskier phase. Signa counts an inverted curve as one hostile-macro stress condition. It is slow background context, not a 5-day timing signal.",
        "formula": "T10Y2Y < 0 counts as 1 stress condition in classify_macro_environment",
    }),
    ("2f9d1f97-52c7-42e8-a2e1-40666c46d0cb", "recovery_regime_opportunity", {
        "explanation": "RECOVERY (VIX 20-30, SPY back above its SMA50, VIX > 30 within the last 30 days) is when momentum crashes are most likely: after deep drawdowns, recent losers rally hardest and momentum leaders can fall sharply (Daniel-Moskowitz 2016). Signa applies no score boost in RECOVERY (the old x1.10 HIGH_RISK boost was removed in 2026-09). Be skeptical of chasing extended winners.",
        "formula": "RECOVERY: no score adjustment",
    }),
    ("b1c7f9bc-0770-4fc2-a921-166c32567b67", "weakening_thesis_management", {
        "explanation": "A weakening thesis on a winning position is NOT a sell signal: conditions are deteriorating but the reason for owning still holds. Exits are price-based: the 2xATR stop is always hard, the target is 2R, and once the trade is +1R a trailing stop at peak minus 2.5xATR takes over. Claude's thesis re-check can only close early when the thesis is invalid with confidence >= 70 on two consecutive checks.",
        "formula": "valid / weakening → hold (stop, 2R target, 2.5xATR trail after +1R). invalid with confidence >= 70 twice → exit early.",
    }),
    # KEEP / KEEP-AS-CONTEXT rows with a concrete correction in the audit.
    ("12a77f49-3ff3-4808-be5b-eeeec42ad6ab", "signa_is_short_term_only", {
        "explanation": "Signa generates signals for 5 to 20 trading day holding periods; p_win is measured at 5 trading days. It is NOT a long-term buy-and-hold tool. Signals expire and are re-evaluated at each scan; a BUY today may become HOLD or AVOID within days. Never treat a Signa signal as a permanent recommendation.",
    }),
    ("9412cef6-f29f-4c44-90fc-2376cec12aaf", "small_sample_fat_tail_warning", {
        "explanation": "Financial returns have fat-tailed distributions (Taleb, 2001): (1) rare extreme events happen far more often than a normal distribution predicts; (2) small-sample backtests (< 30 trades) cannot reliably estimate tail risk; (3) a strategy that 'worked' on 5-10 trades may not yet have met the tail event that destroys it. An 80% win rate on N=5 has a 95% confidence interval of [28%, 99%]. ACTIONABLE: treat win rates from fewer than 30 observations as unreliable and never size up on them. Signa requires 30 observations before a hypothesis reaches the prompt or graduates; 100+ before any sizing change.",
        "formula": "observations < 30 = hypothesis only. 30-100 = tentative, can inform but not override. 100+ = reliable enough to consider sizing changes.",
    }),
    ("fab42de2-3fc8-4ea2-9bc7-3d7b62e142ed", "momentum_factor_umd", {
        "explanation": "Momentum (Up-Minus-Down) is one of the best-documented factors: stocks with the strongest returns over the past 12 months excluding the most recent month (12-1 momentum) tend to keep outperforming for 3-12 months, while 1-month returns tend to reverse. It crashes in sharp bear-to-bull rebounds. Signa's momentum factor currently proxies this with 3-month and 6-month returns plus ADX (> 25 confirms a trend) for up to +6 HIGH_RISK bonus points.",
        "formula": "documented: return(t-12m, t-1m). Signa proxy: momentum_factor = f(3m_return, 6m_return, ADX)",
    }),
    ("1465b270-5c9e-4f5a-8f30-bf764d8cc5e9", "vix_term_structure_interpretation", {
        "explanation": "VIX term structure compares spot VIX to 3-month VIX (VIX3M). CONTANGO (ratio < 1.0) is normal: the market expects calm to persist. BACKWARDATION (ratio > 1.0) means acute fear now. Ratio > 1.15 = severe stress and counts as one hostile-macro condition in Signa. Ratio < 0.85 = unusual complacency.",
    }),
    ("36d36301-97ad-4868-9631-14668958458d", "canada_account_type_strategy", {
        "explanation": "FOR CANADIAN INVESTORS. TFSA: suits long holds (30+ days), dividends, ETFs. Risk: CRA may treat frequent short-term trading in a TFSA as business income (fully taxable); factors include frequency, holding period, knowledge and time spent. US dividends in a TFSA lose the 15% US withholding tax (an RRSP is treaty-exempt). RRSP: suits active trading and US dividend payers. TAXABLE: capital gains at the current inclusion rate; superficial loss rule: no capital loss if you rebuy within 30 days. SIGNA SUGGESTION: SAFE_INCOME → TFSA (Canadian payers) or RRSP (US payers), HIGH_RISK → RRSP, taxable as fallback. General education only, not tax advice.",
    }),
]

# REVISE rows the audit gives no concrete corrected value for: left unchanged.
REVISE_LEFT_AS_IS = [
    ("investment_rules", "7d993956-445c-4c46-b147-4ccf9f14bf69", "score_ceiling_overbought", "Audit: keep only as a UI-label note or remove — owner decision."),
    ("investment_rules", "b77712e8-cd5c-42e2-82b0-428ee55f596e", "sma200_extreme_deviation_blocker", "DB says 80%, code blocks at 50%; audit says pick one number and backtest it."),
    ("signal_knowledge", "588d0043-7f70-4319-8ec8-b468d1907951", "supply_deficit_asymmetry", "Audit: REMOVE from prompt only (done in code); row kept as possible long-term context."),
]

# ── Hypotheses to retire (id, short, reason). bc1aa8c3 is kept. ──────────
RETIRE_THINKING = [
    ("dc8bdbe3-b0bc-44f0-90b3-886d72278202", "5+ HOLD_THROUGH_DIP -> profitable exit", "Unmatchable keys; hold-through-dip behaviour removed in the reset."),
    ("585821ef-061b-44e2-90b4-c357390daadc", "SAFE_INCOME 72-79 VOLATILE MACD<0 bleeds", "Unknown key macd_histogram_lt; score band meaningless now that score does not gate entries."),
    ("2fc26f9f-8843-4a0e-8c15-94373978c445", "Re-buy within 4h of macro THESIS_INVALIDATED", "Unmatchable keys; 3-trading-day re-entry cooldown makes it impossible."),
    ("5f2949fe-4672-4821-aa5c-c8124f79879c", "Score>=85 MOMENTUM tier-1 amplified entries", "Unknown keys sizing_pct_min / is_wallet_trade; amplified sizing replaced by 1% risk sizing (folded into bc1aa8c3)."),
]
KEEP_THINKING_ID = "bc1aa8c3-a29a-4819-ba08-2229220d5ac2"


# ── helpers ──────────────────────────────────────────────────────────────

def fetch_all(db, table: str) -> list[dict]:
    rows: list[dict] = []
    start = 0
    while True:
        batch = db.table(table).select("*").range(start, start + PAGE - 1).execute().data or []
        rows.extend(batch)
        if len(batch) < PAGE:
            return rows
        start += PAGE


def write_and_verify_archive(snapshot: dict[str, list[dict]], out_dir: Path) -> None:
    """Write each table to JSON, read it back, and check ids match. Raises on mismatch."""
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for table, rows in snapshot.items():
        (out_dir / f"{table}.json").write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")
        counts[table] = len(rows)
    (out_dir / "manifest.json").write_text(json.dumps({
        "created_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "pre-curation export (scripts/curate_brain_knowledge.py)",
        "counts": counts,
    }, indent=1), encoding="utf-8")
    for table, rows in snapshot.items():
        back = json.loads((out_dir / f"{table}.json").read_text(encoding="utf-8"))
        if sorted(str(r.get("id")) for r in back) != sorted(str(r.get("id")) for r in rows):
            raise RuntimeError(f"archive verification failed for {table}")
    print(f"Archive written and verified: {out_dir}  {counts}")


def _append_note(existing: str | None, text: str) -> str:
    existing = (existing or "").strip()
    return f"{existing}\n{text}".strip() if existing else text


def build_plan(snapshot: dict[str, list[dict]]) -> dict:
    """Pure: compute every change from the current rows. No DB access."""
    by_id = {t: {str(r.get("id")): r for r in snapshot[t]} for t in TABLES}
    plan: dict = {"deactivate": [], "revise": [], "insert": [], "retire": [], "skipped": [], "left": []}

    def lookup(table, rid, name):
        row = by_id[table].get(rid)
        if row is None:
            plan["skipped"].append((table, rid, name, "not found"))
            return None
        if table != "signal_thinking" and row.get(NAME_COL[table]) != name:
            plan["skipped"].append((table, rid, name, f"name mismatch ({row.get(NAME_COL[table])})"))
            return None
        return row

    for table, items in (("investment_rules", REMOVE_RULES), ("signal_knowledge", REMOVE_KNOWLEDGE)):
        for rid, name, reason in items:
            row = lookup(table, rid, name)
            if row is None:
                continue
            if row.get("is_active") is False:
                plan["skipped"].append((table, rid, name, "already inactive"))
                continue
            plan["deactivate"].append((table, rid, name, reason, {
                "is_active": False,
                "notes": _append_note(row.get("notes"), f"{AUDIT_TAG} deactivated: {reason}"),
            }))

    for table, items in (("investment_rules", REVISE_RULES), ("signal_knowledge", REVISE_KNOWLEDGE)):
        for rid, name, fields in items:
            row = lookup(table, rid, name)
            if row is None:
                continue
            changed = {k: v for k, v in fields.items() if row.get(k) != v}
            if not changed:
                plan["skipped"].append((table, rid, name, "already revised"))
                continue
            plan["revise"].append((table, rid, name, sorted(changed), changed))

    plan["left"] = list(REVISE_LEFT_AS_IS)

    existing_by_concept = {r.get("key_concept"): r for r in snapshot["signal_knowledge"]}
    for row in build_prompt_core_rows():
        current = existing_by_concept.get(row["key_concept"])
        if current is None:
            plan["insert"].append(row)
        elif current.get("explanation") != row["explanation"]:
            # PROMPT_CORE text changed in code: refresh the stored row.
            plan["revise"].append(("signal_knowledge", current["id"], row["key_concept"],
                                   ["explanation"], {"explanation": row["explanation"]}))
        else:
            plan["skipped"].append(("signal_knowledge", "-", row["key_concept"], "PROMPT_CORE row up to date"))

    for rid, short, reason in RETIRE_THINKING:
        assert rid != KEEP_THINKING_ID
        row = lookup("signal_thinking", rid, short)
        if row is None:
            continue
        if row.get("status") == "retired":
            plan["skipped"].append(("signal_thinking", rid, short, "already retired"))
            continue
        plan["retire"].append((rid, short, reason, {
            "status": "retired",
            "notes": _append_note(row.get("notes"), f"{AUDIT_TAG} retired: {reason}"),
        }))
    return plan


def print_plan(plan: dict) -> None:
    print("\n== Deactivate (is_active=false) ==")
    for table, rid, name, reason, _ in plan["deactivate"]:
        print(f"  {table:17} {rid[:8]}  {name:42} {reason}")
    print("\n== Revise ==")
    for table, rid, name, fields, _ in plan["revise"]:
        print(f"  {table:17} {rid[:8]}  {name:42} fields: {', '.join(fields)}")
    print("\n== REVISE left unchanged (no concrete value in audit) ==")
    for table, rid, name, why in plan["left"]:
        print(f"  {table:17} {rid[:8]}  {name:42} {why}")
    print("\n== Insert PROMPT_CORE rows ==")
    for row in plan["insert"]:
        print(f"  {row['key_concept']:42} ({len(row['explanation'])} chars)")
    print("\n== Retire hypotheses (status='retired') ==")
    for rid, short, reason, _ in plan["retire"]:
        print(f"  {rid[:8]}  {short:42} {reason}")
    print(f"  kept: {KEEP_THINKING_ID[:8]}  HIGH_RISK score>=88 underperforms")
    if plan["skipped"]:
        print("\n== Skipped ==")
        for table, rid, name, why in plan["skipped"]:
            print(f"  {table:17} {str(rid)[:8]}  {name:42} {why}")


def print_summary(plan: dict, done: dict | None) -> None:
    rows = [("deactivate", len(plan["deactivate"])), ("revise", len(plan["revise"])),
            ("insert PROMPT_CORE", len(plan["insert"])), ("retire hypotheses", len(plan["retire"])),
            ("left unchanged (REVISE)", len(plan["left"])), ("skipped", len(plan["skipped"]))]
    print("\n| action                  | planned | applied |")
    print("|-------------------------|---------|---------|")
    for label, n in rows:
        applied = "-" if done is None else str(done.get(label, 0))
        print(f"| {label:23} | {n:7} | {applied:>7} |")


def apply_plan(db, plan: dict) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    done = {"deactivate": 0, "revise": 0, "insert PROMPT_CORE": 0, "retire hypotheses": 0}
    for table, rid, _name, _reason, payload in plan["deactivate"]:
        db.table(table).update({**payload, "updated_at": now}).eq("id", rid).execute()
        done["deactivate"] += 1
    for table, rid, _name, _fields, payload in plan["revise"]:
        db.table(table).update({**payload, "updated_at": now}).eq("id", rid).execute()
        done["revise"] += 1
    for row in plan["insert"]:
        db.table("signal_knowledge").insert(row).execute()
        done["insert PROMPT_CORE"] += 1
    for rid, _short, _reason, payload in plan["retire"]:
        db.table("signal_thinking").update({**payload, "updated_at": now}).eq("id", rid).execute()
        done["retire hypotheses"] += 1
    return done


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True, help="print the plan only (default)")
    mode.add_argument("--apply", action="store_true", help="archive, verify, then apply the changes")
    parser.add_argument("--out-dir", type=Path, default=None,
                        help="archive folder (default docs/archive/<date>-knowledge)")
    args = parser.parse_args(argv)

    db = get_client()
    snapshot = {t: fetch_all(db, t) for t in TABLES}
    print("Current rows: " + ", ".join(f"{t}={len(snapshot[t])}" for t in TABLES))
    plan = build_plan(snapshot)
    print_plan(plan)

    if not args.apply:
        print_summary(plan, None)
        print("\nDRY RUN — nothing written. Re-run with --apply to archive and apply.")
        return 0

    out_dir = args.out_dir or BACKEND_DIR / "docs" / "archive" / f"{datetime.now().date().isoformat()}-knowledge"
    write_and_verify_archive(snapshot, out_dir)
    done = apply_plan(db, plan)
    print_summary(plan, done)
    print("\nApplied. The API caches knowledge for 5 minutes (or restart the server).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
