Show the full API endpoint reference for Signa backend.

## Public Endpoints (no auth)
| Method | Path | Body/Params | Response |
|--------|------|-------------|----------|
| POST | `/api/v1/auth/login` | `{ username, password }` | `{ message, session_token }` |
| POST | `/api/v1/auth/verify-otp` | `{ session_token, otp_code }` | `{ access_token, token_type, expires_in }` |
| GET | `/api/v1/health` | — | `{ status, app, uptime_seconds, scheduler_running }` |

## Protected Endpoints (`Authorization: Bearer <token>`)

### Auth
| Method | Path | Response |
|--------|------|----------|
| POST | `/auth/logout` | `{ message }` |
| POST | `/auth/refresh` | `{ access_token, token_type, expires_in }` |

### Signals
| Method | Path | Params | Response |
|--------|------|--------|----------|
| GET | `/signals` | `?bucket=SAFE_INCOME\|HIGH_RISK&action=BUY\|HOLD\|SELL\|AVOID&status=...&period=today\|week\|month&min_score=0-100&limit=1-200` | `{ signals[], count }` |
| GET | `/signals/gems` | `?limit=1-100` | `{ signals[], count }` |
| GET | `/signals/{ticker}` | `?limit=1-100` | `{ signals[], count }` |

### Tickers
| Method | Path | Params | Response |
|--------|------|--------|----------|
| GET | `/tickers/{ticker}` | — | `{ ticker, company_name, exchange, asset_type, current_price, fundamentals, latest_signal, open_position }` |
| GET | `/tickers/{ticker}/chart` | `?period=1d\|5d\|1mo\|3mo\|6mo\|1y\|5y` | `{ data_points[], summary, signal_markers[] }` |
| GET | `/tickers/{ticker}/signals` | `?limit=1-100` | `{ signals[], count }` |

### Scans
| Method | Path | Params | Response |
|--------|------|--------|----------|
| GET | `/scans` | `?limit=1-100` | `{ scans[], count }` |
| GET | `/scans/today` | — | `ScanTodayRecord[]` (4 slots) |
| POST | `/scans/trigger` | `?scan_type=PRE_MARKET\|MORNING\|PRE_CLOSE\|AFTER_CLOSE` | `{ scan_id, status, message }` (409 if scan running) |
| GET | `/scans/{scan_id}/progress` | — | `{ scan_id, status, progress_pct, phase, current_ticker, ... }` |

### Watchlist
| Method | Path | Body | Response |
|--------|------|------|----------|
| GET | `/watchlist` | — | `{ items[], count }` |
| POST | `/watchlist/{ticker}` | `{ notes? }` | item (201) |
| DELETE | `/watchlist/{ticker}` | — | `{ message }` |

### Portfolio
| Method | Path | Body | Response |
|--------|------|------|----------|
| GET | `/portfolio` | — | `{ items[], count }` |
| POST | `/portfolio` | `{ symbol, bucket?, account_type?, shares?, avg_cost?, currency? }` | item (201) |
| PUT | `/portfolio/{id}` | `{ bucket?, account_type?, shares?, avg_cost?, currency? }` | item |
| DELETE | `/portfolio/{id}` | — | `{ message }` |

### Positions
| Method | Path | Body | Response |
|--------|------|------|----------|
| GET | `/positions` | — | `{ positions[], count }` |
| GET | `/positions/history` | `?limit=1-200` | `{ positions[], count }` |
| GET | `/positions/{id}` | — | position |
| POST | `/positions` | `{ symbol, entry_price, shares, account_type?, bucket?, currency?, target_price?, stop_loss?, notes? }` | position (201) |
| PUT | `/positions/{id}` | `{ target_price?, stop_loss?, notes? }` | position |
| POST | `/positions/{id}/close` | `{ exit_price }` | position |

### Stats
| Method | Path | Response |
|--------|------|----------|
| GET | `/stats/daily` | `{ gems_today, gems_yesterday, win_rate_30d, tickers_scanned, next_scan_time, ai_cost_today }` |
| GET | `/stats/recent-alerts` | `alert[]` (last 5) |
| GET | `/stats/virtual-portfolio` | virtual portfolio summary |
| GET | `/stats/positions-summary` | `{ count, positions[] (top 5), total_pnl_pct }` |

### Health / Config
| Method | Path | Body | Response |
|--------|------|------|----------|
| GET | `/health/integrations` | — | `{ status, integrations: { supabase, telegram, claude, grok, gemini, scheduler } }` |
| POST | `/health/ping-telegram` | — | `{ status, message }` |
| GET | `/health/budget` | — | budget summary |
| PUT | `/health/budget` | `{ daily_limit?, claude_monthly?, grok_monthly?, gemini_monthly? }` | budget summary |
| GET | `/health/ai-config` | — | provider config |
| PUT | `/health/ai-config` | `{ language?, synthesis_providers?, sentiment_providers?, ai_enabled?, ... }` | updated config |

## Brain Editor Endpoints (JWT + brain 2FA)

### Challenge/Verify (JWT only)
| Method | Path | Body | Response |
|--------|------|------|----------|
| GET | `/brain/highlights` | — | highlights |
| GET | `/brain/insights/{ticker}` | — | `{ ticker, summary, key_points[], knowledge[] }` |
| POST | `/brain/challenge` | — | `{ message }` |
| POST | `/brain/verify` | `{ otp_code }` | `{ brain_token, expires_in }` |

### Rules & Knowledge (JWT + X-Brain-Token)
| Method | Path | Body | Response |
|--------|------|------|----------|
| GET | `/brain/rules` | — | rules[] |
| GET | `/brain/rules/{id}` | — | rule |
| PUT | `/brain/rules/{id}` | `{ description?, formula?, threshold_min/max?, is_blocker?, weight_safe/risk?, is_active?, notes? }` | rule |
| GET | `/brain/knowledge` | — | knowledge[] |
| GET | `/brain/knowledge/{id}` | — | entry |
| PUT | `/brain/knowledge/{id}` | `{ explanation?, formula?, example?, is_active?, notes? }` | entry |
| GET | `/brain/audit` | — | brain audit events (last 50) |

### Learning (mixed auth)
| Method | Path | Auth | Body | Response |
|--------|------|------|------|----------|
| POST | `/learning/outcomes` | JWT | TradeOutcomeRequest | outcome |
| GET | `/learning/outcomes` | JWT | `?days=1-365&limit=1-500` | `{ outcomes[], count, stats }` |
| POST | `/learning/analyze` | Brain 2FA | `?days=1-90` | `{ suggestions[], count }` |
| GET | `/learning/suggestions` | Brain 2FA | `?status=PENDING\|APPROVED\|REJECTED\|APPLIED&limit=1-200` | suggestions[] |
| PUT | `/learning/suggestions/{id}/approve` | Brain 2FA | — | `{ status }` |
| PUT | `/learning/suggestions/{id}/reject` | Brain 2FA | `{ reason? }` | `{ status }` |
| POST | `/learning/suggestions/{id}/apply` | Brain 2FA | — | result |

### Logs (Brain 2FA)
| Method | Path | Auth | Response |
|--------|------|------|----------|
| GET | `/logs/recent` | Brain 2FA | `{ logs[], count }` (`?limit=1-500&level=DEBUG\|INFO\|...&search=max200`) |
| WS | `/logs/stream` | JWT + Brain token (query params) | Real-time log entries |

## Webhook
| Method | Path | Header | Response |
|--------|------|--------|----------|
| POST | `/telegram/webhook` | `X-Telegram-Bot-Api-Secret-Token` | `{ ok: true }` |
