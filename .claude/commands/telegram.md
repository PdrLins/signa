Show the Signa Telegram bot capabilities — commands, alerts, OTP, and webhook setup.

## Bot Commands

| Command | Action | Auth |
|---------|--------|------|
| `/signals` | Latest 10 signals with scores | chat_id only |
| `/gem` | GEM alerts with reasoning (top 5) | chat_id only |
| `/watch` | View full watchlist | chat_id only |
| `/watch TICKER` | Add ticker (validated) | chat_id only |
| `/remove TICKER` | Remove from watchlist | chat_id only |
| `/score TICKER` | Latest score, action, status, reasoning | chat_id only |
| `/positions` | Open positions with P&L | chat_id only |
| `/close TICKER PRICE` | Close a position | chat_id only |
| `/status` | Last scan info | chat_id only |
| `/help` | List commands | chat_id only |

## Automatic Alerts

| Alert | Trigger | Template Key |
|-------|---------|-------------|
| GEM Alert | Score 85+ with all 5 GEM conditions | `gem_alert` |
| Scan Digest | PRE_MARKET or AFTER_CLOSE scan completes | `scan_digest_header` + `scan_digest_top3` |
| Watchlist Sell | Watchlisted ticker gets SELL/AVOID | `watchlist_sell` |
| Stop Loss Hit | Position hits stop_loss price | `stop_loss` |
| Target Reached | Position hits target_price | `target_reached` |
| P&L Milestone | Position crosses 5% P&L intervals | `pnl_milestone` |
| Signal Weakening | Open position's signal weakens | `signal_weakening` |

## OTP Messages
- **Login OTP** — sent to user's `telegram_chat_id` from DB (auth_service.py). Template: `otp`. 2-minute expiry.
- **Brain OTP** — sent to user's `telegram_chat_id` from DB (brain.py). Template: `brain_otp`. 60-second expiry.

## Bilingual Templates (app/notifications/messages.py)
All templates support EN and PT via `settings.language`. Format: `msg("key", **kwargs)`.

## Webhook Setup
```bash
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://your-domain/api/v1/telegram/webhook",
    "secret_token": "your-webhook-secret"
  }'
```

Set `TELEGRAM_WEBHOOK_SECRET` in `.env`. The endpoint rejects ALL requests when secret is not configured or doesn't match (uses `hmac.compare_digest`).

## How It Works
1. Telegram POSTs to `/api/v1/telegram/webhook`
2. `main.py` validates secret header (constant-time comparison)
3. Ignores messages not from `settings.telegram_chat_id` (owner only)
4. Parses command + args → `telegram_bot.handle_command()`
5. Handler calls service layer → formatted HTML response
6. Response sent via reusable `httpx.AsyncClient`

## Key Files
- `app/notifications/telegram_bot.py` — send functions + handle_command (10 commands)
- `app/notifications/messages.py` — bilingual templates (EN/PT)
- `app/notifications/dispatcher.py` — process pending alert queue
- `main.py:82-117` — webhook endpoint
