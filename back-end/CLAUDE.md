# CLAUDE.md — Signa Backend

AI investment signal engine. Scans 1,000+ stocks daily across TSX, NYSE, NASDAQ. Combines technical analysis, macro data, and X/Twitter sentiment to surface BUY/HOLD/SELL signals. Includes a backtest system to validate scoring accuracy against historical data.

## Commands

```bash
cd back-end

# Run the API server
venv/bin/python -m uvicorn main:app --reload --port 8000

# Run backtest (scorer only, no AI)
venv/bin/python -m backtest.run_backtest --dry-run

# Run backtest on specific tickers
venv/bin/python -m backtest.run_backtest --dry-run --tickers AAPL,SHOP.TO

# Install dependencies
venv/bin/pip install -r requirements.txt
```

## Structure (103 files)

```
back-end/
├── main.py              → Entry point, middleware stack, Telegram webhook
├── app/                 → Live signal engine
│   ├── core/            → Config, security (JWT/bcrypt/OTP), dependencies, utils
│   ├── middleware/       → Auth (JWT), audit logging, rate limiting
│   ├── api/v1/          → Routes: auth, signals, watchlist, portfolio, scans, health
│   ├── models/          → Pydantic request/response schemas
│   ├── services/        → Business logic: auth, scan orchestrator, signals, watchlist
│   ├── scanners/        → yfinance, FRED, pandas-ta indicators, prefilter, universe
│   ├── ai/              → Claude (synthesis), Grok (sentiment), prompts, signal engine
│   ├── scheduler/       → APScheduler: 4 daily scans (6AM, 10AM, 3PM, 4:30PM ET)
│   ├── notifications/   → Telegram bot, formatters, alert dispatcher
│   └── db/              → Supabase client, queries, schema.sql (9 tables)
├── backtest/            → Historical validation system
│   ├── run_backtest.py  → CLI entry point
│   ├── config.py        → Backtest settings (tickers, thresholds, weights)
│   ├── data/            → DataLoader (yfinance + FRED + cache)
│   ├── engine/          → Simulator, indicators, fundamentals, scorer
│   ├── evaluation/      → Evaluator (5/10/20d returns), metrics, auto-detection
│   └── reports/         → Rich terminal output, CSV/JSON/MD report generation
```

## Skills (slash commands for detailed reference)

- `/api-reference` — All 17+ endpoints with methods, params, responses
- `/architecture` — Module map, request flow, scan pipeline flow
- `/security` — Auth flow, JWT, OTP, rate limiting, input validation
- `/scan-pipeline` — Scan schedule, scoring weights, GEM conditions, blockers
- `/telegram` — Bot commands, automatic alerts, OTP, webhook setup
- `/database` — All 9 Supabase tables, indexes, triggers
- `/conventions` — Coding standards, async patterns, security rules

## Scoring (backtest-validated)

Key findings from 6-month backtest (Oct 2024 → Apr 2025, 30 tickers):
- RSI 50-65 is the sweet spot; oversold (< 30) is NOT better
- Momentum > 5% is a TRAP (46.2% win rate); sweet spot is +1% to +3%
- High MACD histogram predicts surges (3.3 vs 1.5 on normal signals)
- Score ceiling: scores above 72 have INVERTED win rates (overbought trap)
- RSI > 75 is an auto-blocker (60%+ fail rate)
- Safe Income: buy the dip (low RSI + low volume wins)
- High Risk: needs momentum confirmation (moderate RSI + volume)

Live BUY threshold: 75 (has Claude + Grok AI). Backtest: 65 (scorer only).
