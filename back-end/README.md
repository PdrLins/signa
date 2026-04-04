# Signa Backend

AI investment signal engine that scans 1,000+ stocks daily across TSX, NYSE, and NASDAQ. Combines technical analysis, macro data, and real-time X/Twitter sentiment to surface high-conviction BUY/HOLD/SELL signals — delivered via Telegram and a Next.js dashboard.

## Tech Stack

- **Runtime:** Python 3.12+ / FastAPI / Uvicorn
- **Database:** Supabase (PostgreSQL + Realtime)
- **AI:** Anthropic Claude (signal synthesis) + xAI Grok (X/Twitter sentiment)
- **Data:** yfinance (market data) + FRED API (macro economics)
- **Alerts:** Telegram Bot API (two-way)
- **Scheduler:** APScheduler (4 daily scans)
- **Backtest:** Historical validation system with data-tuned scoring
- **Hosting:** Fly.io

## Quick Start

```bash
cd back-end
pip install -r requirements.txt
cp .env.example .env   # Fill in your API keys
uvicorn main:app --reload --port 8000
```

Visit `http://localhost:8000/docs` for interactive API docs.

## Project Structure (103 files)

```
back-end/
├── main.py                          # App entry point, middleware, webhook
├── requirements.txt
├── .env.example                     # Template (never put real keys here)
├── .env                             # Your actual keys (gitignored)
│
├── app/                             # Live signal engine
│   ├── api/v1/                      # Route handlers
│   │   ├── auth.py                  # Login (2-step OTP), logout, refresh
│   │   ├── signals.py               # Signal queries + GEM alerts
│   ���   ├── watchlist.py             # Watchlist CRUD
│   │   ├── portfolio.py             # Portfolio CRUD (TFSA/RRSP/Taxable)
│   │   ├── scans.py                 # Scan history + manual trigger
│   │   └── health.py                # Health check (no DB call)
│   ├── core/                        # Config, security, dependencies
│   ├── middleware/                   # Auth (JWT), audit, rate limiting
│   ├── models/                      # Pydantic schemas
│   ├── services/                    # Business logic layer
│   ├── scanners/                    # yfinance, FRED, pandas-ta, prefilter
│   ├── ai/                          # Claude + Grok clients, signal engine
│   ���── scheduler/                   # 4 daily scan jobs
│   ├── notifications/               # Telegram bot + formatters
│   └── db/                          # Supabase client, queries, schema.sql
│
└── backtest/                        # Historical validation
    ├── run_backtest.py              # CLI entry point
    ├── config.py                    # Backtest settings
    ├── data/                        # DataLoader + cache
    ├── engine/                      # Simulator, indicators, scorer
    ├── evaluation/                  # Evaluator + metrics
    └── reports/                     # Rich output + file generation
```

---

## API Reference

All routes versioned under `/api/v1/`. Protected routes require `Authorization: Bearer <token>`.

### Authentication (Public)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/auth/login` | Send credentials → receive OTP via Telegram |
| `POST` | `/api/v1/auth/verify-otp` | Verify OTP → receive JWT (1hr) |
| `POST` | `/api/v1/auth/logout` | Invalidate JWT (Protected) |
| `POST` | `/api/v1/auth/refresh` | Get new JWT (Protected) |

### Signals (Protected)

| Method | Endpoint | Query Params | Description |
|--------|----------|-------------|-------------|
| `GET` | `/api/v1/signals` | `bucket`, `min_score`, `limit` | Latest signals |
| `GET` | `/api/v1/signals/gems` | `limit` | GEM alerts only |
| `GET` | `/api/v1/signals/{ticker}` | `limit` | History for one ticker |

### Scans (Protected)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/scans` | Scan history |
| `POST` | `/api/v1/scans/trigger?scan_type=MORNING` | Manual scan (background) |

### Watchlist (Protected)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/watchlist` | Get watchlist |
| `POST` | `/api/v1/watchlist/{ticker}` | Add ticker |
| `DELETE` | `/api/v1/watchlist/{ticker}` | Remove ticker |

### Portfolio (Protected)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/portfolio` | Get positions |
| `POST` | `/api/v1/portfolio` | Add position (symbol, bucket, account_type, shares, avg_cost, currency) |
| `PUT` | `/api/v1/portfolio/{id}` | Update position |
| `DELETE` | `/api/v1/portfolio/{id}` | Delete position |

### Health + Webhook

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/health` | Public health check |
| `POST` | `/api/v1/telegram/webhook` | Telegram bot webhook (validates secret) |

---

## Scoring System (Backtest-Validated)

Tuned from 6-month backtest (Oct 2024 → Apr 2025, 30 tickers, 3,654 signals):

### Key Findings
- RSI 50-65 is the sweet spot; oversold (< 30) is NOT better
- Momentum > 5% is a TRAP (46.2% win rate); sweet spot +1% to +3%
- High MACD histogram predicts surges (avg 3.3 on surgers vs 1.5 normal)
- Scores above 72 have INVERTED win rates (overbought trap → score ceiling)
- RSI > 75 auto-blocks signal (60%+ fail rate)
- Safe Income: buy the dip (low RSI + low volume = stable accumulation)
- High Risk: needs volume + MACD confirmation

### Thresholds

| | Live System | Backtest |
|---|---|---|
| BUY | >= 75 (has Claude + Grok AI) | >= 65 (scorer only) |
| Score Ceiling | 90 | 72 |
| GEM | >= 85 + 5 conditions | >= 78 + 4 conditions |
| Blockers | fraud, macro, volume, RSI > 75 | Same minus fraud |

### Signal Status Tracking
- `CONFIRMED` — signal still valid
- `WEAKENING` — score dropped 15+ points
- `CANCELLED` — was BUY, reversed to SELL/AVOID
- `UPGRADED` — score increased 10+ points

---

## Telegram Bot

### Commands (sent to bot)
| Command | Description |
|---------|-------------|
| `/signals` | Latest 10 signals |
| `/gem` | GEM alerts with details |
| `/watch` / `/watch AAPL` | View or add to watchlist |
| `/remove AAPL` | Remove from watchlist |
| `/score SHOP.TO` | Score + reasoning for a ticker |
| `/status` | Last scan info |
| `/help` | All commands |

### Automatic Alerts
- GEM alerts with price, target, stop loss, reasoning
- Morning + after-close digests with top 3 picks
- Signal status change notifications

---

## Backtest System

```bash
# Full run (30 tickers, 6 months)
venv/bin/python -m backtest.run_backtest --dry-run

# Quick test
venv/bin/python -m backtest.run_backtest --dry-run --tickers AAPL,SHOP.TO

# Custom dates
venv/bin/python -m backtest.run_backtest --dry-run --start 2024-06-01 --end 2025-01-01

# Generate AI analysis file
venv/bin/python -m backtest.run_backtest --analyze

# Force fresh data
venv/bin/python -m backtest.run_backtest --dry-run --no-cache
```

Outputs 4 files to `backtest/reports/output/`:
- CSV with all signals + actual 5/10/20d returns
- JSON with full metrics
- Claude Code analysis markdown (paste into AI for review)
- IMPROVEMENTS.md with auto-detected issues + config recommendations

---

## Database (9 Supabase Tables)

Run `app/db/schema.sql` in Supabase SQL Editor.

| Table | Purpose |
|-------|---------|
| `users` | App users (username, password_hash, telegram_chat_id) |
| `otp_codes` | OTP verification (session_token, code_hash, attempts) |
| `token_blacklist` | Revoked JWTs |
| `audit_logs` | Security event trail |
| `tickers` | Stock universe (symbol, exchange, bucket) |
| `scans` | Scan run history |
| `signals` | Generated signals with full analysis data (JSONB) |
| `portfolio` | Positions (shares, avg_cost, account_type, currency) |
| `watchlist` | Tracked tickers |
| `alerts` | Telegram notification log |

---

## Environment Variables

| Variable | Source |
|----------|--------|
| `ANTHROPIC_API_KEY` | console.anthropic.com |
| `XAI_API_KEY` | console.x.ai |
| `TELEGRAM_BOT_TOKEN` | @BotFather |
| `TELEGRAM_CHAT_ID` | Telegram getUpdates |
| `SUPABASE_URL` | Supabase project settings |
| `SUPABASE_KEY` | Supabase (use service_role key) |
| `FRED_API_KEY` | fred.stlouisfed.org |
| `JWT_SECRET_KEY` | `openssl rand -hex 32` |
