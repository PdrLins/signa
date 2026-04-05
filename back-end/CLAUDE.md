# CLAUDE.md — Signa Backend

AI investment signal engine. Scans 188+ tickers daily across TSX, NYSE, NASDAQ, and crypto. Uses a two-pass scanning approach: pre-scores all candidates with technicals/fundamentals (free), then sends only the top 15 to AI for full analysis.

## Commands

```bash
cd back-end
source venv/bin/activate

# Run the API server
python -m uvicorn main:app --reload --port 8000

# Run backtest (scorer only, no AI)
python -m backtest.run_backtest --dry-run

# Seed brain tables (investment rules + signal knowledge)
python -m app.db.seed_brain

# Run tests
pytest tests/ -v

# Install dependencies
pip install -r requirements.txt
```

## Structure

```
back-end/
├── main.py                → Entry point, middleware stack, Telegram webhook
├── app/
│   ├── core/              → Config, security (JWT/OTP/bcrypt), dependencies
│   ├── middleware/         → Auth (JWT), brain_auth (2FA), audit, rate limiting
│   ├── api/v1/            → Routes: auth, signals, tickers, watchlist, portfolio,
│   │                        scans, stats, brain, health
│   ├── models/            → Pydantic request/response schemas
│   ├── services/          → Business logic: auth, scan orchestrator, signals,
│   │                        watchlist, positions, stats, knowledge_service
│   ├── signals/           → Kelly criterion, sell detector, market regime
│   ├── scanners/          → yfinance, FRED, pandas-ta, prefilter, universe
│   ├── ai/                → Provider router, Claude, Gemini, Grok clients,
│   │                        signal engine (scorer), prompts
│   ├── scheduler/         → APScheduler: 4 daily scans (6AM, 10AM, 3PM, 4:30PM ET)
│   ├── notifications/     → Telegram bot, bilingual message templates
│   └── db/                → Supabase client, queries, schema.sql, seed_brain.py
├── backtest/              → Historical validation system
│   ├── engine/            → Simulator, scorer, indicators, fundamentals
│   ├── evaluation/        → Evaluator, metrics
│   └── reports/           → Rich terminal output, CSV/JSON/MD reports
```

## AI Provider System

Three AI providers with configurable priority order (Settings page):
- **Claude** (Anthropic) — Primary synthesis, requires credits
- **Gemini** (Google) — Free tier fallback (1,500 req/day on 2.0-flash)
- **Grok** (xAI) — Real-time X/Twitter sentiment, requires credits

Provider router (`app/ai/provider.py`) tries each in configured order, falls through on failure.

## Two-Pass Scanning

1. **Pass 1** (FREE): All 50 candidates get technicals + fundamentals + macro score
2. **Pass 2** (AI): Top 15 by pre-score get sentiment + AI synthesis
3. Safe Income tickers skip sentiment (only 10% weight — not worth the cost)
4. Bottom 35 get stored with tech-only scores and generic reasoning

## Market Regimes

Checked once per scan via VIX:
- **TRENDING** (VIX < 20): Normal operation
- **VOLATILE** (VIX 20-30): High Risk scores reduced 15%, Kelly halved
- **CRISIS** (VIX > 30): High Risk paused, Safe Income dividends only

## Skills

- `/api-reference` — All endpoints with methods, params, responses
- `/architecture` — Module map, request flow, scan pipeline
- `/security` — Auth flow, JWT, OTP, rate limiting
- `/scan-pipeline` — Scan schedule, scoring, GEM conditions, blockers
- `/telegram` — Bot commands, alerts, OTP, webhook
- `/database` — All Supabase tables, indexes, triggers
- `/conventions` — Coding standards, async patterns

## Key Thresholds

- BUY threshold: 75 (live with AI), 65 (backtest without AI)
- Score ceiling: 90 (overbought trap)
- GEM: score >= 85, bullish sentiment >= 80% confidence, catalyst <= 30d, R/R >= 3.0, no red flags
- RSI blocker: > 75 auto-blocks BUY
- Pre-filter: min volume 200K, min price $1.00
- Kelly: fractional 25%, max position 15%
