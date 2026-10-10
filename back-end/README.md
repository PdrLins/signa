# Signa Back-end

Portfolio tracker API for the Signa iOS app: holdings, accounts,
people, transactions, live prices, dividends, allocation, events, price
alerts, goals, monthly recaps, stock suggestions, widgets, push and Telegram notifications, and
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
| Telegram digests / live alerts (Premium) | 8:30 daily, 18:30 weekdays / every 5 min while a followed exchange trades |
| Push notifications (iOS; free basics, Premium all) | 8:31 daily, 18:31 weekdays / every 5 min while a followed exchange trades |
| Monthly recap push | 1st of the month, 9:05 |
| Weekly digest push ("your week") | Sunday 10:00 |
| Automatic dividends (estimated "received" records) | 19:30 |
| Usage counters flush | every 5 min |
| Suggestions data (followed-together counts, symbol profiles) | 3:00 |
| Apple Search Ads attribution (sign-up campaign ids) | every 10 min |
| Cleanup: expired tokens and codes, notification keys (45 days), check snapshots (60), audit log (180), activity (400), closed reports (365); deletes accounts past their 30-day grace; pays earned referrals | 2:00 |

## Environment Variables

See `.env.example`. Required: `JWT_SECRET_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`.
Optional: Telegram (`TELEGRAM_ENABLED=true` + `TELEGRAM_BOT_TOKEN`; off by default: users can't
connect or use it and nothing is sent), email (`EMAIL_PROVIDER`, `RESEND_API_KEY` or `SMTP_*`),
iOS push (`APNS_TEAM_ID`, `APNS_KEY_ID`, `APNS_PRIVATE_KEY`, `APNS_BUNDLE_ID`).
Sign-up: `SIGNUP_INVITE_REQUIRED` (default true = invite-only; false = open sign-up, needed before ads).
Premium sales: `PREMIUM_ON_SALE` (default false: the apps hide upgrade buttons until In-App Purchase exists).

## Deploy (Fly.io)

`Dockerfile` + `fly.toml` in this folder. Fly builds the image on its own servers (no Docker needed
locally) and runs **exactly one machine, always on**: the scheduler runs inside the app, so two copies
would run every job twice. Non-secret production settings are in `fly.toml` `[env]`; secrets are set
with `fly secrets set` (never `fly secrets import < .env`: the local `.env` has dev values such as
`LOGIN_OTP_ENABLED=false` and `DEV_TOOLS_ENABLED=true` that would override `[env]`).

```bash
brew install flyctl && fly auth login
cd back-end
fly launch --no-deploy --copy-config        # creates the app from fly.toml (rename it if taken)
fly secrets set SUPABASE_URL=... SUPABASE_KEY=... JWT_SECRET_KEY=$(openssl rand -hex 32)
fly deploy --ha=false                       # --ha=false: one machine, not two
fly logs                                    # watch it start
curl https://<app>.fly.dev/api/v1/health
```

Then:
- Telegram (off until wanted): `fly secrets set TELEGRAM_BOT_TOKEN=... TELEGRAM_WEBHOOK_SECRET=$(openssl rand -hex 24)`,
  `TELEGRAM_ENABLED = "true"` in `fly.toml`, deploy, then register the webhook once:
  `https://api.telegram.org/bot<TOKEN>/setWebhook` with
  `url=https://<app>.fly.dev/api/v1/telegram/webhook` and `secret_token=<TELEGRAM_WEBHOOK_SECRET>`.
- Custom domain: `fly certs add api.mysigna.app`, then the DNS records it prints.
- Later: `APNS_*` secrets (push), `RESEND_API_KEY` + `EMAIL_PROVIDER=resend` (email codes),
  `SIGNUP_INVITE_REQUIRED=false` before ads (`fly secrets set ...` restarts the machine).
- Admin scripts on the server: `fly ssh console -C "python create_user.py ..."`.

## Database

`app/db/schema.sql` creates the whole database on an empty Supabase project
(37 tables, Row Level Security on, service_role access only). Changes: add the
next numbered file in `app/db/migrations/`, run it, then fold it into
`schema.sql`. See `app/db/README.md`.

## API

Every route lives in `app/api/v1/`, and its docstring documents the request,
the response shape and the errors. Plans and features: `app/core/access.py`
(`GET /api/v1/auth/me` returns what the signed-in user can use).
