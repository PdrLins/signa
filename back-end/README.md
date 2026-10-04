# Signa Back-end

Portfolio tracker API for the Signa iOS and web apps: holdings, accounts,
transactions, live prices, dividends, allocation, events, price alerts and
Telegram notifications, on Free and Premium plans. No AI. The brain (AI
signals) is Signa Advisor, a separate repository.

## Tech Stack

- **Runtime:** Python 3.12 / FastAPI / Uvicorn (one process: the scheduler runs in it)
- **Database:** Supabase (PostgreSQL, accessed with the service_role key)
- **Data:** yfinance (quotes, history, dividends, fund data, earnings dates)
- **Notifications:** Telegram Bot API (sign-in codes, two-step sign-in, Premium alerts), email (Resend / SMTP)
- **Scheduler:** APScheduler (quotes every minute, snapshots and digests daily)

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
│   ├── market/          # Known symbols, symbol resolution, technical checks, fund data, earnings
│   ├── middleware/      # Auth (JWT + sessions), audit, rate limiting
│   ├── models/          # Pydantic schemas
│   ├── notifications/   # Telegram queue/sending, incoming messages, templates
│   ├── scheduler/       # Jobs (quotes, snapshots, notifications, cleanup)
│   ├── services/        # Business logic
│   └── db/              # Supabase client, queries, migrations
└── tests/
```

## Scheduled jobs (Eastern Time)

| Job | When |
|---|---|
| Quotes refresh | every minute, 9:30–16:00 weekdays (+ 16:05) |
| Quotes outside the session (crypto 24/7, US extended hours for Premium) | every minute |
| Portfolio snapshots | 16:30 weekdays |
| Holding status (price fallback, YTD base) | 17:45 weekdays |
| Income forecast / check status snapshots | 18:00 / 18:15 weekdays |
| Telegram digests / live alerts (Premium) | 8:30 daily, 18:30 weekdays / every 5 min in the session |
| Usage counters flush | every 5 min |
| Token and code cleanup | 2:00 |

## Environment Variables

See `.env.example`. Required: `JWT_SECRET_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`.
