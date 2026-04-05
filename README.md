# Signa

AI-powered investment signal engine for Canadian self-directed investors.

Scans 188+ stocks and crypto across TSX, NYSE, NASDAQ, and major crypto markets — four times every trading day. Combines technical analysis, fundamental data, macro indicators, and AI sentiment to produce BUY/HOLD/SELL/AVOID signals with confidence scores.

## Features

- **4 daily scans** — Pre-market (6 AM), Market open (10 AM), Pre-close (3 PM), After-close (4:30 PM ET)
- **Two-pass scanning** — Pre-scores all candidates with technicals first, then sends only the top 15 to AI (saves ~77% on AI costs)
- **Two-bucket strategy** — Safe Income (dividends, TFSA) and High Risk (momentum, RRSP)
- **GEM alerts** — Highest-conviction signals sent instantly via Telegram
- **Market regime detection** — Adapts based on VIX: TRENDING / VOLATILE / CRISIS
- **Kelly position sizing** — Recommends position sizes based on score and risk/reward
- **6 visual themes** — Light + dark modes
- **Bilingual** — English + Brazilian Portuguese
- **Telegram bot** — Alerts, OTP login, scan digests, position monitoring
- **Brain Editor** — Protected rule editor with separate Telegram 2FA
- **On-demand scans** — Scan Now button with real-time progress bar

## Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14, TypeScript, Tailwind CSS, Zustand, React Query |
| Backend | Python, FastAPI, APScheduler |
| Database | Supabase (PostgreSQL) |
| AI | Claude (Anthropic), Gemini (Google), Grok (xAI) — configurable priority |
| Data | yfinance, FRED API, pandas-ta |
| Alerts | Telegram Bot API |

## Quick Start

```bash
# Backend
cd back-end
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Fill in API keys
python -m uvicorn main:app --reload --port 8000

# Frontend
cd front-end
npm install
npm run dev
```

## Environment Variables

See `back-end/.env.example`. Required:
- `JWT_SECRET_KEY` — Auth signing
- `SUPABASE_URL` + `SUPABASE_KEY` — Database
- `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` — Alerts + OTP
- At least one AI provider: `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, or `XAI_API_KEY`

## Status

In active development.
