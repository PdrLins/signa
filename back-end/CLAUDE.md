# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

AI investment signal engine. Scans ~270 tickers daily across TSX, NYSE, NASDAQ, and crypto. Two-pass approach: pre-scores all candidates with technicals/fundamentals (free), then sends top 15 to AI for full analysis (budget-checked). Brain watchdog monitors open positions every 15 min.

## Commands

```bash
source venv/bin/activate
python -m uvicorn main:app --reload --port 8000
pytest tests/ -v                             # all tests
pytest tests/test_scorer.py::test_name -v    # single test
python -m backtest.run_backtest --start 2021-01-01 --end 2026-09-01  # backtest (live code, tech-only)
python -m app.db.seed_brain                  # seed brain tables
```

## Environment

Config in `app/core/config.py` (Pydantic Settings from `.env`). Required: `JWT_SECRET_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`, `BRAIN_TOKEN_SECRET`. Auth is always enabled. Validation at import time.

## Skills (use these — they have all the detail)

- `/architecture` — Module map, request flow, scan flow, all directories
- `/scan-pipeline` — Two-pass pipeline, scoring weights, GEM conditions, blockers, contrarian, regimes
- `/brain-learning` — Self-learning loop: thinking vs knowledge, thesis tracking, pattern stats, audit log
- `/api-reference` — Every endpoint with methods, params, auth level, responses
- `/database` — All 20 tables, indexes, triggers, query patterns, caching
- `/security` — Auth flow, JWT, OTP, brain 2FA, rate limiting tiers, caching architecture
- `/telegram` — Bot commands, alert types, OTP, webhook setup, bilingual templates
- `/conventions` — Async patterns, auth patterns, caching, validation, file organization

## Key Thresholds

All live values are in `app/core/config.py`; this is the shape of the decision.

- **Candidates:** prefilter ranks by trend quality (not today's move). Only candidates that pass `technical_filter` get AI (up to `ai_candidate_limit`, 15), ranked by trend quality; the filter result is stored in `technical_data._tech_filter`. Indicators use completed daily bars only.
- **AI:** Grok live X/web search (uncited results get zero weight) → Sonnet 5.5 synthesis → a routine BUY is re-checked by Opus 5.5. `CLAUDE_LOCAL=true` = `claude` CLI only, never the API. `ai_status="validated"` requires AI BUY with confidence ≥ 60.
- **Score:** BUY at 65 (HIGH_RISK) / 62 (SAFE_INCOME), ceiling 90. Enrichment (estimate revisions, relative strength, insider buying, short trend) adds at most ±5 (`enrichment_scoring_enabled`).
- **Blockers:** RSI > 75; red flags only when cited AND material (severity vs market cap; low-severity litigation never blocks); earnings blackout 3 trading days before earnings.
- **Brain entry:** validated AI BUY + `technical_filter` pass (price > SMA200 and SMA50 > SMA200, RSI ≤ 75, ≤ 15% above SMA50, 20-day dollar volume ≥ $10M, or ≥ $50M for crypto, no blocker) + computed R:R ≥ 2.0. The score doesn't gate or rank entries: the 2021–2026 study found it didn't predict returns. Candidates are taken by AI p_win, then confidence. `brain_entry_mode="score"` restores the old score ≥ 75 gate. Risk 1% of equity per trade, ≤ 10% per position; ≤ 8 open, ≤ 2 per sector, ≤ 25% crypto; correlation gate (≥ 0.80 to one holding, or ≥ 0.70 to two); 3-trading-day same-symbol re-entry cooldown. Drawdown breaker: at −10% from peak equity, entries pause for `brain_drawdown_pause_trading_days` (10) US trading days. The peak then resets to current equity and entries resume, so the breaker never latches (`brain_wallet.breaker_tripped_at`, migration 009). Shorts off by default.
- **Exits:** one policy (`evaluate_exit`) shared by scans and the watchdog. Stop = 2×ATR, always hard (the thesis never suppresses it); target 2R; trailing 2.5×ATR once +1R. Claude's thesis re-eval can only close early (invalid, confidence ≥ 70, twice). Crypto watched on weekends.
- **Costs:** fills include slippage (10 bps stocks / 20 bps crypto) and CAD/USD FX for `.TO`.
- **Learning:** nothing auto-applies. Hypotheses need ≥ 30 observations to reach the prompt or graduate. `candidate_outcomes` tracks 5/10/20-day excess returns vs SPY for every candidate (bought or skipped); the daily report grades skip reasons, p_win calibration and Opus vetoes.
- **Old overfitted gates** (post-loss/winner cooldowns, MOMENTUM/NEUTRAL caps, Filter D, heat, LONG suspension, per-day caps) still exist in code but are disabled via config.
