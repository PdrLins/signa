Show the Signa Telegram bot capabilities — commands, alerts, OTP, and webhook setup.

## Bot Commands (user sends to bot in Telegram)

| Command | What It Does | Example |
|---------|-------------|---------|
| `/signals` | Show latest 10 signals with scores | `/signals` |
| `/gem` | Show current GEM alerts with reasoning | `/gem` |
| `/watch` | View full watchlist | `/watch` |
| `/watch TICKER` | Add ticker to watchlist (validated) | `/watch AAPL` |
| `/remove TICKER` | Remove ticker from watchlist | `/remove SHOP.TO` |
| `/score TICKER` | Get latest score, action, status, reasoning | `/score NVDA` |
| `/status` | Show last scan type, time, signal/GEM counts | `/status` |
| `/help` | List all available commands | `/help` |

## Automatic Alerts (bot sends to you)

| Alert Type | Trigger | Content |
|------------|---------|---------|
| GEM Alert | Signal scores 85+ with all 5 GEM conditions | Ticker, action, score, price, target, stop, R/R, reasoning, catalyst |
| Morning Digest | After 6:00 AM PRE_MARKET scan | Total signals, BUY count, GEM count, top 3 ranked |
| After-Close Digest | After 4:30 PM AFTER_CLOSE scan | Same format, next-day watchlist focus |
| Status Change | Signal changes from prior scan | Ticker, old→new status (CONFIRMED/WEAKENING/CANCELLED/UPGRADED), score |

## OTP Verification Messages
When user logs in via API, bot sends:
```
🔐 Signa Verification Code

Your login code is: 847291

⏱ Valid for 2 minutes only
Never share this code with anyone.
```

## Webhook Setup
Register webhook with Telegram:
```bash
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://your-app.fly.dev/api/v1/telegram/webhook",
    "secret_token": "your-webhook-secret"
  }'
```

Set `TELEGRAM_WEBHOOK_SECRET=your-webhook-secret` in `.env`.

The webhook endpoint rejects ALL requests when no secret is configured.

## How It Works
1. Telegram POSTs message JSON to `/api/v1/telegram/webhook`
2. `main.py` validates `X-Telegram-Bot-Api-Secret-Token` header
3. Parses command and args from message text
4. Dispatches to `telegram_bot.handle_command()`
5. Handler calls appropriate service (signal_service, watchlist_service)
6. Sends formatted response back to user's chat

## Security
- Webhook validates secret token header (rejects if not configured)
- All dynamic values HTML-escaped (prevents content injection)
- Ticker inputs validated before DB queries
- Reusable `httpx.AsyncClient` (no connection churn)

## Key Files
- `app/notifications/telegram_bot.py` — send_message, send_otp_message, send_gem_alert, send_scan_digest, handle_command
- `app/notifications/formatters.py` — format_signal_summary, format_signal_detail, format_morning_digest
- `app/notifications/dispatcher.py` — process_pending_alerts (queue processor)
- `main.py` lines 70-97 — webhook endpoint
