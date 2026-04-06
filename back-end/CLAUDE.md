# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

AI investment signal engine. Scans ~270 tickers daily across TSX, NYSE, NASDAQ, and crypto. Two-pass approach: pre-scores all candidates with technicals/fundamentals (free), then sends top 15 to AI for full analysis (budget-checked). Brain watchdog monitors open positions every 15 min.

## Commands

```bash
source venv/bin/activate
python -m uvicorn main:app --reload --port 8000
pytest tests/ -v                             # all tests
pytest tests/test_scorer.py::test_name -v    # single test
python -m backtest.run_backtest --dry-run    # backtest (no AI)
python -m app.db.seed_brain                  # seed brain tables
```

## Environment

Config in `app/core/config.py` (Pydantic Settings from `.env`). Required: `JWT_SECRET_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`, `BRAIN_TOKEN_SECRET`. Auth is always enabled. Validation at import time.

## Skills (use these — they have all the detail)

- `/architecture` — Module map, request flow, scan flow, all directories
- `/scan-pipeline` — Two-pass pipeline, scoring weights, GEM conditions, blockers, contrarian, regimes
- `/api-reference` — Every endpoint with methods, params, auth level, responses
- `/database` — All 18 tables, indexes, triggers, query patterns, caching
- `/security` — Auth flow, JWT, OTP, brain 2FA, rate limiting tiers, caching architecture
- `/telegram` — Bot commands, alert types, OTP, webhook setup, bilingual templates
- `/conventions` — Async patterns, auth patterns, caching, validation, file organization

## Key Thresholds

- BUY: 65 (HIGH_RISK), 62 (SAFE_INCOME) — `SCORE_BUY_*` env vars
- Contrarian BUY: score >= 55 + contrarian_score >= 60
- Score ceiling: 90 (forced HOLD)
- GEM: score >= 85, bullish sentiment >= 80%, catalyst <= 30d, R/R >= 3.0, no red flags
- RSI blocker: > 75 auto-blocks BUY
- Pre-filter: volume >= 200K, price >= $1, abs(day_change) >= 1%
  - Sorted by absolute day change (most active first), capped at 50 candidates
  - Top 15 by pre-score get AI synthesis, remaining 35 are tech-only
  - Crypto gets 5 reserved slots so equities don't crowd them out
  - **Watchlist tickers are NOT guaranteed** — if they don't move enough, they drop off
- Sentiment: Grok runs for HIGH_RISK only (35% weight); SAFE_INCOME skips it (10% weight, hardcoded neutral)
- Kelly: fractional 25%, max position 15%
- Virtual portfolio: brain auto-picks score >= 72 with target+stop filled, max 10 open, exits on stop/target/30d/SELL signal
