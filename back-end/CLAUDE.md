# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

AI investment signal engine. Scans 188+ tickers daily across TSX, NYSE, NASDAQ, and crypto. Two-pass approach: pre-scores all candidates with technicals/fundamentals (free), then sends top 15 to AI for full analysis.

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

Config in `app/core/config.py` (Pydantic Settings from `.env`). Required: `JWT_SECRET_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`, `BRAIN_TOKEN_SECRET` (when auth enabled). Dev mode: `DEBUG=true` + `AUTH_ENABLED=false` bypasses JWT. Validation at import time — won't start with missing secrets.

## Skills (use these for detailed reference)

- `/architecture` — Module map, request flow, scan pipeline
- `/scan-pipeline` — Scan schedule, scoring, GEM conditions, blockers
- `/api-reference` — All endpoints with methods, params, responses
- `/database` — All Supabase tables, indexes, triggers
- `/security` — Auth flow, JWT, OTP, rate limiting
- `/telegram` — Bot commands, alerts, OTP, webhook
- `/conventions` — Coding standards, async patterns

## Key Thresholds

- BUY: 65 (HIGH_RISK), 62 (SAFE_INCOME) — `SCORE_BUY_*` env vars
- Score ceiling: 90 (overbought trap → forced HOLD)
- Contrarian BUY: score ≥ 55 + contrarian_score ≥ 60
- GEM: score ≥ 85, bullish sentiment ≥ 80%, catalyst ≤ 30d, R/R ≥ 3.0, no red flags
- RSI blocker: > 75 auto-blocks BUY
- Pre-filter: volume ≥ 200K, price ≥ $1
- Kelly: fractional 25%, max position 15%
