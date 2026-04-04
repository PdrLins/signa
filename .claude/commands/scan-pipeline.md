Show the Signa scan pipeline, scoring system, GEM detection, and signal blockers.

## Scan Schedule (Eastern Time, Mon-Fri)
| Time | Type | Purpose |
|------|------|---------|
| 6:00 AM | PRE_MARKET | Pre-market scan, confirm/cancel overnight signals |
| 10:00 AM | MORNING | Morning confirmation (best entry window) |
| 3:00 PM | PRE_CLOSE | Pre-close check (second best entry) |
| 4:30 PM | AFTER_CLOSE | Full scan, generate next-day watchlist |

## Pipeline Steps (scan_service.run_scan)
1. Load ~250 tickers from `app/scanners/universe.py`
2. Bulk screen via yfinance (5d data, batches of 50)
3. Pre-filter to ~50 candidates: volume > 200K, |day_change| > 1%, price > $1
4. Fetch macro snapshot once: FRED (fed funds, 10Y, CPI, unemployment) + VIX — all in parallel
5. For each candidate (asyncio.gather, semaphore=10):
   a. Fetch price_history + fundamentals + Grok sentiment — **in parallel**
   b. Compute technical indicators (pandas-ta, CPU only)
   c. Call Claude **once** with all real data → signal synthesis
   d. Score using bucket-specific weights
   e. Check signal blockers
   f. Check GEM conditions
   g. Determine status vs previous signal
6. Batch insert all signals to Supabase
7. Send GEM alerts + scan digest via Telegram

## Scoring System (backtest-validated from Oct 2024 → Apr 2025)

### Key Findings from Backtest
- RSI 50-65 is the sweet spot; oversold (< 30) is NOT better
- Momentum > 5% is a TRAP (46.2% win rate); sweet spot is +1% to +3%
- High MACD histogram predicts surges (avg 3.3 on surgers vs 1.5 on normal)
- Score ceiling: scores above 72 have INVERTED win rates (overbought trap)
- Safe Income: low RSI + low volume wins (buy the dip on stable stocks)
- High Risk: moderate RSI + volume confirmation needed

### Live System Weights (app/ai/signal_engine.py)
**Safe Income:**
- Dividend reliability: 35%
- Fundamental health: 30%
- Macro environment: 25%
- Sentiment (Grok): 10%

**High Risk:**
- X/Twitter sentiment (Grok): 35%
- Catalyst detection (Claude): 30%
- Technical momentum: 25%
- Fundamentals: 10%

### Backtest Weights (backtest/engine/scorer.py) — no AI
**Safe Income:**
- Dividend: 25%, Fundamental: 25%, Macro: 20%, Technical: 30%

**High Risk:**
- Trend + MACD: 35%, Momentum: 25%, Fundamental: 20%, Macro: 20%

### Thresholds
| | Live | Backtest |
|---|---|---|
| BUY | >= 75 (has AI) | >= 65 |
| Score Ceiling | 90 | 72 |
| HOLD | 50-74 | 50-64 |
| AVOID | < 50 | < 50 |

## GEM Alert Conditions

### Live (all 5 must be true)
1. Score >= 85
2. Catalyst within 30 days (from Claude)
3. Grok sentiment = bullish AND confidence >= 80
4. No red flags from Claude
5. Risk/reward >= 3.0x

### Backtest (all 4 must be true — no AI)
1. Score >= 78
2. MACD bullish with histogram > 1.0
3. Above SMA200 by > 5%
4. RSI between 40-70

## Signal Blockers (auto-AVOID regardless of score)
1. Fraud/legal keywords in Grok sentiment
2. 2+ consecutive earnings misses
3. Hostile macro environment (VIX > 30, high fed funds, high unemployment)
4. Suspiciously low volume (Z-score < -2.0 or avg < 50K)
5. **RSI > 75 overbought** (backtest-validated: 60%+ fail rate)

## Signal Status Tracking
Compared to previous signal for same ticker:
- CONFIRMED — no significant change
- WEAKENING — score dropped 15+ points
- CANCELLED — was BUY, now SELL/AVOID
- UPGRADED — score increased 10+ points, or HOLD → BUY

## Key Files
- `app/services/scan_service.py` — orchestrator
- `app/ai/signal_engine.py` — live scoring + GEM + blockers
- `backtest/engine/scorer.py` — backtest scoring (data-tuned)
- `app/scanners/indicators.py` — RSI, MACD, Bollinger, SMA, ATR
- `app/ai/claude_client.py` — Claude synthesis
- `app/ai/grok_client.py` — Grok sentiment
- `app/scheduler/runner.py` — APScheduler cron jobs
