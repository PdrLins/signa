# Signa Brain Learning Journal

Tracks lessons learned from each day of operation. Each entry records what happened, what we learned, what was fixed, and later -- whether the fix actually worked.

---

## Day 1 -- April 6, 2026

### Environment
- Market: VOLATILE (VIX ~25)
- Scans: 9 (4 scheduled + 5 manual)
- Signals: 435 total (85 AI-analyzed, 350 tech-only)
- Budget: Claude $1.02, Grok $0.012, Gemini exhausted
- Brain positions: 10 open, 1 closed (HUM +0.77%)

### Incidents

**1. HUM false sell (score 75 -> 37)**
- What: HUM scored 75 (BUY) with AI at 10 AM, then 37 (AVOID) tech-only at 12:26 PM. Brain sold at +0.77%.
- Root cause: Ticker lost AI analysis in second scan (fell out of top 15), tech-only score collapsed. Also bucket flipped SAFE_INCOME -> HIGH_RISK due to day_change heuristic.
- Analyst target: $212 (we sold at $183.60 -- left 15% on the table)
- Fix applied: Score drop guard (25+ point drops block auto-sell), forced AI on open positions, stable bucket (stored in DB), removed day_change from bucket classification
- Status: APPLIED
- Verdict: TBD (need to see if guard prevents false sells without blocking real ones)

**2. AI vs tech-only score gap**
- What: Same ticker scores 30 points higher with AI than without. BCE.TO: AI=75, tech=45. HUM: AI=75, tech=50.
- Root cause: Tech-only scoring has no sentiment/catalyst input (defaults to 0), but the scoring model weights these at 25-35%. AI analysis adds the missing context.
- Fix proposed: Calibrate tech-only base scores +10 for SAFE_INCOME
- Status: PENDING
- Verdict: TBD

**3. IFC.TO watchdog noise**
- What: 15 watchdog events in one day, all on IFC.TO. 11 HOLD_THROUGH_DIP, 4 ALERT. Sentiment bullish 13/15 times.
- Root cause: IFC.TO hovered near the 2% alert threshold all day. Watchdog correctly held but kept logging.
- Fix proposed: After 3 consecutive holds with bullish sentiment, reduce check frequency
- Status: PENDING
- Verdict: TBD

**4. yfinance DNS/SQLite errors**
- What: 69+ failed downloads per scan. "getaddrinfo() thread failed to start", "unable to open database file"
- Root cause: Too many concurrent yfinance connections exhausting macOS DNS threads. yfinance internal SQLite cache corrupting under async access.
- Fix applied: threads=False on all yf.download calls, disabled yfinance SQLite cache (YF_CACHE=0), batch size 20 (from 50), semaphore=3, pre-scoring in batches of 10
- Status: APPLIED
- Verdict: WORKING (errors reduced from 97 to ~3 delisted tickers only)

**5. Gemini free tier exhaustion**
- What: Gemini hit daily quota mid-scan, causing 90+ second delays per ticker (3 retries with 15/30/45s waits)
- Fix applied: Fast-fail on quota exhaustion (skip retries when error says "FreeTier" or "quota")
- Status: APPLIED
- Verdict: WORKING (scan time dropped from 288s to ~136s)

**6. Dividend yield data error**
- What: HUM showed 199% dividend yield in AI reasoning (real yield is 1.99%). yfinance sometimes returns decimals vs percentages inconsistently.
- Fix applied: _normalize_pct() function -- values > 1 get divided by 100
- Status: APPLIED
- Verdict: TBD (need to verify on next scan)

### Patterns Observed

**Score clustering at confidence=45**
- 12 BUYs had confidence exactly 45%. Claude may be defaulting to this when uncertain.
- Current guard: BUY downgraded to HOLD if confidence < 40%
- Suggestion: raise to 50% (below majority confidence should not be BUY)
- Status: PENDING

**All brain picks are SAFE_INCOME**
- 10/10 brain positions are SAFE_INCOME. Zero HIGH_RISK.
- Reason: HIGH_RISK scoring weights sentiment at 35%, but Grok data is sparse for many tickers. SAFE_INCOME weights fundamentals heavier which tech-only can partially capture.
- Not necessarily bad -- conservative portfolio. But brain is not finding momentum plays.
- Status: OBSERVATION (no fix needed yet)

**Discovery yield is low**
- 80 tickers discovered per scan, 4 produced signals, 0 reached brain-quality (72+)
- All discovered tickers scored 58-65 (HOLD range)
- Suggestion: Add minimum market cap filter ($5B+) to discovery to exclude small/micro caps
- Status: PENDING

### Brain Knowledge Added
1. `score_consistency_guard` -- teaches AI about methodology changes vs real signal changes
2. `data_quality_validation` -- teaches AI to flag extreme data values (199% dividend etc)

### Brain Rules Added
1. `score_drop_guard` -- blocks auto-sell on 25+ point score drops when new score < 50

### Infrastructure Changes
1. Brain watchdog (every 15 min during market hours)
2. MIDDAY scan (12:00 PM ET)
3. Missed scan catch-up on startup
4. Ticker discovery (Yahoo screeners)
5. Auto-add brain picks to tickers table
6. Stable bucket classification (DB-backed)
7. Token refresh (silent JWT renewal on 401)

### Metrics to Track Tomorrow
- [ ] Does the score drop guard correctly block false sells?
- [ ] Do discovered tickers ever score 72+?
- [ ] Does IFC.TO recover or should the brain have sold?
- [ ] Are all 5 scheduled scans completing?
- [ ] Is the watchdog 2% threshold generating appropriate alerts?
- [ ] Does the confidence=45 clustering continue?
- [ ] Any new bucket flip incidents?

---

## Template for Future Days

### Day N -- [Date]

**Environment:** [regime, VIX, scans count, budget]

**Incidents:**
1. [What happened, root cause, fix, status, verdict]

**Patterns:** [Recurring observations]

**Fixes Applied:** [What was changed]

**Metrics:** [Did yesterday's fixes work?]
