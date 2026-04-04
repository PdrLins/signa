# Signa 💎

Signa is a personal AI investment assistant that scans 
1,000+ stocks daily across the TSX, NYSE, and NASDAQ, 
then uses Claude and Grok to surface high-conviction 
BUY and SELL signals — delivered straight to your phone 
via Telegram.

## How it works
- **yfinance + FRED** pull daily market and macro data
- **Technical indicators** (RSI, MACD, Bollinger Bands) 
  are computed automatically
- **Grok** analyzes real-time X/Twitter sentiment per ticker
- **Claude** synthesizes everything into a final signal 
  with reasoning
- **Gem Alerts** flag the highest-conviction opportunities
- **Telegram bot** delivers your daily digest at 6 AM and 
  real-time alerts throughout the day

## Two-bucket strategy
| 🛡 Safe Income | ⚡ High Risk |
|---|---|
| Dividends, ETFs, blue chips | Catalysts, momentum, small caps |
| Low volatility, steady gains | Asymmetric upside plays |

## Stack
- **Frontend** — Next.js 14 + TypeScript + Tailwind (Vercel)
- **Backend** — Python + FastAPI + APScheduler (Fly.io)
- **Database** — Supabase (PostgreSQL + Realtime)
- **AI** — Anthropic Claude + xAI Grok
- **Alerts** — Telegram Bot API
- **Data** — yfinance, FRED, Polygon.io

## Cost to run
~$6–8/month (AI APIs only — everything else is free)

## Status
🚧 In active development
