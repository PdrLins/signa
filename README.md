# Signa

Signa is a portfolio tracker for self-directed investors. You add your holdings across accounts and people
(for example you, your spouse, a TFSA and a joint account), and Signa shows what they are worth today, what
they pay in dividends, what is coming up, and how the portfolio is built. It works in any country and
currency; **Brazil, Canada and the United States** are the first markets.

- **Clients:** the iOS app (separate repository, `signa-ios`, launching first) and the web app in `front-end/`.
- **This repository:** the back-end API (`back-end/`) and the web app (`front-end/`).
- **Not here:** the AI signal engine ("the brain": scans, signals, AI checks, paper trading) is a separate,
  paused product called **Signa Advisor** (`signa-advisor`, a fork of this repository).

Status: in development, not deployed yet. Hosting is still to be decided.

## What it does

| | Free | Premium |
|---|---|---|
| Stocks followed (holdings + watchlist) | 15, +5 per invited friend (up to +25) | Unlimited |
| Holdings, accounts, people, transactions, CSV import | ✓ | ✓ |
| Prices | Every 15 min, during each exchange's hours | Every minute, plus US pre/after-hours |
| Crypto prices | 24/7 | 24/7 |
| Portfolio value, history, performance, allocation | ✓ (history up to 1 year) | ✓ full history, target allocation and deposit plan |
| Dividends: calendar, expected income, safety, estimated vs declared | ✓ | ✓ after-tax view (CA/US), income quality |
| Coming up: dividends, earnings, economy events | ✓ | ✓ |
| Stock and ETF pages, Signa checks, fund details | ✓ | ✓ similar funds |
| Price alerts | 3 active | Unlimited |
| Push notifications (iOS) | Price alerts, dividends, earnings | Every type (big moves, daily summary …) |
| Telegram notifications | — | ✓ |
| Home-screen widgets (iOS) | 1 | All |
| Goals (portfolio value, monthly dividend income) | 1 | Unlimited |
| Monthly recap | ✓ | ✓ |
| Report a problem / report wrong data | ✓ | ✓ |

Country-specific tools (Canadian adjusted cost base, Brazilian income tax, US cost basis) are planned for
Premium.

## Works in any country

- Each stock is priced in its own currency (PETR4.SA in reais, VOD.L in pounds, SAP.DE in euros) and
  totals are shown in the user's home currency, converting between any two currencies.
- Search covers every exchange (B3, TSX, NYSE/Nasdaq, London, XETRA, Euronext, Tokyo …), with the user's
  own market first; "PETR4" finds the B3 listing.
- Prices refresh while each exchange is open, using its own trading hours and holidays.
- Sign-up takes the phone's country, currency and language. The apps are in English and Portuguese.

## Stack

| Layer | Technology |
|-------|-----------|
| Back-end | Python 3.12, FastAPI, APScheduler (in-process, one instance) |
| Database | Supabase (PostgreSQL); schema in `back-end/app/db/schema.sql` |
| Market data | yfinance; exchange calendars from `exchange_calendars` |
| Notifications | Apple Push Notifications, Telegram Bot API, email (Resend / SMTP) |
| iOS | SwiftUI (`signa-ios`) |
| Web | Next.js 14, TypeScript, Tailwind CSS, React Query |

There is no AI in Signa.

## Quick start

```bash
# Back-end
cd back-end
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # Supabase, JWT secret, Telegram bot (see below)
python -m uvicorn main:app --reload --port 8000
pytest tests/ -q

# Web
cd front-end
npm install
npm run dev
```

A new database is created by running `back-end/app/db/schema.sql` once in the Supabase SQL Editor.

## Environment variables

See `back-end/.env.example`.

- **Required:** `JWT_SECRET_KEY`, `SUPABASE_URL`, `SUPABASE_KEY` (the service_role key).
- **Telegram:** `TELEGRAM_BOT_TOKEN` for sign-in codes, two-step sign-in and Premium notifications.
- **Email:** `EMAIL_PROVIDER` (console, resend or smtp) and its keys.
- **iOS push:** `APNS_TEAM_ID`, `APNS_KEY_ID`, `APNS_PRIVATE_KEY`, `APNS_BUNDLE_ID`. Without them, pushes
  are only logged.

## Versions

Every commit bumps the back-end (`back-end/VERSION`, shown by `GET /api/v1/version`) and web
(`front-end/package.json`) versions through `.githooks/pre-commit`. A version changed by hand in the same
commit is kept. In a new clone, run `git config core.hooksPath .githooks`.

## Web app note

The web app still contains the old Advisor pages. They are owner-only and hidden, because the back-end no
longer serves them. The iOS app is the launch client.
