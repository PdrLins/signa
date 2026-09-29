# Signa backtest — entry55-2021-2026

Window 2021-01-01 → 2026-09-01 · 281 symbols loaded · entry rule: score >= 55 (NON-LIVE threshold), live blockers/ceiling · generated 2026-09-29 01:00 UTC

## Read this first

- **TECHNICAL / TREND LAYER ONLY.** Historical AI inputs (X/Twitter sentiment, Claude synthesis, catalysts, cited red flags) do not exist, so every signal is the live pipeline's *tech-only* signal (`compute_score` with empty grok/synthesis, `ai_status="skipped"`). The live brain NEVER auto-buys tech-only signals (it requires a validated AI BUY and score >= 75). This is NOT the brain's track record.
- AI veto: not simulated (no historical AI data).
- Fundamentals excluded (no point-in-time source). Only sector / industry / quote type / name are used, for the bucket and the sector cap; the fundamental score components sit at their neutral defaults.
- **SURVIVORSHIP BIAS.** The universe is today's `app/scanners/universe.py` list — names chosen with hindsight, delisted/failed names absent. This inflates returns; pass `--universe <csv>` with a point-in-time list to fix.
- Macro is point-in-time VIX + SPY trend only; FRED series, Fear & Greed, VIX term structure are absent (the hostile-macro blocker therefore never fires).
- Earnings calendar not modelled point-in-time: the earnings blackout and PEAD / PRE_EARNINGS catalyst never trigger (optimistic: no earnings-gap avoidance).
- Execution: signals at day-t close, fills at the symbol's next bar OPEN with live slippage (10.0 bps stocks / 20.0 bps crypto) and $0.0 commission per fill; stop assumed hit before target when one bar touches both; gaps fill at the open.
- Prices are split/dividend-adjusted (yfinance auto_adjust) for strategy and benchmarks alike. TSX (.TO) names are converted to USD with point-in-time CAD=X at entry, mark and exit.

## Portfolio vs benchmarks

| Series | Total % | CAGR % | MaxDD % | Sharpe | Vol % |
|---|---|---|---|---|---|
| Strategy (USD) | -0.72 | -0.13 | -10.95 | -0.0 | 4.8 |
| SPY buy & hold | 118.59 | 14.83 | -24.5 | 0.91 | 16.72 |
| XIU.TO buy & hold | 137.44 | 16.52 | -16.36 | 1.29 | 12.49 |
| XIU.TO buy & hold (USD) | 118.09 | 14.78 | -24.07 | 1.05 |  |

Excess total return (strategy − benchmark): SPY -119.31 pp, XIU.TO -118.81 pp

Exposure: avg 10.01% of equity invested, 16.32% of sessions with a position · turnover 2.29x/yr · fees $0.0 · drawdown-breaker blocked entries on 1734 days

## Portfolio trades

|  | Trades | Win % | Avg win % | Avg loss % | Payoff | Expectancy % | Avg R | Hold d |
|---|---|---|---|---|---|---|---|---|
| All | 127 | 46.5 | 5.96 | -5.29 | 1.13 | -0.065 | 0.008 | 16.2 |

Exit reasons: STOP_HIT 58, TRAILING_STOP 27, TIME_EXPIRED 24, TARGET_HIT 18

Entry decisions: drawdown_breaker 18451, max_open_positions_8 2619, already_held 642, ENTERED 127, reentry_cooldown 78, sector_cap 74, correlation_limit 49

### By entry score band

| Band | Trades | Win % | Avg win % | Avg loss % | Payoff | Expectancy % | Avg R | Hold d |
|---|---|---|---|---|---|---|---|---|
| 55-59 | 126 | 46.8 | 5.96 | -5.28 | 1.13 | -0.017 | 0.016 | 16.2 |
| 60-64 | 1 | 0.0 | 0.0 | -6.07 | 0.0 | -6.068 | -1.016 | 17.0 |

### By bucket

| Bucket | Trades | Win % | Avg win % | Avg loss % | Payoff | Expectancy % | Avg R | Hold d |
|---|---|---|---|---|---|---|---|---|
| HIGH_RISK | 48 | 52.1 | 3.64 | -7.49 | 0.49 | -1.695 | -0.124 | 16.4 |
| SAFE_INCOME | 79 | 43.0 | 7.67 | -4.17 | 1.84 | 0.926 | 0.088 | 16.1 |

## Walk-forward (no parameters are fitted; the split is reporting only)

### In-Sample (2021-01-01 → 2024-12-18)

| Series | Total % | CAGR % | MaxDD % | Sharpe | Vol % |
|---|---|---|---|---|---|
| Strategy | -0.72 | -0.18 | -10.95 | -0.0 | 5.73 |
| SPY | 64.85 | 13.48 | -24.5 | 0.85 | 16.51 |
| XIU.TO | 59.27 | 12.49 | -16.36 | 1.03 | 12.09 |

|  | Trades | Win % | Avg win % | Avg loss % | Payoff | Expectancy % | Avg R | Hold d |
|---|---|---|---|---|---|---|---|---|
| Trades | 127 | 46.5 | 5.96 | -5.29 | 1.13 | -0.065 | 0.008 | 16.2 |

### Out-Of-Sample (2024-12-19 → 2026-09-01)

| Series | Total % | CAGR % | MaxDD % | Sharpe | Vol % |
|---|---|---|---|---|---|
| Strategy | 0.0 | 0.0 | 0.0 |  | 0.0 |
| SPY | 31.46 | 17.46 | -18.76 | 1.03 | 17.24 |
| XIU.TO | 48.64 | 26.25 | -12.36 | 1.83 | 13.38 |

|  | Trades | Win % | Avg win % | Avg loss % | Payoff | Expectancy % | Avg R | Hold d |
|---|---|---|---|---|---|---|---|---|
| Trades | 0 |  |  |  |  |  |  |  |

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

## Score distribution (all candidate-days)

69999 candidate-days. HIGH_RISK: n=40207, max=64, p95=55.0, >=BUY thr=0, >=75=0 · SAFE_INCOME: n=29792, max=57, p95=56.0, >=BUY thr=0, >=75=0

Live tech-only actions: AVOID 39558, HOLD 22072, BLOCKED 8369
