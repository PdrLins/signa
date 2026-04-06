Show the full API endpoint reference for the Signa frontend.

## Client Config (`src/lib/api.ts`)
- Base: `NEXT_PUBLIC_API_URL` or `http://localhost:8000/api/v1`
- Timeout: 15s
- Auth: Bearer token auto-injected for non-public routes
- Brain: `X-Brain-Token` header added manually via `brainStore.getHeaders()`

## Auth Endpoints

| Method | Path | Request | Response | Notes |
|--------|------|---------|----------|-------|
| POST | `/auth/login` | `{ username, password }` | `{ message, session_token }` | Public |
| POST | `/auth/verify-otp` | `{ session_token, otp_code }` | `{ access_token, token_type, expires_in }` | Public |
| POST | `/auth/logout` | — | `{ message }` | Clears token |
| POST | `/auth/refresh` | — | `{ access_token, token_type, expires_in }` | |

## Signals

| Method | Path | Params | Response |
|--------|------|--------|----------|
| GET | `/signals` | `?bucket=&action=&status=&period=&min_score=&limit=` | `{ signals: Signal[], count }` |
| GET | `/signals/gems` | `?limit=` | `{ signals: Signal[], count }` |
| GET | `/signals/{ticker}` | `?limit=` | `{ signals: Signal[], count }` |

**Signal fields**: id, symbol, action (BUY/HOLD/SELL/AVOID), status (CONFIRMED/WEAKENING/CANCELLED/UPGRADED), score, confidence, is_gem, bucket (SAFE_INCOME/HIGH_RISK), price_at_signal, target_price, stop_loss, risk_reward, catalyst, sentiment_score, reasoning, signal_style (MOMENTUM/CONTRARIAN/NEUTRAL), market_regime (TRENDING/VOLATILE/CRISIS), account_recommendation (TFSA/RRSP/TAXABLE), superficial_loss_warning

## Tickers

| Method | Path | Params | Response |
|--------|------|--------|----------|
| GET | `/tickers/{ticker}` | — | `TickerDetail` (name, exchange, sector, fundamentals, current_price) |
| GET | `/tickers/{ticker}/chart` | `?period=1d/1w/1mo/3mo` | `TickerChart` (timestamps[], prices[], volumes[]) |
| GET | `/tickers/{ticker}/signals` | `?limit=` | `{ signals: Signal[], count }` |

## Watchlist

| Method | Path | Params | Response |
|--------|------|--------|----------|
| GET | `/watchlist` | — | `{ items: WatchlistItem[], count }` |
| POST | `/watchlist/{ticker}` | `?notes=` | `WatchlistItem` |
| DELETE | `/watchlist/{ticker}` | — | `{ message }` |

## Scans

| Method | Path | Params | Response |
|--------|------|--------|----------|
| GET | `/scans` | `?limit=` | `{ scans: ScanRecord[], count }` |
| GET | `/scans/today` | — | `ScanTodayRecord[]` (4 daily slots) |
| POST | `/scans/trigger` | `?scan_type=MORNING/PRE_CLOSE/...` | `{ scan_id, status, message }` |
| GET | `/scans/{scanId}/progress` | — | `ScanProgress` (status, phase, current_ticker, tickers_done/total, signals_found, gems_found) |

**Scan phases**: QUEUED → LOADING_DATA → SCREENING → FILTERING → MACRO_ANALYSIS → PRE_SCORING → ANALYZING → SAVING → ALERTING → MONITORING → COMPLETE

## Stats

| Method | Path | Response |
|--------|------|----------|
| GET | `/stats/daily` | `DailyStats` (gems_today/yesterday, win_rate_30d, tickers_scanned, next_scan_time, ai_cost_today, claude_cost, grok_cost) |

## Portfolio & Positions

| Method | Path | Response |
|--------|------|----------|
| GET | `/portfolio` | `{ items: PortfolioItem[], count }` |
| POST | `/portfolio` | `PortfolioItem` |
| PUT | `/portfolio/{id}` | `PortfolioItem` |
| DELETE | `/portfolio/{id}` | `{ message }` |
| GET | `/positions` | `{ positions: Position[], count }` |
| GET | `/positions/history` | `{ positions: Position[], count }` |
| GET | `/positions/{id}` | `Position` |
| POST | `/positions` | `Position` |
| PUT | `/positions/{id}` | `Position` |
| POST | `/positions/{id}/close` | `Position` |

## Brain (requires X-Brain-Token)

| Method | Path | Response |
|--------|------|----------|
| GET | `/brain/highlights` | Summary stats (no auth required, safe data) |
| POST | `/brain/challenge` | `{ message, session_token }` — triggers Telegram OTP |
| POST | `/brain/verify` | `{ brain_token, expires_in }` — unlocks brain |
| GET | `/brain/rules` | Rule[] |
| PUT | `/brain/rules/{id}` | Updated rule |
| GET | `/brain/knowledge` | Knowledge[] |
| PUT | `/brain/knowledge/{id}` | Updated knowledge |
| GET | `/brain/audit` | AuditEvent[] |

## Learning (Self-Learning Loop)

| Method | Path | Response |
|--------|------|----------|
| GET | `/learning/suggestions` | `?status=PENDING/APPROVED/REJECTED` → Suggestion[] |
| POST | `/learning/analyze` | `?days=30` → `{ suggestions, count }` |
| PUT | `/learning/suggestions/{id}/approve` | Suggestion |
| PUT | `/learning/suggestions/{id}/reject` | Suggestion |
| POST | `/learning/suggestions/{id}/apply` | Suggestion |

## Health (Public)

| Method | Path | Response |
|--------|------|----------|
| GET | `/health` | `{ status, app, uptime_seconds, scheduler_running }` |
| GET | `/health/budget` | Budget data (AI provider costs) |
| PUT | `/health/ai-config` | Update AI provider settings |

## React Query Cache Keys

| Key Pattern | Hook | StaleTime | Refetch |
|------------|------|-----------|---------|
| `['signals', limit, bucket, action, status, period, min_score]` | `useAllSignals` | 2min | — |
| `['gems', limit]` | `useGemSignals` | 5min | 5min |
| `['signal-history', ticker]` | `useSignalHistory` | 2min | — |
| `['stats']` | `useStats` | 60s | 60s (not in bg) |
| `['scans']` | `useScans` | — | 60s |
| `['scans-today']` | `useScansToday` | — | 60s |
| `['watchlist']` | `useWatchlist` | default | — |
| `['brain-highlights']` | `useBrainHighlights` | 30s | — |
| `['brain-rules']` | `useBrainRules` | 30s | enabled when unlocked |
| `['brain-knowledge']` | `useBrainKnowledge` | 30s | enabled when unlocked |
| `['brain-audit']` | `useBrainAudit` | — | enabled when unlocked |
| `['brain-suggestions', status]` | `useBrainSuggestions` | — | enabled when unlocked |
| `['price-history', symbol, range]` | `usePriceHistory` | 5min | — |
