# Signa Backtest System

Tests the signal scoring engine against historical data to validate accuracy before going live.

## Quick Start

```bash
cd back-end

# Full backtest (30 tickers, Oct 2024 → Apr 2025)
venv/bin/python -m backtest.run_backtest --dry-run

# Quick test (2 tickers)
venv/bin/python -m backtest.run_backtest --dry-run --tickers AAPL,SHOP.TO

# Custom date range
venv/bin/python -m backtest.run_backtest --dry-run --start 2024-06-01 --end 2025-01-01

# Force fresh data (skip cache)
venv/bin/python -m backtest.run_backtest --dry-run --no-cache

# Generate Claude Code analysis file
venv/bin/python -m backtest.run_backtest --analyze
```

## CLI Options

| Flag | Description |
|------|-------------|
| `--dry-run` | Use scorer only, no Claude API calls |
| `--analyze` | Same as dry-run + generates Claude analysis markdown |
| `--tickers AAPL,SHOP.TO` | Override ticker list (comma-separated) |
| `--start 2024-06-01` | Override start date |
| `--end 2025-01-01` | Override end date |
| `--no-cache` | Force fresh data pull from yfinance/FRED |

## What It Does

1. **Loads data** — OHLCV from yfinance (with 300-day warmup for SMA200), fundamentals, macro from FRED
2. **Simulates daily** — for each trading day, scores every ticker using technicals + fundamentals + macro
3. **Evaluates** — measures actual 5/10/20-day returns after each signal
4. **Reports** — prints rich terminal summary + saves CSV, JSON, analysis markdown, improvements file

## Output Files

After each run, 4 files are saved to `backtest/reports/output/`:

| File | Contents |
|------|----------|
| `backtest_results_{timestamp}.csv` | One row per signal with all fields + actual returns |
| `backtest_summary_{timestamp}.json` | Full metrics dict (win rates, counts, distribution) |
| `claude_code_analysis_{timestamp}.md` | Formatted for AI analysis — failed BUYs, missed opportunities, GEM analysis, questions |
| `IMPROVEMENTS_{timestamp}.md` | Auto-detected issues with recommended config changes |

## Key Differences from Live System

| Feature | Live | Backtest |
|---------|------|----------|
| Grok (X/Twitter sentiment) | Yes (35% weight) | No — replaced by momentum proxy |
| Claude signal synthesis | Yes | No — pure math scorer |
| BUY threshold | 75 | 65 (compensates for missing AI signals) |
| GEM conditions | 5 conditions | Same 5, but harder to trigger without sentiment |
| Data source | Real-time yfinance | Historical yfinance with warmup |
| Macro data | FRED real-time | FRED historical via API |

## Configuration

Edit `backtest/config.py` to change:

- **Tickers**: US and TSX lists
- **Date range**: start_date, end_date
- **Thresholds**: buy (65), hold (50), gem_min_score (85)
- **Weights**: safe_income and high_risk scoring weights
- **Eval windows**: [5, 10, 20] days forward
- **Cache**: use_cache, cache_dir

## Understanding the Results

### Win Rate
Percentage of BUY signals where the price was higher after N days.
- **> 55%** = scorer is adding value
- **50%** = coin flip, scorer is not useful
- **< 50%** = scorer is worse than random

### Score Distribution
Where signals cluster tells you about scorer calibration:
- Clustered at 50-60 = too conservative
- Spread across 40-90 = good dynamic range
- Everything at 80+ = not selective enough

### Auto-Detected Issues
The system flags patterns like:
- Win rate below 50% (scorer not better than random)
- High RSI on failed BUYs (overbought stocks failing)
- Safe Income beating High Risk by 20%+ (risk bucket needs tuning)
- GEM win rate worse than BUY win rate (GEM filter not helping)
- Tickers with 0 BUYs (possible data issues)

## Caching

Data is cached in `backtest/data/cache/`:
- `{ticker}.parquet` — OHLCV price history
- `fundamentals/{ticker}.json` — yfinance .info
- `macro.parquet` — FRED macro data

Delete cache to force refetch: `rm -rf backtest/data/cache/*`

## Project Structure

```
backtest/
├── run_backtest.py          # Entry point
├── config.py                # All settings
├── data/
│   ├── loader.py            # DataLoader: OHLCV, fundamentals, macro
│   └── cache/               # Cached data files
├── engine/
│   ├── simulator.py         # BacktestSimulator: runs signals per day
│   ├── indicators.py        # Technical indicators (pandas-ta)
│   ├── fundamentals.py      # Fundamental extraction + bucket classification
│   ├── scorer.py            # Scoring logic (safe_income + high_risk weights)
│   ├── claude_signal.py     # (future) Claude API integration
│   └── gem_detector.py      # (future) standalone GEM detection
├── evaluation/
│   ├── evaluator.py         # Measures actual returns vs signals
│   └── metrics.py           # Computes win rates, distributions, issues
└── reports/
    ├── summary.py           # Rich terminal output
    ├── generator.py         # Saves CSV, JSON, analysis, improvements
    └── output/              # Generated report files
```
