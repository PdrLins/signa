Show the Signa backend architecture and how modules connect.

## Module Map (103 files)

### Live System (app/)
```
main.py                    → FastAPI app, lifespan (starts scheduler), middleware stack, webhook
app/core/config.py         → All env vars via pydantic-settings, startup validators
app/core/security.py       → JWT encode/decode (jose), bcrypt (passlib), OTP (HMAC-SHA256)
app/core/dependencies.py   → get_current_user reads request.state.user (set by middleware)
app/core/exceptions.py     → AuthenticationError, RateLimitExceeded, OTPExpired/Invalid
app/core/utils.py          → get_client_ip (trusted proxy aware), validate_ticker (regex)
app/middleware/auth.py      → JWT validation, sets request.state.user, skips public paths
app/middleware/audit.py     → Logs method/path/status/duration/IP/username per request
app/middleware/rate_limit.py → IP rate limiting on /auth/*, LRU bounded OrderedDict
app/api/v1/*.py             → Route handlers (thin — delegate to services)
app/models/*.py             → Pydantic schemas for requests/responses
app/services/auth_service.py → Login, OTP send/verify, JWT issue/revoke/refresh
app/services/scan_service.py → Full scan pipeline orchestrator (the main engine)
app/services/signal_service.py → Signal queries
app/services/watchlist_service.py → Watchlist CRUD
app/scanners/market_scanner.py → yfinance: OHLCV, fundamentals (async via to_thread)
app/scanners/macro_scanner.py → FRED API: fed funds, 10Y, CPI, unemployment + VIX
app/scanners/indicators.py → RSI, MACD, Bollinger Bands, SMA 50/200, ATR, volume Z-score
app/scanners/prefilter.py  → 1000 → 50 candidates by volume + price change
app/scanners/universe.py   → Hardcoded ticker lists (TSX .TO, NYSE, NASDAQ)
app/ai/grok_client.py      → xAI sentiment analysis (OpenAI SDK), async lock, retries
app/ai/claude_client.py    → Anthropic signal synthesis, async lock, retries
app/ai/prompts.py          → All prompt templates + clean_json_response utility
app/ai/signal_engine.py    → Scoring (backtest-tuned), GEM detection, blockers, status
app/scheduler/runner.py    → APScheduler AsyncIOScheduler, 4 CronTrigger jobs
app/scheduler/jobs.py      → Async functions that call scan_service.run_scan()
app/notifications/telegram_bot.py → Send messages, handle commands, HTML-escaped
app/notifications/formatters.py → Signal summary/detail/digest templates
app/notifications/dispatcher.py → Process pending alert queue
app/db/supabase.py         → Thread-safe Supabase client singleton
app/db/queries.py          → All DB operations
app/db/schema.sql          → 9 tables + indexes + triggers + RPC function
```

### Backtest System (backtest/)
```
backtest/run_backtest.py   → CLI entry point (--dry-run, --tickers, --start, --end, --no-cache)
backtest/config.py         → Tickers (15 US + 15 TSX), thresholds (buy=65, ceiling=72), weights
backtest/data/loader.py    → DataLoader: yfinance OHLCV (300-day warmup), fundamentals, FRED macro
backtest/engine/simulator.py → BacktestSimulator: runs all tickers x all trading days
backtest/engine/indicators.py → compute_indicators(df, as_of_date) — sliced, no look-ahead
backtest/engine/fundamentals.py → extract_fundamentals, classify_bucket (SAFE_INCOME/HIGH_RISK)
backtest/engine/scorer.py  → Data-tuned scoring (RSI sweet spots, MACD histogram, momentum caps)
backtest/evaluation/evaluator.py → Measures 5/10/20d actual returns per signal
backtest/evaluation/metrics.py → Win rates, distributions, top/worst, auto-detected issues
backtest/reports/summary.py → Rich terminal output
backtest/reports/generator.py → CSV, JSON, Claude analysis MD, IMPROVEMENTS MD
```

## Request Flow (Live)
```
Request → CORSMiddleware → AuditMiddleware → RateLimitMiddleware → AuthMiddleware
  → AuthMiddleware sets request.state.user (or rejects)
  → Route handler → Depends(get_current_user) reads request.state.user
  → Service layer → DB queries → Response
```

## Scan Flow (Live)
```
APScheduler CronTrigger → jobs.py → scan_service.run_scan()
  → Load universe → bulk screen (yfinance) → prefilter → macro snapshot (FRED+VIX)
  → For each candidate (semaphore=10):
      (price_history + fundamentals + grok_sentiment) in parallel
      → compute_indicators → claude synthesis → score → blockers → GEM check → status
  → batch insert signals → send Telegram alerts
```

## Backtest Flow
```
run_backtest.py → DataLoader.load_all() + load_macro() + load_fundamentals()
  → BacktestSimulator.run(): for each day x each ticker:
      indicators(df, as_of_date) → fundamentals → classify_bucket → score → signal
  → BacktestEvaluator.evaluate(): measure 5/10/20d returns
  → compute_metrics(): win rates, distributions, auto-detected issues
  → print_summary() + save_results() (CSV, JSON, MD, IMPROVEMENTS)
```
