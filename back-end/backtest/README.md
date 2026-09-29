# Signa Backtest

Replays the **live** scan → score → entry → exit pipeline on historical daily
bars. Every rule comes from `app/` at call time — nothing is re-implemented —
so the backtest follows changes to the live code automatically.

> **What it measures: the technical / trend layer only.** Historical AI
> inputs (X sentiment, Claude synthesis, catalysts, cited red flags) don't
> exist. Each signal is exactly what the live scan emits for a candidate that
> did not get AI analysis (`compute_score(..., grok={}, synthesis={})`,
> `ai_status="skipped"`). The live brain never auto-buys those, so **this is
> not the brain's track record.** It tells you whether the technical scoring,
> blockers, prefilter, levels, sizing and exits have an edge by themselves.

## Quick start

```bash
cd back-end

# Full run: today's universe (survivorship-biased, see below)
venv/bin/python -m backtest.run_backtest --start 2021-01-01 --end 2026-09-01

# Point-in-time universe, custom output dir
venv/bin/python -m backtest.run_backtest --start 2021-01-01 --end 2026-09-01 \
    --universe my_universe.csv --out docs/backtests/pit_2021_2026

# Smoke test (seconds)
venv/bin/python -m backtest.run_backtest --start 2025-09-01 --end 2026-09-01 \
    --tickers AAPL,MSFT,JPM,SHOP.TO,BTC-USD --smoke
```

The run writes `report.md` and `report.json` to `--out` (default
`docs/backtests/<name>`). Data is cached under `backtest/.cache/`, which is
gitignored.

## CLI flags

| Flag | Meaning |
|------|---------|
| `--start / --end` | Test window (required). ~420 days of warm-up bars are loaded before `--start`. |
| `--universe CSV` | Historical universe: a `symbol` column plus optional `start`,`end` (membership window, inclusive). |
| `--tickers A,B` / `--max-tickers N` | Quick-run overrides. |
| `--exclude-tsx` | Drop `.TO` listings. By default they are converted to USD with point-in-time `CAD=X`. |
| `--include-fundamentals` | Apply **today's** yfinance fundamentals to every past date. **Lookahead.** The report gets a LOOKAHEAD WARNING and the default name gets a `_LOOKAHEAD` suffix. |
| `--no-info` | Skip `.info` entirely: no sector (so no sector cap), bucket from the live hard-coded lists only. |
| `--entry-score N` | **Not a live rule.** Enter at `score >= N` instead of the bucket BUY threshold. Live blockers, blackout and the >90 ceiling still apply. |
| `--ai-veto` | Sends entries through the AI-veto placeholder (`signals.ai_veto`). It never vetoes, because there is no historical AI data. The hook exists so archived AI outputs can be plugged in later. |
| `--no-drawdown-breaker`, `--no-correlation-gate` | Turn off those live gates. |
| `--commission USD` | Commission per fill. The default is live `brain_commission_usd`. |
| `--initial-cash`, `--oos-start`, `--workers`, `--no-cache`, `--smoke`, `--name`, `--out` | Self-explanatory. The default out-of-sample start is 70% of the way through the window. |

## Design

```
backtest/
├── run_backtest.py   CLI + orchestration (run())
├── live.py           the ONLY bridge to app/ — thin wrappers, no rules
├── data.py           yfinance loader, disk cache, universe CSV, fundamentals filter
├── macro.py          point-in-time VIX / SPY-trend macro → live regime + environment
├── signals.py        point-in-time daily scan (live prefilter / indicators / score / action)
├── execution.py      daily-bar replay of the live evaluate_exit
├── portfolio.py      cash / positions / live sizing, limits, cooldown, breaker, correlation
├── study.py          per-symbol non-overlapping signal study (score bands etc.)
├── metrics.py        CAGR, drawdown, Sharpe, win rate, payoff, expectancy, benchmarks
├── report.py         markdown + JSON
├── replay_horizons.py  (separate tool: replays REAL stored signals from the DB)
└── engine/scorer.py, engine/fundamentals.py
                      DEPRECATED divergent copies, kept only because
                      tests/test_scorer.py and tests/test_fundamentals.py import them
```

**Live functions used** (via `backtest/live.py`):
`indicators.compute_indicators`, `market_scanner._screening_features`,
`prefilter.prefilter_candidates`, `signal_engine.compute_score / check_blockers /
check_entry_blackout / score_to_action`, `scan_service._tech_only_action /
_known_bucket / _bucket_from_fundamentals / _asset_class`,
`regime.get_market_regime`, `macro_scanner.classify_macro_environment`,
`virtual_portfolio.apply_slippage / compute_entry_levels / check_portfolio_limits /
evaluate_exit / compute_close_amounts / drawdown_breaker_tripped /
trading_days_between`, `wallet.calc_risk_position_size`,
`portfolio_risk.check_correlation_limit` (with a point-in-time closes loader).

### No lookahead

- On day *t* each symbol's window is its bars in `(t − 1y, t]`, the same length as the live `period="1y"`. The screening features, indicators, macro (VIX, 30-day VIX high, SPY vs SMA50/200) and regime all come from that window. A test changes every bar after *t* and asserts that the day-*t* signal does not change.
- A signal on day *t* fills at that symbol's **next bar's open**, with live slippage and commission. It is never filled at the signal-day close.
- Exits are replayed bar by bar through the live `evaluate_exit`. First the open: a gap through the stop or target, or a time expiry, fills at the open. Then the low is checked against the stop, **before** the high is checked against the target. If a bar touches both, the stop wins. Then the high drives the live trailing ratchet. Last comes the close: if the stop raised from today's high sits above the close, the position exits at that stop.
- Fundamentals: by default only sector, industry, quote type and name are used, and only for the bucket and the sector cap. Earnings-timing keys are always stripped.

### Portfolio

The simulator uses live sizing (1% risk, 10% cap, cash net of commission) and the live limits: max open positions, per-sector cap and crypto cap. It also applies the re-entry cooldown (in trading days), the drawdown breaker and the correlation gate. Orders fill in descending score order, the same as live. The cost basis is allocation plus commission, and exits settle through the live `compute_close_amounts`. A position occupies its symbol, so trades never overlap. Anything still open at the end is closed at the last close (`END_OF_WINDOW`).

### Signal study

The study runs per symbol and ignores portfolio capacity. Every prefiltered candidate signal (BUY, HOLD, AVOID or blocked) opens a one-share trade whenever its symbol is free. It uses the same live levels and exits. Results are grouped by score band, bucket, live action and regime, and each trade is compared with SPY over the same window. This shows whether the score and the blockers actually separate outcomes.

### Metrics and benchmarks

- **Portfolio metrics:** total return, CAGR, max drawdown, Sharpe (daily returns on the SPY calendar, ×√252, risk-free rate 0), volatility, exposure, turnover and fees.
- **Trade metrics:** win rate, payoff ratio, expectancy (% and $), average R, hold time and exit reasons.
- **Benchmarks:** SPY and XIU.TO buy-and-hold over the same window, from the first open to the last close, using adjusted prices and no costs. XIU.TO is reported in CAD and in USD. Excess return is reported against each.
- **Walk-forward:** metrics for the in-sample and out-of-sample periods of a single run. **No parameters are fitted.** The split exists so you can see whether results hold up across time.

## Known limitations (also printed in every report)

1. **Survivorship bias.** The default universe is today's `app/scanners/universe.py` list, and those names were picked with hindsight. Use `--universe` with a point-in-time CSV to remove the bias.
2. **Tech-only scores are structurally capped.** With no sentiment or catalyst, HIGH_RISK scores top out around 60 and SAFE_INCOME around 56. That is below the live BUY thresholds (65/62) and far below the brain's 75. With live rules the portfolio usually makes **zero trades**. Read the signal study, or use `--entry-score` and label the result as non-live.
3. **Macro coverage.** Only VIX and the SPY trend are available. FRED data, Fear & Greed and VIX term structure are absent, so the hostile-macro blocker can't fire.
4. **Earnings.** There is no point-in-time earnings calendar, so the earnings blackout and the PEAD / PRE_EARNINGS catalysts never fire.
5. **Execution simplifications.** The simulation uses daily bars only, with no intraday watchdog, no thesis tracker and no AI SELL exits. Shorts are off, as in live. Market-hours rules are reduced to "fill at the regular-session open".
