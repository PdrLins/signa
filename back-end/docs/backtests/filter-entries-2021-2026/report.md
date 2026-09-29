# Signa backtest — filter-entries-2021-2026

Window 2021-01-01 → 2026-09-01 · 281 symbols loaded · entry rule: NON-LIVE --filter-only-entries: enter on a live technical_filter PASS alone (the live brain also requires a validated AI BUY) · generated 2026-09-29 01:17 UTC

## Read this first

- **TECHNICAL / TREND LAYER ONLY.** Historical AI inputs (X/Twitter sentiment, Claude synthesis, catalysts, cited red flags) do not exist, so every signal is the live pipeline's *tech-only* signal (`compute_score` with empty grok/synthesis, `ai_status="skipped"`). The live brain NEVER auto-buys tech-only signals (it requires a validated AI BUY that passes the technical filter — or, in legacy score mode, score >= 75). This is NOT the brain's track record.
- AI veto: not simulated (no historical AI data).
- **NON-LIVE ENTRY RULE — `--filter-only-entries`.** Portfolio entries fire on a technical-filter PASS alone. The live brain additionally requires a validated AI BUY; this run studies the filter as an entry rule, not live behaviour.
- Fundamentals excluded (no point-in-time source). Only sector / industry / quote type / name are used, for the bucket and the sector cap; the fundamental score components sit at their neutral defaults.
- **SURVIVORSHIP BIAS.** The universe is today's `app/scanners/universe.py` list — names chosen with hindsight, delisted/failed names absent. This inflates returns; pass `--universe <csv>` with a point-in-time list to fix.
- Macro is point-in-time VIX + SPY trend only; FRED series, Fear & Greed, VIX term structure are absent (the hostile-macro blocker therefore never fires).
- Earnings calendar not modelled point-in-time: the earnings blackout and PEAD / PRE_EARNINGS catalyst never trigger (optimistic: no earnings-gap avoidance).
- Execution: signals at day-t close, fills at the symbol's next bar OPEN with live slippage (10.0 bps stocks / 20.0 bps crypto) and $0.0 commission per fill; stop assumed hit before target when one bar touches both; gaps fill at the open.
- Prices are split/dividend-adjusted (yfinance auto_adjust) for strategy and benchmarks alike. TSX (.TO) names are converted to USD with point-in-time CAD=X at entry, mark and exit.

## Portfolio vs benchmarks

| Series | Total % | CAGR % | MaxDD % | Sharpe | Vol % |
|---|---|---|---|---|---|
| Strategy (USD) | 36.94 | 5.71 | -32.76 | 0.43 | 15.81 |
| SPY buy & hold | 118.59 | 14.83 | -24.5 | 0.91 | 16.72 |
| XIU.TO buy & hold | 137.44 | 16.52 | -16.36 | 1.29 | 12.49 |
| XIU.TO buy & hold (USD) | 118.09 | 14.78 | -24.07 | 1.05 |  |

Excess total return (strategy − benchmark): SPY -81.65 pp, XIU.TO -81.15 pp

Exposure: avg 69.67% of equity invested, 99.3% of sessions with a position · turnover 17.13x/yr · fees $0.0 · drawdown breaker: 10 trips, 10 resumes, entries paused on 144 days (pause 10 trading days, then peak reset)

## Portfolio trades

|  | Trades | Win % | Avg win % | Avg loss % | Payoff | Expectancy % | Avg R | Hold d |
|---|---|---|---|---|---|---|---|---|
| All | 1008 | 44.2 | 8.46 | -6.11 | 1.38 | 0.335 | 0.055 | 14.9 |

Exit reasons: STOP_HIT 457, TARGET_HIT 213, TRAILING_STOP 189, TIME_EXPIRED 143, END_OF_WINDOW 6

Entry decisions: max_open_positions_8 36016, already_held 7769, drawdown_breaker_pause 3163, sector_cap 1366, reentry_cooldown 1090, ENTERED 1008, correlation_limit 135, crypto_cap 3

### By entry score band

| Band | Trades | Win % | Avg win % | Avg loss % | Payoff | Expectancy % | Avg R | Hold d |
|---|---|---|---|---|---|---|---|---|
| <50 | 392 | 46.9 | 9.44 | -6.81 | 1.39 | 0.821 | 0.154 | 15.4 |
| 50-54 | 304 | 41.8 | 8.96 | -6.7 | 1.34 | -0.16 | 0.001 | 14.5 |
| 55-59 | 310 | 43.5 | 6.65 | -4.7 | 1.41 | 0.238 | -0.012 | 14.5 |
| 60-64 | 2 | 0.0 | 0.0 | -4.54 | 0.0 | -4.54 | -0.622 | 18.0 |

### By bucket

| Bucket | Trades | Win % | Avg win % | Avg loss % | Payoff | Expectancy % | Avg R | Hold d |
|---|---|---|---|---|---|---|---|---|
| HIGH_RISK | 560 | 45.9 | 10.25 | -7.73 | 1.33 | 0.52 | 0.101 | 14.7 |
| SAFE_INCOME | 448 | 42.2 | 6.02 | -4.21 | 1.43 | 0.104 | -0.002 | 15.1 |

## Walk-forward (no parameters are fitted; the split is reporting only)

### In-Sample (2021-01-01 → 2024-12-18)

| Series | Total % | CAGR % | MaxDD % | Sharpe | Vol % |
|---|---|---|---|---|---|
| Strategy | 12.16 | 2.94 | -32.76 | 0.25 | 15.66 |
| SPY | 64.85 | 13.48 | -24.5 | 0.85 | 16.51 |
| XIU.TO | 59.27 | 12.49 | -16.36 | 1.03 | 12.09 |

|  | Trades | Win % | Avg win % | Avg loss % | Payoff | Expectancy % | Avg R | Hold d |
|---|---|---|---|---|---|---|---|---|
| Trades | 703 | 43.0 | 8.29 | -5.93 | 1.4 | 0.177 | 0.032 | 14.9 |

### Out-Of-Sample (2024-12-19 → 2026-09-01)

| Series | Total % | CAGR % | MaxDD % | Sharpe | Vol % |
|---|---|---|---|---|---|
| Strategy | 22.45 | 12.65 | -13.33 | 0.82 | 16.18 |
| SPY | 31.46 | 17.46 | -18.76 | 1.03 | 17.24 |
| XIU.TO | 48.64 | 26.25 | -12.36 | 1.83 | 13.38 |

|  | Trades | Win % | Avg win % | Avg loss % | Payoff | Expectancy % | Avg R | Hold d |
|---|---|---|---|---|---|---|---|---|
| Trades | 305 | 47.2 | 8.82 | -6.56 | 1.34 | 0.699 | 0.11 | 14.8 |

## Signal study — per-symbol, non-overlapping (capacity-free)

Every prefiltered candidate signal can open a one-share study trade when its symbol is free; same live levels and exits; slippage both sides, no commission. Shows whether score / action / blockers separate outcomes.

|  | Trades | Win % | Expectancy % | Median % | Avg R | Excess vs SPY % | Beat SPY % |
|---|---|---|---|---|---|---|---|
| All | 8996 | 43.8 | 0.312 | -1.132 | 0.054 | -0.277 | 40.8 |

### By score band

| Band | Trades | Win % | Expectancy % | Median % | Avg R | Excess vs SPY % | Beat SPY % |
|---|---|---|---|---|---|---|---|
| <50 | 3600 | 46.1 | 0.817 | -0.851 | 0.115 | 0.018 | 42.6 |
| 50-54 | 2338 | 41.9 | -0.074 | -1.793 | 0.027 | -0.555 | 39.2 |
| 55-59 | 3041 | 42.6 | 0.019 | -1.078 | 0.003 | -0.407 | 39.7 |
| 60-64 | 17 | 41.2 | -1.101 | -3.664 | -0.126 | -1.492 | 47.1 |

### By bucket

| Bucket | Trades | Win % | Expectancy % | Median % | Avg R | Excess vs SPY % | Beat SPY % |
|---|---|---|---|---|---|---|---|
| HIGH_RISK | 4911 | 44.2 | 0.478 | -1.388 | 0.081 | -0.048 | 41.3 |
| SAFE_INCOME | 4085 | 43.3 | 0.113 | -0.916 | 0.021 | -0.553 | 40.1 |

### By live tech-only action

| Action | Trades | Win % | Expectancy % | Median % | Avg R | Excess vs SPY % | Beat SPY % |
|---|---|---|---|---|---|---|---|
| AVOID | 5090 | 44.3 | 0.474 | -1.126 | 0.082 | -0.246 | 41.0 |
| BLOCKED | 1055 | 43.5 | 0.093 | -2.352 | 0.033 | -0.226 | 41.6 |
| HOLD | 2851 | 43.0 | 0.103 | -0.967 | 0.012 | -0.352 | 40.0 |

### By regime

| Regime | Trades | Win % | Expectancy % | Median % | Avg R | Excess vs SPY % | Beat SPY % |
|---|---|---|---|---|---|---|---|
| CRISIS | 655 | 47.2 | 0.502 | -0.436 | 0.074 | -0.91 | 41.7 |
| RECOVERY | 129 | 47.3 | 0.847 | -0.539 | 0.094 | -0.387 | 42.6 |
| TRENDING | 5774 | 42.4 | 0.082 | -1.515 | 0.02 | -0.296 | 39.9 |
| VOLATILE | 2438 | 46.1 | 0.777 | -0.771 | 0.127 | -0.057 | 42.5 |

### By technical filter

Live `technical_filter` (trend above SMA200 with SMA50 > SMA200, RSI <= 75, <= 15% above SMA50, 20d dollar-volume floor, no blocker). Does PASS beat FAIL?

| Filter | Trades | Win % | Expectancy % | Median % | Avg R | Excess vs SPY % | Beat SPY % |
|---|---|---|---|---|---|---|---|
| PASS | 6143 | 43.7 | 0.355 | -1.026 | 0.061 | -0.316 | 40.4 |
| FAIL | 2853 | 44.0 | 0.22 | -1.445 | 0.039 | -0.194 | 41.5 |

Failing trades by reason (a trade failing several conditions appears in each row, so rows overlap):

| Failing reason | Trades | Win % | Expectancy % | Median % | Avg R | Excess vs SPY % | Beat SPY % |
|---|---|---|---|---|---|---|---|
| overextended_vs_sma50 | 1415 | 42.7 | 0.178 | -2.376 | 0.027 | -0.217 | 40.2 |
| active_blocker | 1055 | 43.5 | 0.093 | -2.352 | 0.033 | -0.226 | 41.6 |
| sma50_below_sma200 | 1015 | 44.5 | 0.151 | -1.349 | 0.052 | -0.261 | 41.6 |
| below_sma200 | 395 | 48.4 | 0.429 | -0.525 | 0.088 | -0.197 | 42.0 |
| low_liquidity | 339 | 45.1 | 0.131 | -0.864 | 0.045 | -0.471 | 43.7 |
| rsi_overbought | 104 | 53.8 | 2.654 | 0.442 | 0.214 | 2.392 | 52.9 |
| insufficient_history | 5 | 80.0 | 16.374 | 15.172 | 0.766 | 14.386 | 80.0 |

## Score distribution (all candidate-days)

69999 candidate-days. HIGH_RISK: n=40207, max=64, p95=55.0, >=BUY thr=0, >=75=0 · SAFE_INCOME: n=29792, max=57, p95=56.0, >=BUY thr=0, >=75=0

Live tech-only actions: AVOID 39558, HOLD 22072, BLOCKED 8369
