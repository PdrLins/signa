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

### Backtest Results (run end of Day 1)

Backtest: 18,759 signals across ~18 months of historical data (tech-only, no AI).

| Metric | SAFE_INCOME | HIGH_RISK | Overall |
|--------|------------|-----------|---------|
| Signals | 3,148 | 2,339 | 5,487 |
| 5d win rate | 58.4% | 53.6% | 56.4% |
| 10d win rate | 59.1% | 53.8% | 56.8% |
| 20d win rate | 62.2% | 56.7% | 59.9% |
| 20d avg return | +1.47% | +1.75% | +1.59% |

Key findings:
1. SAFE_INCOME has higher win rate (62%) -- brain's bias toward SAFE_INCOME is correct
2. HIGH_RISK has higher avg returns (+1.75%) but lower consistency -- high variance
3. Best/worst trades are ALL crypto (DOGE +84%, SOL -29%) -- crypto needs the watchdog
4. Score distribution bottom-heavy: 9,355 in 60-70 range, only 1,810 at 70+, zero above 80 -- validates tech-only calibration need
5. 20-day hold outperforms 5-day (60% vs 56% win rate) -- current 30-day max hold is reasonable
6. Zero GEMs found -- GEM conditions (85+ score) are very strict, needs real AI sentiment to trigger

Impact on pending suggestions:
- low_confidence_guard: SUPPORTED (too many marginal BUYs)
- discovery_market_cap_filter: SUPPORTED (best trades are established names)
- tech_only_score_calibration: SUPPORTED (scores cluster low without AI)
- brain_bucket_diversification: WAIT (HIGH_RISK lower win rate, let brain find balance)
- watchdog_cooldown: NOT TESTABLE (needs real-time data)

### Suggestions Status (end of Day 1)

| Suggestion | Confidence | Decision | Rationale |
|-----------|-----------|----------|-----------|
| low_confidence_guard (40->50%) | 80% | APPLIED | Backtest shows too many marginal BUYs |
| discovery_market_cap_filter ($5B+) | 70% | APPLIED | Day 1 found 80 tickers, 0 scored 72+ |
| tech_only_score_calibration (+10) | 75% | WAIT | See if forced AI on open positions is enough first |
| watchdog_cooldown (3 holds -> hourly) | 65% | WAIT | Only 1 day of data |
| brain_bucket_diversification | 50% | REJECT | Brain naturally picks quality, don't force it |

---

## Day 2 -- April 7, 2026

### Environment
- Market: VOLATILE (VIX ~26.5)
- Fear & Greed: 21.4 (Extreme Fear)
- Scans: 13 (5 scheduled + 8 manual during development)
- Signals: 522 total (31 BUY, 226 HOLD, 265 AVOID)
- Budget: Claude $0.18, Grok $0.02, Total $0.20
- Brain positions: 11 open (was 10, added AVGO), 2 closed total
- Universe: expanded to 282 tickers (added 34 Canadian ETFs)

### Portfolio Performance (End of Day 2)
- **Realized P&L: -2.2%** (HUM +0.8%, PYPL -3.0%)
- **Unrealized P&L: +0.46% avg** (+6.0% total across 13 positions)
- **Winners: 10/13** (77% of open positions are green)
- **Best position: VLO +3.7%**
- **Worst position: CCO.TO -2.2%** (under watchdog monitoring)

### Incidents

**1. PYPL watchdog exit (-3.0%)**
- What: PYPL entered at score 72 (lowest brain pick), gradually dropped to -3.0%. Watchdog detected slow bleed at -3%, fetched sentiment, sentiment was bearish, auto-sold.
- Root cause: Marginal entry (score 72 is the minimum threshold). PYPL had weak fundamentals for the bucket it was in.
- Lesson: Score 72 picks have higher failure rate. Consider raising BRAIN_MIN_SCORE to 73-74 to reduce marginal entries.
- Status: CLOSED (watchdog worked correctly)
- Verdict: CORRECT EXIT. The -3.0% loss was better than holding to the stop at $43 (-7.1%).

**2. discovered_set bug crashed all AI signals**
- What: After code refactoring, `_process_candidate()` became a module-level function but still referenced `discovered_set` via closure. All 15 AI-analyzed signals failed silently.
- Root cause: Variable scoping -- `discovered_set` was defined in `run_scan()` but not passed as parameter.
- Fix: Added `discovered_set` as explicit parameter to `_process_candidate()`.
- Status: APPLIED
- Verdict: FIXED

**3. CNN Fear & Greed HTTP 418**
- What: CNN blocked our generic "Mozilla/5.0" User-Agent, returning HTTP 418 ("I'm a teapot").
- Fix: Updated to full Chrome User-Agent string.
- Status: APPLIED
- Verdict: WORKING (F&G = 21.4, Extreme Fear)

**4. Supabase HTTP/2 disconnections (recurring)**
- What: Multiple 500 errors from stale HTTP/2 connections dropping. stats, virtual-portfolio, and positions-summary endpoints affected.
- Fix: Added `@with_retry` decorator that catches RemoteProtocolError, resets client, retries once.
- Status: APPLIED
- Verdict: SIGNIFICANTLY REDUCED (not eliminated)

**5. Stuck scans from code reloads**
- What: 9 scans stuck in RUNNING status from server restarts during development, blocking new scan triggers.
- Fix: Manual cleanup (set to FAILED), no code change needed.
- Status: RESOLVED
- Verdict: Expected during development, not a production issue

**6. Hardcoded open_trades[:10] limit**
- What: Brain performance page showed 9 positions when 11 existed. The `get_virtual_summary()` function had `open_trades[:10]` hardcoded from when max was 10.
- Fix: Removed the slice, now enriches all open trades.
- Status: APPLIED
- Verdict: FIXED

### Features Shipped (Day 2)

**Brain Intelligence:**
1. Quality factor scoring (Fama-French QMJ) -- +6 bonus for high-quality SAFE_INCOME
2. Momentum factor scoring (UMD) -- +6 bonus for strong 3m/6m trend on HIGH_RISK
3. Short squeeze detection -- up to +20 bonus for high short float + bullish momentum
4. ADX indicator (trend strength) for dynamic strategy selection
5. SMA200 overextension blocker (>50% above = blocked)
6. Crypto volatility scaling (half Kelly, 8% max stop)
7. Portfolio rotation (replace weakest with stronger when full, +5 threshold)
8. Composite concern rule (weakest + losing + held 1d+ = auto-escalate)
9. Force-sell on catastrophic events (-8% total, score < 50, SELL signal + negative P&L)
10. Watchdog slow bleed detection (-3% total)
11. Watchdog cooldown (3 bullish holds -> 1hr pause)
12. ETF-specific scoring weights (15% dividend instead of 35%)
13. Fear & Greed Index in scoring + AI prompts
14. VIX term structure (contango/backwardation)
15. Intermarket signals (gold, oil, copper/gold ratio)
16. PEAD earnings drift module (new file)
17. Brain Telegram notifications (buy/sell/force-sell)

**Frontend:**
1. Market status floating pill (top-right, hover for details)
2. ETF badge on signal cards
3. Asset type filter (Stock/ETF/Crypto)
4. Sub-score pills on signal detail page
5. Probability chip ("70% vs SPY") on signal cards
6. Fear & Greed in stats bar
7. Track record table on brain performance page
8. Short interest in fundamentals grid
9. Settings: Watchdog section (min notify, P&L alert, max positions sliders)
10. How It Works: 7 new sections + updated card/detail reading guides

**Performance:**
1. All stats endpoints wrapped in asyncio.to_thread (was blocking event loop)
2. Supabase retry-on-disconnect decorator
3. Overview signals 200 -> 50, sidebar 200 -> 50
4. Price cache TTL 5min -> 10min
5. Stats cache TTL 30s -> 120s
6. Virtual portfolio + charts: 5-min TTL cache added
7. New DB indexes: signals(created_at DESC), signals(action, created_at DESC)

**Infrastructure:**
1. 34 Canadian ETFs added to universe (XEQT, VEQT, VFV, TEC, etc.)
2. Asset class detection (STOCK/ETF/CRYPTO)
3. Brain knowledge: 13 new entries seeded
4. Backtest regression tracker (`python -m backtest.compare_runs`)
5. Backtest scorer ported: quality, momentum, short squeeze, SMA200 guard

### Backtest Comparison (Day 2 vs Day 1)

| Metric | Day 1 Baseline | Day 2 (Phase 1) | Change |
|--------|---------------|-----------------|--------|
| 10d Win Rate | 56.8% | 58.4% | +1.6% |
| 10d Avg Return | +0.57% | +0.75% | +0.18% |
| 20d Win Rate | 59.9% | 61.5% | +1.6% |
| 20d Avg Return | +1.59% | +1.89% | +0.30% |
| SAFE_INCOME WR | 59.1% | 60.1% | +1.0% |
| HIGH_RISK WR | 53.8% | 55.8% | +2.0% |
| Signals 70+ | 1,810 | 2,882 | +59% |
| Signals 80+ | 0 | 30 | New tier |

### Patterns Observed

**1. All brain picks are still SAFE_INCOME**
- 11/11 positions are SAFE_INCOME. Zero HIGH_RISK. Same as Day 1.
- VIX at 26.5 (VOLATILE regime) reduces HIGH_RISK scores by 15%, making them harder to reach 72+.
- This is the regime system working correctly -- conservative in volatile markets.

**2. AVGO is the standout**
- Scored 77-79 across 4 scans. Strong fundamentals, momentum in sweet spot.
- Brain correctly identified and picked it.

**3. Fear & Greed at 21 (Extreme Fear) is contrarian bullish**
- Historical data: F&G below 25 has preceded market rallies ~70% of the time.
- The brain's macro score incorporates this, but current positions are all SAFE_INCOME which is appropriate for extreme fear.

**4. Watchdog noise on IFC.TO continues**
- 24 events today, mostly HOLD_THROUGH_DIP. Cooldown should reduce this.
- IFC.TO is a Contrarian pick hovering near thresholds -- the brain correctly holds.

**5. PYPL was the only loss**
- Entry score 72 (minimum). Lost -3.0%.
- Lesson: marginal picks (72) fail more often than strong picks (75+).

### Metrics to Track Tomorrow
- [ ] Did the composite concern rule catch any positions early?
- [ ] Is the watchdog cooldown reducing IFC.TO noise?
- [ ] Are ETFs getting scanned and scored correctly (XEQT in watchlist)?
- [ ] Does portfolio rotation trigger when a new 77+ signal appears and brain is full?
- [ ] Net P&L trajectory -- are we heading toward +1-2% monthly?
- [ ] Does Fear & Greed persist in stats bar across sessions?

### Learnings for Brain

1. **Score 72 picks have higher failure rate** -- PYPL was the only loss, and it was the lowest entry score. Consider raising BRAIN_MIN_SCORE to 73.
2. **Slow bleed detection works** -- PYPL was caught at -3.0% instead of hitting stop at -7.1%. Saved ~4% loss.
3. **The brain is conservative in volatile markets** -- all SAFE_INCOME picks, which is correct behavior.
4. **10/13 positions are winners** (77%) -- the brain's stock picking is working, the issue was one marginal entry.
5. **VLO +3.7% is covering PYPL's -3.0% loss** -- diversification across 11 positions means one bad pick doesn't kill the portfolio.

---

## Template for Future Days

### Day N -- [Date]

**Environment:** [regime, VIX, scans count, budget]

**Incidents:**
1. [What happened, root cause, fix, status, verdict]

**Patterns:** [Recurring observations]

**Fixes Applied:** [What was changed]

**Backtest comparison:** [Did metrics improve from previous backtest?]

**Metrics:** [Did yesterday's fixes work?]
