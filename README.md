# Signa

Portfolio tracker for self-directed investors (Canada and US): holdings across
accounts and people, live prices, dividends and income, allocation, what's
coming up, price alerts and Telegram notifications. Free and Premium plans.
Clients: the iOS app (`signa-ios`) and the web app (`front-end/`).

The AI signal engine ("the brain": scans, signals, AI checks, paper trading)
is a separate product, **Signa Advisor**, in the `signa-advisor` repository.

## Stack

| Layer | Technology |
|-------|-----------|
| Back-end | Python 3.12, FastAPI, APScheduler (in-process) |
| Database | Supabase (PostgreSQL) |
| Market data | yfinance |
| Notifications | Telegram Bot API, email (Resend / SMTP) |
| Web | Next.js 14, TypeScript, Tailwind CSS, React Query |

## Quick Start

```bash
# Back-end
cd back-end
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in Supabase, JWT secret, Telegram bot
python -m uvicorn main:app --reload --port 8000

# Web
cd front-end
npm install
npm run dev
```

## Environment Variables

See `back-end/.env.example`. Required: `JWT_SECRET_KEY`, `SUPABASE_URL`,
`SUPABASE_KEY` (service_role). `TELEGRAM_BOT_TOKEN` for sign-in codes and
notifications.

## Versions

Every commit bumps the back-end (`back-end/VERSION`, `GET /api/v1/version`)
and web (`front-end/package.json`) versions via `.githooks/pre-commit`
(`git config core.hooksPath .githooks` in a new clone).
