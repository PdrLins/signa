# Signa Back-end

Portfolio tracker API for the Signa iOS and web apps: holdings, accounts,
people, transactions, live prices, dividends, allocation, events, price
alerts, goals, monthly recaps, widgets, push and Telegram notifications, and
problem reports, on Free and Premium plans. Works in any country and currency
(Brazil, Canada and the US first). No AI: the brain (AI signals) is Signa
Advisor, a separate repository.

## Tech Stack

- **Runtime:** Python 3.12 / FastAPI / Uvicorn (one process: the scheduler runs in it)
- **Database:** Supabase (PostgreSQL, accessed with the service_role key)
- **Data:** yfinance (quotes, history, dividends, fund data, earnings dates, FX rates)
- **Exchange hours and holidays:** `exchange_calendars` (B3, TSX, NYSE, LSE, XETRA, Tokyo …)
- **Notifications:** Apple Push Notifications (iOS), Telegram Bot API (sign-in codes, two-step sign-in, Premium alerts), email (Resend / SMTP)
- **Scheduler:** APScheduler, in-process (run exactly one instance)

## Quick Start

```bash
cd back-end
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # Supabase, JWT secret, Telegram bot
uvicorn main:app --reload --port 8000
pytest tests/ -q
```

With `DEBUG=true`, interactive API docs are at `http://localhost:8000/docs`.

## Project Structure

```
back-end/
├── main.py              # App entry point, middleware, routers, Telegram webhook
├── app/
│   ├── api/v1/          # Routes (every docstring has the response shape)
│   ├── core/            # Config, access levels, security, market calendar, cache
│   ├── market/          # Currency per listing, exchange sessions, symbols, technical checks, funds, earnings
│   ├── middleware/      # Auth (JWT + sessions), audit, rate limiting
│   ├── models/          # Pydantic schemas
│   ├── notifications/   # Telegram queue/sending, incoming messages, templates
│   ├── scheduler/       # Jobs (quotes, snapshots, notifications, cleanup)
│   ├── services/        # Business logic
│   └── db/              # Supabase client, queries, schema.sql (new database), migrations
└── tests/
```

## Scheduled jobs (Eastern Time)

| Job | When |
|---|---|
| Quotes refresh: each symbol while its own exchange is open (+10 min after its close) | every minute |
| Quotes after the US close (all followed symbols) | 16:05 weekdays |
| Crypto 24/7 and US pre/after-hours (Premium) | every minute |
| Portfolio snapshots | 16:30 weekdays |
| Holding status (price fallback, YTD base) | 17:45 weekdays |
| Income forecast / check status snapshots | 18:00 / 18:15 weekdays |
| Telegram digests / live alerts (Premium) | 8:30 daily, 18:30 weekdays / every 5 min in the session |
| Push notifications (iOS; free basics, Premium all) | 8:31 daily, 18:31 weekdays / every 5 min in the session |
| Monthly recap push | 1st of the month, 9:05 |
| Usage counters flush | every 5 min |
| Token and code cleanup | 2:00 |

## Environment Variables

See `.env.example`. Required: `JWT_SECRET_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`.
Optional: `TELEGRAM_BOT_TOKEN`, email (`EMAIL_PROVIDER`, `RESEND_API_KEY` or `SMTP_*`),
iOS push (`APNS_TEAM_ID`, `APNS_KEY_ID`, `APNS_PRIVATE_KEY`, `APNS_BUNDLE_ID`).

## Database

`app/db/schema.sql` creates the whole database on an empty Supabase project
(29 tables, Row Level Security on, service_role access only). Changes: add the
next numbered file in `app/db/migrations/`, run it, then fold it into
`schema.sql`. See `app/db/README.md`.

## API

Every route lives in `app/api/v1/`, and its docstring documents the request,
the response shape and the errors. Plans and features: `app/core/access.py`
(`GET /api/v1/auth/me` returns what the signed-in user can use).
